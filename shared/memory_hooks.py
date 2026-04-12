"""
memory_hooks.py — AgentCore Memory 훅 프로바이더

Strands HookProvider로 3개 콜백을 등록합니다:
  - retrieve_context (BeforeInvocation): 첫 턴에 시맨틱 검색, 이후 턴에 cachePoint 관리
  - dump_prompt (BeforeModelCall): debug 모드에서 LLM 입력 시각화
  - save_interaction (AfterInvocation): 마지막 user-assistant 쌍을 Memory에 저장

MEMORY_ID가 없으면 이 훅 자체가 등록되지 않습니다 (example_single_shot.py/chat.py에서 조건 분기).

사용법:
    from shared.memory_hooks import StandupMemoryHooks
    hooks = [StandupMemoryHooks(memory_id, dev_name)]
    agent = Agent(..., hooks=hooks)
"""

import logging
import os

from bedrock_agentcore.memory import MemoryClient
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterInvocationEvent, BeforeInvocationEvent, BeforeModelCallEvent

logger = logging.getLogger(__name__)


class StandupMemoryHooks(HookProvider):
    """개발자별 스탠드업 메모리 훅.

    BeforeInvocationEvent (retrieve_context):
      - 첫 턴: AgentCore Memory에서 시맨틱 검색 → user 메시지에 컨텍스트 주입
      - 이후 턴: 검색 건너뜀, 메시지 cachePoint만 관리 (moving + anchor)
    BeforeModelCallEvent (dump_prompt):
      - debug 모드에서만 작동, LLM에 보내는 프롬프트를 색상 코딩으로 시각화
    AfterInvocationEvent (save_interaction):
      - 마지막 user-assistant 쌍을 Memory에 저장 (주입된 메모리 컨텍스트는 제외)
    """

    def __init__(self, memory_id: str, dev_name: str, region: str | None = None, debug: bool = False, session_id: str | None = None):
        """Args:
            memory_id: AgentCore Memory 리소스 ID (create_memory.py로 생성)
            dev_name: 개발자 이름 — Memory namespace(standup/actor/{dev_name}/facts) 결정
            region: AWS 리전 (None이면 AWS_REGION 환경 변수 사용)
            debug: True면 dump_prompt가 LLM 입력을 터미널에 시각화
            session_id: Memory 이벤트 그룹화 키 (None이면 "{dev_name}-standup")
        """
        self.memory_id = memory_id
        self.dev_name = dev_name
        self.debug = debug
        self.session_id = session_id or f"{dev_name}-standup"
        self.client = MemoryClient(
            region_name=region or os.getenv("AWS_REGION")
        )
        # Per-turn counters for dump_prompt iteration tracking
        self._turn_call_count = 0
        self._last_dumped_count = 0

    def retrieve_context(self, event: BeforeInvocationEvent):
        """호출 전: 두 가지 분기로 동작합니다.

        첫 턴 (agent.messages 비어있음):
          - user 입력을 쿼리로 AgentCore Memory에서 시맨틱 검색 (top_k=5)
          - 결과를 "[이전 대화에서 알게 된 정보]" 블록으로 user 메시지에 삽입

        이후 턴 (agent.messages에 히스토리 있음):
          - 메모리 검색 건너뜀 (agent.messages가 인세션 컨텍스트 처리)
          - 기존 cachePoint 전부 제거 후 재배치:
            moving cachePoint → 마지막 user 메시지
            anchor cachePoint → 첫 user 메시지 (히스토리 10+ 메시지일 때만)
          - Bedrock 한도: 요청당 cache_control 최대 4개 (tools + system + 2 message)
        """
        # 새 턴 시작 시 dump_prompt 카운터 리셋
        self._turn_call_count = 0
        self._last_dumped_count = 0

        try:
            # BeforeInvocationEvent 시점에서 agent.messages에는 아직 현재 사용자 메시지가 없음
            # event.messages에 현재 입력이 있고, agent.messages에는 이전 턴들이 있음
            history = event.agent.messages
            input_messages = event.messages

            # 색상 체계: CYAN = Step 2/6 retrieve_context (메모리 읽기)
            if self.debug:
                print(f"\n\033[0;36m[DEBUG 🔍 retrieve_context] history: {len(history)}건, input: {len(input_messages) if input_messages else 0}건\033[0m")

            # 첫 번째 턴에서만 검색 (이후 턴은 agent.messages가 처리)
            if history:
                user_messages = [m for m in history if m["role"] == "user"]
                if user_messages:
                    # 턴 경계 캐시: user 메시지에 cachePoint 부착 (Strands 내장 패턴과 일치)
                    # Bedrock 한도: 요청당 cache_control 최대 4개 (tools + system + 최대 2 message)
                    # 전략: moving cp (마지막 user msg) + anchor cp (첫 user msg, 히스토리 길 때)
                    removed_count = 0
                    for msg in history:
                        content = msg.get("content", [])
                        if not isinstance(content, list):
                            continue
                        new_content = [
                            b for b in content
                            if not (isinstance(b, dict) and "cachePoint" in b)
                        ]
                        if len(new_content) != len(content):
                            removed_count += len(content) - len(new_content)
                            msg["content"] = new_content

                    # user 메시지 인덱스 수집
                    user_indices = [i for i, m in enumerate(history) if m["role"] == "user"]

                    if user_indices:
                        # moving cachePoint: 마지막 user 메시지에 부착
                        last_user_idx = user_indices[-1]
                        last_user_content = history[last_user_idx].get("content", [])
                        if isinstance(last_user_content, list):
                            last_user_content.append({"cachePoint": {"type": "default"}})

                        # anchor cachePoint: 히스토리가 10+ 메시지이고 user 메시지가 2개 이상이면
                        # 첫 번째 user 메시지에 고정 앵커 — lookback 20블록 한계 대비
                        anchor_idx = None
                        if len(history) > 10 and len(user_indices) > 1 and user_indices[0] != last_user_idx:
                            anchor_idx = user_indices[0]
                            anchor_content = history[anchor_idx].get("content", [])
                            if isinstance(anchor_content, list):
                                anchor_content.append({"cachePoint": {"type": "default"}})

                        if self.debug:
                            anchor_msg = f", anchor at msg {anchor_idx}" if anchor_idx else ""
                            print(f"\033[2;36m  → 턴 경계 캐시 이동 (moving at msg {last_user_idx}{anchor_msg}, removed {removed_count} old cachePoints)\033[0m")

                    if self.debug:
                        print(f"\033[2;36m  → 첫 턴 아님 (이전 {len(user_messages)}턴) — 검색 건너뜀\033[0m\n")
                    return

            # 입력 메시지에서 쿼리 추출
            user_query = ""
            if input_messages:
                for msg in input_messages:
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and "text" in block:
                                user_query = block["text"]
                                break
                    elif isinstance(msg, str):
                        user_query = msg
                    if user_query:
                        break

            if not user_query:
                return

            namespace = f"standup/actor/{self.dev_name}/facts"
            memories = self.client.retrieve_memories(
                memory_id=self.memory_id,
                namespace=namespace,
                query=user_query,
                top_k=5,
            )

            if not memories:
                return

            # 검색된 기억을 텍스트로 조합
            context_parts = []
            for mem in memories:
                if isinstance(mem, dict):
                    content = mem.get("content", {})
                    if isinstance(content, dict):
                        text = content.get("text", "").strip()
                        if text:
                            context_parts.append(f"- {text}")

            if not context_parts:
                return

            context_text = "\n".join(context_parts)
            context_block = {
                "text": (
                    f"[이전 대화에서 알게 된 정보]\n{context_text}\n\n"
                    f"위 정보를 참고하되, 현재 질문에 관련된 내용만 활용하세요.\n\n"
                )
            }

            # 입력 메시지에 컨텍스트 삽입
            if input_messages:
                for msg in input_messages:
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        msg["content"].insert(0, context_block)
                        break
            logger.info("Retrieved %d memories for %s", len(context_parts), self.dev_name)

            # 블록 전체를 CYAN으로 감쌈 — Step 2 retrieve 시각적 단일 덩어리
            if self.debug:
                print(f"\n\033[0;36m[DEBUG 🔍 retrieve_context]")
                print(f"  query: {user_query}")
                print(f"  namespace: {namespace}")
                print(f"  results: {len(context_parts)}건")
                for i, part in enumerate(context_parts, 1):
                    print(f"  [{i}] {part}")
                print(f"\033[0m")

        except Exception as e:
            logger.warning("Failed to retrieve memories: %s", e)
            if self.debug:
                print(f"\n\033[0;31m[DEBUG ❌ retrieve_context] {e}\033[0m\n")

    def save_interaction(self, event: AfterInvocationEvent):
        """호출 후: 마지막 user-assistant 쌍을 AgentCore Memory에 저장합니다.

        역순 탐색으로 가장 최근 쌍만 추출합니다. tool 호출/결과 메시지는 건너뜁니다.
        retrieve_context가 주입한 "[이전 대화에서 알게 된 정보]" 블록은 제외하여
        메모리가 자기 자신을 다시 저장하는 것을 방지합니다.
        """
        try:
            messages = event.agent.messages
            if len(messages) < 2:
                return

            # 마지막 사용자 + 어시스턴트 메시지 쌍 추출
            # messages에 tool 호출/결과가 섞여 있으므로 역순으로 탐색
            interaction = []
            last_assistant = None
            last_user = None
            for msg in reversed(messages):
                if msg["role"] == "assistant" and last_assistant is None:
                    text_parts = []
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and "text" in block:
                            text_parts.append(block["text"])
                    text = "\n".join(text_parts)
                    if text:
                        last_assistant = text
                elif msg["role"] == "user" and last_user is None:
                    text_parts = []
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and "text" in block:
                            if not block["text"].startswith("[이전 대화에서 알게 된 정보]"):
                                text_parts.append(block["text"])
                    text = "\n".join(text_parts)
                    if text:
                        last_user = text
                if last_assistant and last_user:
                    break

            if last_user:
                interaction.append((last_user, "USER"))
            if last_assistant:
                interaction.append((last_assistant, "ASSISTANT"))

            if not interaction:
                return

            self.client.create_event(
                memory_id=self.memory_id,
                actor_id=self.dev_name,
                session_id=self.session_id,
                messages=interaction,
            )
            logger.info("Saved interaction for %s", self.dev_name)

            # 색상 체계: GREEN = Step 4 save_interaction (메모리 쓰기)
            if self.debug:
                print(f"\n\033[0;32m[DEBUG 💾 save_interaction]\033[0m")
                print(f"\033[0;32m  session_id: {self.session_id}\033[0m")
                for text, role in interaction:
                    preview = text[:80] + "..." if len(text) > 80 else text
                    print(f"\033[0;32m  [{role}] {preview}\033[0m")
                print()

        except Exception as e:
            logger.warning("Failed to save interaction: %s", e)
            if self.debug:
                print(f"\n\033[0;31m[DEBUG ❌ save_interaction] {e}\033[0m\n")

    def dump_prompt(self, event: BeforeModelCallEvent):
        """모델 호출 직전: LLM에 보내는 프롬프트를 색상 코딩으로 시각화합니다 (debug 모드에서만).

        한 턴에 도구 호출이 있으면 여러 번 발동합니다. 첫 호출은 전체 메시지를,
        이후 호출은 delta(추가된 메시지)만 표시합니다. _last_dumped_count로 추적.

        색상: BLUE=user 입력, WHITE=LLM 응답/도구 호출, YELLOW=도구 결과, MAGENTA=시스템.
        chat.py의 stream_response와 연동: agent._debug_text_label_pending 플래그로
        dump_prompt 박스와 실제 스트리밍 텍스트를 시각적으로 구분합니다.
        """
        if not self.debug:
            return

        self._turn_call_count += 1
        messages = event.agent.messages

        header_color = "\033[0;35m"   # MAGENTA — 박스 프레임
        n = self._turn_call_count
        is_first = n == 1
        delta_start = 0 if is_first else self._last_dumped_count
        new_count = len(messages) - delta_start

        # 박스 상단 — "Before LLM CALL #N" + 시점 명시
        if is_first:
            top_label = f"Before LLM CALL #{n} — initial prompt"
        else:
            top_label = f"Before LLM CALL #{n} — since call #{n-1} (+{new_count} new)"
        print(f"\n{header_color}┏━━━ {top_label} " + "━" * max(2, 60 - len(top_label)) + f"\033[0m")

        # 박스 안쪽 헤드라인 — "📥 입력 자료"
        if is_first:
            print(f"{header_color}  📥 Full prompt being assembled:\033[0m")
        else:
            print(f"{header_color}  📥 New since call #{n-1} (+{new_count} messages):\033[0m")
        print()

        # 시스템 프롬프트는 첫 호출에만 표시
        if is_first:
            system_prompt = getattr(event.agent, 'system_prompt', None)
            if system_prompt:
                print(f"\033[0;35m[SYSTEM]")
                print(f"{system_prompt}\033[0m")
                print()

        # 메시지 순회 — 엔티티 화살표 라벨 적용
        for i in range(delta_start, len(messages)):
            msg = messages[i]
            role = msg["role"].lower()
            content = msg.get("content", [])

            has_tool_result = any(
                isinstance(b, dict) and "toolResult" in b for b in content
            )
            has_tool_use = any(
                isinstance(b, dict) and "toolUse" in b for b in content
            )
            has_text = any(
                isinstance(b, dict) and "text" in b for b in content
            )

            if has_tool_result:
                # 🔧 TOOL → 🧠 AGENT (result)
                color = "\033[0;33m"   # YELLOW
                print(f"{color}[{i}] 🔧 TOOL → 🧠 AGENT (result)")
                for block in content:
                    if isinstance(block, dict) and "toolResult" in block:
                        for rc in block["toolResult"].get("content", []):
                            if isinstance(rc, dict) and "text" in rc:
                                print(f"  📋 {rc['text']}")
                print(f"\033[0m", end="")

            elif role == "user":
                # 👤 USER → 🧠 AGENT (input)
                color = "\033[0;34m"   # BLUE
                print(f"{color}[{i}] 👤 USER → 🧠 AGENT (input)")
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        print(f"{block['text']}")
                print(f"\033[0m", end="")

            elif role == "assistant":
                color = "\033[0;37m"   # WHITE
                # 텍스트 부분이 있으면 먼저 출력
                if has_text:
                    print(f"{color}[{i}] 💬 LLM → 🧠 AGENT (text response)")
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            print(f"{block['text']}")
                    print(f"\033[0m", end="")
                # 도구 호출 결정 부분이 있으면 별도 sub-block으로 출력
                # 라벨은 "LLM이 도구 호출을 결정"임을 명시 — agent는 LLM 결정을 그대로 전달
                if has_tool_use:
                    print(f"{color}[{i}] 💬 LLM → 🧠 AGENT (decided: call tool)")
                    for block in content:
                        if isinstance(block, dict) and "toolUse" in block:
                            tool_use = block["toolUse"]
                            tool_name = tool_use.get("name", "?")
                            tool_input = tool_use.get("input", {})
                            print(f"  🔧 {tool_name}({tool_input})")
                    print(f"\033[0m", end="")
                if not has_text and not has_tool_use:
                    print(f"{color}[{i}] 💬 LLM → 🧠 AGENT (empty)\033[0m")

            else:
                # 알 수 없는 역할 — fallback
                print(f"\033[0;33m[{i}] {role.upper()} (unknown role)\033[0m")

            print()  # 메시지 간 빈 줄

        self._last_dumped_count = len(messages)

        # 박스 하단 — "📤 발사" + 닫기
        print(f"{header_color}  📤 Sending all above to LLM #{n} now\033[0m")
        print(f"{header_color}┗━━━ END CALL #{n} " + "━" * 50 + f"\033[0m\n")

        # 다음 텍스트 burst가 LIVE 라벨을 다시 받도록 플래그 리셋
        # (chat.py:stream_response에서 이 플래그를 확인하여 라벨 출력 결정)
        event.agent._debug_text_label_pending = True

    def register_hooks(self, registry: HookRegistry) -> None:
        """Strands HookProvider 인터페이스 — 3개 이벤트에 콜백 등록."""
        registry.add_callback(BeforeInvocationEvent, self.retrieve_context)
        registry.add_callback(BeforeModelCallEvent, self.dump_prompt)
        registry.add_callback(AfterInvocationEvent, self.save_interaction)
