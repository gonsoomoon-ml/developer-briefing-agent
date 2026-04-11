"""
memory_hooks.py — AgentCore Memory 훅 프로바이더

에이전트 호출 전에 관련 기억을 검색하고, 호출 후에 대화를 저장합니다.

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

    BeforeInvocationEvent: 관련 기억을 검색하여 메시지에 주입
    AfterInvocationEvent: 대화를 이벤트로 저장
    """

    def __init__(self, memory_id: str, dev_name: str, region: str | None = None, debug: bool = False):
        self.memory_id = memory_id
        self.dev_name = dev_name
        self.debug = debug
        self.client = MemoryClient(
            region_name=region or os.getenv("AWS_REGION")
        )
        # Per-turn counters for dump_prompt iteration tracking
        self._turn_call_count = 0
        self._last_dumped_count = 0

    def retrieve_context(self, event: BeforeInvocationEvent):
        """호출 전: 세션의 첫 번째 턴에서만 관련 기억을 검색하여 컨텍스트로 주입합니다.

        이후 턴은 agent.messages가 인세션 컨텍스트를 처리하므로 검색을 건너뜁니다.
        이렇게 하면 토큰 낭비, 중복, 턴당 ~100-200ms 지연을 방지합니다.
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
                    # 턴 경계 캐시: 이전 턴의 마지막 메시지에만 cachePoint 1개 유지
                    # Bedrock 한도: 한 요청당 cache_control 최대 4개 (tools + system 차지)
                    # → 메시지 영역엔 1개만 두고, 새 턴마다 위치를 마지막 메시지로 이동
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

                    # 가장 최신 메시지에 cachePoint 1개 부착
                    last_msg = history[-1]
                    last_content = last_msg.get("content", [])
                    if isinstance(last_content, list):
                        last_content.append({"cachePoint": {"type": "default"}})
                        if self.debug:
                            print(f"\033[2;36m  → 턴 경계 캐시 이동 (message {len(history)-1}, removed {removed_count} old cachePoints)\033[0m")

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
        """호출 후: 사용자-어시스턴트 대화를 이벤트로 저장합니다."""
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
                session_id=f"{self.dev_name}-standup",
                messages=interaction,
            )
            logger.info("Saved interaction for %s", self.dev_name)

            # 색상 체계: GREEN = Step 4 save_interaction (메모리 쓰기)
            if self.debug:
                print(f"\n\033[0;32m[DEBUG 💾 save_interaction]\033[0m")
                print(f"\033[0;32m  session_id: {self.dev_name}-standup\033[0m")
                for text, role in interaction:
                    preview = text[:80] + "..." if len(text) > 80 else text
                    print(f"\033[0;32m  [{role}] {preview}\033[0m")
                print()

        except Exception as e:
            logger.warning("Failed to save interaction: %s", e)
            if self.debug:
                print(f"\n\033[0;31m[DEBUG ❌ save_interaction] {e}\033[0m\n")

    def dump_prompt(self, event: BeforeModelCallEvent):
        """모델 호출 직전: 프롬프트의 새 내용만 출력합니다 (debug 모드에서만).

        한 턴 안에서 여러 번 발동할 수 있습니다 (각 도구 호출 후 재호출).
        첫 호출: 시스템 프롬프트 + 전체 메시지 표시.
        이후 호출: 마지막 dump 이후 추가된 메시지(delta)만 표시.

        엔티티 흐름 라벨링:
          - 👤 USER → 🧠 AGENT (input)        : 실제 사용자 입력 (BLUE)
          - 💬 LLM → 🧠 AGENT (text)          : 에이전트 텍스트 응답 (WHITE)
          - 🧠 AGENT → 🔧 TOOL (calls)        : 에이전트의 도구 호출 결정 (WHITE)
          - 🔧 TOOL → 🧠 AGENT (result)       : 도구 실행 결과 (YELLOW)
          - [SYSTEM]                           : 시스템 프롬프트 (MAGENTA)
        박스 의미:
          - 박스 = "Agent가 LLM에게 N번째 호출을 보낼 준비"
          - 박스 안 = "그 호출의 입력 (delta)"
          - 박스 닫힘 = "지금 발사"
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
        registry.add_callback(BeforeInvocationEvent, self.retrieve_context)
        registry.add_callback(BeforeModelCallEvent, self.dump_prompt)
        registry.add_callback(AfterInvocationEvent, self.save_interaction)
