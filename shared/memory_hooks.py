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
from strands.hooks.events import AfterInvocationEvent, BeforeInvocationEvent

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

    def retrieve_context(self, event: BeforeInvocationEvent):
        """호출 전: 세션의 첫 번째 턴에서만 관련 기억을 검색하여 컨텍스트로 주입합니다.

        이후 턴은 agent.messages가 인세션 컨텍스트를 처리하므로 검색을 건너뜁니다.
        이렇게 하면 토큰 낭비, 중복, 턴당 ~100-200ms 지연을 방지합니다.
        """
        try:
            # BeforeInvocationEvent 시점에서 agent.messages에는 아직 현재 사용자 메시지가 없음
            # event.messages에 현재 입력이 있고, agent.messages에는 이전 턴들이 있음
            history = event.agent.messages
            input_messages = event.messages

            if self.debug:
                print(f"\n\033[0;36m[DEBUG 🔍 retrieve_context] history: {len(history)}건, input: {len(input_messages) if input_messages else 0}건\033[0m")

            # 첫 번째 턴에서만 검색 (이후 턴은 agent.messages가 처리)
            if history:
                user_messages = [m for m in history if m["role"] == "user"]
                if user_messages:
                    if self.debug:
                        print(f"\033[0;33m  → 첫 턴 아님 (이전 {len(user_messages)}턴) — 검색 건너뜀\033[0m\n")
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

            if self.debug:
                print(f"\n\033[0;36m[DEBUG 🔍 retrieve_context]\033[0m")
                print(f"  query: {user_query}")
                print(f"  namespace: {namespace}")
                print(f"  results: {len(context_parts)}건")
                for i, part in enumerate(context_parts, 1):
                    print(f"  [{i}] {part}")
                print()

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

            if self.debug:
                print(f"\n\033[0;32m[DEBUG 💾 save_interaction]\033[0m")
                print(f"  session_id: {self.dev_name}-standup")
                for text, role in interaction:
                    preview = text[:80] + "..." if len(text) > 80 else text
                    print(f"  [{role}] {preview}")
                print()

        except Exception as e:
            logger.warning("Failed to save interaction: %s", e)
            if self.debug:
                print(f"\n\033[0;31m[DEBUG ❌ save_interaction] {e}\033[0m\n")

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.retrieve_context)
        registry.add_callback(AfterInvocationEvent, self.save_interaction)
