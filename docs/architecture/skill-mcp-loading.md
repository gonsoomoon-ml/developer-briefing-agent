# SKILL과 MCP의 정적/동적 로딩 — 아키텍처 결정 가이드

## 개요

LLM 에이전트를 설계할 때 마주치는 핵심 질문 중 하나:

> **"에이전트가 사용할 스킬(SKILL.md)이나 도구(MCP tool)를 매 요청에 모두 등록할 것인가, 아니면 필요할 때 동적으로 로드할 것인가?"**

직관적으로는 "동적이 효율적"이라고 느낄 수 있습니다 — 사용 안 하는 것을 빼면 토큰이 절약되니까요. 하지만 **prompt caching**을 함께 고려하면 결론이 뒤집힙니다.

이 문서는 두 가지 사례 (SKILL.md, MCP Tool)를 통해 정적/동적 로딩의 트레이드오프를 분석하고, 우리 프로젝트의 결정 근거를 기록합니다.

---

## 1. 핵심 충돌 — Prompt Caching과 동적 로딩

### Bedrock prompt caching 작동 방식

Bedrock의 prompt caching은 **반복되는 컨텍스트를 캐시 체크포인트로 표시하면 90% 비용 할인**을 제공합니다.

| 토큰 유형 | 비용 배수 | 설명 |
|-----------|----------|------|
| Cache Write | 1.25x | 캐시에 처음 쓸 때 25% 추가 비용 (1회) |
| Cache Read | 0.1x | 캐시에서 읽을 때 90% 할인 |
| Regular Input | 1.0x | 일반 입력 토큰 |

**핵심 제약**:
- 첫 번째 cache checkpoint는 **최소 1,024 토큰** 이상
- 캐시는 **순차적**으로 작동: prefix가 동일해야 cache hit
- Prefix가 달라지면 그 이후 모든 토큰은 cache miss

### 동적 로딩이 캐싱에 미치는 영향

동적 로딩 = 매 요청에 따라 시스템 프롬프트나 도구 정의가 달라짐 = **prefix 변화** = **cache 분열**.

```
요청 1: [system + skill_A + tools] → cache entry 1
요청 2: [system + skill_B + tools] → cache entry 2 (다름)
요청 3: [system + skill_A + skill_B + tools] → cache entry 3 (또 다름)
```

각 unique 조합마다 별도 cache entry가 생기고, 캐시 hit율이 떨어집니다. 극단적인 경우 매 요청이 cache miss입니다.

**이것이 이 문서의 핵심 통찰입니다**: "동적 최적화"는 캐싱과 근본적으로 충돌합니다.

---

## 2. SKILL.md 사례 — AgentSkills 플러그인 분석

### 현재 패턴: AgentSkills 동적 로딩

이 프로젝트는 Strands SDK의 `AgentSkills` 플러그인을 사용합니다:

```python
agent = Agent(
    system_prompt=base_prompt,
    plugins=[AgentSkills(skills=skills_dir)],  # ← 동적 로더
    ...
)
```

작동 방식:
1. `BeforeInvocationEvent`에서 `AgentSkills._on_before_invocation()` 발동
2. 에이전트의 `system_prompt`를 문자열로 읽어 `<available_skills>` XML 블록을 append
3. `agent.system_prompt = new_string` 으로 재할당

### 발견된 부작용 — Turn 1 캐싱 무효화

이 재할당 과정에서 `agent.system_prompt`가 **`SystemContentBlock` 리스트에서 문자열로 다운캐스트**됩니다. 결과적으로 사용자가 명시적으로 추가한 `cachePoint` 블록이 사라집니다:

```python
# 사용자가 의도한 구조
system_prompt=[
    SystemContentBlock(text=...),
    SystemContentBlock(cachePoint={"type": "default"}),  # ← 캐시 포인트
]

# AgentSkills 처리 후 (다운캐스트)
system_prompt = "...텍스트만 평탄화된 문자열..."  # cachePoint 사라짐!
```

이로 인해 **Turn 1 시스템 프롬프트 캐싱이 작동하지 않습니다**. (자세한 분석은 `docs/prompt-caching.md` 참고.)

### Static 대안의 토큰 수학

**Static = `create_agent()`에서 SKILL.md를 직접 읽어 시스템 프롬프트에 inline**

```python
def create_agent(dev_name):
    skill_path = PROJECT_ROOT / "skills" / dev_name / "SKILL.md"
    skill_content = skill_path.read_text()
    skill_content = skill_content.replace("{skill_dir}", str(skill_path.parent))

    base_prompt = (PROJECT_ROOT / "prompts" / "system_prompt.md").read_text()
    combined = f"{base_prompt}\n\n## Active Skill\n\n{skill_content}"

    return Agent(
        system_prompt=[
            SystemContentBlock(text=combined),
            SystemContentBlock(cachePoint={"type": "default"}),
        ],
        tools=[shell, file_read],
        # plugins 제거 ─ AgentSkills 사용 안 함
    )
```

| 구성 요소 | AgentSkills (현재) | Static (대안) |
|-----------|-------------------|---------------|
| 시스템 프롬프트 | ~400 토큰 | ~400 토큰 |
| SKILL.md 내용 | ~250 토큰 (런타임 주입) | ~250 토큰 (생성 시 inline) |
| `<available_skills>` XML wrapper | ~150 토큰 | 없음 |
| 매 턴 `skills` 도구 호출 | 1회 (~50 토큰 + 100ms) | **0회** |
| **Turn 1 캐싱** | ❌ (cachePoint 무효화) | ✅ (1,024 임계 통과 조건부) |

### 1,024 토큰 임계의 함정

**중요**: Static으로 가도 시스템 프롬프트 + SKILL.md 합계가 1,024 토큰 미만이면 캐싱이 작동하지 않습니다.

현재 우리 트림된 시스템 프롬프트 (~400) + SKILL.md (~250) = **~650 토큰**. **임계 미만**입니다.

따라서 Static 전환만으로는 캐싱 활성화가 보장되지 않으며, **시스템 프롬프트를 부풀리는 추가 작업**이 필요합니다 (예: few-shot 예시, edge case 가이드, 메모리 활용 패턴 등 ~600-800 토큰 추가).

부풀린 시스템 프롬프트 (~1,200) + SKILL.md (~250) + 도구 정의 (~250) = **~1,700 토큰** → ✅ 캐싱 활성화.

### SKILL.md 결정의 트레이드오프

| 항목 | AgentSkills (현재) | Static (대안) |
|------|-------------------|---------------|
| 매 턴 `skills` 도구 호출 | 1회 (낭비) | 0회 |
| Turn 1 캐싱 | ❌ | ✅ (조건부) |
| Turn 2+ 캐싱 | ✅ (turn boundary) | ✅ (turn boundary) |
| 코드 단순성 | 보통 (플러그인 의존) | 단순 |
| 디버그 출력 가독성 | 보통 (`<available_skills>` XML) | 좋음 (XML 없음) |
| 데모에서 "magic" | 플러그인 자동 로딩 | SKILL.md 직접 가시화 |
| 다중 스킬 지원 | 자연스러움 | 어려움 (모두 inline 필요) |
| 1 dev = 1 skill 패턴 | 적합 | 적합 |

---

## 3. MCP Tool 사례 — 30개 MCP의 시나리오

### 질문

> "만약 우리가 30개 MCP 서버를 사용한다면, 정적/동적 결정이 SKILL.md와 비슷할까?"

### 본질적 차이

| 항목 | SKILL.md | MCP Tool |
|------|----------|----------|
| **데이터 형식** | 자연어 텍스트 (가이드, 지시) | 구조화된 JSON 스키마 |
| **위치** | 시스템 프롬프트에 inline | API 요청의 `tools` 파라미터 |
| **모델 사용 방식** | 추론 시 참고 (행동 가이드) | 명시적 호출 (`tool_use` 블록) |
| **개당 토큰 비용** | ~250 토큰 (가변) | ~100-300 토큰 (고정에 가까움) |
| **Lazy load 가능?** | 부분적 (AgentSkills 패턴) | 매우 어려움 |

핵심 차이: **MCP tool은 "스키마"라서 형식이 엄격합니다.** 한 번 등록되면 모델이 정확한 형식으로 호출할 수 있어야 하므로, 런타임 추가/제거가 SKILL.md보다 훨씬 까다롭습니다.

### 30개 MCP의 토큰 수학

**30개 MCP 도구 × ~150 토큰 = ~4,500 토큰** (도구 정의만)

#### 시나리오 A: Static (모든 30개 도구를 매 요청에 등록)

| 구성 | 토큰 |
|------|------|
| 시스템 프롬프트 | ~400 |
| 30 MCP tool 스키마 | ~4,500 |
| **합계 (정적 부분)** | **~4,900** |

**캐싱 적용 시**:
- Cache write 1회: 4,900 × 1.25 = 6,125
- Cache read 매 턴: 4,900 × 0.1 = **490 effective 토큰/턴**
- 10턴 세션: 6,125 + 9 × 490 = **~10,535 effective**

#### 시나리오 B: Dynamic (필요한 도구만 등록)

런타임에 사용자 의도를 분류해서 평균 5개 도구만 등록한다고 가정:

| 구성 | 토큰 |
|------|------|
| 시스템 프롬프트 | ~400 |
| 5 MCP tool 스키마 | ~750 |
| **합계** | **~1,150** |

**캐싱 적용 시 (가정: 동일 도구 집합 cache hit율 ~50%)**:
- 캐시 히트한 턴: ~115 effective
- 캐시 미스한 턴: ~1,150 (full)
- 평균: ~630 effective/턴
- 10턴 세션: ~6,300 effective

#### 비교

| 방식 | 10턴 effective 토큰 | 코드 복잡도 |
|------|---------------------|-------------|
| Static + caching | ~10,535 | **단순** |
| Dynamic + 부분 caching | ~6,300 | 복잡 |
| 캐싱 없음 (참고) | ~50,000 | 단순하지만 비쌈 |

Dynamic이 토큰만 보면 ~40% 절감하지만, **추가 비용**이 있습니다:

1. **의도 분류 LLM 호출** — "어떤 도구를 로드할지" 결정 자체에 LLM이 필요할 수 있음 (~500 토큰 + 1초 지연)
2. **휴리스틱 오류** — 잘못된 도구 집합 선택 시 모델이 다시 호출해야 함
3. **캐시 분열** — unique 조합이 많을수록 cache 히트율 감소
4. **유지보수 부담** — 도구 분류 로직이 비즈니스 로직에 섞임

이 비용을 감안하면 **Static + caching이 운영 측면에서 거의 항상 우위**입니다.

### Dynamic이 진짜 유리한 시나리오

다음 조건 중 하나라도 해당될 때만 Dynamic을 고려:

- **수백~수천 개 도구** — 4,500 토큰을 훨씬 넘어 컨텍스트 윈도우 압박
- **세션마다 완전히 다른 도구 집합** — cache 분열이 어차피 불가피
- **보안 격리** — 일부 도구는 특정 사용자만 접근 가능 (필요 시에만 노출)
- **컨텍스트 윈도우 한계** — 도구 정의가 대화 히스토리 공간을 잠식

30개 정도면 이 임계점들을 넘지 않습니다.

---

## 4. 통합 원칙 — "동적 최적화는 캐싱의 적"

### 결정 매트릭스

| Agent당 entity 수 | SKILL.md | MCP Tool | 추천 |
|-------------------|----------|----------|------|
| 1 entity (1 skill, 1 tool) | sejong → standup | sejong → 1 deploy tool | **Static** |
| ~5 entity | sejong → 5 skills | sejong → 5 dev tools | **Static** |
| ~30 entity (안정적) | sejong → 30 skills | sejong → 30 tools | **Static** |
| ~30 entity (가변적) | per-session 다름 | per-session 다름 | Dynamic 검토 |
| 수백+ entity | (희귀) | API 마켓플레이스 | Dynamic 필수 |

**핵심**: agent **당** entity 수가 중요합니다. 시스템 전체 entity 총량이 아닙니다.

예를 들어 30개 SKILL.md가 디스크에 존재해도, 각 agent (`create_agent(dev_name)`)가 1개씩만 사용한다면 그 agent에게는 1 entity 시나리오입니다.

### 일반 원칙

> **"가능한 한 정적으로 유지하라. 캐싱이 비용을 절약하게 두라."**

LLM 시스템 설계에서 가장 큰 비용 절감 메커니즘은 **prompt caching**입니다. 캐싱은 "정적이고 반복적인 컨텍스트"에서만 작동합니다.

동적 최적화는 다음 조건이 모두 충족될 때만 합리적입니다:
1. 정적 컨텍스트가 컨텍스트 윈도우를 압박할 정도로 큼
2. 동적으로 결정되는 부분이 작고 명확함
3. 캐시 분열의 추가 비용을 감수할 수 있음

대부분의 프로젝트는 이 조건을 만족하지 않으므로, **Static이 기본 선택**이어야 합니다.

---

## 5. 우리 프로젝트의 결정 (현재 시점)

### 현재 패턴

`developer-briefing-agent`는 **시나리오 A (1 dev = 1 skill)** 패턴을 사용합니다:
- 각 dev_name 당 1개 SKILL.md
- `create_agent(dev_name)`이 해당 dev의 SKILL.md만 로드
- `/switch sunshin`이 새 agent + 새 SKILL.md 로드

30명까지 확장해도 패턴은 동일합니다 — 각 사용자는 자기 SKILL.md만 봅니다.

### 추천: Static + 부풀린 시스템 프롬프트

이 패턴에 가장 적합한 아키텍처:

1. **AgentSkills 제거** → `create_agent()`에서 SKILL.md를 직접 inline
2. **시스템 프롬프트 부풀리기** (~1,200-1,500 토큰):
   - 응답 형식 few-shot 예시
   - Edge case 처리 가이드
   - 메모리 컨텍스트 활용 패턴
   - 시간 표현 해석 규칙 (오늘/어제/이번 주)
3. **결과**: 시스템 프롬프트 + SKILL.md + 도구 정의 합계 ~1,700 토큰 → 캐싱 활성화

### 얻는 것

- **Turn 1 캐싱 ON** — 프로덕션에서 매 첫 턴 비용 절감
- **매 턴 `skills` 도구 호출 제거** — ~50 토큰 + ~100ms 절약
- **코드 단순화** — 플러그인 의존성 제거
- **디버그 출력 깨끗** — `<available_skills>` XML 사라짐
- **데모 교육성 향상** — SKILL.md → 시스템 프롬프트 매핑이 직접 보임

### 잃는 것 (현재 패턴에서는 거의 없음)

- 다중 스킬 동적 활성화 (사용 안 함)
- 스킬 메타데이터 자동 발견 (사용 안 함)
- AgentSkills 플러그인의 "magic" 인상 (대체 가능)

### 결정 미루기 — 언제 재검토할 것인가

다음 시점에 이 결정을 다시 검토해야 합니다:

- **Multi-skill 에이전트가 필요해질 때** — 한 사용자가 여러 스킬을 동적으로 활용하고 싶어할 때
- **스킬 발견이 필요할 때** — 사용자가 "무엇을 할 수 있어?"라고 묻는 시나리오
- **MCP 도구 수가 100개를 넘을 때** — 컨텍스트 윈도우 압박이 시작되는 지점
- **세션마다 도구 집합이 달라질 때** — cache 분열이 불가피해지는 시점

---

## 6. 미래 확장성 고려사항

### Multi-skill 에이전트로 진화하려면

만약 미래에 sejong이 standup, PR review, code search 등 여러 스킬을 동시에 쓰는 형태로 진화한다면:

**옵션 1**: 모든 스킬을 시스템 프롬프트에 inline (5-10개까지는 OK)
**옵션 2**: AgentSkills 같은 동적 로더로 다시 전환 (10개 이상)
**옵션 3**: 하이브리드 — 항상 사용하는 "기본 스킬"은 inline, 옵션 스킬은 동적

이때 토큰 비용을 측정해서 결정합니다. 1,500-3,000 토큰 정도의 다중 스킬 inline은 캐싱과 잘 어울립니다.

### MCP 도구로 진화하려면

만약 GitHub API를 직접 호출하는 MCP 서버, Jira MCP, Slack MCP 등을 추가한다면:

- 처음 ~30개까지: Static 등록 + 캐싱 (이 문서의 권장)
- 50-100개: 여전히 Static 가능, 토큰 비용 모니터링 필요
- 100+개: Dynamic 검토 필수, cache 분열 vs 토큰 절감 비교

---

## 7. 부록 — 토큰 계산 가정

이 문서의 토큰 계산은 다음 가정을 기반으로 합니다:

| 항목 | 가정 |
|------|------|
| Bedrock cache 최소 임계 | 1,024 토큰 (첫 체크포인트) |
| Cache write 비용 | 1.25x (일반 input의 1.25배) |
| Cache read 비용 | 0.1x (일반 input의 90% 할인) |
| SKILL.md 평균 크기 | ~250 토큰 (1KB 내외) |
| MCP tool 정의 평균 크기 | ~150 토큰 (이름 + 설명 + 스키마) |
| 시스템 프롬프트 (트림) | ~400 토큰 (22줄) |
| 시스템 프롬프트 (부풀림) | ~1,200-1,500 토큰 (~80줄) |
| 도구 정의 합계 (현재) | ~250 토큰 (shell + file_read) |

**근거**:
- 한국어 1글자 ≈ 0.5-1.5 토큰 (Claude tokenizer)
- 영어 1단어 ≈ 1.3 토큰
- JSON 스키마는 구조 자체가 토큰을 차지

이 가정은 대략적이며, 실제 토큰 수는 Bedrock의 응답 메타데이터로 정확히 측정해야 합니다.

---

## 참고 자료

- `docs/prompt-caching.md` — Bedrock prompt caching의 구체적 구현과 AgentSkills 충돌 분석
- `docs/prompt-flow.md` — 메시지 흐름과 hook 이벤트 타이밍
- `shared/memory_hooks.py` — `_restore_system_prompt_cache` 워크어라운드의 비효과 입증 (이미 제거됨)
- Strands SDK `vended_plugins/skills/agent_skills.py` — `_on_before_invocation`의 시스템 프롬프트 다운캐스트 위치

---

## 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-04-11 | 최초 작성 — SKILL.md와 MCP Tool의 정적/동적 로딩 분석 |
