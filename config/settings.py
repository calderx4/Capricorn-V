"""
Settings - 配置管理

职责：
- 加载配置文件
- 解析环境变量
- 配置验证
"""

import json
import os
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field
from loguru import logger


class WorkspaceConfig(BaseModel):
    """工作空间配置"""

    root: str = "./workspace"
    memory_dir: str = "memory"
    session_dir: str = "sessions"
    sandbox: bool = True  # True = 文件操作限制在 workspace 内；False = 允许访问任意路径

    def get_memory_path(self, filename: str) -> Path:
        """
        获取记忆文件路径

        Args:
            filename: 文件名（如 MEMORY.md, HISTORY.md）

        Returns:
            完整路径
        """
        return Path(self.root) / self.memory_dir / filename

    def get_session_path(self, thread_id: str) -> Path:
        """
        获取会话文件路径

        Args:
            thread_id: 会话 ID

        Returns:
            完整路径
        """
        return Path(self.root) / self.session_dir / f"{thread_id}.jsonl"


class LLMConfig(BaseModel):
    """LLM 配置"""

    provider: str
    model: str
    api_key: str
    api_base: str = None  # Optional: for custom API endpoints
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)


class MCPServerConfig(BaseModel):
    """MCP 服务器配置"""

    type: str  # stdio, sse, streamable_http
    command: str = None
    args: list = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: str = None
    headers: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    enabled_tools: list = Field(default_factory=lambda: ["*"])
    tool_timeout: int = Field(default=30, gt=0)


class MemoryConfig(BaseModel):
    """记忆整合配置"""

    enabled: bool = True
    message_threshold: int = Field(default=20, gt=0)
    messages_to_keep: int = Field(default=10, gt=0)
    token_threshold: int = Field(default=8000, gt=0)
    context_budget: int = Field(default=16000, gt=0)


class CronConfig(BaseModel):
    """Cron 调度配置"""

    enabled: bool = False
    tick_interval: int = Field(default=60, gt=0)
    output_dir: str = "cron/output"
    default_timeout: int = Field(default=300, gt=0)
    fresh_session: bool = False


class GatewayConfig(BaseModel):
    """Gateway HTTP 配置"""

    host: str = "127.0.0.1"
    port: int = Field(default=8080, gt=0)


class Config(BaseModel):
    """主配置类"""

    workspace: WorkspaceConfig
    llm: LLMConfig
    mcp_servers: Dict[str, MCPServerConfig] = Field(default_factory=dict)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    skills: Dict[str, Any] = Field(default_factory=dict)
    agent: Dict[str, Any] = Field(default_factory=dict)
    blocked_commands: list[str] = Field(default_factory=list)
    cron: CronConfig = Field(default_factory=CronConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    vertical_hub: str = "vertical_hub"
    verticals: list[str] = Field(default_factory=lambda: ["default"])

    @classmethod
    def load(cls, config_path: str) -> "Config":
        """
        加载配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            Config 实例

        Raises:
            FileNotFoundError: 配置文件不存在
            ValidationError: 配置验证失败
        """
        path = Path(config_path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 解析环境变量
        data = cls._resolve_env_vars(data)

        # 解析 workspace.root 为绝对路径（基于项目根目录 = config 文件的上上级）
        if "workspace" in data and "root" in data["workspace"]:
            ws_root = Path(data["workspace"]["root"])
            if not ws_root.is_absolute():
                project_root = path.parent.parent  # config/config.json → project root
                data["workspace"]["root"] = str((project_root / ws_root).resolve())

        config = cls(**data)
        logger.info(f"Configuration loaded from {config_path}")
        return config

    @staticmethod
    def _resolve_env_vars(data: Any) -> Any:
        """
        递归解析环境变量

        支持格式：
        - ${ENV_VAR_NAME} - 完整替换
        - "prefix ${ENV_VAR} suffix" - 字符串中嵌入
        """
        if isinstance(data, str):
            if "${" not in data:
                return data
            import re
            def _replace(m):
                val = os.getenv(m.group(1))
                if val is None:
                    logger.warning(f"Environment variable not set: {m.group(1)}")
                    return m.group(0)
                return val
            return re.sub(
                r'\$\{([^}]+)\}',
                _replace,
                data,
            )

        if isinstance(data, dict):
            return {k: Config._resolve_env_vars(v) for k, v in data.items()}

        if isinstance(data, list):
            return [Config._resolve_env_vars(item) for item in data]

        return data

    def __repr__(self) -> str:
        return f"<Config(workspace={self.workspace.root}, llm={self.llm.provider})>"
