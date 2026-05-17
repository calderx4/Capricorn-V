"""
Run - 启动入口

三种模式：
  python run.py                                  # CLI 交互（默认）
  python run.py --mode gateway                   # HTTP API + Cron，纯后台
  python run.py --mode gateway_with_webui        # HTTP API + Cron + Web 前端
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from agent.executor import CapricornAgent
from agent.gateway import Gateway
from agent.notification import NotificationBus
from config.settings import Config
from loguru import logger


class CapricornCLI:
    """CLI 交互界面"""

    def __init__(self, config_path: str = "config/config.json"):
        self.config_path = config_path
        self.config = None
        self.agent = None
        self.notification_bus = None

    async def start(self, mode: str = "interactive"):
        """启动"""
        print("🚀 Capricorn Agent 启动中...")

        try:
            self.config = Config.load(self.config_path)
            logger.info(f"Configuration loaded from {self.config_path}")

            self.notification_bus = NotificationBus()
            self.notification_bus.cleanup()

            self.agent = await CapricornAgent.create(
                self.config, self.config_path,
                notification_bus=self.notification_bus,
            )
            print("✓ Agent 已就绪")

            if mode == "interactive":
                await self._run_interactive()
            elif mode == "gateway":
                await self._run_gateway()
            elif mode == "gateway_with_webui":
                await self._run_gateway(webui=True)

        except FileNotFoundError as e:
            print(f"❌ 错误: 配置文件未找到 - {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Startup failed: {e}")
            print(f"❌ 启动失败: {e}")
            sys.exit(1)

    async def _run_interactive(self):
        """CLI 交互模式"""
        print("💡 输入 'exit' 或 'quit' 退出，'help' 查看帮助\n")
        while True:
            try:
                user_input = input("👤 You: ").strip()

                if not user_input:
                    continue
                if user_input.lower() in ('exit', 'quit'):
                    await self.agent.cleanup()
                    print("👋 再见！")
                    break
                if user_input.lower() == 'help':
                    self._show_help()
                    continue
                if user_input.lower() == 'clear':
                    import os
                    os.system('clear' if os.name == 'posix' else 'cls')
                    continue

                response = await self.agent.chat(user_input)
                print(f"\n🤖 Assistant: {response}\n")

            except KeyboardInterrupt:
                print("\n")
                await self.agent.cleanup()
                print("👋 再见！")
                break
            except Exception as e:
                logger.error(f"Error in interaction: {e}")
                print(f"\n❌ 错误: {e}\n")

    async def _run_gateway(self, webui: bool = False):
        """Gateway 模式（HTTP + Cron，可选 WebUI）"""
        gateway = Gateway(self.agent, self.config, notification_bus=self.notification_bus, webui=webui)

        tasks = [asyncio.create_task(gateway.start())]

        if self.agent._cron_scheduler:
            tasks.append(asyncio.create_task(self.agent._cron_scheduler.run()))

        print(f"✓ Gateway API: http://{self.config.gateway.host}:{self.config.gateway.port}")

        streamlit_proc = None
        if webui:
            webui_port = self.config.gateway.port + 1
            webui_path = Path(__file__).parent / "agent" / "webui" / "app.py"
            streamlit_proc = subprocess.Popen(
                [
                    sys.executable, "-m", "streamlit", "run",
                    str(webui_path),
                    "--server.port", str(webui_port),
                    "--server.headless", "true",
                    "--browser.gatherUsageStats", "false",
                ],
            )
            print(f"✓ WebUI: http://{self.config.gateway.host}:{webui_port}")

        if self.agent._cron_scheduler:
            print("✓ Cron scheduler started")
        print("按 Ctrl+C 退出")

        try:
            await asyncio.gather(*tasks)
        finally:
            if streamlit_proc:
                streamlit_proc.terminate()

    def _show_help(self):
        print("""
📖 可用命令：
  - exit/quit: 退出程序
  - help: 显示帮助
  - clear: 清空屏幕

💡 使用提示：
  - 直接输入问题与 Agent 对话
  - Agent 会自动调用相应的工具和技能
        """)


def main():
    parser = argparse.ArgumentParser(description="Capricorn Agent")
    parser.add_argument(
        "--mode",
        choices=["interactive", "gateway", "gateway_with_webui"],
        default="interactive",
        help="启动模式: interactive（默认）, gateway（API+Cron）, gateway_with_webui（API+Cron+Web前端）",
    )
    args = parser.parse_args()

    # 配置日志
    log_dir = Path(__file__).parent / "gateway" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_fmt = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    log_rotation = {"rotation": "10 MB", "retention": "7 days", "encoding": "utf-8"}

    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
    )
    logger.add(log_dir / "trace.log", format=log_fmt, level="DEBUG", **log_rotation)
    logger.add(
        log_dir / "cron.log", format=log_fmt, level="DEBUG", **log_rotation,
        filter=lambda r: "scheduler" in r["name"] or "cron" in r["name"].lower(),
    )
    logger.add(
        log_dir / "gateway.log", format=log_fmt, level="DEBUG", **log_rotation,
        filter=lambda r: "gateway" in r["name"].lower(),
    )

    cli = CapricornCLI()
    asyncio.run(cli.start(mode=args.mode))


if __name__ == "__main__":
    main()
