"""
共享图表工具模块 - 智能图表生成器 v3.1

图表选型决策树：
┌─ 少量行 + 百分比&价格混合量纲 → 对比摘要双面板图（涨跌幅 + 价格分离）
├─ 有日期列 + 分组列（多实体对比）→ 分组折线图
├─ 有日期列（单实体时间序列）     → 折线图 / 面积图
├─ 分类对比（≤8 类 + 多数值列）  → 分组柱状图
├─ 分类排名（≤10 类）            → 横向柱状图
└─ 其他                          → 柱状图 / 折线图
"""

import os
import re
import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg', force=True)  # 非交互后端，force=True 无视加载顺序
import logging as _logging
_logging.getLogger('matplotlib.font_manager').setLevel(_logging.ERROR)  # 抑制 bold 字体警告
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.dates import DateFormatter

# 中文字体配置
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# ====== 可视化配置 ======
LINE_CHART_THRESHOLD = 30
MAX_XTICK_LABELS = 12

# 专业配色（参考 ECharts / AntV 色系，高辨识度 + 色盲友好）
COLOR_PALETTE = [
    '#5470C6',  # 蓝
    '#91CC75',  # 绿
    '#EE6666',  # 红
    '#FAC858',  # 黄
    '#73C0DE',  # 浅蓝
    '#FC8452',  # 橙
    '#9A60B4',  # 紫
    '#EA7CCC',  # 粉
]


# ========== 年度摘要计算 ==========

def compute_yearly_summary(df, db_path):
    """
    当日度数据量过大时，自动计算年度摘要。
    采用首尾收盘价法（更直观），同时统计上涨/下跌天数。
    """
    try:
        results = []
        conn = sqlite3.connect(db_path)
        for stock_name, grp in df.groupby('stock_name'):
            grp_sorted = grp.sort_values('trade_date')
            first_date = grp_sorted.iloc[0]['trade_date']
            last_date = grp_sorted.iloc[-1]['trade_date']

            # 查询首尾收盘价
            sql = """SELECT trade_date, `close` FROM stock_daily
                     WHERE stock_name=? AND trade_date IN (?,?)
                     ORDER BY trade_date"""
            prices = pd.read_sql(sql, conn, params=[stock_name, first_date, last_date])
            if len(prices) < 2:
                continue
            first_close = prices.iloc[0]['close']
            last_close = prices.iloc[-1]['close']
            year_pct = (last_close - first_close) / first_close * 100

            # 统计上涨/下跌天数
            up_days = (grp_sorted['pct_chg'] > 0).sum()
            down_days = (grp_sorted['pct_chg'] < 0).sum()

            direction = '涨' if year_pct > 0 else '跌'
            results.append(
                f"- {stock_name}：从{first_close}元{direction}到{last_close}元，"
                f"{direction}幅 {year_pct:+.2f}%"
                f"（上涨{up_days}天 / 下跌{down_days}天）"
            )
        conn.close()

        summary = "【年度涨跌幅摘要】\n" + "\n".join(results)
        summary += "\n\n以上为年度涨跌幅，基于首尾收盘价计算。"
        return summary
    except Exception as e:
        print(f'[compute_yearly_summary] 计算失败: {e}')
        return None


# ========== 数据特征检测 ==========

def is_date_column(series):
    """检测列是否为日期类型"""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    # 尝试匹配日期格式
    sample = series.dropna().head(5).astype(str)
    date_pattern = re.compile(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}')
    return all(date_pattern.match(str(v)) for v in sample)


# ========== 列语义分类 ==========

_PCT_KEYWORDS = {'pct_chg', 'pct', 'change_pct', '涨跌幅', '涨跌幅(%)', 'rate', 'ratio', 'percent', 'growth'}
_PRICE_KEYWORDS = {'open', 'close', 'high', 'low', 'pre_close', '开盘价', '收盘价', '最高价', '最低价', '昨收价'}


def classify_columns(num_cols):
    """将数值列分为 百分比类 / 价格类 / 其他类"""
    pct_cols, price_cols, other_cols = [], [], []
    for c in num_cols:
        c_lower = c.lower().strip()
        if c_lower in _PCT_KEYWORDS or 'pct' in c_lower or '涨跌幅' in c:
            pct_cols.append(c)
        elif c_lower in _PRICE_KEYWORDS or '价' in c:
            price_cols.append(c)
        else:
            other_cols.append(c)
    return pct_cols, price_cols, other_cols


def detect_chart_strategy(df):
    """
    分析数据特征，返回最佳图表策略。

    返回 dict:
        type: 'comparison_summary' | 'grouped_line' | 'line' | 'area'
              'grouped_bar' | 'h_bar' | 'bar'
        x_col: X 轴列名
        group_col: 分组列名（可选）
        y_cols: Y 轴列名列表
        pct_cols / price_cols: 语义分类列（仅 comparison_summary）
    """
    columns = df.columns.tolist()
    n = len(df)
    obj_cols = df.select_dtypes(include='O').columns.tolist()
    num_cols = df.select_dtypes(exclude='O').columns.tolist()

    # 日期列检测
    date_cols = [c for c in obj_cols if is_date_column(df[c])]
    non_date_obj = [c for c in obj_cols if c not in date_cols]

    # 策略 0：对比摘要（少量行 + 同时含百分比列和价格列）→ 双面板图
    if non_date_obj and not date_cols and n <= 10 and num_cols:
        pct_cols, price_cols, other_cols = classify_columns(num_cols)
        if pct_cols and (price_cols or other_cols):
            return {
                'type': 'comparison_summary',
                'x_col': non_date_obj[0],
                'group_col': None,
                'y_cols': num_cols,
                'pct_cols': pct_cols,
                'price_cols': price_cols + other_cols,
            }

    # 策略 1：有日期列 + 分组列（多实体时间对比）→ 分组折线图
    if date_cols and non_date_obj and num_cols:
        return {
            'type': 'grouped_line',
            'x_col': date_cols[0],
            'group_col': non_date_obj[0],
            'y_cols': num_cols,
        }

    # 策略 2：有日期列 + 无数值分组（单实体时间序列）→ 折线图/面积图
    if date_cols and num_cols:
        chart_type = 'area' if len(num_cols) <= 2 and n > 20 else 'line'
        return {
            'type': chart_type,
            'x_col': date_cols[0],
            'group_col': None,
            'y_cols': num_cols,
        }

    # 策略 3：有分组列 + 无日期列（分类对比）
    if non_date_obj and num_cols:
        group_col = non_date_obj[0]
        n_groups = df[group_col].nunique()
        if n_groups <= 8:
            return {
                'type': 'grouped_bar',
                'x_col': group_col,
                'group_col': None,
                'y_cols': num_cols,
            }

    # 策略 4：纯分类对比（少量条目）
    if obj_cols and num_cols:
        x_col = obj_cols[0]
        n_unique = df[x_col].nunique()
        if n_unique <= 10:
            return {
                'type': 'h_bar',
                'x_col': x_col,
                'group_col': None,
                'y_cols': num_cols,
            }

    # 策略 5：纯数值 + 少量行 → 柱状图
    if n <= LINE_CHART_THRESHOLD:
        return {
            'type': 'bar',
            'x_col': columns[0],
            'group_col': None,
            'y_cols': num_cols if num_cols else columns[1:],
        }

    # 策略 6：默认折线图
    return {
        'type': 'line',
        'x_col': columns[0],
        'group_col': None,
        'y_cols': num_cols if num_cols else columns[1:],
    }


# ========== X 轴智能采样 ==========

def smart_xticks(n, max_labels=MAX_XTICK_LABELS):
    """均匀采样索引位置"""
    if n <= max_labels:
        return list(range(n))
    return np.linspace(0, n - 1, max_labels, dtype=int).tolist()


# ========== 图表绘制函数 ==========

def _draw_comparison_summary(fig, axes, df, strategy):
    """
    对比摘要 → 双面板图：上面板展示涨跌幅（%），下面板展示价格/绝对值。
    解决不同量纲混合展示的可视化灾难问题。
    """
    x_col = strategy['x_col']
    pct_cols = strategy['pct_cols']
    price_cols = strategy['price_cols']

    categories = df[x_col].astype(str).tolist()
    n = len(df)
    x = np.arange(n)

    # ----- 上面板：涨跌幅对比 -----
    ax_top = axes[0]
    n_pct = len(pct_cols)
    bar_w = 0.8 / max(n_pct, 1)

    for i, col in enumerate(pct_cols):
        offset = (i - n_pct / 2 + 0.5) * bar_w
        vals = df[col].values.astype(float)
        colors = ['#EE6666' if v < 0 else '#91CC75' for v in vals]  # 红跌绿涨
        bars = ax_top.bar(x + offset, vals, width=bar_w, color=colors,
                          edgecolor='white', linewidth=0.5, zorder=3)
        # 标注数值 + %
        for bar, val in zip(bars, vals):
            y_pos = bar.get_height()
            va = 'bottom' if val >= 0 else 'top'
            offset_y = 0.5 if val >= 0 else -0.5
            ax_top.annotate(f'{val:+.2f}%', xy=(bar.get_x() + bar.get_width() / 2, y_pos),
                            xytext=(0, 3 * (1 if val >= 0 else -1)),
                            textcoords='offset points',
                            ha='center', va=va, fontsize=10, fontweight='bold',
                            color='#EE6666' if val < 0 else '#91CC75')

    ax_top.axhline(y=0, color='black', linewidth=0.8, zorder=0)
    ax_top.set_title('涨跌幅对比 (%)', fontsize=14, fontweight='bold')
    ax_top.set_xticks(x)
    ax_top.set_xticklabels(categories, fontsize=11)
    ax_top.grid(True, axis='y', alpha=0.3, linestyle='--', zorder=0)
    if n_pct > 1:
        ax_top.legend(pct_cols, loc='best', fontsize=9)
    ax_top.spines['top'].set_visible(False)
    ax_top.spines['right'].set_visible(False)

    # ----- 下面板：价格/绝对值对比 -----
    if price_cols:
        ax_bot = axes[1]
        n_price = len(price_cols)
        bar_w2 = 0.8 / max(n_price, 1)

        for i, col in enumerate(price_cols):
            offset = (i - n_price / 2 + 0.5) * bar_w2
            color = COLOR_PALETTE[i % len(COLOR_PALETTE)]
            bars = ax_bot.bar(x + offset, df[col], width=bar_w2, color=color,
                              edgecolor='white', linewidth=0.5, zorder=3)
            # 标注数值
            for bar in bars:
                h = bar.get_height()
                ax_bot.annotate(f'{h:.2f}',
                                xy=(bar.get_x() + bar.get_width() / 2, h),
                                xytext=(0, 3), textcoords='offset points',
                                ha='center', fontsize=8, color='gray')

        ax_bot.set_title('价格对比', fontsize=13, fontweight='bold')
        ax_bot.set_xticks(x)
        ax_bot.set_xticklabels(categories, fontsize=11)
        ax_bot.grid(True, axis='y', alpha=0.3, linestyle='--', zorder=0)
        if n_price > 1:
            ax_bot.legend(price_cols, loc='best', fontsize=9)
        ax_bot.spines['top'].set_visible(False)
        ax_bot.spines['right'].set_visible(False)
    else:
        axes[1].set_visible(False)


def _draw_grouped_line(ax, df, strategy):
    """多实体时间对比 → 分组折线图（如：茅台 vs 中芯国际 涨跌幅对比）"""
    x_col = strategy['x_col']
    group_col = strategy['group_col']
    y_cols = strategy['y_cols']

    # 选取最关键的 Y 列（如果多列，取第一列做主对比）
    y_col = y_cols[0]

    groups = df[group_col].unique()
    for i, grp in enumerate(groups):
        sub = df[df[group_col] == grp].sort_values(x_col)
        color = COLOR_PALETTE[i % len(COLOR_PALETTE)]
        x = np.arange(len(sub))
        ax.plot(x, sub[y_col], color=color, linewidth=2, marker='o',
                markersize=3, label=f'{grp}', zorder=3)

    # X 轴标签
    ref = df[df[group_col] == groups[0]].sort_values(x_col)
    labels = [str(v) for v in ref[x_col]]
    tick_pos = smart_xticks(len(ref))
    ax.set_xticks(tick_pos)
    ax.set_xticklabels([labels[i] for i in tick_pos], rotation=45, ha='right', fontsize=8)

    ax.set_title(f"{y_col} 多股票对比趋势", fontsize=14, fontweight='bold')
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    ax.grid(True, alpha=0.3, linestyle='--', zorder=0)
    ax.legend(loc='best', framealpha=0.9, fontsize=10)


def _draw_line(ax, df, strategy, use_area=False):
    """单实体时间序列 → 折线图 / 面积图"""
    x_col = strategy['x_col']
    y_cols = strategy['y_cols']

    df_sorted = df.sort_values(x_col)
    x = np.arange(len(df_sorted))
    labels = [str(v) for v in df_sorted[x_col]]

    for i, col in enumerate(y_cols):
        color = COLOR_PALETTE[i % len(COLOR_PALETTE)]
        if use_area:
            ax.fill_between(x, df_sorted[col], alpha=0.15, color=color)
        ax.plot(x, df_sorted[col], color=color, linewidth=2,
                marker='.' if len(df_sorted) < 60 else None,
                markersize=4, label=col, zorder=3)

    # 添加均值参考线
    if len(y_cols) == 1:
        mean_val = df_sorted[y_cols[0]].mean()
        ax.axhline(y=mean_val, color='gray', linestyle='--', alpha=0.5, linewidth=1)
        ax.annotate(f'均值: {mean_val:.2f}', xy=(len(df_sorted) * 0.85, mean_val),
                    fontsize=8, color='gray', va='bottom')

    tick_pos = smart_xticks(len(df_sorted))
    ax.set_xticks(tick_pos)
    ax.set_xticklabels([labels[i] for i in tick_pos], rotation=45, ha='right', fontsize=8)
    ax.set_title(f"{', '.join(y_cols)} 趋势", fontsize=14, fontweight='bold')
    ax.set_xlabel(x_col)
    ax.grid(True, alpha=0.3, linestyle='--', zorder=0)
    if len(y_cols) > 1:
        ax.legend(loc='best', framealpha=0.9, fontsize=9)


def _draw_grouped_bar(ax, df, strategy):
    """分类对比 → 分组柱状图（如：各股票平均涨跌幅排名）"""
    x_col = strategy['x_col']
    y_cols = strategy['y_cols']

    categories = df[x_col].astype(str).tolist()
    n = len(df)
    n_y = len(y_cols)
    bar_width = 0.8 / max(n_y, 1)
    x = np.arange(n)

    for i, col in enumerate(y_cols):
        offset = (i - n_y / 2 + 0.5) * bar_width
        color = COLOR_PALETTE[i % len(COLOR_PALETTE)]
        bars = ax.bar(x + offset, df[col], width=bar_width, color=color,
                      label=col, edgecolor='white', linewidth=0.5, zorder=3)
        # 在柱子上方标注数值（仅当数据不多时）
        if n <= 15:
            for bar in bars:
                h = bar.get_height()
                ax.annotate(f'{h:.1f}', xy=(bar.get_x() + bar.get_width() / 2, h),
                            xytext=(0, 3), textcoords='offset points',
                            ha='center', fontsize=7, color='gray')

    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=30, ha='right', fontsize=9)
    ax.set_title(f"{' vs '.join(y_cols)} 分类对比", fontsize=14, fontweight='bold')
    ax.grid(True, axis='y', alpha=0.3, linestyle='--', zorder=0)
    if n_y > 1:
        ax.legend(loc='best', framealpha=0.9, fontsize=9)


def _draw_h_bar(ax, df, strategy):
    """横向柱状图（适合排名类，标签较长时）"""
    x_col = strategy['x_col']
    y_cols = strategy['y_cols']
    y_col = y_cols[0]

    df_sorted = df.sort_values(y_col, ascending=True)
    labels = [str(v) for v in df_sorted[x_col]]
    values = df_sorted[y_col].values
    n = len(df_sorted)

    colors = [COLOR_PALETTE[i % len(COLOR_PALETTE)] for i in range(n)]
    bars = ax.barh(range(n), values, color=colors, edgecolor='white',
                   linewidth=0.5, height=0.6, zorder=3)

    # 标注数值
    for bar, val in zip(bars, values):
        ax.annotate(f'{val:.2f}', xy=(bar.get_width(), bar.get_y() + bar.get_height() / 2),
                    xytext=(5, 0), textcoords='offset points',
                    va='center', fontsize=8)

    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_title(f"{y_col} 排名", fontsize=14, fontweight='bold')
    ax.set_xlabel(y_col)
    ax.grid(True, axis='x', alpha=0.3, linestyle='--', zorder=0)
    ax.invert_yaxis()


def _draw_bar(ax, df, strategy):
    """基础柱状图"""
    x_col = strategy['x_col']
    y_cols = strategy['y_cols']

    labels = [str(v) for v in df[x_col]]
    n = len(df)
    n_y = len(y_cols)
    bar_width = 0.8 / max(n_y, 1)
    x = np.arange(n)

    for i, col in enumerate(y_cols):
        offset = (i - n_y / 2 + 0.5) * bar_width
        color = COLOR_PALETTE[i % len(COLOR_PALETTE)]
        ax.bar(x + offset, df[col], width=bar_width, color=color,
               label=col, edgecolor='white', linewidth=0.5, zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
    ax.grid(True, axis='y', alpha=0.3, linestyle='--', zorder=0)
    if n_y > 1:
        ax.legend(loc='best', framealpha=0.9, fontsize=9)


# ========== 图表类型标签 ==========

CHART_TYPE_LABELS = {
    'comparison_summary': '对比摘要图',
    'grouped_line': '分组折线图',
    'line': '折线图',
    'area': '面积图',
    'grouped_bar': '分组柱状图',
    'h_bar': '横向柱状图',
    'bar': '柱状图',
}

DRAW_DISPATCH = {
    'grouped_line': lambda ax, df, s: _draw_grouped_line(ax, df, s),
    'line':         lambda ax, df, s: _draw_line(ax, df, s, use_area=False),
    'area':         lambda ax, df, s: _draw_line(ax, df, s, use_area=True),
    'grouped_bar':  lambda ax, df, s: _draw_grouped_bar(ax, df, s),
    'h_bar':        lambda ax, df, s: _draw_h_bar(ax, df, s),
    'bar':          lambda ax, df, s: _draw_bar(ax, df, s),
}


def generate_chart_png(df_sql, save_path):
    """
    智能图表生成器（v3.1）。
    """
    strategy = detect_chart_strategy(df_sql)
    chart_label = CHART_TYPE_LABELS.get(strategy['type'], strategy['type'])
    print(f'[chart] 数据 {len(df_sql)} 行 → 策略: {chart_label} | '
          f'x={strategy["x_col"]}, y={strategy["y_cols"]}, '
          f'group={strategy["group_col"]}')

    # 对比摘要 → 双面板子图
    if strategy['type'] == 'comparison_summary':
        fig, axes = plt.subplots(2, 1, figsize=(10, 9), gridspec_kw={'height_ratios': [1, 1]})
        _draw_comparison_summary(fig, axes, df_sql, strategy)
        plt.tight_layout()
        plt.savefig(save_path, dpi=120)
        plt.close()
        print(f'[chart] {chart_label}已保存: {save_path}')
        return

    # 横向柱状图用不同的 figure 尺寸
    if strategy['type'] == 'h_bar':
        fig_height = max(4, len(df_sql) * 0.4 + 1)
        fig, ax = plt.subplots(figsize=(10, fig_height))
    else:
        fig, ax = plt.subplots(figsize=(14, 6))

    DRAW_DISPATCH[strategy['type']](ax, df_sql, strategy)

    # 全局美化
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    plt.close()
    print(f'[chart] {chart_label}已保存: {save_path}')
