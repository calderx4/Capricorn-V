"""
Executor - Agent 执行器

职责：
- 初始化所有组件
- 协调执行
- 资源管理
"""

from pathlib import Path
from typing import Optional
import importlib.util
from loguru import logger
from langchain_core.messages import AIMessage

from agent.agent import CapricornGraph
from config.settings import Config
from capabilities.capability_registry import CapabilityRegistry
from capabilities.vertical_loader import VerticalLoader
from capabilities.skills.manager import SkillManager
from memory.session import SessionManager
from memory.long_term import LongTermMemory
from memory.history import HistoryLog
from core import trace
from core.token_counter import TokenCounter


class CapricornAgent:
    """Capricorn Agent 执行器"""

    def __init__(self, config: Config, config_path: str = None):
        """
        初始化执行器

        Args:
            config: 配置对象
            config_path: 配置文件路径（用于 SessionManager 初始化 LLM）
        """
        self.config = config
        self.config_path = config_path
        self.graph: Optional[CapricornGraph] = None
        self.llm_client = None
        self.capability_registry: Optional[CapabilityRegistry] = None
        self.skill_manager: Optional[SkillManager] = None
        self.session_manager: Optional[SessionManager] = None
        self.long_term_memory: Optional[LongTermMemory] = None
        self.history_log: Optional[HistoryLog] = None
        self._cron_scheduler = None
        self._notification_bus = None
        self.vertical_loader: Optional[VerticalLoader] = None
        self._loaded_verticals: list[str] = []
        self._system_prompt_path: Optional[str] = None
        self._cron_prompt_path: Optional[str] = None
        self._bia_path: Optional[str] = None
        self._roles: dict = {}  # 角色配置

    @classmethod
    async def create(cls, config: Config, config_path: str = None, notification_bus=None) -> "CapricornAgent":
        """
        工厂方法：创建并初始化 Agent

        Args:
            config: 配置对象
            config_path: 配置文件路径（用于 SessionManager 初始化 LLM）
            notification_bus: 通知总线（可选）

        Returns:
            初始化后的 Agent
        """
        agent = cls(config, config_path)
        agent._notification_bus = notification_bus
        await agent.initialize()
        return agent

    async def initialize(self):
        """初始化所有组件"""
        logger.info("Initializing Capricorn Agent...")

        # 1. 初始化 LLM 客户端
        self._init_llm_client()

        # 2. 初始化技能管理器（空，由 VerticalLoader 加载）
        self.skill_manager = SkillManager()

        # 3. 初始化能力注册中心（空，由 VerticalLoader 加载）
        self.capability_registry = await CapabilityRegistry.create(
            workspace_root=self.config.workspace.root,
            sandbox=self.config.workspace.sandbox,
            skill_manager=self.skill_manager,
            blocked_commands=self.config.blocked_commands,
        )

        # 4. 初始化 VerticalLoader，加载所有声明的垂类
        project_root = str(Path(self.config_path).parent) if self.config_path else "."
        self.vertical_loader = VerticalLoader(
            hub_root=self.config.vertical_hub,
            project_root=project_root,
        )
        for vertical_name in self.config.verticals:
            await self._load_vertical(vertical_name)

        # 从当前垂类目录获取路径（独立模式：只加载一个垂类）
        if not self._loaded_verticals:
            raise RuntimeError("No verticals loaded. Check config.verticals setting.")
        active_vertical = self._loaded_verticals[-1]
        active_dir = self.vertical_loader.get_vertical_dir(active_vertical)
        self._bia_path = str(active_dir / "prompts" / "bia.md")
        self._active_dir = active_dir

        # 注册 skill_view 工具（如果有可用 skills）
        await self.capability_registry.register_skill_tools(self.skill_manager, vertical_dir=active_dir)

        # 注册 bia_update 工具
        bia_tool_path = active_dir / "tools" / "bia_tools.py"
        spec = importlib.util.spec_from_file_location("bia_tools", bia_tool_path)
        _bia_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_bia_mod)
        bia_tool = _bia_mod.BiaUpdateTool(bia_path=self._bia_path)
        self.capability_registry.tools.register(bia_tool, layer="builtin")

        # 5. 初始化会话管理器
        self.session_manager = SessionManager(
            self.config.workspace
        )

        # 6. 初始化长期记忆
        self.long_term_memory = LongTermMemory(self.config.workspace)

        # 7. 初始化历史日志
        self.history_log = HistoryLog(self.config.workspace)

        # 8. 初始化 Cron 调度器（在构建图之前，确保 cron 工具已注册）
        if self.config.cron.enabled:
            from agent.scheduler import CronScheduler

            # 动态加载 CronTool（auto_discover=False，需手动注册）
            cron_tool_path = self._active_dir / "tools" / "cron_tools.py"
            spec = importlib.util.spec_from_file_location("cron_tools", cron_tool_path)
            _mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mod)
            CronTool = _mod.CronTool

            self._cron_scheduler = CronScheduler(self.config)
            self._cron_scheduler.initialize(
                llm_client=self.llm_client,
                capability_registry=self.capability_registry,
                skill_manager=self.skill_manager,
                long_term_memory=self.long_term_memory,
                notification_bus=self._notification_bus,
                cron_prompt_path=self._cron_prompt_path,
                bia_path=self._bia_path,
                roles=self._roles,
                active_dir=str(self._active_dir),
            )

            cron_tool = CronTool(self._cron_scheduler)
            self.capability_registry.tools.register(cron_tool, layer="builtin")

        # 9. 注册 Team 工具（如果垂类定义了 roles）
        if self._roles:
            team_tool_path = self._active_dir / "tools" / "team_tools.py"
            if team_tool_path.exists():
                spec = importlib.util.spec_from_file_location("team_tools", team_tool_path)
                _team_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_team_mod)

                # 注册 task 工具
                task_tool = _team_mod.TaskManageTool(
                    workspace_root=self.config.workspace.root,
                )
                self.capability_registry.tools.register(task_tool, layer="builtin")

                # 注册 spawn 工具
                spawn_tool = _team_mod.SpawnTool(
                    llm_client=self.llm_client,
                    capability_registry=self.capability_registry,
                    skill_manager=self.skill_manager,
                    long_term_memory=self.long_term_memory,
                    roles=self._roles,
                    bia_path=self._bia_path,
                    workspace_root=self.config.workspace.root,
                    sandbox=self.config.workspace.sandbox,
                    max_iterations=self.config.agent.get("max_iterations", 50),
                )
                self.capability_registry.tools.register(spawn_tool, layer="builtin")
                logger.info(f"Team tools registered (roles: {list(self._roles.keys())})")

            # 自动注册 verifier cron（如果不存在）
            if self._cron_scheduler and "verifier" in self._roles:
                await self._auto_register_verifier_cron()

        # 10. 构建图（绑定所有工具到 LLM，包括 cron + team tools）
        self.graph = CapricornGraph(
            self.capability_registry,
            self.skill_manager,
            self.session_manager,
            self.long_term_memory,
            self.history_log,
            self.llm_client,
            sandbox=self.config.workspace.sandbox,
            max_iterations=self.config.agent.get("max_iterations", 50),
            system_prompt_path=self._system_prompt_path,
            bia_path=self._bia_path,
        )

        logger.info("✓ Capricorn Agent initialized")

    async def _load_vertical(self, name: str):
        """加载单个垂类"""
        result = await self.vertical_loader.load(
            name,
            self.capability_registry,
            self.skill_manager,
        )
        self._loaded_verticals.append(name)

        if result.get("system_prompt_path"):
            self._system_prompt_path = result["system_prompt_path"]
        if result.get("cron_prompt_path"):
            self._cron_prompt_path = result["cron_prompt_path"]
        if result.get("roles"):
            self._roles = result["roles"]

    def _init_llm_client(self):
        """初始化 LLM 客户端"""
        llm_config = self.config.llm

        if llm_config.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            self.llm_client = ChatAnthropic(
                model=llm_config.model,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
                api_key=llm_config.api_key
            )
        elif llm_config.provider == "openai":
            from langchain_openai import ChatOpenAI
            from langchain_openai.chat_models import base as _lc_base

            # 构建 ChatOpenAI 参数
            openai_params = {
                "model": llm_config.model,
                "temperature": llm_config.temperature,
                "max_tokens": llm_config.max_tokens,
                "api_key": llm_config.api_key
            }

            if llm_config.api_base:
                openai_params["base_url"] = llm_config.api_base

            self.llm_client = ChatOpenAI(**openai_params)

            # Patch：LangChain 解析 API 响应时不保留非标准字段（如 reasoning_content），
            # 序列化时也不带 additional_kwargs。两个方向都补回来。
            _LC_KNOWN_KEYS = {
                "role", "content", "name", "id", "function_call", "tool_calls",
                "audio", "refusal", "parsed",
            }

            _orig_to_msg = _lc_base._convert_dict_to_message
            def _to_msg_with_extras(_dict):
                msg = _orig_to_msg(_dict)
                if isinstance(msg, AIMessage):
                    for k, v in _dict.items():
                        if k not in _LC_KNOWN_KEYS and k not in msg.additional_kwargs:
                            msg.additional_kwargs[k] = v
                return msg
            _lc_base._convert_dict_to_message = _to_msg_with_extras

            _orig_to_dict = _lc_base._convert_message_to_dict
            def _to_dict_with_extras(message, api="chat/completions"):
                d = _orig_to_dict(message, api=api)
                if isinstance(message, AIMessage) and message.additional_kwargs:
                    for k, v in message.additional_kwargs.items():
                        if k not in d:
                            d[k] = v
                return d
            _lc_base._convert_message_to_dict = _to_dict_with_extras
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_config.provider}")

        logger.debug(f"Initialized LLM client: {llm_config.provider}/{llm_config.model}")
        if llm_config.api_base:
            logger.debug(f"Using custom API base: {llm_config.api_base}")

    async def chat(self, user_input: str, thread_id: str = "default") -> str:
        """
        执行对话

        Args:
            user_input: 用户输入
            thread_id: 会话 ID

        Returns:
            响应结果
        """
        if not self.graph:
            raise RuntimeError("Agent not initialized")

        # 对话开始前：检查并同步整合记忆（阻塞式）
        await self._check_and_consolidate_memory(thread_id)

        # 获取未读通知，注入到本次对话
        notifications = ""
        unread_ids = []
        if self._notification_bus:
            unread = self._notification_bus.get_unread()
            if unread:
                lines = []
                for n in unread:
                    d = n["data"]
                    ts = n["timestamp"][:16]
                    name = d.get("job_name", "未命名任务")
                    msg = d.get("message", "")[:300]
                    status = d.get("status", "")
                    icon = "✅" if status == "success" else "❌"
                    lines.append(f"{icon} [{ts}] {name}: {msg}")
                notifications = (
                    "# 未读通知\n\n"
                    "以下是你之前设定的定时任务执行结果，请在回复中视情况自然提及：\n\n"
                    + "\n".join(lines)
                )
                unread_ids = [n["id"] for n in unread]

        # 执行对话
        response = await self.graph.run(user_input, thread_id, notifications=notifications)

        # 对话成功后标记通知已读
        if unread_ids:
            await self._notification_bus.mark_read(unread_ids)

        return response

    async def _check_and_consolidate_memory(self, thread_id: str):
        """对话前检查：是否需要整合记忆。两种触发：条数或 token 数超阈值。"""
        try:
            mem_cfg = self.config.memory
            if not mem_cfg.enabled:
                return

            # 直接用内存中的 session，不重读文件
            session = self.session_manager.get_session(thread_id)
            messages = session.get_history(max_messages=0)

            if not messages:
                return

            # 触发条件 1：消息条数超阈值
            total = len(messages)
            triggered_by = None
            if total > mem_cfg.message_threshold:
                triggered_by = f"messages({total} > {mem_cfg.message_threshold})"

            # 触发条件 2：总 token 数超阈值（仅条数未触发时才算）
            if not triggered_by:
                est_tokens = TokenCounter.count_messages_tokens(messages)
                if est_tokens > mem_cfg.token_threshold:
                    triggered_by = f"tokens({est_tokens} > {mem_cfg.token_threshold})"

            if not triggered_by:
                return

            logger.info(f"Memory consolidation triggered by {triggered_by}")

            import sys
            mc_path = self._active_dir / "workflows" / "memory_consolidation" / "__init__.py"
            project_root = str(Path(__file__).parent.parent)
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            spec = importlib.util.spec_from_file_location("memory_consolidation", mc_path)
            _mc_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mc_mod)
            MemoryConsolidationWorkflow = _mc_mod.MemoryConsolidationWorkflow

            workflow = MemoryConsolidationWorkflow(
                long_term_memory=self.long_term_memory,
                history_log=self.history_log,
                llm_client=self.llm_client,
                config={
                    "max_messages": mem_cfg.message_threshold,
                    "messages_to_keep": mem_cfg.messages_to_keep,
                    "max_tokens": mem_cfg.token_threshold,
                    "context_budget": mem_cfg.context_budget,
                }
            )

            session_data = {"messages": messages}
            logger.info(f"Consolidating {len(messages)} messages, keep={mem_cfg.messages_to_keep}")
            success = await workflow.execute(session_data=session_data)
            logger.info(f"Consolidation result: {success}")

            if success:
                to_consolidate = workflow.get_messages_to_consolidate(session_data)
                num_remove = len(to_consolidate)
                remaining = messages[num_remove:]

                # 去掉开头的孤儿 tool 消息（其父 AIMessage 已被整合掉）
                while remaining and remaining[0].get("role") == "tool":
                    remaining.pop(0)

                trace.consolidation(triggered_by, len(messages), len(remaining), True)

                self.session_manager.rewrite_session(thread_id, remaining)

                logger.info(f"Consolidated {num_remove} messages, kept {len(remaining)}")
            else:
                logger.warning("Memory consolidation failed")
                trace.consolidation(triggered_by, len(messages), len(messages), False)

        except Exception as e:
            logger.exception(f"Memory consolidation error: {e}")

    async def cleanup(self):
        """清理资源"""
        logger.info("Cleaning up resources...")

        if self._cron_scheduler:
            self._cron_scheduler.stop()

        if self.capability_registry:
            await self.capability_registry.cleanup()

        logger.info("✓ Cleanup completed")

    async def _auto_register_verifier_cron(self):
        """自动注册 verifier 定时验收任务（仅当不存在时）"""
        existing = self._cron_scheduler.list_jobs()
        for job in existing:
            if "auto_verifier" in job.get("tags", []):
                logger.debug("Verifier cron already exists, skipping auto-registration")
                return

        await self._cron_scheduler.create_job(
            name="每日质量验收",
            schedule="0 18 * * *",
            prompt="执行质量验证流程。",
            role="verifier",
            fresh_session=True,
            tags=["auto_verifier"],
        )
        logger.info("Auto-registered verifier cron job (daily 18:00)")
