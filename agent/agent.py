"""
Agent - 原生 Function Calling 循环

职责：
- 构建 System Prompt
- FC 循环：LLM 调用 → 工具执行 → 终止判断
- 并发工具执行
- 迭代上限和熔断保护
"""

import asyncio
import time
from datetime import datetime
from typing import Dict

TOOL_TIMEOUT = 300  # 单个工具执行全局超时 5 分钟

from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage, BaseMessage,
)
from loguru import logger

from pathlib import Path

from core.utils import strip_thinking_tags
from core import trace
from core.prompt_utils import (
    build_tools_section, build_skills_section, build_memory_section,
    build_bia_section, PromptBuilder,
)


class CapricornGraph:
    """Capricorn Agent — 原生 Function Calling 循环"""

    def __init__(
        self,
        capability_registry,
        skill_manager,
        session_manager,
        long_term_memory,
        history_log,
        llm_client=None,
        sandbox: bool = True,
        max_iterations: int = 50,
        exclude_tools: list = None,
        system_prompt_override: str = None,
        system_prompt_path: str = None,
        bia_path: str = None,
    ):
        self.capability_registry = capability_registry
        self.skill_manager = skill_manager
        self.session_manager = session_manager
        self.long_term_memory = long_term_memory
        self.history_log = history_log
        self.llm_client = llm_client
        self.sandbox = sandbox
        self.max_iterations = max_iterations
        self._exclude_tools = set(exclude_tools or [])
        self.system_prompt_override = system_prompt_override
        self.system_prompt_path = system_prompt_path
        self.bia_path = bia_path

        # 预绑定工具（排除指定工具）
        if self.llm_client:
            tools = self.capability_registry.get_langchain_tools()
            if self._exclude_tools:
                tools = [t for t in tools if t.name not in self._exclude_tools]
            self._llm_with_tools = self.llm_client.bind_tools(tools)
        else:
            self._llm_with_tools = None
            logger.warning("LLM client not initialized")

    async def run(self, user_input: str, thread_id: str = "default", notifications: str = "") -> str:
        """运行 FC 循环"""
        logger.info(f"Running agent with thread_id: {thread_id}")

        session = self.session_manager.get_session(thread_id)

        system_prompt = self._build_system_prompt()
        if notifications:
            system_prompt += f"\n\n{notifications}"
        history_messages = session.get_history(max_messages=0)

        messages = [
            SystemMessage(content=system_prompt),
            *[self._dict_to_message(msg) for msg in history_messages],
            HumanMessage(content=user_input),
        ]

        session.add_message("user", user_input)

        # 记录本轮输入的 messages 结构
        logger.debug(f"[Trace] 输入 messages 结构: {self._summarize_messages(messages)}")
        logger.debug(f"[Trace] 用户输入: {user_input}")

        if not self._llm_with_tools:
            return "LLM 客户端未初始化"

        tools_used = []

        try:
            for i in range(self.max_iterations):
                round_start_ts = time.monotonic()
                logger.info(f"Thinking... (iteration {i + 1})")
                trace.round_start(i + 1, len(messages))

                response = await self._llm_with_tools.ainvoke(messages)
                messages.append(response)

                response_content = self._extract_content(response)
                logger.debug(f"[Trace] LLM 响应 (iter {i + 1}): {response_content[:500]}")

                if not (hasattr(response, "tool_calls") and response.tool_calls):
                    round_latency = int((time.monotonic() - round_start_ts) * 1000)
                    trace.round_end(i + 1, 0, round_latency)
                    logger.debug(f"[Trace] 无工具调用，FC 循环结束 (iter {i + 1})")
                    break

                tool_names = [tc["name"] for tc in response.tool_calls]
                tool_args = [{"name": tc["name"], "args": tc["args"]} for tc in response.tool_calls]
                logger.info(f"Tool calls: {tool_names}")
                logger.debug(f"[Trace] 工具调用详情: {tool_args}")

                # 保存 AI 工具调用到 session（含 reasoning_content）
                ai_tool_calls = []
                for tc in response.tool_calls:
                    ai_tool_calls.append({
                        "id": tc["id"],
                        "name": tc["name"],
                        "args": tc["args"],
                    })
                rc = response.additional_kwargs.get("reasoning_content")
                session.add_message("assistant", response_content or "",
                                    tool_calls=ai_tool_calls,
                                    reasoning_content=rc)

                # 并发执行工具（带 trace）
                tool_messages = await self._execute_tools(response.tool_calls, round=i + 1)
                messages.extend(tool_messages)
                tools_used.extend(tool_names)

                # 保存工具返回到 session
                for tm in tool_messages:
                    session.add_message("tool", tm.content, tool_call_id=tm.tool_call_id)

                # 每轮写盘（防崩溃丢消息）
                self.session_manager.save_session(session)

                round_latency = int((time.monotonic() - round_start_ts) * 1000)
                trace.round_end(i + 1, len(tool_names), round_latency)

                for tm in tool_messages:
                    logger.debug(f"[Trace] 工具返回 (id={tm.tool_call_id}): {tm.content}")

            final_response = self._extract_content(messages[-1])

            # 迭代上限检查
            if i >= self.max_iterations - 1 and (hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls):
                logger.warning(f"FC loop hit max_iterations={self.max_iterations}")
                final_response += (
                    f"\n\n⚠ 已达到最大迭代次数 ({self.max_iterations})，"
                    f"任务可能未完成。"
                )

            logger.debug(f"[Trace] 最终回复: {final_response[:500]}")
            logger.debug(f"[Trace] 总迭代: {i + 1}, 使用工具: {tools_used}")
            final_rc = messages[-1].additional_kwargs.get("reasoning_content") if hasattr(messages[-1], "additional_kwargs") else None
            session.add_message("assistant", final_response, tools_used=tools_used,
                                reasoning_content=final_rc)
            self.session_manager.save_session(session)
            return final_response

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return f"执行失败: {str(e)}"

    async def _execute_tools(self, tool_calls, round: int = 0) -> list:
        async def _run_one(call):
            name, args = call["name"], call["args"]
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self.capability_registry.tools.execute(name, args),
                    timeout=TOOL_TIMEOUT,
                )
                content = str(result)
                latency = int((time.monotonic() - start) * 1000)
                logger.info(f"  {name} -> {content[:100]}")
                trace.tool_call(round, name, args, latency, "ok")
            except asyncio.TimeoutError:
                content = f"Error: Tool '{name}' execution timed out after {TOOL_TIMEOUT} seconds"
                latency = int((time.monotonic() - start) * 1000)
                logger.error(f"Tool {name} timed out")
                trace.tool_call(round, name, args, latency, "timeout")
            except Exception as e:
                content = f"Error: {e}"
                latency = int((time.monotonic() - start) * 1000)
                logger.error(f"Tool {name} failed: {e}")
                trace.tool_call(round, name, args, latency, "error")
            return ToolMessage(content=content, tool_call_id=call["id"])

        return await asyncio.gather(*[_run_one(tc) for tc in tool_calls])

    def _summarize_messages(self, messages: list) -> str:
        """生成 messages 列表的结构摘要"""
        summary = []
        for idx, msg in enumerate(messages):
            role = type(msg).__name__
            content = getattr(msg, "content", "")
            preview = content[:80].replace("\n", " ") if content else "(empty)"
            summary.append(f"  [{idx}] {role}: {preview}...")
        return f"共 {len(messages)} 条:\n" + "\n".join(summary)

    def _dict_to_message(self, msg: Dict) -> BaseMessage:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            return HumanMessage(content=content)
        elif role == "system":
            return SystemMessage(content=content)
        elif role == "tool":
            return ToolMessage(
                content=content,
                tool_call_id=msg.get("tool_call_id", ""),
            )
        else:
            ai_msg = AIMessage(content=content)
            if msg.get("tool_calls"):
                ai_msg.tool_calls = msg["tool_calls"]
            if msg.get("reasoning_content") is not None:
                ai_msg.additional_kwargs["reasoning_content"] = msg["reasoning_content"]
            return ai_msg

    def _extract_content(self, message) -> str:
        content = getattr(message, "content", "")

        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = "\n".join(text_parts) if text_parts else str(content)

        content = strip_thinking_tags(content)
        return content

    def _build_system_prompt(self) -> str:
        if self.system_prompt_override:
            return self.system_prompt_override

        builder = PromptBuilder(self.system_prompt_path)

        workspace_root = getattr(
            getattr(self.session_manager, "workspace", None), "root", "./workspace"
        )
        sandbox_note = "（沙盒模式：路径限制在工作区内）" if self.sandbox else "（可访问工作区外的路径）"
        builder.set("workspace_section", (
            f"# Workspace\n\n"
            f"工作区根目录：`{workspace_root}` {sandbox_note}\n"
            f"所有工具（read_file、write_file、list_files、exec）都以工作区根目录为基准。\n"
            f"路径直接写相对路径，例如 `main/my-task/index.html`。"
            f" 不要加 `{workspace_root}/` 前缀。\n\n"
            f"规则：\n"
            f"- 任务文件放在 `main/<任务名>/` 下，每个任务一个独立文件夹。\n"
            f"- `exec` 执行命令时默认在工作区根目录下运行。"
            f" 所以 `python main/my-task/app.py` 能直接找到文件。\n"
            f"- 操作前先用 `list_files` 查看工作区结构。"
        ))

        builder.set("bia_section", build_bia_section(self.bia_path))
        builder.set("memory_section", build_memory_section(self.long_term_memory))

        # agent.md 项目概述（CWD 相对：跟随启动目录，允许多项目共享同一 agent 进程）
        agent_md_section = ""
        agent_md_path = Path("agent.md")
        if agent_md_path.exists():
            content = agent_md_path.read_text(encoding="utf-8").strip()
            if content:
                agent_md_section = f"# Project Context\n\n{content}"
        builder.set("agent_md_section", agent_md_section)

        builder.set("tools_section", build_tools_section(self.capability_registry))
        builder.set("skills_section", build_skills_section(self.skill_manager))
        builder.set("current_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        return builder.build()
