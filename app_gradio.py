#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票行情助手 -- Gradio Web 界面

基于 nanobot 框架 + Gradio 的股票查询与分析 Web 界面。
参考 qwen-agent WebUI 风格，支持 SQL 查询可视化、ARIMA 预测、布林带检测、Prophet 分析。

运行: python app_gradio.py
"""

import asyncio
import os
import re
import sys
import threading
import time
import glob as glob_mod
import warnings
from pathlib import Path

# 抑制 plotly 导入警告（来自 prophet 的 logger.error，不是 warnings）
import logging as _logging
_logging.getLogger('prophet.plot').setLevel(_logging.CRITICAL)
os.environ['PROPHET_PLOTLY'] = '0'

# Windows UTF-8 兼容处理
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import gradio as gr

# 工作空间路径
WORKSPACE = Path(__file__).resolve().parent

# nanobot 框架路径
NANOBOT_ROOT = Path(r"E:\AIstudent\AI大模型应用第21期\12-项目实战：ChatBI开发实战\nanobot-main")
if str(NANOBOT_ROOT) not in sys.path:
    sys.path.insert(0, str(NANOBOT_ROOT))

# nanobot 导入
from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.nanobot import Nanobot, _make_provider

# 自定义工具导入
from tools.exc_sql import ExcSQLTool
from tools.arima_stock import ArimaStockTool
from tools.boll_detection import BollDetectionTool
from tools.prophet_analysis import ProphetAnalysisTool

# ====== 图片目录 ======
IMAGE_DIR = WORKSPACE / "image_show"
IMAGE_DIR.mkdir(exist_ok=True)


# ====== Bot 构建 ======

class GradioHook(AgentHook):
    """流式输出钩子：逐字推送 LLM 输出 + 工具调用日志"""

    def __init__(self, stream_buf: list, tool_log: list):
        self._buf = stream_buf      # 累积的完整文本 (list 以支持跨线程修改)
        self._log = tool_log        # 工具日志行
        self._raw_buf = ""          # 原始 token 缓冲（用于 strip_think）

    def wants_streaming(self) -> bool:
        return True

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        # 累积原始 token，手动 strip  标签（框架传的是原始 delta）
        self._raw_buf += delta
        # 简单 strip  块
        text = self._raw_buf
        while '<think>' in text:
            start = text.find('<think>')
            end = text.find('</think>', start)
            if end == -1:
                # 未闭合的 <think>，丢弃当前内容
                clean = text[:start]
                break
            text = text[:start] + text[end + len('</think>'):]
        else:
            clean = text
        # 计算增量
        old_len = len(self._buf[0]) if self._buf else 0
        new_text = clean
        if len(new_text) > old_len:
            delta_text = new_text[old_len:]
            if not self._buf:
                self._buf.append(new_text)
            else:
                self._buf[0] = new_text
            # 实时推送到 Gradio（通过 list 共享）

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        self._raw_buf = ""

    async def before_execute_tools(self, ctx: AgentHookContext) -> None:
        for tc in ctx.tool_calls:
            args_preview = str(tc.arguments)[:80]
            line = f"> 🔧 调用工具 `{tc.name}`: {args_preview}"
            self._log.append(line)

    async def after_iteration(self, ctx: AgentHookContext) -> None:
        if ctx.tool_calls:
            self._log.append("> ✅ 工具执行完成")


_bot_instance: Nanobot | None = None


def get_bot() -> Nanobot:
    """获取或创建 bot 单例"""
    global _bot_instance
    if _bot_instance is not None:
        return _bot_instance

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not dashscope_key:
        raise ValueError("DASHSCOPE_API_KEY 环境变量未设置")

    config = load_config(WORKSPACE / "config.json")
    config.providers.dashscope.api_key = dashscope_key
    config.agents.defaults.workspace = str(WORKSPACE)

    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        config.tools.web.search.api_key = tavily_key

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

    db_path = WORKSPACE / "stock_prices.db"
    image_dir = WORKSPACE / "image_show"
    image_dir.mkdir(exist_ok=True)

    loop.tools.register(ExcSQLTool(db_path, image_dir))
    loop.tools.register(ArimaStockTool(db_path, image_dir))
    loop.tools.register(BollDetectionTool(db_path, image_dir))
    loop.tools.register(ProphetAnalysisTool(db_path, image_dir))

    _bot_instance = Nanobot(loop)
    print("股票助手初始化成功！（Gradio 版）")
    return _bot_instance


# ====== 持久后台事件循环（解决 asyncio.Lock 跨循环问题） ======
_bg_loop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
_bg_thread.start()


# ====== Gradio 交互逻辑 ======

def chat_fn(user_message: str, chat_history: list, session_counter: int):
    """
    Gradio 聊天回调函数（支持流式输出）。
    返回: (chat_history, session_counter, gallery_images, input_clear)
    """
    if not user_message or not user_message.strip():
        yield chat_history, session_counter, [], ""
        return

    # 清理旧图片，确保 Gallery 只展示本次查询生成的图
    for f in IMAGE_DIR.glob('*'):
        if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif'):
            try:
                f.unlink()
            except Exception:
                pass

    # 添加用户消息到历史
    chat_history.append([user_message, None])
    yield chat_history, session_counter, [], ""

    # 共享缓冲区（主线程轮询 + 后台线程写入）
    stream_buf = []    # [accumulated_text]
    tool_log = []      # 工具日志行
    result_buf = []    # [final_content]
    done_event = threading.Event()

    async def on_stream_cb(delta: str):
        pass

    async def on_progress_cb(text: str, *, tool_hint: bool = False):
        if tool_hint and text:
            tool_log.append(f"> 🔧 {text}")

    async def _run_query():
        """在持久后台循环中执行"""
        try:
            bot = get_bot()
            hook = GradioHook(stream_buf, tool_log)
            session_key = f"stock:gradio:{session_counter}"
            result = await bot._loop.process_direct(
                user_message,
                session_key=session_key,
                on_stream=on_stream_cb,
                on_progress=on_progress_cb,
            )
            content = result.content if result else ""
            result_buf.append(content)
        except Exception as e:
            result_buf.append(f"__ERROR__:{e}")
        finally:
            done_event.set()

    # 提交到后台事件循环
    asyncio.run_coroutine_threadsafe(_run_query(), _bg_loop)

    # 主线程轮询更新 UI
    while not done_event.is_set():
        done_event.wait(timeout=0.3)
        display_parts = []
        if tool_log:
            display_parts.append('\n'.join(tool_log))
        if stream_buf:
            display_parts.append(stream_buf[0])
        display = '\n\n'.join(display_parts) if display_parts else "⏳ 思考中..."
        chat_history[-1][1] = display
        yield chat_history, session_counter, [], ""

    # 完成，获取最终结果
    final_text = result_buf[0] if result_buf else ""
    if not final_text and stream_buf:
        final_text = stream_buf[0]
    if final_text.startswith("__ERROR__:"):
        final_text = f"**出错:** {final_text[10:]}"
    if not final_text:
        final_text = "⚠️ 未获取到回复，请重试。"

    chat_history[-1][1] = final_text

    # 扫描本次生成的图片（清理后目录中所有图片都是本次查询的）
    gallery_images = []
    for ext in ('*.png', '*.jpg', '*.jpeg'):
        for p in IMAGE_DIR.glob(ext):
            gallery_images.append(str(p))
    gallery_images.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    yield chat_history, session_counter, gallery_images, ""


def clear_fn():
    """清空对话"""
    import time
    # 用时间戳作为新会话标识
    return [], int(time.time() * 1000), []


# ====== 构建 Gradio 界面 ======

def create_ui():
    """构建 Gradio Blocks 界面"""

    custom_css = """
    .gradio-container { max-width: 1200px !important; margin: auto !important; }
    .message { font-size: 14px; }
    #title-bar { text-align: center; padding: 10px 0; }
    #info-bar { text-align: center; color: #666; font-size: 13px; padding-bottom: 10px; }
    """

    with gr.Blocks(
        title="股票行情助手 - nanobot",
        css=custom_css,
        theme=gr.themes.Default(
            primary_hue=gr.themes.colors.blue,
        ),
    ) as demo:
        # 标题
        gr.HTML(
            '<div id="title-bar">'
            '<h2>📈 股票行情助手 <span style="font-size:14px;color:#999;">(nanobot 版)</span></h2>'
            '</div>'
        )
        gr.HTML(
            '<div id="info-bar">'
            '支持 SQL 查询可视化 · ARIMA 价格预测 · 布林带异常检测 · Prophet 周期性分析'
            '</div>'
        )

        # 会话状态
        session_state = gr.State(value=1000)

        with gr.Row():
            # ====== 左侧：聊天区域 ======
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    label="对话",
                    height=480,
                    show_copy_button=True,
                    bubble_full_width=False,
                    type="tuples",
                )

                # 图表展示区（工具生成的图片会显示在这里）
                gallery = gr.Gallery(
                    label="📊 图表",
                    columns=2,
                    height=300,
                    visible=True,
                    show_download_button=True,
                )

                with gr.Row():
                    user_input = gr.Textbox(
                        placeholder="输入你的问题，如：对比2025年贵州茅台和中芯国际的涨跌幅走势",
                        lines=1,
                        show_label=False,
                        scale=5,
                        container=False,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)

                with gr.Row():
                    clear_btn = gr.Button("🗑️ 清空对话", size="sm")

            # ====== 右侧：信息面板 ======
            with gr.Column(scale=1):
                gr.Markdown("### 💡 推荐问题")
                example_btns = gr.Examples(
                    label="点击试试",
                    examples=[
                        ["对比2025年贵州茅台和中芯国际的涨跌幅走势"],
                        ["预测贵州茅台未来10天价格"],
                        ["检测中芯国际过去一年的超买超卖点"],
                        ["用Prophet分析贵州茅台的周期性规律"],
                        ["查询五粮液最近30天的收盘价"],
                        ["对比四只股票2024年的表现"],
                    ],
                    inputs=[user_input],
                )

                gr.Markdown("---")
                gr.Markdown("### 📊 可用股票")
                gr.Markdown(
                    "| 代码 | 名称 |\n"
                    "|------|------|\n"
                    "| 600519.SH | 贵州茅台 |\n"
                    "| 000858.SZ | 五粮液 |\n"
                    "| 000776.SZ | 广发证券 |\n"
                    "| 688981.SH | 中芯国际 |\n"
                )

                gr.Markdown("---")
                gr.Markdown("### 🔧 工具列表")
                gr.CheckboxGroup(
                    label="已注册工具",
                    value=["exc_sql", "arima_stock", "boll_detection", "prophet_analysis", "web_search"],
                    choices=["exc_sql", "arima_stock", "boll_detection", "prophet_analysis", "web_search"],
                    interactive=False,
                )

        # ====== 事件绑定 ======

        # 发送按钮
        send_btn.click(
            fn=chat_fn,
            inputs=[user_input, chatbot, session_state],
            outputs=[chatbot, session_state, gallery, user_input],
        )

        # Enter 键发送
        user_input.submit(
            fn=chat_fn,
            inputs=[user_input, chatbot, session_state],
            outputs=[chatbot, session_state, gallery, user_input],
        )

        # 清空按钮
        clear_btn.click(
            fn=clear_fn,
            outputs=[chatbot, session_state, gallery],
        )

    return demo


# ====== 启动入口 ======

def main():
    print("=" * 60)
    print("股票行情助手 - Gradio Web 界面")
    print("=" * 60)

    # 启动时清理旧图片，确保 Gallery 只显示最新生成的
    for f in IMAGE_DIR.glob('*'):
        if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif'):
            try:
                f.unlink()
            except Exception:
                pass

    # 预初始化 bot
    try:
        get_bot()
    except Exception as e:
        print(f"[警告] Bot 预初始化失败: {e}")
        print("  首次对话时将重新初始化")

    demo = create_ui()

    print("\n正在启动 Web 界面...")
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
