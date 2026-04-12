# AgentCore Runtime 실험 기록

이 문서는 AgentCore Runtime 배포, 멀티턴 대화 연속성, 프롬프트 캐싱 최적화에 대한 실험 과정과 결과를 기록합니다.

## 1. AgentCore 배포 (코드 변경 없이)

### 목표
Strands 로컬 에이전트를 코드 변경 없이 AgentCore Runtime에 배포.

### 결과
- `01_create_agentcore_runtime.py`로 in-place 업데이트 (42초 소요)
- `02_invoke_agentcore_runtime.py --dev_name sejong` 단발 호출 성공 (14.2초)
- 스트리밍, 스킬 로딩, GitHub 데이터 조회 모두 정상

---

## 2. 멀티턴 대화 연속성 문제 발견

### 문제
Turn 2에서 "이전 대화 내용이 없어서 파악하기 어렵습니다"라고 응답. `agentcore_runtime.py`가 매 요청마다 `create_agent(dev_name)`을 호출하여 새 `Agent` 인스턴스를 생성 → `agent.messages = []`로 초기화 → Turn 1 컨텍스트 유실.

### 시도 1: AgentCore Memory STM (list_events)

**접근**: `save_interaction`이 저장한 이벤트를 `list_events`로 다음 턴에 복원.

**결과**: 실패. `create_event` 직후 `list_events`가 빈 결과 반환 — AgentCore Memory의 **eventual consistency** 때문. 파이프 테스트에서 턴 간격이 수 밀리초라 인덱싱 지연에 걸림.

**검증**: otel 로그에서 Turn 2의 Bedrock 입력에 Turn 1 메시지가 없는 것을 확인.

### 시도 2: 모듈 레벨 Agent 캐시 (공식 패턴)

**발견**: 공식 Strands 튜토리얼(`amazon-bedrock-agentcore-samples/01-tutorials/01-AgentCore-runtime/01-hosting-agent/01-strands-with-bedrock-model`)에서 Agent를 **모듈 레벨**에 정의:

```python
# 공식 예제 — Agent가 엔트리포인트 바깥
agent = Agent(model=model, tools=[...])

@app.entrypoint
def handler(payload):
    response = agent(payload["prompt"])  # 같은 Agent 재사용
```

우리 코드는 엔트리포인트 안에서 매번 `create_agent()`를 호출하고 있었음. 멀티 개발자 지원을 위해 `_session_agents: dict[str, Agent]` 딕셔너리로 확장:

```python
_session_agents: dict[str, Agent] = {}

def _get_or_create_agent(dev_name, session_id=None):
    cache_key = f"{dev_name}:{session_id or 'default'}"
    if cache_key not in _session_agents:
        _session_agents[cache_key] = create_agent(dev_name, session_id=session_id)
    return _session_agents[cache_key]
```

**결과**: 아직 실패. Turn 2에서 여전히 "이전 대화 내용이 없어서..."

### 시도 3: runtimeSessionId 추가 (최종 해결)

**원인 발견**: AgentCore Runtime은 **Firecracker microVM 기반**. `runtimeSessionId` 없이 호출하면 매 요청이 새 microVM → 새 Python 프로세스 → 새 모듈 레벨 전역변수. 모듈 레벨 캐시가 있어도 다른 프로세스이므로 무용.

**수정**: `chat.py`에서 첫 응답의 `response.get('runtimeSessionId')`를 캡처하고 이후 호출에 재사용:

```python
response = client.invoke_agent_runtime(
    agentRuntimeArn=RUNTIME_ARN,
    qualifier="DEFAULT",
    runtimeSessionId=runtime_session_id,  # 이 파라미터가 핵심
    payload=payload,
)
```

**결과**: 성공.
- Turn 2가 Turn 1 컨텍스트를 완벽히 기억
- 도구 재실행 없음 (Turn 1의 GitHub JSON이 `agent.messages`에 보존)
- Turn 2 Input: 4,655 (Turn 1의 2,542보다 +2,113 = 히스토리 포함 확인)
- `/switch sunshin` 시 새 `runtimeSessionId` → 새 microVM → 세션 격리 확인

---

## 3. 프롬프트 캐싱 심층 분석

### 초기 관찰 (4턴 테스트)

```
Turn  Input   Output  CacheRead  CacheWrite  Total
-----------------------------------------------------
T1    2,107     781     9,754      4,877    17,519
T2    3,883   1,057    14,631      4,877    24,448
T3    5,959   1,302    19,508      4,877    31,646
T4    8,294   1,372    24,385      4,877    38,928
```

패턴: CacheRead +4,877/턴, CacheWrite 고정 4,877.

### 핵심 메커니즘: Backward Lookback

Anthropic 공식 문서에서 발견:

> "Cache reads look backward for entries that prior requests wrote. On each request the system walks backward one block at a time (최대 20블록), checking whether the prefix hash at each earlier position matches something already in the cache."

cachePoint를 이동해도 이전 캐시 엔트리가 삭제되지 않음 → lookback이 이전 위치를 찾아 Read.

### 누적 메트릭 vs 턴별 메트릭

`agentcore_runtime.py`가 보고하는 `accumulated_usage`는 Agent 객체에 **모든 호출을 합산**한 값. CacheWrite=4,877이 매 턴 "동일"하게 보인 것은 T1에서 한 번 Write된 후 누적값이 불변이었기 때문.

턴별 delta를 계산하면:
```
T1: dWrite=4,877 (시스템 프롬프트 최초 Write)
T2: dWrite=0     (이미 캐시됨)
T3: dWrite=0
```

### 캐시 범위: 모델 엔드포인트 단위 공유

Bedrock 프롬프트 캐시는 microVM별이 아닌 **모델 엔드포인트 전체에서 공유**. 이전 테스트가 5분 TTL 안에 캐시를 채웠으면 다음 테스트에서 Write=0.

### 메시지 cachePoint 동작 확인

로컬 테스트에서 monkey-patch로 실제 Bedrock 요청을 가로채 확인:

```
=== Turn 2 request ===
FOUND_CP: messages[0].content[1] = {'cachePoint': {'type': 'default'}} (role=user)
FOUND_CP: system[1] = {'cachePoint': {'type': 'default'}}
FOUND_CP: tools[2] = {'cachePoint': {'type': 'default'}}
accumulated: Read=9772, Write=323
```

메시지 cachePoint가 Bedrock에 정상 전달되고 Write도 발생 (323 tokens = 짧은 테스트 메시지의 delta). Cold cache 동기 테스트:

```
T1: dWrite=4,874 (시스템 프롬프트)
T2: dWrite=1,645 (Turn 1 메시지 delta)
T3: dWrite=526   (Turn 2 메시지 delta)
```

메시지 cachePoint Write는 **수백~수천 토큰** 수준 (대화 delta만), 시스템 프롬프트 전체(4,877)가 아님.

### 이전 분석의 정정

| 초기 분석 | 검증된 사실 |
|----------|------------|
| "CacheWrite 4,877 = 시스템 프롬프트가 매 턴 재Write" | 한 번만 Write, 누적값 불변 |
| "메시지 cachePoint 미작동 (Write=0)" | 정상 작동. 이전 테스트가 5분 TTL 안에 캐시를 채웠기 때문 |
| "턴별 메시지 Write = 4,877 (고정)" | 실제 526-1,645 토큰 (소량 delta) |
| "시스템 프롬프트가 cachePoint 이동 때문에 무효화" | 상위 변경만 하위 무효화. 메시지 변경은 시스템 캐시에 영향 없음 |

---

## 4. 캐싱 최적화

### 적용된 최적화

#### cachePoint를 user 메시지로 이동
- **변경 전**: `retrieve_context`가 `history[-1]` (assistant 메시지)에 부착
- **변경 후**: 마지막 user 메시지에 부착 (Strands SDK `_inject_cache_point` 내장 패턴과 일치)
- **효과**: T4 기준 Input -10%

#### 앵커 cachePoint 추가 (4번째 블록)
- 히스토리 >10 메시지일 때 첫 번째 user 메시지에 고정 cachePoint
- 20-block lookback 한계 대비 (장기 대화 캐시 유지)

### 차단된 최적화

#### 1h TTL
- 시도: `SystemContentBlock(cachePoint={"type": "default", "ttl": "1h"})`
- 결과: `ValidationException` — `"a ttl='1h' cache_control block must not come after a ttl='5m' cache_control block"`
- 원인: `cache_tools="default"`가 tools에 5분 TTL 고정. 요청 순서 `tools(5m) → system(1h)`이 제약 위반
- 해결: Strands SDK가 `cache_tools`에 TTL 파라미터를 지원해야 함

---

## 5. SlidingWindowConversationManager 적용

### 문제
30턴 테스트에서 누적 Input이 208K+ 토큰까지 증가 → 응답 지연 증가.

### 해결
```python
from strands.agent.conversation_manager import SlidingWindowConversationManager

Agent(
    conversation_manager=SlidingWindowConversationManager(window_size=20),
    ...
)
```

### 동작 방식 (Strands SDK 소스 확인)
1. `agent.messages` 수가 `window_size`를 초과하면 가장 오래된 tool result부터 truncate (앞뒤 200자 보존)
2. 그래도 초과하면 가장 오래된 메시지부터 삭제 (orphaned toolResult/toolUse 쌍 보호)
3. `per_turn=True` 옵션: 매 LLM 호출 전에 적용 (mid-turn context blowup 방지)

### 캐시 영향
첫 trim 발생 시 메시지 prefix가 변경되어 **한 턴 cache miss** 발생. 이후 새 prefix가 캐시되어 정상 Read+Write 패턴 복원. 지속적으로 캐시가 깨지는 것이 아님.

### 33턴 비교 테스트

```
Turn  Before(dInput)  After(dInput)  개선율
---------------------------------------------
T6        2,782          2,616       -6%   (window 미도달)
T10       6,845          4,397      -36%   (trimming 시작)
T15       7,266          3,323      -54%
T20       8,238          3,346      -59%
T25       8,537          3,501      -59%
T30       8,373          3,346      -60%
```

- 턴별 Input이 3,000-4,000에서 안정화 (window 없이는 8,000+까지 지속 증가)
- T30 기준 **60% Input 감소** → 응답 시간 직접 개선
- 33턴 누적 총 토큰: 135K vs 215K (-37%)
- 캐시 패턴 (CacheRead +4,877/턴) 유지 — 캐시 파괴 없음

---

## 6. 적용된 변경 요약

| 파일 | 변경 내용 |
|------|----------|
| `managed-agentcore/agentcore_runtime.py` | 모듈 레벨 `_session_agents` 딕셔너리 + `_get_or_create_agent()` + `SlidingWindowConversationManager(window_size=20)` |
| `managed-agentcore/chat.py` | `runtimeSessionId` 캡처 및 재사용 + `session_id` 생성/전달 |
| `shared/memory_hooks.py` | `session_id` 파라미터 추가 + cachePoint를 user 메시지로 이동 + 앵커 cachePoint (history >10) |
| `local-agent/strands_agent.py` | `SlidingWindowConversationManager(window_size=20)` |
| `local-agent/chat.py` | `SlidingWindowConversationManager(window_size=20)` |
| `docs/prompt-caching.md` | Backward lookback 메커니즘, 토큰 분류 공식, 실측 데이터, 최적화 전략 문서화 |

## 7. 아키텍처 비교

### Strands 로컬 (변경 없음)

```
chat.py → Agent(persistent) → agent.messages 자연 유지
                              SlidingWindow가 window_size 초과 시 trim
```

### AgentCore Runtime (변경 후)

```
chat.py → invoke_agent_runtime(runtimeSessionId=X)
       → 같은 microVM의 같은 Python 프로세스
       → _session_agents[key] → 같은 Agent 객체
       → agent.messages 자연 유지 (Strands 로컬과 동일)
       → SlidingWindow가 window_size 초과 시 trim
```

핵심: `runtimeSessionId`가 같은 microVM으로 라우팅 → 모듈 레벨 딕셔너리가 Agent를 보존 → Strands 로컬과 동일한 in-process 상태 유지.

## 8. 참고한 공식 샘플

| 샘플 | 경로 | 활용 |
|------|------|------|
| Strands 호스팅 튜토리얼 | `01-tutorials/01-AgentCore-runtime/01-hosting-agent/01-strands-with-bedrock-model` | 모듈 레벨 Agent 패턴 발견 |
| Managed Session Storage | `01-tutorials/01-AgentCore-runtime/10-managed-session-storage` | `runtimeSessionId` + `filesystemConfigurations` 패턴 |
| Streamlit Chat | `03-integrations/ux-examples/streamlit-chat` | `runtimeSessionId` 캡처/재사용 패턴 |
| SRE Agent | `02-use-cases/SRE-agent` | AgentCore Memory `ConversationMemoryManager` 패턴 |
