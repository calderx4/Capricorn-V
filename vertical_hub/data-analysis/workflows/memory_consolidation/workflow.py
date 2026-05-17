"""
Memory Consolidation Workflow

并不由llm调用，而是被动触发。

自动化记忆整合流程，基于双重触发机制：
1. 消息数触发：未整合消息 ≥ 30 条
2. Token 数触发：未整合 tokens ≥ 8000
3. 上下文预算检查：总上下文 ≥ 16000 tokens

整合方式：
- LLM 调用 save_memory 工具
- 结果通过 LongTermMemory 和 HistoryLog 封装类写入
"""

import json
from datetime import datetime
from typing import Any, Dict, List

from loguru import logger

from core.base_workflow import BaseWorkflow
from core.token_counter import TokenCounter
from memory.long_term import LongTermMemory
from memory.history import HistoryLog
from vertical_hub.default.workflows.memory_consolidation.prompts import SAVE_MEMORY_TOOL, build_consolidation_prompt


class MemoryConsolidationWorkflow(BaseWorkflow):
    """记忆整合 Workflow"""

    auto_discover = False  # 依赖复杂，不走自动发现

    @property
    def name(self) -> str:
        return "memory_consolidation"

    @property
    def description(self) -> str:
        return "Consolidate session messages into long-term memory and history log."

    @property
    def required_tools(self) -> List[str]:
        return []

    # ========== 配置 ==========
    MAX_MESSAGES_BEFORE_CONSOLIDATION = 30
    MESSAGES_TO_KEEP = 15

    MAX_TOKENS_BEFORE_CONSOLIDATION = 8000
    TOKENS_TO_CONSOLIDATION_RATIO = 0.5

    TOTAL_CONTEXT_BUDGET = 16000

    def __init__(self, long_term_memory: LongTermMemory, history_log: HistoryLog,
                 llm_client, config: Dict = None):
        self.long_term_memory = long_term_memory
        self.history_log = history_log
        self.llm = llm_client
        self._consecutive_failures = 0
        self._max_failures = 3

        if config:
            self.MAX_MESSAGES_BEFORE_CONSOLIDATION = config.get(
                "max_messages", self.MAX_MESSAGES_BEFORE_CONSOLIDATION
            )
            self.MESSAGES_TO_KEEP = config.get(
                "messages_to_keep", self.MESSAGES_TO_KEEP
            )
            self.MAX_TOKENS_BEFORE_CONSOLIDATION = config.get(
                "max_tokens", self.MAX_TOKENS_BEFORE_CONSOLIDATION
            )
            self.TOTAL_CONTEXT_BUDGET = config.get(
                "context_budget", self.TOTAL_CONTEXT_BUDGET
            )

    def get_messages_to_consolidate(self, session_data: Dict) -> List[Dict]:
        messages = session_data.get("messages", [])
        n = len(messages)

        if n <= self.MESSAGES_TO_KEEP:
            return []

        # 消息数触发：按条数保留
        if n >= self.MAX_MESSAGES_BEFORE_CONSOLIDATION:
            return messages[:-self.MESSAGES_TO_KEEP]

        # Token 数触发：凑 tokens，同时强制保留 MESSAGES_TO_KEEP 条
        token_count = TokenCounter.count_messages_tokens(messages)
        if token_count >= self.MAX_TOKENS_BEFORE_CONSOLIDATION:
            target_tokens = int(token_count * (1 - self.TOKENS_TO_CONSOLIDATION_RATIO))
            # 必须保留的最后 MESSAGES_TO_KEEP 条不参与累加
            kept_tail = messages[-self.MESSAGES_TO_KEEP:]
            tail_tokens = TokenCounter.count_messages_tokens(kept_tail)
            budget = target_tokens - tail_tokens
            if budget <= 0:
                return messages[:-self.MESSAGES_TO_KEEP]
            accumulated = 0
            for i, msg in enumerate(messages):
                accumulated += TokenCounter.count_messages_tokens([msg])
                if accumulated > budget:
                    return messages[:max(1, i)]

        return messages[:-self.MESSAGES_TO_KEEP]

    async def execute(self, tools: Any = None, **kwargs) -> Any:
        session_data = kwargs.get("session_data", {})
        messages_to_consolidate = self.get_messages_to_consolidate(session_data)

        if not messages_to_consolidate:
            return True

        current_memory = self.long_term_memory.read()
        prompt = build_consolidation_prompt(
            current_memory,
            self._format_messages(messages_to_consolidate),
        )

        max_retries = 2
        for attempt in range(max_retries):
            try:
                llm_with_tools = self.llm.bind_tools(SAVE_MEMORY_TOOL)

                from langchain_core.messages import HumanMessage
                response = await llm_with_tools.ainvoke([
                    HumanMessage(content=prompt)
                ])

                if not hasattr(response, "tool_calls") or not response.tool_calls:
                    if attempt < max_retries - 1:
                        continue
                    return self._fail_or_raw_archive(messages_to_consolidate)

                tool_call = response.tool_calls[0]

                if tool_call.get("name") != "save_memory":
                    if attempt < max_retries - 1:
                        continue
                    return self._fail_or_raw_archive(messages_to_consolidate)

                args = tool_call.get("args", {})
                if isinstance(args, str):
                    args = json.loads(args)

                history_entry = args.get("history_entry", "")
                memory_update = args.get("memory_update", "")

                if not history_entry or not memory_update:
                    if attempt < max_retries - 1:
                        continue
                    return self._fail_or_raw_archive(messages_to_consolidate)

                self.history_log.append(history_entry)
                if memory_update != current_memory:
                    self.long_term_memory.write(memory_update)

                self._consecutive_failures = 0
                return True

            except Exception:
                if attempt < max_retries - 1:
                    continue
                return self._fail_or_raw_archive(messages_to_consolidate)

        return self._fail_or_raw_archive(messages_to_consolidate)

    def _format_messages(self, messages: List[Dict]) -> str:
        lines = []
        for msg in messages:
            if not msg.get("content"):
                continue
            role = msg.get("role", "unknown").upper()
            content = msg["content"]
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            timestamp = msg.get("timestamp", "?")[:16]
            tools = f" [tools: {', '.join(msg['tools_used'])}]" if msg.get("tools_used") else ""
            lines.append(f"[{timestamp}] {role}{tools}: {content}")
        return "\n".join(lines)

    def _estimate_total_context(self, session_data: Dict) -> int:
        messages = session_data.get("messages", [])
        memory_tokens = TokenCounter.estimate_tokens(self.long_term_memory.read())
        messages_tokens = TokenCounter.count_messages_tokens(messages)
        return memory_tokens + messages_tokens + 500

    def _fail_or_raw_archive(self, messages: List[Dict]) -> bool:
        self._consecutive_failures += 1

        if self._consecutive_failures < self._max_failures:
            return False

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.history_log.append(
            f"[{ts}] [RAW] {len(messages)} messages\n{self._format_messages(messages)}"
        )
        self._consecutive_failures = 0
        return True
