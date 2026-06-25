"""
prophet_analysis 工具 - Prophet周期性分析（trend/weekly/yearly分解）
"""

import asyncio
import os
import sqlite3
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import matplotlib
matplotlib.use('Agg', force=True)  # 非交互后端，force=True 无视加载顺序
import logging as _logging
_logging.getLogger('matplotlib.font_manager').setLevel(_logging.ERROR)  # 抑制 bold 字体警告
import matplotlib.pyplot as plt
from prophet import Prophet

from nanobot.agent.tools.base import Tool

# 中文字体配置
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False


class ProphetAnalysisTool(Tool):
    """Prophet股票周期性分析工具，分解trend/weekly/yearly成分。"""

    def __init__(self, db_path: Path, image_dir: Path):
        self._db_path = str(db_path)
        self._image_dir = image_dir

    @property
    def name(self) -> str:
        return "prophet_analysis"

    @property
    def description(self) -> str:
        return "使用Prophet模型分析股票的周期性规律，分解趋势、周效应、年效应。用户提到'Prophet'、'周期性'、'季节性'、'趋势分解'时使用此工具。"

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
                    "description": "分析开始日期，格式 YYYY-MM-DD，用户未指定则默认为一年前"
                },
                "end_date": {
                    "type": "string",
                    "description": "分析结束日期，格式 YYYY-MM-DD，用户未指定则默认为今天"
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
        print(f'[prophet_analysis] ts_code={ts_code}, {start_date} ~ {end_date}')

        # 1. 获取历史数据
        conn = sqlite3.connect(self._db_path)
        try:
            sql = """SELECT trade_date, stock_name, `close`, vol
                     FROM stock_daily
                     WHERE ts_code=? AND trade_date >= ? AND trade_date <= ?
                     ORDER BY trade_date"""
            df = pd.read_sql(sql, conn, params=[ts_code, start_date, end_date])
        finally:
            conn.close()

        if df.empty:
            return f"未找到股票代码 {ts_code} 在指定范围内的数据。"

        stock_name = df.iloc[0]['stock_name']
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date').reset_index(drop=True)

        print(f'[prophet_analysis] 获取到 {len(df)} 条数据 ({stock_name})')

        # 2. 转换为 Prophet 格式
        prophet_df = df[['trade_date', 'close']].rename(
            columns={'trade_date': 'ds', 'close': 'y'}
        )

        # 3. 训练 Prophet 模型
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                model = Prophet(
                    yearly_seasonality=True,
                    weekly_seasonality=True,
                    daily_seasonality=False,
                    changepoint_prior_scale=0.05
                )
                model.fit(prophet_df)

                # 生成预测（用于分解）
                future = model.make_future_dataframe(periods=0)
                forecast = model.predict(future)
            except Exception as e:
                return f"Prophet建模失败: {e}，可能数据不足。"

        # 4. 生成可视化图表
        self._image_dir.mkdir(parents=True, exist_ok=True)
        ts_tag = ts_code.replace('.', '_')
        timestamp = int(time.time() * 1000)

        # 4.1 总览图
        fig1 = model.plot(forecast)
        fig1.suptitle(f'{stock_name}({ts_code}) Prophet 拟合总览', fontsize=14, fontweight='bold')
        fig1.savefig(os.path.join(self._image_dir, f'prophet_overview_{ts_tag}_{timestamp}.png'), dpi=120)
        plt.close(fig1)

        # 4.2 成分分解图
        fig2 = model.plot_components(forecast)
        fig2.suptitle(f'{stock_name}({ts_code}) 周期性成分分解', fontsize=14, fontweight='bold', y=1.02)
        fig2.tight_layout()
        fig2.savefig(os.path.join(self._image_dir, f'prophet_components_{ts_tag}_{timestamp}.png'), dpi=120, bbox_inches='tight')
        plt.close(fig2)

        img_overview = os.path.join('image_show', f'prophet_overview_{ts_tag}_{timestamp}.png')
        img_components = os.path.join('image_show', f'prophet_components_{ts_tag}_{timestamp}.png')

        print(f'[prophet_analysis] 图表已保存')

        # 5. 提取关键分析数据
        trend = forecast[['ds', 'trend']].dropna()
        weekly = forecast[['ds', 'weekly']].dropna()
        yearly = forecast[['ds', 'yearly']].dropna()

        # 趋势分析
        if len(trend) >= 2:
            trend_start = trend.iloc[0]['trend']
            trend_end = trend.iloc[-1]['trend']
            trend_pct = (trend_end - trend_start) / trend_start * 100
            trend_dir = '上升' if trend_pct > 0 else '下降'
        else:
            trend_pct, trend_dir = 0, '持平'

        # 周效应（取一周内最大/最小）
        if len(weekly) > 0:
            weekly_df = weekly.copy()
            weekly_df['weekday'] = weekly_df['ds'].dt.dayofweek
            weekly_avg = weekly_df.groupby('weekday')['weekly'].mean()
            weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            best_day = weekday_names[weekly_avg.idxmax()]
            worst_day = weekday_names[weekly_avg.idxmin()]
        else:
            best_day, worst_day = 'N/A', 'N/A'

        # 年效应（取年内最大/最小月份）
        if len(yearly) > 0:
            yearly_df = yearly.copy()
            yearly_df['month'] = yearly_df['ds'].dt.month
            monthly_avg = yearly_df.groupby('month')['yearly'].mean()
            best_month = f'{monthly_avg.idxmax()}月'
            worst_month = f'{monthly_avg.idxmin()}月'
        else:
            best_month, worst_month = 'N/A', 'N/A'

        # 6. 构建返回结果
        md = f"**{stock_name}({ts_code}) Prophet 周期性分析结果：**\n"
        md += f"分析范围：{start_date} 至 {end_date}（共{len(df)}个交易日）\n\n"

        md += "**趋势成分 (Trend)：**\n"
        md += f"- 整体趋势：{trend_dir} {abs(trend_pct):.2f}%\n"
        md += f"- 起始趋势值：{trend.iloc[0]['trend']:.2f}\n"
        md += f"- 结束趋势值：{trend.iloc[-1]['trend']:.2f}\n\n"

        md += "**周效应 (Weekly)：**\n"
        md += f"- 表现最佳交易日：{best_day}\n"
        md += f"- 表现最差交易日：{worst_day}\n\n"

        md += "**年效应 (Yearly)：**\n"
        md += f"- 历史强势月份：{best_month}\n"
        md += f"- 历史弱势月份：{worst_month}\n\n"

        md += f"![拟合总览]({img_overview})\n\n"
        md += f"![成分分解]({img_components})"
        return md
