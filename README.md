# 📈 股票行情助手（nanobot 版）

基于 [nanobot](https://github.com/nanobot) 框架的 **ChatBI 股票查询与分析助手**。通过自然语言对话，即可完成 SQL 查询可视化、ARIMA 价格预测、布林带异常检测、Prophet 周期性分析等专业功能。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| **SQL 查询 + 智能可视化** | 自然语言生成 SQL，自动选择最佳图表类型（折线图、柱状图、散点图等） |
| **ARIMA 价格预测** | 基于 ARIMA(5,1,5) 模型预测未来 N 天收盘价，含 95% 置信区间 |
| **布林带异常检测** | 20 日均线 ± 2σ 检测超买/超卖异常点，标注偏离度 |
| **Prophet 周期性分析** | 分解趋势（Trend）、周效应（Weekly）、年效应（Yearly）成分 |
| **网络搜索** | 集成 Tavily 搜索引擎，获取实时资讯（可选） |

## 📊 数据范围

- **时间跨度**：2020-01-02 至 2026-06-12
- **包含股票**：

| 股票代码 | 股票名称 |
|---------|---------|
| 600519.SH | 贵州茅台 |
| 000858.SZ | 五粮液 |
| 000776.SZ | 广发证券 |
| 688981.SH | 中芯国际 |

---

## 🚀 快速开始

### 1. 环境要求

- Python >= 3.10
- nanobot 框架（通过 `sys.path` 引用本地目录）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

| 环境变量 | 必填 | 说明 |
|---------|------|------|
| `DASHSCOPE_API_KEY` | ✅ | 阿里云 DashScope API Key（通义千问模型） |
| `TAVILY_API_KEY` | ❌ | Tavily 搜索 API Key（可选，用于网络搜索） |
| `TUSHARE_TOKEN` | ❌ | Tushare Token（可选，仅数据采集脚本使用） |
| `MYSQL_USERNAME` | ❌ | MySQL 用户名（可选，仅 MySQL 导出脚本使用） |
| `MYSQL_PASSWORD` | ❌ | MySQL 密码（可选，仅 MySQL 导出脚本使用） |

### 4. 运行程序

支持三种运行模式：

| 命令 | 模式 | 说明 |
|------|------|------|
| `python agent.py` | CLI 交互模式 | 命令行持续提问，支持多轮对话 |
| `python agent.py --gui` | Gradio Web 界面 | 启动浏览器可视化页面（端口 7860） |
| `python agent.py "你的问题"` | 单次查询 | 回答一次后程序退出 |

---

## 🏗️ 项目结构

```
├── agent.py                # 主入口（CLI 交互 / 单次查询 / Gradio 启动）
├── app_gradio.py           # Gradio Web 界面（流式输出 + Gallery 图表展示）
├── config.json             # nanobot 配置文件（模型参数、工具开关）
│
├── tools/                  # 自定义工具集
│   ├── exc_sql.py          #   SQL 查询 + 智能图表可视化
│   ├── arima_stock.py      #   ARIMA(5,1,5) 价格预测
│   ├── boll_detection.py   #   布林带超买超卖检测
│   ├── prophet_analysis.py #   Prophet 周期性分析
│   └── chart_utils.py      #   图表生成工具函数
│
├── skills/
│   └── stock-query-guide/  # SQL 查询参考问答 Skill
│
├── fetch_stock_prices.py   # 数据采集：Tushare 拉取历史行情 → xlsx
├── export_to_sqlite.py     # ETL：xlsx → SQLite（本地查询用）
├── export_to_mysql.py      # ETL：xlsx → MySQL（智能增量导入）
│
├── stock_prices.db         # SQLite 数据库（主数据存储）
├── stock_prices.xlsx       # Excel 原始数据
├── image_show/             # 工具生成的图表临时目录
├── sessions/               # 对话会话记录
└── requirements.txt        # Python 依赖清单
```

---

## 🔧 技术架构

### 核心技术栈

| 组件 | 技术 |
|------|------|
| AI 框架 | nanobot（Agent Loop + Tool 注册机制） |
| LLM 模型 | 通义千问 qwen3.7-plus（DashScope API） |
| Web 界面 | Gradio 5.x（Blocks + Chatbot + Gallery） |
| 数据存储 | SQLite（主）/ MySQL（可选） |
| 图表绘制 | matplotlib（Agg 非交互后端） |
| 数据分析 | pandas、numpy、statsmodels、prophet |
| 数据采集 | tushare |

### 工具架构

所有自定义工具继承 nanobot 的 `Tool` 基类，通过 `AgentLoop.tools.register()` 注册：

```
AgentLoop
├── exc_sql          → SQL 执行 + 智能图表
├── arima_stock      → ARIMA 预测
├── boll_detection   → 布林带检测
├── prophet_analysis → Prophet 分析
└── web_search       → Tavily 搜索（内置）
```

### Gradio 架构

- 使用**持久后台事件循环**（`asyncio.new_event_loop` + 守护线程）解决跨循环 `asyncio.Lock` 问题
- `GradioHook` 钩子实现**流式输出**：逐 token 推送 LLM 响应 + 工具调用日志
- Gallery 组件展示工具生成的图表，每次查询前自动清理旧图片

---

## 💡 使用示例

```
# SQL 查询
> 查询贵州茅台最近30天的收盘价
> 对比2025年四只股票的涨跌幅走势
> 五粮液2024年每月平均成交量是多少

# ARIMA 预测
> 预测贵州茅台未来10天价格
> 用ARIMA预测中芯国际未来15天的走势

# 布林带检测
> 检测中芯国际过去一年的超买超卖点
> 用布林带分析五粮液2024年的异常点

# Prophet 分析
> 用Prophet分析贵州茅台的周期性规律
> 分析广发证券的季节性趋势
```

---

## 📦 数据 ETL 工具

| 脚本 | 用途 | 前置依赖 |
|------|------|---------|
| `fetch_stock_prices.py` | 从 Tushare 拉取日线行情数据，保存为 `stock_prices.xlsx` | `TUSHARE_TOKEN` 环境变量 |
| `export_to_sqlite.py` | 将 Excel 数据导入 SQLite（`stock_prices.db`） | 无额外依赖 |
| `export_to_mysql.py` | 将 Excel 数据智能增量导入 MySQL | `MYSQL_USERNAME` / `MYSQL_PASSWORD` 环境变量 |

`export_to_mysql.py` 支持智能增量导入：
1. 自动检查数据库和表是否存在
2. 表结构不匹配时自动备份重建
3. 结构匹配时按每只股票最大日期增量插入

---

## ⚙️ 配置说明

`config.json` 主要配置项：

```json
{
  "agents": {
    "defaults": {
      "model": "qwen3.7-plus",       // LLM 模型
      "max_tokens": 4096,            // 最大输出 token
      "context_window_tokens": 32768,// 上下文窗口
      "temperature": 0,              // 温度（0=确定性输出）
      "max_tool_iterations": 20,     // 最大工具调用轮次
      "timezone": "Asia/Shanghai"    // 时区
    }
  },
  "tools": {
    "web": {
      "enable": true,                // 启用网络搜索
      "search": { "provider": "tavily" }
    },
    "exec": { "enable": false }      // 禁用代码执行工具
  }
}
```

---

## 📄 数据库表结构

`stock_daily` 表：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| stock_name | TEXT | 股票名称 |
| ts_code | TEXT | 股票代码（如 600519.SH） |
| trade_date | TEXT | 交易日期（YYYY-MM-DD） |
| open | REAL | 开盘价（元） |
| high | REAL | 最高价（元） |
| low | REAL | 最低价（元） |
| close | REAL | 收盘价（元） |
| pre_close | REAL | 昨收价（元） |
| change | REAL | 涨跌额（元） |
| pct_chg | REAL | 涨跌幅（%） |
| vol | REAL | 成交量（手） |
| amount | REAL | 成交额（千元） |

> `UNIQUE(ts_code, trade_date)` 保证同一股票同一交易日不重复。

---

## 📝 注意事项

1. `open`、`close`、`change` 是 SQL 保留字，在 SQLite 中需用反引号包裹
2. `vol` 单位是"手"（1 手 = 100 股），`amount` 单位是"千元"
3. `pct_chg` 是百分比数值，如 1.91 表示涨 1.91%
4. Gradio 界面默认端口 **7860**，启动后自动打开浏览器
5. 图表生成在 `image_show/` 目录下，每次查询前自动清理
## 项目启动三种运行模式
| 执行命令 | 进入模式 | 效果 |
|--------|--------|------|
| `python agent.py` | CLI 交互式命令行 | 持续提问、多轮对话 |
| `python agent.py --gui` | Gradio 网页界面 | 打开浏览器可视化页面 |
| `python agent.py 你的问题` | 单次查询 | 回答一次后程序关闭 |