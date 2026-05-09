# Capricorn-V

> **v0.1.0** | 基于 Capricorn 的垂直领域扩展版

轻量级 Agent Runtime，垂直能力配置即用，tools / skills / workflows 一键扩展。

---

## 核心特性

- **原生 FC 循环** — LLM → tool_calls → execute → repeat，无 ReAct / 无状态机
- **垂直领域一键加载** — tools / MCP / skills / workflows 按 vertical_hub 组织，config.json 声明即用
- **三层记忆系统** — JSONL 会话 + MEMORY.md 长期记忆 + HISTORY.md 历史摘要
- **Cron 定时任务** — FC 管理定时任务，支持 SSE 实时推送
- **Gateway HTTP API** — aiohttp 轻量服务，对接前后端
- **MCP 协议支持** — stdio / SSE / streamable_http 三种方式接入外部服务

---

## 安装

```bash
git clone https://github.com/calderx4/Capricorn-V.git
cd Capricorn-V
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 API Key
```

---

## 快速开始

```bash
python run.py                                  # CLI 交互
python run.py --mode gateway                   # HTTP API + Cron
python run.py --mode gateway_with_webui        # HTTP API + Cron + Web 前端
```

---

## 内置工具

| 工具 | 文件 | 说明 |
|------|------|------|
| `read_file` | file_tools.py | 读取文件内容 |
| `write_file` | file_tools.py | 写入文件 |
| `edit_file` | file_tools.py | 编辑文件（diff 格式） |
| `list_files` | file_tools.py | 列出目录文件 |
| `exec` | exec_tools.py | 执行 shell 命令 |
| `todo` | todo_tools.py | 任务规划与追踪 |
| `cron` | cron_tools.py | 定时任务管理（create/list/pause/resume/remove） |
| `skill_view` | skill_tool.py | 按需加载技能说明 |
| `memory_update` | memory_tools.py | 更新长期记忆 |
| `history_search` | memory_tools.py | 搜索历史摘要 |
| `bia_update` | bia_tools.py | 行为修正 |

---

## 内置技能

| 技能 | 说明 |
|------|------|
| `self-evolution` | 自进化技能 — 根据执行结果自动优化工作流 |

---

## 内置工作流

| 工作流 | 说明 |
|--------|------|
| `memory_consolidation` | 自动整合超长对话记忆 |
| `self-evolution` | 根据执行结果迭代优化 |

---

## MCP 服务

| 服务器 | 说明 |
|--------|------|
| `minimax` | MiniMax 多模态 MCP，支持联网搜索，图片/视频/语音/音乐生成 |

---

## 项目结构

```
Capricorn-V/
├── run.py                      # 启动入口（3种模式）
├── config/
│   └── settings.py            # Pydantic 配置模型
├── agent/
│   ├── executor.py             # CapricornAgent 工厂类
│   ├── agent.py                # CapricornGraph（FC 循环）
│   ├── scheduler.py            # CronScheduler
│   ├── gateway.py              # HTTP API 服务
│   └── notification.py         # 通知总线
├── capabilities/
│   ├── capability_registry.py  # 能力注册中心
│   ├── vertical_loader.py      # 垂类加载器
│   └── skills/manager.py       # 技能管理器
├── core/
│   ├── base_tool.py           # BaseTool 抽象基类
│   └── base_workflow.py       # BaseWorkflow 抽象基类
├── memory/
│   ├── session.py             # SessionManager（JSONL 会话）
│   ├── long_term.py           # LongTermMemory（MEMORY.md）
│   └── history.py             # HistoryLog（HISTORY.md）
├── vertical_hub/              # 垂类能力中心
│   ├── manifest.yaml          # 全局注册表
│   └── default/              # 默认垂类（通用能力）
│       ├── vertical.yaml
│       ├── tools/             # BaseTool 子类
│       ├── mcp/config.json    # MCP 配置
│       ├── skills/            # SKILL.md 技能包
│       ├── workflows/         # BaseWorkflow 子类
│       └── prompts/           # system.md / cron.md / bia.md
└── workspace/                 # 运行时工作区
```

---

## Gateway HTTP API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat` | POST | 对话（支持 thread_id 多会话） |
| `/task` | POST | 异步任务 |
| `/task/{id}` | GET | 查询任务状态 |
| `/jobs` | GET | 列出 Cron 任务 |
| `/events` | GET | SSE 实时推送 |
| `/notifications` | GET | 查询通知 |
| `/notifications/read` | POST | 标记已读 |
| `/health` | GET | 健康检查 |

---

## 二次开发

### 添加新垂类

详见 [docs/vertical/how-to-add-vertical.md](docs/vertical/how-to-add-vertical.md)。

### 加工具

在垂类 `tools/` 下新建 `.py`，继承 `BaseTool`：

```python
from typing import Any, Dict
from core.base_tool import BaseTool

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "工具描述"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {...}, "required": [...]}

    async def execute(self, **kwargs: Any) -> Any:
        return result
```

### 接 MCP

在垂类 `mcp/config.json` 配置：

```json
{
  "server-name": {
    "type": "stdio",
    "command": "uvx",
    "args": ["mcp-server-package"],
    "env": {"KEY": "${ENV_VAR}"},
    "enabled": true,
    "enabled_tools": ["*"]
  }
}
```

---

## 外部项目集成

支持四种集成方式，详见 [docs/vertical/how-to-add-vertical.md#外部项目集成-capricorn](docs/vertical/how-to-add-vertical.md#外部项目集成-capricorn)。

| 方式 | 适用场景 |
|------|----------|
| HTTP Gateway | 任何语言的前后端项目，推荐 |
| Python 模块导入 | Python 项目直接使用 |
| Docker 部署 | 容器化生产环境 |
| 嵌入 Web 应用 | FastAPI/Flask 子模块 |

---

## 配置

环境变量使用 `${VAR_NAME}` 格式注入：

```json
{
  "llm": {
    "provider": "openai",
    "model": "MiniMax-M2",
    "api_key": "${OPENAI_API_KEY}",
    "api_base": "https://api.minimax.chat"
  }
}
```

---

## 日志

日志位于 `logs/` 目录：
- `trace.log` — 全量日志
- `cron.log` — Cron 相关
- `gateway.log` — HTTP 请求相关

---

<p align="center">
  <em>原生 FC · 极简循环 · 垂直能力一键扩展</em>
</p>
