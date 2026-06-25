"""
arima_stock 工具 - ARIMA(5,1,5) 股票价格预测
"""

import asyncio
import os
import sqlite3
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg', force=True)  # 非交互后端，force=True 无视加载顺序
import logging as _logging
_logging.getLogger('matplotlib.font_manager').setLevel(_logging.ERROR)  # 抑制 bold 字体警告
from matplotlib.dates import DateFormatter, AutoDateLocator
import matplotlib.pyplot as plt
from statsmodels.tsa.arima.model import ARIMA

from nanobot.agent.tools.base import Tool

# 中文字体配置
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False


def _draw_arima_chart(hist_df, pred_df, stock_name, ts_code, n, save_path):
    """绘制ARIMA预测图表：历史价格 + 预测价格 + 95%置信区间"""
    fig, ax = plt.subplots(figsize=(14, 6))

    # 历史数据（取最近60天用于展示）
    show_n = min(60, len(hist_df))
    hist_show = hist_df.tail(show_n)
    hist_dates = hist_show['trade_date']
    hist_close = hist_show['close']

    # 绘制历史价格
    ax.plot(hist_dates, hist_close, color='#5470C6', linewidth=2,
            marker='.', markersize=3, label='历史收盘价', zorder=3)

    # 预测日期
    future_dates = pd.to_datetime(pred_df['trade_date'])
    predicted = pred_df['predicted_close']
    lower = pred_df['lower_95']
    upper = pred_df['upper_95']

    # 连接线：历史最后一天 → 预测第一天
    last_hist_date = hist_dates.iloc[-1]
    last_hist_close = hist_close.iloc[-1]
    conn_dates = pd.Series([last_hist_date, future_dates.iloc[0]])
    conn_vals = pd.Series([last_hist_close, predicted.iloc[0]])
    ax.plot(conn_dates, conn_vals, color='#EE6666', linewidth=2, linestyle='--', zorder=3)

    # 预测价格
    ax.plot(future_dates, predicted, color='#EE6666', linewidth=2,
            marker='D', markersize=5, linestyle='--', label='ARIMA预测', zorder=4)

    # 95% 置信区间
    ax.fill_between(future_dates, lower, upper, alpha=0.15, color='#EE6666',
                    label='95%置信区间', zorder=2)

    # 分隔线
    ax.axvline(x=last_hist_date, color='gray', linestyle=':', alpha=0.5, linewidth=1)

    # X轴格式化
    all_dates = list(hist_dates) + list(future_dates)
    locator = AutoDateLocator(minticks=4, maxticks=12)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(DateFormatter('%m-%d'))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right', fontsize=8)

    ax.set_title(f'{stock_name}({ts_code}) ARIMA(5,1,5) 未来{n}天价格预测',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('日期')
    ax.set_ylabel('收盘价（元）')
    ax.grid(True, alpha=0.3, linestyle='--', zorder=0)
    ax.legend(loc='best', framealpha=0.9, fontsize=10)

    # 在预测点标注数值
    for i, (d, v) in enumerate(zip(future_dates, predicted)):
        if n <= 15 or i % max(1, n // 8) == 0:
            ax.annotate(f'{v:.2f}', xy=(d, v),
                        xytext=(0, 8), textcoords='offset points',
                        ha='center', fontsize=7, color='#EE6666')

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    plt.close()
    print(f'[arima_stock] 预测图已保存: {save_path}')


class ArimaStockTool(Tool):
    """ARIMA股票价格预测工具，使用ARIMA(5,1,5)模型预测未来N天收盘价。"""

    def __init__(self, db_path: Path, image_dir: Path):
        self._db_path = str(db_path)
        self._image_dir = image_dir

    @property
    def name(self) -> str:
        return "arima_stock"

    @property
    def description(self) -> str:
        return "使用ARIMA模型预测指定股票未来N天的收盘价走势。用户提到'预测'、'未来走势'、'ARIMA'时使用此工具。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "股票代码，从用户输入中提取。可用值：600519.SH（贵州茅台）、000858.SZ（五粮液）、000776.SZ（广发证券）、688981.SH（中芯国际）。用户提到茅台/600519就用600519.SH，提到五粮液/000858就用000858.SZ，提到广发证券/000776就用000776.SZ，提到中芯国际/688981就用688981.SH"
                },
                "n": {
                    "type": "integer",
                    "description": "预测未来天数，用户提到'N天'则传N，否则默认10",
                    "default": 10
                }
            },
            "required": ["ts_code"]
        }

    async def execute(self, **kwargs: Any) -> str:
        ts_code = kwargs.get("ts_code", "")
        n = int(kwargs.get("n", 10))
        if not ts_code:
            return "Error: 股票代码不能为空"
        return await asyncio.to_thread(self._execute_sync, ts_code, n)

    def _execute_sync(self, ts_code: str, n: int) -> str:
        print(f'[arima_stock] ts_code={ts_code}, n={n}')

        # 1. 获取截止到今天的前一年历史数据
        conn = sqlite3.connect(self._db_path)
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            one_year_ago = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            sql = """SELECT trade_date, stock_name, `close`
                     FROM stock_daily
                     WHERE ts_code=? AND trade_date >= ? AND trade_date <= ?
                     ORDER BY trade_date"""
            df = pd.read_sql(sql, conn, params=[ts_code, one_year_ago, today])
        finally:
            conn.close()

        if df.empty:
            return f"未找到股票代码 {ts_code} 的历史数据，请检查股票代码是否正确。"

        stock_name = df.iloc[0]['stock_name']
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date').reset_index(drop=True)

        print(f'[arima_stock] 获取到 {len(df)} 条历史数据 ({stock_name})')

        # 2. ARIMA(5,1,5) 建模与预测
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                model = ARIMA(df['close'].values, order=(5, 1, 5))
                fitted = model.fit()
                forecast = fitted.get_forecast(steps=n)
                predicted_mean = forecast.predicted_mean
                conf_int = forecast.conf_int(alpha=0.05)
            except Exception as e:
                return f"ARIMA建模失败: {e}，可能数据不足或模型不收敛。"

        # 3. 构建预测结果表
        last_date = df['trade_date'].iloc[-1]
        future_dates = pd.bdate_range(start=last_date + timedelta(days=1), periods=n)
        pred_df = pd.DataFrame({
            'trade_date': future_dates.strftime('%Y-%m-%d'),
            'predicted_close': np.round(predicted_mean, 2),
            'lower_95': np.round(conf_int[:, 0], 2),
            'upper_95': np.round(conf_int[:, 1], 2),
        })

        # 4. 生成预测图表
        self._image_dir.mkdir(parents=True, exist_ok=True)
        filename = f'arima_{ts_code.replace(".", "_")}_{int(time.time() * 1000)}.png'
        save_path = os.path.join(self._image_dir, filename)

        _draw_arima_chart(df, pred_df, stock_name, ts_code, n, save_path)
        img_path = os.path.join('image_show', filename)

        # 5. 构建返回结果
        md = f"**{stock_name}({ts_code}) ARIMA(5,1,5) 未来{n}天预测：**\n\n"
        md += pred_df.to_markdown(index=False)
        md += f"\n\n![预测图表]({img_path})"
        md += f"\n\n模型信息：历史数据 {len(df)} 天（{df['trade_date'].iloc[0].strftime('%Y-%m-%d')} 至 {df['trade_date'].iloc[-1].strftime('%Y-%m-%d')}），AIC={fitted.aic:.2f}"
        return md
