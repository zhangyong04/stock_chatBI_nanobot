#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票行情助手 -- nanobot 版

基于 nanobot 框架的股票查询与分析助手。
支持 SQL 查询可视化、ARIMA 价格预测、布林带异常检测、Prophet 周期性分析。

运行: python agent.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Windows UTF-8 兼容处理
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 工作空间路径
WORKSPACE = Path(__file__).resolve().parent

# nanobot 框架路径（通过 sys.path 引入，避免 -e 安装时中文路径编码问题）
NANOBOT_ROOT = Path(r"E:\AIstudent\AI大模型应用第21期\12-项目实战：ChatBI开发实战\nanobot-main")
if not NANOBOT_ROOT.exists():
    print("=" * 60)
    print("[错误] nanobot 框架目录不存在！")
    print(f"  路径: {NANOBOT_ROOT}")
    print("  请检查路径是否正确，或修改本文件中的 NANOBOT_ROOT 变量")
    print("=" * 60)
    sys.exit(1)
if str(NANOBOT_ROOT) not in sys.path:
    sys.path.insert(0, str(NANOBOT_ROOT))

# nanobot 导入（框架自身的依赖需通过 requirements.txt 安装）
try:
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import load_config
    from nanobot.nanobot import Nanobot, _make_provider
except ImportError as e:
    print("=" * 60)
    print("[错误] nanobot 框架或其依赖未安装！")
    print(f"  导入失败: {e}")
    print()
    print("  请执行以下命令安装业务依赖：")
    print("    pip install -r requirements.txt")
    print("=" * 60)
    sys.exit(1)

# 自定义工具导入
from tools.exc_sql import ExcSQLTool
from tools.arima_stock import ArimaStockTool
from tools.boll_detection import BollDetectionTool
from tools.prophet_analysis import ProphetAnalysisTool


class StockQueryHook(AgentHook):
    """监控工具调用，打印工具名和参数摘要"""
    
    async def before_execute_tools(self, ctx: AgentHookContext) -> None:
        for tc in ctx.tool_calls:
            print(f"  >> {tc.name}: {str(tc.arguments)[:120]}")


def build_bot() -> Nanobot:
    """构建股票助手"""
    # 检查 API Key
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not dashscope_key:
        print("[Error] DASHSCOPE_API_KEY 环境变量未设置")
        sys.exit(1)

    # 加载配置
    config = load_config(WORKSPACE / "config.json")
    config.providers.dashscope.api_key = dashscope_key
    config.agents.defaults.workspace = str(WORKSPACE)
    
    # 设置 Tavily API Key（可选）
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        config.tools.web.search.api_key = tavily_key

    # 创建 provider 和 loop
    provider = _make_provider(config)
    defaults = config.agents.defaults

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=WORKSPACE,
        model=defaults.model,
        max_iterations=defaults.max_tool_iterations,
        context_window_tokens=defaults.context_window_tokens,
        max_tool_result_chars=defaults.max_tool_result_chars,
        web_config=config.tools.web,
        exec_config=config.tools.exec,
        restrict_to_workspace=False,
        timezone=defaults.timezone,
    )

    # 注册自定义工具
    db_path = WORKSPACE / "stock_prices.db"
    image_dir = WORKSPACE / "image_show"
    image_dir.mkdir(exist_ok=True)

    loop.tools.register(ExcSQLTool(db_path, image_dir))
    loop.tools.register(ArimaStockTool(db_path, image_dir))
    loop.tools.register(BollDetectionTool(db_path, image_dir))
    loop.tools.register(ProphetAnalysisTool(db_path, image_dir))

    print("股票助手初始化成功！（nanobot 版）")
    return Nanobot(loop)


async def interactive_loop():
    """CLI 多轮交互模式"""
    bot = build_bot()
    
    print("\n" + "=" * 60)
    print("股票行情助手（nanobot 版）")
    print("=" * 60)
    print("可用功能：")
    print("  - SQL 查询 + 智能图表可视化")
    print("  - ARIMA 价格预测")
    print("  - 布林带超买超卖检测")
    print("  - Prophet 周期性分析")
    print("\n输入 quit/exit/q 退出\n")

    while True:
        try:
            query = input("\n请输入问题: ").strip()
            if not query:
                print("问题不能为空！")
                continue
            if query.lower() in ('quit', 'exit', 'q'):
                print("再见！")
                break

            print("正在查询...")
            result = await bot.run(
                query, 
                session_key="stock:cli", 
                hooks=[StockQueryHook()]
            )
            print(f"\n助手: {result.content}")
            
        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"出错: {e}")


async def single_query(question: str):
    """单次查询模式"""
    bot = build_bot()
    print(f"\n问题: {question}\n")
    
    result = await bot.run(
        question, 
        session_key="stock:single", 
        hooks=[StockQueryHook()]
    )
    
    print(f"\n{'=' * 60}")
    print(f"回答: {result.content}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        # Gradio Web 界面模式
        from app_gradio import main as gradio_main
        gradio_main()
    elif len(sys.argv) > 1:
        # 单次查询模式
        question = " ".join(sys.argv[1:])
        asyncio.run(single_query(question))
    else:
        # CLI 交互模式
        asyncio.run(interactive_loop())
