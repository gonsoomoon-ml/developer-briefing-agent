# 프롬프트 캐싱 — 구현 및 제약 사항

## 개요

Bedrock 프롬프트 캐싱은 반복되는 컨텍스트(시스템 프롬프트, 도구 정의, 대화 히스토리)를 캐시하여 비용과 지연 시간을 줄이는 기능입니다.

## 3-Layer 캐싱 구조

| Layer | 대상 | 구현 방법 | 상태 |
|-------|------|----------|------|
| 시스템 프롬프트 | 시스템 프롬프트 텍스트 | `SystemContentBlock(cachePoint={"type": "default"})` | AgentSkills로 인해 비활성화 |
| 도구 정의 | shell, file_read, skills 스키마 | `BedrockModel(cache_tools="default")` | AgentSkills로 인해 비활성화 |
| 턴 경계 | 이전 턴의 전체 대화 히스토리 | `BeforeInvocationEvent` 훅에서 `cachePoint` 추가 | **활성화 (Turn 2+)** |

## 비용 절감 효과

| 토큰 유형 | 비용 배수 | 설명 |
|-----------|----------|------|
| Cache Write | 1.25x | 캐시에 쓸 때 25% 추가 비용 (1회) |
| Cache Read | 0.1x | 캐시에서 읽을 때 90% 할인 |
| Regular Input | 1.0x | 일반 입력 토큰 |

### 실제 측정 결과

```
Turn 1: Total: 22,027 | Input: 21,069 | Cache Read: 0     | Cache Write: 0
Turn 2: Total: 36,577 | Input: 18,184 | Cache Read: 11,304 | Cache Write: 5,652
```

Turn 2에서 11,304 토큰이 캐시에서 읽혔습니다 (90% 할인 적용).

## AgentSkills와 캐싱 충돌

### 발견된 문제

`AgentSkills` 플러그인이 시스템 프롬프트에 `<available_skills>` 내용을 주입할 때, `SystemContentBlock`의 `cachePoint`를 덮어쓰거나 제거합니다.

### 검증 결과

| 구성 | 캐싱 | 캐시 토큰 |
|------|------|----------|
| `file_read` 만 | 작동 | 3,682 write |
| `shell + file_read` | 작동 | 4,536 write |
| `shell + file_read + AgentSkills` | **비활성화** | 0 |

### 결론

AgentSkills를 사용하는 한 Turn 1의 시스템 프롬프트/도구 캐싱은 작동하지 않습니다. 이는 Strands SDK의 AgentSkills 구현 문제입니다.

**대안으로 검토한 방법:**
- AgentSkills를 제거하고 SKILL.md 내용을 시스템 프롬프트에 직접 포함 → 캐싱은 작동하지만 AgentSkills의 동적 스킬 로딩 기능을 잃음
- **현재 선택:** AgentSkills를 유지하고, Turn 2+의 턴 경계 캐싱으로 절감

## 턴 경계 캐싱 동작 방식

Turn 2부터 `BeforeInvocationEvent` 훅이 이전 턴의 마지막 메시지에 `cachePoint`를 추가합니다:

```python
# shared/memory_hooks.py — retrieve_context() 내부
if history:
    last_msg = history[-1]
    last_content = last_msg.get("content", [])
    has_cache = any(isinstance(b, dict) and "cachePoint" in b for b in last_content)
    if not has_cache:
        last_content.append({"cachePoint": {"type": "default"}})
```

### 캐시 블록 예산

Bedrock은 요청당 최대 **4개의 cache_control 블록**을 허용합니다:

```
1. 시스템 프롬프트 cachePoint     → AgentSkills로 인해 무효
2. cache_tools (도구 정의)        → AgentSkills로 인해 무효
3. 턴 경계 cachePoint             → 활성화 ✅
4. (여유 1개)
```

## 캐싱 최소 토큰 요건

Bedrock은 캐시 체크포인트를 활성화하려면 **최소 1,024 토큰**이 필요합니다:

- 첫 번째 체크포인트: 1,024 토큰 이상
- 두 번째 체크포인트: 2,048 토큰 이상

최소 토큰 미만이면 캐시 체크포인트가 무시됩니다 (오류 없이 작동하지만 캐싱되지 않음).

### 시스템 프롬프트 크기

`prompts/system_prompt.md`는 ~6,300 바이트 / ~2,000-3,000 토큰으로 최소 요건을 충족합니다. 하지만 AgentSkills가 cachePoint를 제거하므로 현재는 효과가 없습니다.

## 캐시 TTL (Time To Live)

| TTL | 지원 모델 |
|-----|----------|
| 5분 (기본) | 모든 지원 모델 |
| 1시간 | Claude Sonnet 4.5, Opus 4.5, Haiku 4.5 |

현재 프로젝트는 기본 5분 TTL을 사용합니다: `{"type": "default"}`

## Cross-Region Inference 호환성

`global.anthropic.claude-sonnet-4-6` (글로벌 크로스 리전 추론)에서 프롬프트 캐싱이 **지원됩니다**. AWS 문서에 "Global CRIS supports key Amazon Bedrock features, including prompt caching"으로 명시되어 있습니다.

## 토큰 사용량 표시

`chat.py`는 매 턴 후 토큰 사용량을 표시합니다:

```
📊 Tokens — Total: 36,577 | Input: 18,184 | Output: 1,437 | Cache Read: 11,304 | Cache Write: 5,652
```

### 토큰 수집 방법

- **로컬 에이전트:** `agent.stream_async()` 이벤트의 `event.metadata.usage`에서 수집
- **AgentCore Runtime:** 서버가 `token_usage` SSE 이벤트로 클라이언트에 전송

### 알려진 제한

AgentSkills가 활성화된 상태에서는 Bedrock가 `cacheReadInputTokens`와 `cacheWriteInputTokens` 필드를 응답에 포함하지 않습니다. 따라서 Turn 1에서는 캐시 관련 토큰이 항상 0으로 표시됩니다.

## 향후 개선 가능성

1. **Strands SDK AgentSkills 수정** — cachePoint를 보존하도록 AgentSkills를 업데이트하면 Turn 1 캐싱이 활성화됩니다
2. **수동 스킬 로딩** — AgentSkills 대신 SKILL.md를 시스템 프롬프트에 직접 포함하면 즉시 캐싱이 가능합니다 (현재는 AgentSkills의 동적 로딩 이점을 유지하기로 결정)
3. **1시간 TTL** — Claude Sonnet 4.5/4.6으로 업그레이드 시 `{"type": "default", "ttl": "1h"}`로 변경 가능

## 참고 자료

- [Amazon Bedrock Prompt Caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Global Cross-Region Inference](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html)
