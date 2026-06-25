"""
boll_detection 工具 - 布林带(20日±2σ)超买超卖检测
"""

import asyncio
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg', force=True)  # 非交互后端，force=True 无视加载顺序
import logging as _logging
_logging.getLogger('matplotlib.font_manager').setLevel(_logging.ERROR)  # 抑制 bold 字体警告
from matplotlib.dates import DateFormatter, MonthLocator
import matplotlib.pyplot as plt

from nanobot.agent.tools.base import Tool

# 中文字体配置
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False


def _draw_boll_chart(df, stock_name, ts_code, save_path):
    """绘制布林带图表：价格 + MA20 + 上轨 + 下轨 + 异常点标注"""
    fig, ax = plt.subplots(figsize=(14, 6))

    dates = df['trade_date']
    close = df['close']
    ma20 = df['MA20']
    upper = df['upper']
    lower = df['lower']

    # 收盘价
    ax.plot(dates, close, color='#5470C6', linewidth=1.5, label='收盘价', zorder=3)

    # MA20
    ax.plot(dates, ma20, color='#FAC858', linewidth=1.2, linestyle='--', label='MA20', zorder=2)

    # 上轨/下轨
    ax.plot(dates, upper, color='#EE6666', linewidth=1, alpha=0.6, label='上轨 (+2σ)', zorder=2)
    ax.plot(dates, lower, color='#91CC75', linewidth=1, alpha=0.6, label='下轨 (-2σ)', zorder=2)

    # 布林带填充
    ax.fill_between(dates, lower, upper, alpha=0.08, color='#FAC858', zorder=1)

    # 标注超买点
    overbought = df[df['overbought']]
    if not overbought.empty:
        ax.scatter(overbought['trade_date'], overbought['close'],
                   color='#EE6666', marker='^', s=80, zorder=5, label=f'超买 ({len(overbought)}天)')
        for _, row in overbought.iterrows():
            ax.annotate(row['trade_date'].strftime('%m-%d'),
                        xy=(row['trade_date'], row['close']),
                        xytext=(0, 8), textcoords='offset points',
                        ha='center', fontsize=6, color='#EE6666')

    # 标注超卖点
    oversold = df[df['oversold']]
    if not oversold.empty:
        ax.scatter(oversold['trade_date'], oversold['close'],
                   color='#91CC75', marker='v', s=80, zorder=5, label=f'超卖 ({len(oversold)}天)')
        for _, row in oversold.iterrows():
            ax.annotate(row['trade_date'].strftime('%m-%d'),
                        xy=(row['trade_date'], row['close']),
                        xytext=(0, -12), textcoords='offset points',
                        ha='center', fontsize=6, color='#91CC75')

    # X轴格式化：按月显示
    ax.xaxis.set_major_locator(MonthLocator())
    ax.xaxis.set_major_formatter(DateFormatter('%Y-%m'))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right', fontsize=8)

    ax.set_title(f'{stock_name}({ts_code}) 布林带异常检测 (20日, 2σ)',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('日期')
    ax.set_ylabel('价格（元）')
    ax.grid(True, alpha=0.3, linestyle='--', zorder=0)
    ax.legend(loc='best', framealpha=0.9, fontsize=9)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    plt.close()
    print(f'[boll_detection] 布林带图已保存: {save_path}')


class BollDetectionTool(Tool):
    """布林带异常检测工具，使用20日周期+2σ检测超买超卖点。"""

    def __init__(self, db_path: Path, image_dir: Path):
        self._db_path = str(db_path)
        self._image_dir = image_dir

    @property
    def name(self) -> str:
        return "boll_detection"

    @property
    def description(self) -> str:
        return "使用布林带(20日MA±2σ)检测股票的超买和超卖异常点。用户提到'布林带'、'超买超卖'、'异常检测'时使用此工具。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "股票代码，从用户输入中提取。可用值：600519.SH（贵州茅台）、000858.SZ（五粮液）、000776.SZ（广发证券）、688981.SH（中芯国际）"
                },
                "start_date": {
                    "type": "string",
                    "description": "检测开始日期，格式 YYYY-MM-DD，用户未指定则默认为一年前"
                },
                "end_date": {
                    "type": "string",
                    "description": "检测结束日期，格式 YYYY-MM-DD，用户未指定则默认为今天"
                }
            },
            "required": ["ts_code"]
        }

    async def execute(self, **kwargs: Any) -> str:
        ts_code = kwargs.get("ts_code", "")
        end_date = kwargs.get("end_date", datetime.now().strftime('%Y-%m-%d'))
        start_date = kwargs.get("start_date",
                                (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'))
        if not ts_code:
            return "Error: 股票代码不能为空"
        return await asyncio.to_thread(self._execute_sync, ts_code, start_date, end_date)

    def _execute_sync(self, ts_code: str, start_date: str, end_date: str) -> str:
        print(f'[boll_detection] ts_code={ts_code}, {start_date} ~ {end_date}')

        # 1. 获取历史数据（多取45天用于计算MA）
        conn = sqlite3.connect(self._db_path)
        try:
            pre_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=45)).strftime('%Y-%m-%d')
            sql = """SELECT trade_date, stock_name, `close`
                     FROM stock_daily
                     WHERE ts_code=? AND trade_date >= ? AND trade_date <= ?
                     ORDER BY trade_date"""
            df = pd.read_sql(sql, conn, params=[ts_code, pre_start, end_date])
        finally:
            conn.close()

        if df.empty:
            return f"未找到股票代码 {ts_code} 的历史数据，请检查股票代码是否正确。"

        stock_name = df.iloc[0]['stock_name']
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date').reset_index(drop=True)

        # 2. 计算布林带
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['STD20'] = df['close'].rolling(window=20).std()
        df['upper'] = df['MA20'] + 2 * df['STD20']
        df['lower'] = df['MA20'] - 2 * df['STD20']

        # 3. 筛选检测范围内的数据
        detect_df = df[df['trade_date'] >= start_date].copy()
        if detect_df.empty:
            return f"检测范围内无数据，请调整日期范围。"

        # 4. 检测超买/超卖
        detect_df['overbought'] = detect_df['close'] > detect_df['upper']
        detect_df['oversold'] = detect_df['close'] < detect_df['lower']

        overbought_days = detect_df[detect_df['overbought']]
        oversold_days = detect_df[detect_df['oversold']]

        # 5. 生成图表
        self._image_dir.mkdir(parents=True, exist_ok=True)
        filename = f'boll_{ts_code.replace(".", "_")}_{int(time.time() * 1000)}.png'
        save_path = os.path.join(self._image_dir, filename)
        _draw_boll_chart(detect_df, stock_name, ts_code, save_path)
        img_path = os.path.join('image_show', filename)

        # 6. 构建返回结果
        md = f"**{stock_name}({ts_code}) 布林带异常检测结果：**\n"
        md += f"检测范围：{start_date} 至 {end_date}（共{len(detect_df)}个交易日）\n\n"

        md += f"**超买点（收盘价 > 上轨）：{len(overbought_days)} 天**\n"
        if len(overbought_days) > 0:
            ob_show = overbought_days[['trade_date', 'close', 'upper']].copy()
            ob_show['trade_date'] = ob_show['trade_date'].dt.strftime('%Y-%m-%d')
            ob_show.columns = ['日期', '收盘价', '上轨']
            ob_show['偏离度'] = ((overbought_days['close'] - overbought_days['upper']) / overbought_days['upper'] * 100).round(2).astype(str) + '%'
            md += ob_show.to_markdown(index=False) + '\n\n'
        else:
            md += "无超买信号\n\n"

        md += f"**超卖点（收盘价 < 下轨）：{len(oversold_days)} 天**\n"
        if len(oversold_days) > 0:
            os_show = oversold_days[['trade_date', 'close', 'lower']].copy()
            os_show['trade_date'] = os_show['trade_date'].dt.strftime('%Y-%m-%d')
            os_show.columns = ['日期', '收盘价', '下轨']
            os_show['偏离度'] = ((oversold_days['lower'] - oversold_days['close']) / oversold_days['lower'] * 100).round(2).astype(str) + '%'
            md += os_show.to_markdown(index=False) + '\n\n'
        else:
            md += "无超卖信号\n\n"

        md += f"![布林带图表]({img_path})"
        return md
