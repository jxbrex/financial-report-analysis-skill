# 数据源速查（data-sources）

> 各 Phase 的取数入口与字段映射。原则：**报告原文为一手锚点，数据库为校验与补充**。

## 一、报告转换：markitdown 技能

- 报告来源两条路（v0.0.7）：① 用户提供的 PDF/DOCX/HTML；② **A 股定期报告默认自动
  获取**——`mx_finance_search_notice` 定位公告 PDF 链接（tushare `anns_d` 本环境无权限
  40203，不作主路径）→ curl 下载；未指定期次时按披露节奏取最新已披露期次
  （规则见 SKILL.md Phase 0）
- 报告文件 → 调用 `markitdown` 技能转 md，存 `reports/archive/原始报告/`
- 转换后立即检查：表格是否保留结构（财报三表是核心）；若表格乱码/丢失，
  换「按页分段转换」或提示用户提供文字版
- 长文档用 Grep 定位章节锚点（「主要会计数据」「经营情况讨论与分析」「合并资产负债表」
  「合并利润表」「合并现金流量表」「在建工程」「研发投入」「股东总数」），Read 分页读

## 一·五、转换失败降级路径（扫描件，P2-24）

markitdown 对**扫描版 PDF**（图片型，无文字层）会输出近乎空白的 md。识别与降级：

1. **识别**：转换后的 md 体量远小于 PDF 应有信息量（如 200 页年报 < 50KB），
   或 Grep「营业收入」「合并资产负债表」等锚点零命中 → 判为扫描件
2. **降级路径（按成本递增尝试）**：
   - ① 先找**文字版替代源**：巨潮/交易所公告页常有 HTML 版年报摘要；
     港美股用 HKEX/EDGAR 的 HTML 版本（EDGAR 的 10-K 多为文本型）
   - ② 按页 OCR：用 `tesseract`（若已安装）或平台自带的 OCR 能力逐页识别；
     建议先 OCR 关键章节（主要会计数据 / 三表 / 附注），不要全书 OCR
   - ③ OCR 后**必须做表格人工抽查**：抽查 10 个以上数字与 PDF 原页比对，
     确认数字无错位、小数点无误
3. **失败后的诚实处理**：若 OCR 质量不可接受，向用户说明并索取文字版；
   **禁止用低质量 OCR 结果直接产出报告**
4. OCR 得来的数据在 data.json 的 `src` 里标注 `[OCR]`，并在报告页脚声明

## 二、tushare（结构化数据主力·HTTP 脚本通道）

**调用方式（无 tushare MCP 的环境等价可用）**：一律经 `scripts/ts_fetch.py` 走官方 HTTP API——
`python "<技能目录>/scripts/ts_fetch.py" <接口> --params k=v k=v --fields a,b,c`（stdout 为
JSONL 每行一个对象，默认截断 200 行、`--limit 0` 取全部、`--out path` 落盘）。token 读环境变量
`TUSHARE_TOKEN`，未设置时脚本报设置提示。**权限与频控跟 token 走、不跟通道走**，与 MCP / Python
SDK 完全等价；本环境无权限接口（40203）清单不变，报错文案已带降级提示（40203 两义：无权限或
`hk_daily` 限流 1 次/小时）。

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
| `mx_finance_search_notice` | 问询函/处罚/诉讼/问询回复；**股权激励计划与考核目标**（P2-22 四线考核线用） | 「XX公司 2025年以来 问询函 监管函 处罚」「XX公司 股权激励计划 考核目标 行权条件」 |
| `mx_finance_search_news` | 研报观点、评级目标价、行业观点 | 「XX公司 最新研报 评级 目标价」 |
| `mx_ashare_finance_data` | 同业可比公司批量指标 | 「A公司、B公司、C公司 2024年 毛利率 研发费率 资产负债率」 |
| `mx_stocks_screener` | 按条件找同行 | 「XX行业 市值最接近XX公司的5家」 |
| `mx_macro_data` | 大宗商品/汇率/利率/行业量价 | 「2024年以来 碳酸锂/铜/螺纹钢 价格走势」 |

## 三·五、港股 / 美股路径（非 A 股标的，P1-9）

**实测结论（2026-09 验证，勿再照抄计划里的 `westock`——该 CLI 在本环境不存在）：**

| 环节 | 港股（如 00700.HK） | 美股（如 AAPL） |
|---|---|---|
| 报告原文 | HKEX 披露易 `www1.hkexnews.hk` / 公司 IR 页 → markitdown 转 md | SEC EDGAR `sec.gov/edgar`（10-K/10-Q）→ markitdown |
| 财务数据主源 | **妙想 `mx_hk_finance_data`** ✅ 实测返回三表 + 附注明细（在建工程/递延收入/借款/存货）+ 会计准则 + 审计意见 + 核数师 | **妙想 `mx_us_finance_data`** |
| 行情 | tushare `hk_daily` / `hk_daily_adj` ✅ 有权限 | tushare `us_daily` / `us_daily_adj` |
| 公告/研报 | 妙想 `mx_finance_search_notice` / `_news`（支持港美股） | 同左 |
| 股东结构 | 妙想三表附注 + 港交所权益披露；tushare `hk_hold`（沪深港通持股，非全部股东） | 妙想 + SEC 13F/Form 4 |

⚠️ **tushare 港股财报接口本环境无权限**（`hk_income`/`hk_balancesheet`/`hk_cashflow` 返回 40203），
只能取行情。因此港股财务的**双源核对降级为**：妙想（主）+ 年报原文（锚）——
两源一致即通过；仍冲突时以报告原文为准并标注。

⚠️ **币种陷阱（港股特有）**：妙想港股接口的汇总表可能按**港元**展示，而三表明细按报表原币种
（腾讯报表为人民币，`显示币种：人民币`）。提取任何数字前先看返回里的「显示币种/原始币种」字段，
禁止港元与人民币混用。data.json 的 `meta.unit` 旁边加 `currency` 注明。

⚠️ **会计准则差异**：港股/美股为 IFRS/US GAAP，科目名称与口径与 CAS 不同（详见 report-types.md
「IFRS 与 CAS 差异提示」节）。勾稽等式（articulation.md）的科目映射要做对应，不能硬套 A 股科目名。

**A 股专属模块（港股/美股无数据，须在报告中置灰标注「仅 A 股」）：**
股东户数 `stk_holdernumber`、质押 `pledge_stat`、互动易问答 `irm_qa_*`、概念热榜
`dc_index`/`ths_hot`、业绩预告 `forecast`、券商一致预期 `report_rc`。
港股替代方案：前十大股东变动用妙想三表附注 + 权益披露；卖方观点用 `mx_finance_search_news`；
赛道重合度用市场公开热点（mx 检索）替代板块热榜。

**单源降级纪律**：非 A 股拿不到第二源时，报告与 data.json 中该标的的所有数字加 `[单源]` 标记，
并在报告页脚说明「未完成双源核对」。宁可显式标注，不可默认可信。

## 四、取数顺序纪律

1. Phase 1 先用 tushare 拉结构化三表（便宜、规整），再回原文核对异常值
2. 报告独有的明细（分产品量价、成本构成、在建工程项目表、募投项目）只能来自原文，
   数据库没有——找不到就标注「报告未披露」，禁止编造
3. 同业对比 ≥3 家时委派子代理批量取数，主会话只收压缩后的表
4. 每次调用记录口径（报告期、单位），单位混淆（元/万元/亿元）是头号翻车点
