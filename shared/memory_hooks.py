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

    def __init__(self, memory_id: str, dev_name: str, region: str | None = None):
        self.memory_id = memory_id
        self.dev_name = dev_name
        self.client = MemoryClient(
            region_name=region or os.getenv("AWS_REGION")
        )

    def retrieve_context(self, event: BeforeInvocationEvent):
        """호출 전: 세션의 첫 번째 턴에서만 관련 기억을 검색하여 컨텍스트로 주입합니다.

        이후 턴은 agent.messages가 인세션 컨텍스트를 처리하므로 검색을 건너뜁니다.
        이렇게 하면 토큰 낭비, 중복, 턴당 ~100-200ms 지연을 방지합니다.
        """
        try:
            messages = event.agent.messages
            if not messages or messages[-1]["role"] != "user":
                return

            # 첫 번째 턴에서만 검색 (이후 턴은 agent.messages가 처리)
            user_messages = [m for m in messages if m["role"] == "user"]
            if len(user_messages) > 1:
                return

            # 마지막 사용자 메시지에서 쿼리 추출
            last_content = messages[-1].get("content", [])
            user_query = ""
            for block in last_content:
                if isinstance(block, dict) and "text" in block:
                    user_query = block["text"]
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

            # 사용자 메시지 앞에 컨텍스트 삽입
            messages[-1]["content"].insert(0, context_block)
            logger.info("Retrieved %d memories for %s", len(context_parts), self.dev_name)

        except Exception as e:
            logger.warning("Failed to retrieve memories: %s", e)

    def save_interaction(self, event: AfterInvocationEvent):
        """호출 후: 사용자-어시스턴트 대화를 이벤트로 저장합니다."""
        try:
            messages = event.agent.messages
            if len(messages) < 2:
                return

            # 마지막 사용자 + 어시스턴트 메시지 쌍 추출
            interaction = []
            for msg in messages[-2:]:
                role = "USER" if msg["role"] == "user" else "ASSISTANT"
                text_parts = []
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "text" in block:
                        # 주입된 컨텍스트 블록 제외
                        if not block["text"].startswith("[이전 대화에서 알게 된 정보]"):
                            text_parts.append(block["text"])
                text = "\n".join(text_parts)
                if text:
                    interaction.append((text, role))

            if not interaction:
                return

            self.client.create_event(
                memory_id=self.memory_id,
                actor_id=self.dev_name,
                session_id=f"{self.dev_name}-standup",
                messages=interaction,
            )
            logger.info("Saved interaction for %s", self.dev_name)

        except Exception as e:
            logger.warning("Failed to save interaction: %s", e)

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.retrieve_context)
        registry.add_callback(AfterInvocationEvent, self.save_interaction)
