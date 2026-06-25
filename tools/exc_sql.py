"""
exc_sql 工具 - SQL查询 + 智能可视化
"""

import asyncio
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pandas as pd

from nanobot.agent.tools.base import Tool
from .chart_utils import (
    compute_yearly_summary,
    generate_chart_png,
)


class ExcSQLTool(Tool):
    """SQL查询工具，执行SQL并返回结果，智能选择最佳图表类型。"""

    def __init__(self, db_path: Path, image_dir: Path):
        self._db_path = str(db_path)
        self._image_dir = image_dir

    @property
    def name(self) -> str:
        return "exc_sql"

    @property
    def description(self) -> str:
        return "对生成的SQL进行查询，并自动选择最佳图表类型进行可视化"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql_input": {
                    "type": "string",
                    "description": "生成的SQL语句"
                }
            },
            "required": ["sql_input"]
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        sql_input = kwargs.get("sql_input", "")
        if not sql_input:
            return "Error: SQL 语句不能为空"
        return await asyncio.to_thread(self._execute_sync, sql_input)

    def _execute_sync(self, sql_input: str) -> str:
        print(f'[exc_sql] SQL: {sql_input}')

        conn = sqlite3.connect(self._db_path)
        try:
            df = pd.read_sql(sql_input, conn)
        finally:
            conn.close()

        print(f'[exc_sql] 返回 {len(df)} 行, 列: {list(df.columns)}')

        if df.empty:
            return "查询结果为空，没有匹配的数据。"

        # 智能追加：当查询了大量日度涨跌幅数据时，保留日度数据和图表，同时追加年度摘要
        cols_lower = [c.lower() for c in df.columns]
        _append_summary = None
        if ('trade_date' in cols_lower and 'pct_chg' in cols_lower
                and 'stock_name' in cols_lower and len(df) > 50):
            _append_summary = compute_yearly_summary(df, self._db_path)

        # 构建 markdown 输出：前5行 + 后5行 + 描述统计
        n = len(df)
        if n <= 10:
            md = df.to_markdown(index=False)
        else:
            head_md = df.head(5).to_markdown(index=False)
            sep_cells = ['...'] * len(df.columns)
            sep_row = '| ' + ' | '.join(sep_cells) + ' |'
            tail_md = df.tail(5).to_markdown(index=False)
            tail_data_rows = '\n'.join(tail_md.split('\n')[2:])
            md = f"{head_md}\n{sep_row}\n{tail_data_rows}"

        # 描述统计（仅对数值列）
        num_cols = df.select_dtypes(exclude='O').columns.tolist()
        if num_cols:
            stats = df[num_cols].describe().round(2)
            stats_md = stats.to_markdown()
            md = f"{md}\n\n**描述统计：**\n{stats_md}"

        md = f"查询共返回 **{n}** 行数据：\n\n{md}"

        # 生成图表
        self._image_dir.mkdir(parents=True, exist_ok=True)
        filename = f'stock_{int(time.time() * 1000)}.png'
        save_path = os.path.join(self._image_dir, filename)

        try:
            generate_chart_png(df, save_path)
            img_path = os.path.join('image_show', filename)
            img_md = f'![图表]({img_path})'
            result = f"{md}\n\n{img_md}"
        except Exception as e:
            print(f'[exc_sql] 图表生成失败: {e}')
            import traceback
            traceback.print_exc()
            result = md

        # 追加年度摘要（如果有）
        if _append_summary:
            result = f"{result}\n\n{_append_summary}"
        return result
