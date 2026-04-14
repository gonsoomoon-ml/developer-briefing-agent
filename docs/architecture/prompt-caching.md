# 프롬프트 캐싱 — 동작 원리 및 최적화 전략

## 개요

Bedrock 프롬프트 캐싱은 반복되는 컨텍스트(도구 정의, 시스템 프롬프트, 대화 히스토리)를 캐시하여 비용과 지연 시간을 줄이는 기능입니다. **prefix 기반**으로 동작하며, `cachePoint` 마커가 캐시 경계를 정의합니다.

## 핵심 메커니즘: Prefix 기반 캐싱

각 `cachePoint`는 요청 시작부터 해당 지점까지의 **누적 prefix를 해시**하여 캐시 엔트리를 생성합니다. 캐시 prefix는 `tools → system → messages` 순서로 구성됩니다.

```
cachePoint A (tools):    hash([tools])
cachePoint B (system):   hash([tools + system])
cachePoint C (messages): hash([tools + system + messages_until_C])
```

상위 레벨 변경이 하위를 무효화합니다:
- tools 변경 → tools + system + messages 캐시 모두 무효화
- system 변경 → system + messages 캐시 무효화 (tools 유지)
- messages만 변경 → messages 캐시만 무효화 (tools, system 유지)

**cachePoint 이후 내용 변경은 해당 cachePoint의 캐시에 영향 없음.**

## Backward Lookback

cachePoint를 이동해도 이전에 저장된 캐시 엔트리는 삭제되지 않습니다. Bedrock는 새 cachePoint에서 매치가 없으면 **뒤로 최대 20블록**을 걸어가며 이전 캐시를 찾습니다.

```
Turn 1: 10 blocks, cachePoint at block 10 → Write at block 10
Turn 2: 15 blocks, cachePoint at block 15
        → block 15: miss
        → lookback: 14, 13, 12, 11, 10 → HIT!
        → Read: blocks 1-10, Write: blocks 11-15
```

이 메커니즘 덕분에 매 턴 cachePoint를 이동해도 이전 턴의 캐시가 Read로 재활용됩니다.

## 토큰 분류 공식

```
A = 가장 높은 캐시 히트 위치의 토큰 수
C = 마지막 cachePoint 위치의 토큰 수

cacheReadInputTokens  = A          (히트된 prefix 전체, 90% 할인)
cacheWriteInputTokens = C - A      (히트 이후 ~ 마지막 cachePoint, 25% 할증)
inputTokens           = 나머지     (마지막 cachePoint 이후, 기본가)
```

검증: `Total = cacheRead + cacheWrite + input + output` (상호 배타적 합산)

## 3-Layer 캐싱 구조

| Layer | 대상 | 구현 방법 | 상태 |
|-------|------|----------|------|
| 도구 정의 | shell, file_read 스키마 | `BedrockModel(cache_tools="default")` | 활성화 |
| 시스템 프롬프트 | 시스템 프롬프트 + Active Skill | `SystemContentBlock(cachePoint={"type": "default"})` | 활성화 |
| 턴 경계 | 이전 턴의 대화 히스토리 | `retrieve_context` 훅에서 마지막 user 메시지에 `cachePoint` 이동 | 활성화 (Turn 2+) |

Static SKILL.md 마이그레이션 이후 3개 레이어 모두 정상 작동합니다. `retrieve_context` 훅은 **user 메시지**에 cachePoint를 부착합니다 (Strands SDK 내장 패턴과 일치). 히스토리가 10개 메시지를 초과하면 첫 번째 user 메시지에 **앵커 cachePoint**도 추가됩니다 (4번째 캐시 블록 사용).

참고: `cache_tools="default"`와 `cache_config`는 Strands SDK에서 **별개의 설정**입니다. 본 프로젝트는 `cache_tools`만 사용하며, `cache_config` (`_inject_cache_point` 자동 모드를 활성화)는 설정하지 않습니다. 메시지 레벨 cachePoint는 훅에서 수동 관리합니다.

## 비용 구조

| 토큰 유형 | 비용 배수 | 설명 |
|-----------|----------|------|
| Cache Read | 0.1x | 캐시에서 읽을 때 90% 할인 |
| Cache Write | 1.25x | 캐시에 쓸 때 25% 추가 비용 |
| Input | 1.0x | 캐시되지 않은 일반 입력 토큰 |

## 캐시 범위: 모델 엔드포인트 단위 공유

**Bedrock 프롬프트 캐시는 같은 모델 엔드포인트의 모든 요청에서 공유됩니다** (microVM이나 runtimeSessionId별 격리가 아님). 이는 다음을 의미합니다:

- 한 세션에서 Write된 캐시 엔트리를 다른 세션에서 Read 가능 (prefix가 일치하면)
- `tools + system` prefix는 같은 개발자의 모든 세션에서 동일 → 항상 공유
- 사용자가 같은 질문을 하면 메시지 prefix도 일치 가능 (같은 도구 출력 → 같은 prefix 해시)

이것이 warm-cache 테스트에서 CacheWrite=0인 이유입니다 — 이전 테스트가 이미 캐시를 채웠기 때문입니다.

## 실측 데이터

### Cold Cache (엔드포인트에서 첫 요청)

로컬에서 sync `agent()`로 측정 (cold cache):

```
Turn  턴별 dRead  턴별 dWrite  설명
------------------------------------------------------
T1       9,748       4,874     tools(Read, 이전 세션) + system(Write, 신규)
T2       4,874       1,645     system(Read) + T1 메시지(Write, 메시지 cp)
T3       6,519         526     system+T1(Read) + T2 메시지(Write)
```

**메시지 cachePoint Write는 작습니다** (526-1,645 토큰) — system cachePoint와 message cachePoint 사이의 대화 교환 분량만 해당되며, 시스템 프롬프트 전체가 아닙니다.

### Warm Cache (AgentCore Runtime 누적 메트릭)

이전 테스트가 5분 TTL 이내에 캐시를 채운 경우, 모든 공통 prefix는 Read:

```
Turn  프롬프트               누적 Read  누적 Write  턴별 dRead  턴별 dWrite
--------------------------------------------------------------------------
T1    업무 쿼리               14,631        0       14,631         0
T2    후속 질문               19,508        0        4,877         0
T3    또 다른 후속            24,385        0        4,877         0
...
T30   마지막 쿼리           170,695        0        4,877         0
```

턴별 dRead = 4,877 = LLM 호출 1회당 시스템 프롬프트 1회 Read. 도구 사용 턴은 dRead = 14,631 = 시스템 프롬프트 3회 Read (tool loop에서 LLM 3회 호출).

### 누적 메트릭 vs 턴별 메트릭 이해하기

`agentcore_runtime.py`는 `agent.event_loop_metrics.accumulated_usage`를 보고합니다. 이 값은 같은 Agent 객체의 **모든 호출에 걸쳐 합산**됩니다:

- 누적 CacheWrite=4,877이 매 턴 동일 = 시스템 프롬프트가 T1에서 한 번만 Write되고 누적값이 불변 (매 턴 재Write가 아님)
- warm-cache 테스트에서 CacheWrite=0 = 이전 테스트 세션에서 이미 시스템이 캐시됨
- 턴별 delta를 보려면 연속된 누적값을 빼야 합니다

## 턴별 캐시 흐름 (Cold Cache)

```
T1:  [tools cp][system cp][user_input]
     tools: READ (9,748)      — 이전 세션에서 캐시됨
     system: WRITE (4,874)    — 이 엔드포인트에서 처음
     messages: cp 없음        — 첫 턴, 히스토리 없음
     → 캐시 엔트리: tools prefix, system prefix 저장

T2:  [tools cp][system cp][T1_msgs ... last_user cp][new_input]
     tools: READ
     system: READ              — T1에서 캐시됨
     messages cp: WRITE (1,645) — T1 메시지 delta (user+assistant+tool 교환)
     → lookback이 system 엔트리 찾음, 그 위에 메시지 delta Write

T3:  [tools cp][system cp][T1_msgs][T2_msgs ... last_user cp][new_input]
     tools: READ
     system: READ
     messages cp: lookback → T2 엔트리 HIT! → T1 부분 Read, T2 delta Write (526)
```

### 토큰 흐름 시각화

```
        |---- READ (90% 할인) --------|- WRITE(25% 할증) -|- INPUT -|

T1: =========XXXXXXX==============================================
    tools(R)  sys(W)  messages(I) — message cp 없음

T2: ================XX=============================================
    tools(R) sys(R)  T1(W)  new_user(I) — message cp (마지막 user msg)
                     소량!

T3: ====================X==========================================
    tools(R) sys(R) T1(R)  T2(W)  new_user(I)
                           미량!
```

Write 세그먼트는 초기 예상보다 **훨씬 작습니다** — 수백 토큰 (대화 delta) 수준이며, 수천 토큰이 아닙니다.

## Turn 1/2 프롬프트 구조 시각화

### Turn 1 — Bedrock에 보내는 프롬프트

```
   ┌────────────────────────────────────────────────────────────────┐
   │  ┌────────────────────────────────────────────────────────┐    │
   │  │ [SYSTEM PROMPT]                  ~2,500 토큰           │    │
   │  │   • 당신은 sejong의 어시스턴트...                       │    │
   │  │   • ## Active Skill (SKILL.md 내용 inline)             │    │
   │  └────────────────────────────────────────────────────────┘    │
   │  ┌────────────────────────────────────────────────────────┐    │
   │  │ ★ cachePoint: "여기까지 캐시에 외워둬라!"               │    │
   │  └────────────────────────────────────────────────────────┘    │
   │  ┌────────────────────────────────────────────────────────┐    │
   │  │ [👤 USER #1]                     ~50 토큰               │    │
   │  │   "지난 주 작업 내역 알려줘"                            │    │
   │  └────────────────────────────────────────────────────────┘    │
   └────────────────────────────────────────────────────────────────┘
                                    │
                          Bedrock Cache (텅 빔)
                                    │
                          "처음 보는 prefix → cachePoint까지 캐시에 저장!"
```

### Turn 2 — 이전 대화 포함

```
   ┌────────────────────────────────────────────────────────────────┐
   │  [SYSTEM PROMPT]                                ◀── 캐시 hit  │
   │  ★ cachePoint #1                                              │
   │  [👤 USER #1]  "지난 주 작업 내역 알려줘"                      │
   │  [💬 ASSISTANT #1] "데이터 수집 중..." + tool_use              │
   │  [🔧 TOOL RESULT #1] github_standup 결과 ~12k 토큰            │
   │  [💬 ASSISTANT #1 final] "지난 주 작업 마크다운..."            │
   │  ★ cachePoint #2 (NEW! turn boundary cache)                   │
   │  [👤 USER #2] "이번 주 작업 내역 알려줘"          ← NEW        │
   └────────────────────────────────────────────────────────────────┘

   cachePoint #1까지: 90% 할인 ✅
   cachePoint #1 ~ #2: 새로 캐시 Write (Turn 1 messages)
   cachePoint #2 이후: 풀가격 (새 입력)
```

## Turn 1 상세: 4개 LLM 호출

도구 사용이 있는 Turn에서는 LLM이 여러 번 호출됩니다. 일반적인 Turn 1 흐름:

### Call #1: 초기 입력

```
   [TOOLS]  ~250 토큰
   ★ cachePoint (cache_tools="default")
   [SYSTEM] ~2,500 토큰
   ★ cachePoint (explicit)
   [👤 USER] ~500 토큰

   → Cache 빔 → TOOLS+SYSTEM Write
   📊 Write ~2,750 | Read 0 | Regular ~500
   💬 → tool_use(shell)
```

### Call #2: shell 결과

```
   [TOOLS]     ★ hit
   [SYSTEM]    ★ hit
   [USER]      ~500 토큰
   [ASSIST #1] ~100 토큰  NEW
   [TOOL_RESULT #1] ~700 토큰  NEW

   📊 Write ~1,300 | Read ~2,750 | Regular 0
   💬 → tool_use(file_read)
```

### Call #3: file_read 결정

```
   [TOOLS ~ TOOL_RESULT #1]  ★ 전부 hit
   [ASSIST #2]  ~50 토큰  NEW

   📊 Write ~50 | Read ~4,050 | Regular 0
```

### Call #4: JSON → 최종 응답

```
   [TOOLS ~ ASSIST #2]  ★ 전부 hit
   [TOOL_RESULT #2 JSON]  ~2,000 토큰  NEW

   📊 Write ~800 | Read ~3,000 | Regular ~3,400
   💬 → 최종 마크다운 브리핑
```

### Call별 합계 검증

```
   ┌─────────┬───────────┬───────────┬────────────┐
   │  Call   │   Write   │   Read    │  Regular   │
   ├─────────┼───────────┼───────────┼────────────┤
   │  #1     │  ~2,750   │       0   │     ~500   │
   │  #2     │  ~1,300   │   ~2,750  │       0    │
   │  #3     │     ~50   │   ~4,050  │       0    │
   │  #4     │    ~800   │   ~3,000  │   ~3,400   │
   ├─────────┼───────────┼───────────┼────────────┤
   │  합계   │  ~4,900   │   ~9,800  │   ~3,900   │
   │  실제   │   4,886   │    9,772  │    3,931   │ ◀── ~98% 일치
   └─────────┴───────────┴───────────┴────────────┘
```

## 호출별 측정 방법

현재 `chat.py`는 한 Turn의 모든 LLM call 토큰을 **합산**하여 출력합니다. 각 호출별 수치를 보려면 `shared/memory_hooks.py`에 `AfterModelCallEvent` 콜백을 추가:

```python
def report_call_tokens(self, event: AfterModelCallEvent):
    if not self.debug:
        return
    usage = getattr(event, "usage", None)
    if not usage:
        return
    write = usage.get("cacheWriteInputTokens", 0)
    read = usage.get("cacheReadInputTokens", 0)
    regular = usage.get("inputTokens", 0)
    print(f"  💰 Call #{self._turn_call_count}: "
          f"Write {write:,} | Read {read:,} | Regular {regular:,}")
```

등록: `registry.add_callback(AfterModelCallEvent, self.report_call_tokens)` (~25줄 수정).

## 캐시 블록 예산

Bedrock은 요청당 최대 **4개의 cache_control 블록**을 허용합니다:

```
1. cache_tools (도구 정의)                                    → 활성화
2. 시스템 프롬프트 cachePoint                                  → 활성화
3. 턴 경계 cachePoint (마지막 user 메시지, 이동형)              → 활성화
4. 앵커 cachePoint (첫 번째 user 메시지, history >10일 때)     → 활성화 (조건부)
```

## 캐싱 최소 토큰 요건

| 모델 | 최소 토큰 |
|------|----------|
| Claude Sonnet 4.6 | 2,048 |
| Claude Sonnet 4.5, 4, 3.7 | 1,024 |
| Claude Opus 4.5, 4.6 | 4,096 |
| Claude Haiku 4.5 | 4,096 |

미달 시 캐시 체크포인트가 무시됩니다 (오류 없이 작동하지만 캐싱되지 않음). 시스템 프롬프트 + Active Skill 약 4,877 tokens로 Claude Sonnet 4.6의 2,048 요건을 충족합니다.

## 캐시 TTL (Time To Live)

| TTL | 지원 모델 | 설정 |
|-----|----------|------|
| 5분 (기본) | 모든 지원 모델 | `{"type": "default"}` |
| 1시간 | Claude Sonnet 4.5/4.6, Opus 4.5/4.6, Haiku 4.5 | `{"type": "default", "ttl": "1h"}` |

TTL은 캐시 히트마다 리셋됩니다. 현재 프로젝트는 기본 5분 TTL을 사용합니다.

**순서 제약**: 긴 TTL 캐시 엔트리는 짧은 TTL 엔트리보다 앞에 위치해야 합니다 (요청 순서: tools → system → messages). `cache_tools`가 5분 TTL을 고정하므로, system에 1시간을 설정하면 tools(5분) → system(1시간) 순서가 되어 `ValidationException` 발생. 아래 "조사 후 차단됨" 참조.

## 최적화 전략

### 적용된 최적화

| 최적화 | 효과 | 상태 |
|--------|------|------|
| **cachePoint를 user 메시지로** | Strands 내장 패턴과 일치, lookback 안정성 향상 | 적용 완료 |
| **앵커 cachePoint 추가** (4번째 블록) | 장기 대화에서 lookback 실패 방지 (history >10 메시지 시 활성화) | 적용 완료 |

### 조사 후 차단됨

| 최적화 | 차단 사유 |
|--------|----------|
| **1h TTL (시스템 프롬프트)** | `cache_tools="default"`가 tools에 5분 TTL 고정 생성. system(1h)이 tools(5m) 뒤에 오면 `"a ttl='1h' cache_control block must not come after a ttl='5m' cache_control block"` ValidationException 발생. Strands SDK가 `cache_tools`에 TTL 파라미터를 지원해야 해제 가능. |

### 향후 고려 사항

| 최적화 | 효과 | 필요 시점 |
|--------|------|----------|
| **N턴마다 cachePoint 이동** | Write 빈도 감소 | Write 비용이 문제가 될 때 (현재 소량이라 불필요) |
| **1h TTL** (SDK 지원 후) | 세션 간 캐시 유지 (5분 초과 간격) | 데모 중 5분 이상 대기 시간이 있을 때 |

### 20-block lookback 한계

대화가 길어져 message 블록이 20개를 초과하면 lookback이 이전 캐시를 찾지 못합니다:

```
T11: cachePoint at block #55
     lookback: #55 → #54 → ... → #35 (20칸 한계)
     T1의 캐시 (block #10)까지 도달 못함 → MISS!
```

**앵커 cachePoint** (적용 완료, history >10 메시지 시 활성화)가 첫 번째 user 메시지에 고정 cachePoint를 두어 lookback 거리를 짧게 유지합니다.

## Cross-Region Inference 호환성

`global.anthropic.claude-sonnet-4-6` (글로벌 크로스 리전 추론)에서 프롬프트 캐싱이 **지원됩니다**.

## 이전 분석의 정정 사항

| 초기 분석 | 테스트로 검증된 사실 |
|----------|---------------------|
| "CacheWrite 4,877 = 시스템 프롬프트가 매 턴 재Write" | 4,877은 시스템 프롬프트가 한 번만 Write된 것; 누적값이 불변으로 유지됨 |
| "메시지 cachePoint 미작동 (Write=0)" | 정상 작동 — Write=0은 이전 테스트가 5분 TTL 안에 캐시를 채웠기 때문 |
| "턴별 메시지 Write = 4,877 (고정)" | 실제 턴별 메시지 Write = 526-1,645 토큰 (소량의 대화 delta) |
| "CacheWrite=0은 cachePoint 고장" | 캐시는 모델 엔드포인트 수준에서 공유됨; 이전 테스트가 이미 채워둠 |

## 참고 자료

- [Amazon Bedrock Prompt Caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Anthropic Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [Bedrock CachePointBlock API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CachePointBlock.html)
- [Global Cross-Region Inference](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html)
