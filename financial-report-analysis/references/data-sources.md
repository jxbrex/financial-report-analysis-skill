# 数据源速查（data-sources）

> 各 Phase 的取数入口与字段映射。原则：**报告原文为一手锚点，数据库为校验与补充**。

## 一、报告转换：markitdown 技能

- 用户提供的 PDF/DOCX/HTML → 调用 `markitdown` 技能转 md，存 `reports/`
- 转换后立即检查：表格是否保留结构（财报三表是核心）；若表格乱码/丢失，
  换「按页分段转换」或提示用户提供文字版
- 长文档用 Grep 定位章节锚点（「主要会计数据」「经营情况讨论与分析」「合并资产负债表」
  「合并利润表」「合并现金流量表」「在建工程」「研发投入」「股东总数」），Read 分页读

## 二、tushare MCP（结构化数据主力）

### 三表与财务指标（Phase 1/2 双源核对）
| 接口 | 关键字段 |
|---|---|
| `income` | `total_revenue` `oper_cost` `n_income_attr_p`（归母净利）`basic_eps` `sell_exp` `admin_exp` `fin_exp` `rd_exp` `assets_impair_loss` `invest_income` `income_tax` `minority_gain` |
| `balancesheet` | `money_cap`（货币资金）`notes_receiv` `accounts_receiv` `oth_receiv` `inventories` `fix_assets` `cip`（在建工程）`goodwill` `st_borr` `non_cur_liab_due_1y` `lt_borr` `bond_payable` `total_assets` `total_liab` `total_hldr_eqy_exc_min_int`（归母净资产） |
| `cashflow` | `n_cashflow_act`（经营现金流净额）`c_fr_sale_sg`（销售收现）`c_pay_acq_const_fiolta`（资本开支）`free_cashflow` `c_pay_dist_dpcp_int_exp`（分红付息） |
| `fina_indicator` | `roe` `grossprofit_margin` `netprofit_margin` `debt_to_assets` `current_ratio` `quick_ratio` `ar_turn` `inv_turn` `assets_turn` `or_yoy` `netprofit_yoy` `dt_netprofit_yoy` `rd_exp` `ocfps` `q_sales_yoy` `q_profit_yoy`（单季度） |

注意：`income`/`balancesheet`/`cashflow` 必填 `ts_code`，用 `period`（如 `20241231`）或
`start_date`/`end_date`（公告日区间）限定；`fina_indicator` 单次最多 100 条。

### 股东与筹码（Phase 6）
| 接口 | 用途 |
|---|---|
| `stk_holdernumber` | 股东户数趋势（`holder_num`，按 `end_date` 拉多期） |
| `top10_holders` / `top10_floatholders` | 前十大（流通）股东。⚠️ `hold_change` 是**环比上一报告期**（季度）；做「本期 vs 上年同期」对比须分两次拉取自行计算 |
| `stk_holdertrade` | 董监高与大股东增减持（`in_de`：IN 增持 / DE 减持） |
| `pledge_stat` | 控股股东质押比例 |

### 预期与事件（Phase 7）
| 接口 | 用途 |
|---|---|
| `report_rc` | 券商盈利预测与评级。⚠️ **`np`/`op_rt` 单位是万元**，必须换算；**取数窗口**：按 `quarter`=目标年度且 `report_date` 在上一份定期报告披露日之后筛选、取中位数作一致预期——年报发布日后的预测已转向下一年度，直接用会污染对比 |
| `forecast` / `express` | 业绩预告 / 业绩快报（与实际值对照） |
| `anns_d` | 公告列表（补报告 PDF、重大事项）。⚠️ 需专项权限，无权限报 40203——改用 mx_finance_search_notice 定位 PDF 链接 |
| `dc_index` / `ths_index` / `dc_hot` / `ths_hot` | 概念板块行情与热榜（赛道重合度） |
| `index_classify` / `index_member_all` | 申万行业归属与同行名单 |
| `dividend` | 分红历史 |
| `irm_qa_sh` / `irm_qa_sz` | 互动易/e 互动问答（投资者在追问什么） |

## 二·五、Q4 单季数据（年报分析的必做拆解，见 report-types.md）

- **取数两条路**：
  1. 原文相减：年报「报告期分季度的主要会计数据」表（多数年报直接披露四个单季的
     收入/归母净利/扣非/经营现金流，Grep 锚点「分季度」）——首选
  2. tushare 补充：`fina_indicator` 的 `q_sales_yoy`/`q_profit_yoy`/`q_gsprofit_margin`
     （单季同比与单季毛利率，period=20251231 即 Q4 单季口径）；或用
     `income`/`daily` 拉三季报（period=20250930）与年报相减
- **注意**：年报若披露「季度数据与已披露定期报告数据差异说明」，以年报口径为准
- 五项异常检测阈值见 report-types.md 年报节；结果写入 data.json `derived.q4`

## 三、mx-ds MCP（检索与宏观补充）

| 工具 | 用途 | 典型问法 |
|---|---|---|
| `mx_finance_search_notice` | 问询函/处罚/诉讼/问询回复 | 「XX公司 2025年以来 问询函 监管函 处罚」 |
| `mx_finance_search_news` | 研报观点、评级目标价、行业观点 | 「XX公司 最新研报 评级 目标价」 |
| `mx_ashare_finance_data` | 同业可比公司批量指标 | 「A公司、B公司、C公司 2024年 毛利率 研发费率 资产负债率」 |
| `mx_stocks_screener` | 按条件找同行 | 「XX行业 市值最接近XX公司的5家」 |
| `mx_macro_data` | 大宗商品/汇率/利率/行业量价 | 「2024年以来 碳酸锂/铜/螺纹钢 价格走势」 |

## 四、取数顺序纪律

1. Phase 1 先用 tushare 拉结构化三表（便宜、规整），再回原文核对异常值
2. 报告独有的明细（分产品量价、成本构成、在建工程项目表、募投项目）只能来自原文，
   数据库没有——找不到就标注「报告未披露」，禁止编造
3. 同业对比 ≥3 家时委派子代理批量取数，主会话只收压缩后的表
4. 每次调用记录口径（报告期、单位），单位混淆（元/万元/亿元）是头号翻车点
