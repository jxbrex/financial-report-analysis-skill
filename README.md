# Bo-FinancialAnalyzer

> 上市公司年报 / 半年报 / 季报 / 招股说明书分析技能（Agent Skill）——输入一份定期报告或招股说明书，产出一份单文件自包含 HTML 分析报告。

[![版本](https://img.shields.io/badge/version-0.1.8-blue)](https://github.com/jxbrex/bo-financial-analyzer/releases/latest)
[![回归](https://img.shields.io/badge/%E5%9B%9E%E5%BD%92-437%2F437%20%E7%BB%BF-brightgreen)](bo-financial-analyzer/tests/run_regression.py)
[![CI](https://github.com/jxbrex/bo-financial-analyzer/actions/workflows/regression.yml/badge.svg)](https://github.com/jxbrex/bo-financial-analyzer/actions/workflows/regression.yml)

---

## 一、概述

本技能把「读财报」这件事变成一条可复算、可追溯、可证伪的流水线：

- **输入**：上市公司定期报告或招股说明书（PDF / DOCX / HTML），用户在对话中直接提供文件，或指定公告由技能定位下载
- **处理**：结构化抽取 → 勾稽验算 → 排雷扫描 → 因素分解 → 文字部分（MD&A）分析 → 外部数据交叉校验
- **产出**：单文件自包含 HTML 报告（10 章，锚点 `s0~s8`），落在当前工作目录 `reports/` 顶层，命名 `{公司名}-{代码}-{报告类型}-{报告期}-{生成日}.html`

核心立场：**财报分析的产出是「排除与揭示」——这份报告哪里可疑、哪里被解释清楚了，而不是给一个跨维度加权总分做质量排序**。技能与股票分析类 skill（如 bo-equity-researcher）完全独立：本技能只解读已发生事项，无条件未来断言与多空立场不在产出范围内。

## 二、整体逻辑与方法论

### 四层分析引擎（每层结论可回溯到下层证据）

```
数据层（extraction-schema.md 的 data.json）
  → 恒等式层（articulation.md 的过程勾稽）
    → 比率与基准层（frameworks.md）
      → 叙事层（text-mining.md 的断言验证）
```

- **数据层**：从报告原文抽取结构化 data.json，tushare / 东方财富双源核对，报告原文为一手锚点；`md_clean.py` 先把 PDF 拆碎的表格拼回逻辑行
- **恒等式层**：A 组 8 条恒等式（资产=负债+权益、现金勾稽、Capex 勾稽、收入-收现闭环等）+ B 组 4 条 roll-forward + C 组 2 条周期判定 + D 组 5 条母公司单体勾稽
- **比率与基准层**：杜邦三分解与连环替代归因（当期/扣非双版/五年累计 + 因子分位）、ROIC（去杠杆口径）、内生增长率、CCC、费用 ROI、周期定位、四线考核贴线检测、破产双模型（Altman Z + Ohlson O 并列）、流动性压力情景
- **叙事层**：MD&A 三层读法、措辞对比、断言验证矩阵（✅ 通过 / ❓ 无法验证 / 🔴 不成立）

**最重要的认知：勾稽闭合 ≠ 科目真实**。造假者能在自己的账套里把等式做平（本仓库康得新金标准样本中，A1 现金勾稽算术闭合，但 122 亿存款已被资金归集协议锁定不可用）。因此审计意见 / 独董异议 / 问询函 / 期后违约的信息优先级不低于任何等式。

### 分析流水线（Phase 0 → 8）

输入识别转换（markitdown + md_clean 确定性清洗）→ 并行派发窗（7 子代理分区提取，后台派发、分块落盘）→ 数据抽取合成 → **Phase 2.5 勾稽验算** → 排雷扫描（四态呈现：🔴 命中 / 🟡 观察 / ↩ 反向未触发）→ 文字部分分析 → **Phase 7.5 计算自检门禁（`calc --fill` 机械字段预填 + fillsheet 槽位契约）** → 因素分析（三座桥）→ 股东与期后 → 机构预期与回看 → **Phase 8 fill→render 脚本化锚定填充 + 报告机检 + 渲染测量（三道门禁）** → 交付

「三座桥」是因素分析主干：**收入桥**（量/价/结构三效应，无量价数据降级分部桥）、**净利润桥**（毛利→税金→费用→减值→投资→非经→所得税→少数股东）、**净利→经营现金流调节桥**（间接法，营运资本吞噬逐项量化）。同一公司第二份报告自动进入**回看模式**：逐条核对上期 watchlist 的 if-then 触发线兑现情况（兑现 ✅/❌ + 归因），让分析从单点快照变成连续追踪。

### 三道质量关 + 单入口（机器门禁，不是装饰）

| 门禁 | 位置 | 校验内容 | 失败后果 |
|---|---|---|---|
| `scripts/calc.py` | Phase 7.5，写报告前 | 结构/出处、核心科目覆盖、恒等式与三座桥闭合、比率复算（14 项趋势逐期 + 8 项单期含 ROIC/内生增长率）、勾稽三态一致、杜邦三口径复算、破产双模型（含年化卡口）、压力情景、现金时序、分部自洽、断言结构、`--min-recon auto` 覆盖硬门禁（按主市场前缀+报告类型查校准表，未知组合退回 WARN 态并提示显式给数） | exit 非 0 禁止写报告 |
| `scripts/check_html.py` | Phase 8，交付前 | 占位符残留、裸数字启发式、数据来源标注、模板硬规则、WCAG 小字对比度（text-contrast）、SVG 可访问名称（svg-a11y）、必备要素、锚点完整性、章节形态（s1 杜邦双卡/s2 瘦身/s8 阈值）、数据缺口声明集中落点（gap-declaration）、桑基数据槽比对（sankey-slot）、**T8 数字回验**（`--json`：HTML↔data.json 笔误检测 + data.json↔原文行号回核） | exit 非 0 禁止交付 |
| `scripts/check_render.py` | Phase 8，交付前 | headless Chrome/Edge 真渲染测量：SVG 文本重叠 / HTML 溢出 .sheet / 横向裁剪 / 关键 SVG 非空（empty-svg）/ SVG 文本出视口（svgclip）；`--png` 按章分片截图供视觉验收 | 发现问题 exit 1 |
| `scripts/gate.py` | 单入口 | 上三条一条命令串完（`--png`/`--verbose`/`--min-recon` 透传） | 统一退出码 |
| `tests/run_regression.py` | 任何改动后 | 金标准五例（茅台干净样本零误报 / 康得新造假样本须命中 / 万科连亏地产样本扣非双版与双驱动真实触发 / 万华周期股样本双驱动第二样本与白描分位锚点 / 清越新准则造假样本处罚交叉验证）+ 赢合 render 重放金标准（fillsheet 逐字锁）+ check_html/T8/渲染冒烟 + md_clean 双合成样本 + `--fill` 幂等（字符串叶精确比对）+ 构造用例，共 437 条断言 | 不绿不许提交 |

## 三、目录结构

```
Financial Report Analysis/          本仓库（技能唯一真源）
├── bo-financial-analyzer/          技能源——只改这里
│   ├── SKILL.md                    技能主文档：触发条件、何时不用、Phase 0~8 工作流、版本记录
│   ├── assets/
│   │   └── report-template.html    单文件报告模板（内联 SVG 绘图、锚点 s0~s8、置信度徽章体系）
│   ├── references/                 方法库 ×10
│   │   ├── extraction-schema.md    data.json 数据契约（每个字段的出处与校验规则）
│   │   ├── articulation.md         勾稽核对手册（A/B/C/D 四组恒等式与使用总则）
│   │   ├── factor-analysis.md      三因素分解、三座桥、四象限、桑基图卡
│   │   ├── frameworks.md           口径总则 + 公式库、杜邦、破产双模型、CCC、周期定位、费用 ROI、四线考核、压力情景
│   │   ├── redflags.md             排雷信号库（四态判定 + 红/黄/亮点 + 审计交叉命中 + severity 试点）
│   │   ├── text-mining.md          MD&A 三层读法、断言验证矩阵、赛道重合度四问 + 行业坐标
│   │   ├── industry-profiles.md    八类商业模式调焦 + 各模式先行指标建议集
│   │   ├── data-sources.md         markitdown / tushare / 妙想接口速查、港股路径、OCR 降级
│   │   ├── report-types.md         年报/半年报/季报/招股书/港美股的差异与裁剪规则
│   │   └── subagent-prompts.md     并行派发窗的 7 份子代理派单模板
│   ├── scripts/
│   │   ├── calc.py                 Phase 7.5 数据层门禁入口（--fill 预填 / --min-recon auto）
│   │   ├── calc_common.py          共享层：取值助手 + 比率公式唯一定义处 + 批量比对助手
│   │   ├── calc_dupont.py          杜邦族：连环替代三口径 / 因子下钻 / 五年归因与分位
│   │   ├── calc_evidence.py        周期证据 / 四线贴线 / peers 结构
│   │   ├── calc_risk.py            破产双模型 / 压力情景 / 现金时序
│   │   ├── calc_models.py          --fill 编排层 + fillsheet 速查表产出（不含公式）
│   │   ├── calc_slots.py           槽位契约层：build_slots + write_fillsheet + JS 槽单一出处 + 文本链
│   │   ├── calc_sankey.py          桑基图：compute_sankey 公式唯一出处 + route_items 符号路由 + check_sankey 复算
│   │   ├── calc_ipo.py             招股书发行/募投/期后审阅与股权槽位（南方乳业首验）
│   │   ├── render_report.py        Phase 8 fill→render 脚本化：模板 + fillsheet.json → 报告骨架，锚定填充（断锚 exit 1）
│   │   ├── check_html.py           Phase 8 报告层门禁入口（结构/硬规则族+主流程）
│   │   ├── check_html_common.py    报告机检共享助手
│   │   ├── check_html_text.py      呈现文本族 16 条检查（含 text-contrast；PCTILE_LABEL 居此）
│   │   ├── check_html_t8.py        T8 数字回验整族（①级笔误检测 + hist_pool 豁免 + ②级行号回核）
│   │   ├── check_render.py         渲染测量门禁（headless Chrome/Edge；empty-svg 非空 + svgclip 出视口检测）
│   │   ├── gate.py                 三道门禁单入口
│   │   ├── md_clean.py             财报 md 确定性清洗（拼碎行/删页眉页脚 + 章节索引 + 图片型主表缺失提示）
│   │   └── ts_fetch.py             tushare HTTP 取数（双源核对通道，token 读环境变量）
│   ├── tests/
│   │   ├── moutai_2025.json        干净样本金标准（应零误报）
│   │   ├── kangdexin_2018.json     造假样本金标准（应命中）
│   │   ├── vanke_2026h1.json       连亏地产样本（扣非双版/双驱动真实触发锚点）
│   │   ├── wanhua_2026h1.json      周期股样本（双驱动第二样本/ROIC·SGR 首验/白描分位锚点）
│   │   ├── qingyue_2022.json       新准则造假样本（处罚×收入KAM×少计减值；外部硬证据交叉验证）
│   │   ├── yinghe_2026h1.json      render 重放金标准（fill→render 锚定与断言结构锚点）
│   │   ├── breo_2025_b2.json       B2 完整存货流真实专用样本
│   │   ├── yinghe_2025_leverage.json  话语权型杠杆真实专用样本
│   │   ├── midea_2025_leverage_negative.json  负向杠杆不得升档真实样本
│   │   ├── yinghe_2026h1.fillsheet.golden.md  赢合 fillsheet 金标准（render 重放逐字锁）
│   │   ├── md_clean_synth.md       md_clean 合成金标准（自包含，覆盖四类历史病理）
│   │   ├── md_clean_synth2.md      第二合成金标准（v0.1.5：表题行/分隔行污染两形态）
│   │   ├── t8_demo.html            T8 数字回验验收样例（改错版由回归运行时改数生成）
│   │   └── run_regression.py       唯一回归入口（437 断言：五金标准 + render 重放 + 全部门禁冒烟 + 构造用例）
├── reports/                        产出目录。顶层只放成品 HTML（每公司最新版；PDF/md 不入库，json 入库）
│   └── archive/                    原始报告（PDF/md，不入库）+ json 底稿（入库）
├── .github/workflows/              CI：push 自动跑金标准回归
├── deploy.cmd                      部署：robocopy 镜像技能源到用户级 skills 目录（排除 __pycache__ + 部署后自检）
├── AGENTS.md                       工作区纪律 + 发布流程（一条链：回归→commit→tag→push→release→deploy）
└── handoff/
    ├── HANDOFF.md                  交接文档（最新版）：本轮工作、已知局限、下一步计划、运维速查
    └── supersede/                  已发布轮次归档（按版本区间一文件；子目录外只留最新版）
```

用户级目录 `C:/Users/rexji/.agents/skills/bo-financial-analyzer/` 只是 `deploy.cmd` 的镜像副本，**绝不直接修改**。

## 四、环境

**运行时（使用技能分析报告）**

- 任意支持 Skill 机制的 Agent 会话（Kimi Code 等），操作系统 win32 / darwin / linux
- `markitdown` 技能：PDF/DOCX/HTML → Markdown 转换（必需）
- tushare：结构化财务数据双源核对——经 `scripts/ts_fetch.py` HTTP 通道调用，token 读环境变量
  `TUSHARE_TOKEN`，**无需 tushare MCP**（无权限接口清单见 data-sources.md；未设置 token 时 A 股降级妙想单源并标注）
- 妙想 mx-ds MCP：A股/港股/美股财务、公告、新闻检索（港股路径依赖它）
- Chrome 或 Edge（可选）：check_render 渲染测量与分片截图；找不到浏览器时该门禁声明跳过
- `tesseract`（可选）：扫描版 PDF 的 OCR 降级路径；无则改用 HTML 版公告源
- 字体「朱雀仿宋」（可选）：报告视觉最优；未安装自动降级系统仿宋，不影响内容

**开发与自检**

- Python 3.x（全部脚本仅依赖标准库）
- 部署脚本 `deploy.cmd` 为 Windows 批处理（robocopy）；macOS/Linux 可用任意目录同步命令等价替代

## 五、使用方式

```bash
# 1. 确认环境（自包含，clone 后即可跑）
python bo-financial-analyzer/tests/run_regression.py   # 应 437/437 通过

# 2. 部署到本机（如需）
cmd //c deploy.cmd

# 3. 触发分析：把一份年报/半年报/季报/招股书拖进对话，说「分析这份报告」
```

- 产出：`reports/{公司名}-{代码}-{报告类型}-{报告期}-{生成日}.html` 落 `reports/` 顶层，data.json 底稿落 `reports/archive/json/`；markitdown 转换的原始 md 落 `reports/archive/原始报告/`（PDF/md 不入库）
- 同一公司第二份报告自动进入**回看模式**：逐条核对上期跟踪清单的 if-then 触发线
- 裸数字检查等启发式输出的是「待人工确认清单」，关键结论以人工通读为准

## 六、已知边界（诚实清单）

- 港股半年报已首验（蜜雪 2026H1）、港股年报已首验（阿里巴巴 09988 2026FY，IFRS/US GAAP 与非日历年财年已适配）；A 股季报已首验（中国移动 / 宁德时代 / 恒瑞医药 2026Q3）；招股书已首验（南方乳业 920196 2025FY，2026-11-13 三道门禁绿）——**当前只规划 A 股/H 股（2026-11-12 用户定案），美股未实测但不列首验计划**
- render 年报专属路径（Q4 卡 / review 回看卡 / 预期对照表 / 高管增减持 / big_moves 大动表）仍有未脚本化部分，残留 `{{}}` 判断孔由分析师手工填充（二期）
- `check_html.py` 裸数字检查是启发式，会误报/漏报；T8 ①级数字回验是数字正确性的硬门禁，裸数字仅辅助
- recon 覆盖率硬门禁用 `--min-recon auto`：按主上市市场前缀+report_type 查校准表（A 股年报 15/半年报 13/季报 4/招股书 14、港股半年报 8、港股年报 12）；季报 4 是三例真实最低可执行数，招股书 14 是南方乳业首验实测，其余未执行项仍保留 WARN；未知组合退回 WARN 态并提示显式给数
- OCR 数据须在 data.json 标注 `[OCR]` 并抽查比对，禁止用低质量 OCR 直接产出报告
- 康得新样本有 3 条等式因附注未披露无法执行（A5/B2/B3）；清越新准则造假样本已补齐 A5/B3 的真实覆盖，B2 因缺本期生产入库额仍合法降级，不以倒挤冒充验证

## 七、版本与发布

版本记录全表见 `bo-financial-analyzer/SKILL.md` 末节；已发布轮的详细轮节归档在 `handoff/supersede/`。
发布走 `AGENTS.md` 的一条链：回归通过 → commit（说清做了什么/为什么/怎么验证）→ annotated tag
→ `git push origin main --tags` → `gh release create <tag> --latest` → `deploy.cmd` → 回报结果。

| 版本 | 日期 | 要点 |
|---|---|---|
| 0.1.0 | 2026-10-06 | N4 落地：fill→render 脚本化（render_report.py + fillsheet.json 槽位契约，schema 1.6） |
| 0.1.1 | 2026-10-09 | ponytail-audit 审计 20 项修复（None 进 JS / 空桥团灭 / _NO_SRC 词边界等）+ 阳性断言 30 条 |
| 0.1.2 | 2026-10-10 | 港股首跑反馈轮：OCF 桥起点标签参数化（税前利润）；`--min-recon auto` 校准表；md_clean 港式章节名索引；方法库阅读按报告类型预裁剪 |
| 0.1.3 | 2026-10-10 | 阿里港股年报首验反馈轮：非日历年财年 FY 标签 + render 期次修复；T8② 百万单位档与千位符解析；`--min-recon auto` 港股年报=12；妙想双通道 + yahoo_finance 兜底链 |
| 0.1.4 | 2026-10-22 | 资金流向桑基图卡模板化（calc_sankey.py 符号路由 + 模板 drawSankey + sankey-slot 机检）；schema 1.7；Q3 单季差额通用取数 |
| 0.1.5 | 2026-10-22 | ponytail-audit 全技能审计修复 19 条（md_clean 表题误并 / 跨期错配 / T8① 全角减号失明等）；回归 209→252；md_clean 第二合成金标准 |
| 0.1.6 | 2026-11-01 | 技能更名 Bo-FinancialAnalyzer：源目录 / 报告品牌 / CI / 部署路径同步，回归 252→257（含 render 成品品牌断言） |
| 0.1.7 | 2026-11-12 | 通用季报 Q1/Q3 标签与 Altman 年化；auto 主市场前缀识别、A 股季报下限校准为 4；WCAG 小字对比度与 text-contrast 门禁；SVG 可访问名称、ncrline/stackH/npchart 标签避让、空分部桥降级、watchlist 单次转义、旧来源定位归一与 md_clean 标题索引修复；招股书期间/专属专章/T8期后单位与视觉裁剪首验（南方乳业）；清越新准则造假金标准与 A2 权益扣减口径；回归 257→402 |
| 0.1.8 | 2026-11-14 | 八类商业模式与 A 股/H 股/北交所真实样本扩充；独立复核闭环；未执行勾稽可见、利率差 pct、在建投入/余额双字段；图片型主表缺失提示与 fillsheet 闭合计数修复；回归 402→437 |

## 八、免责声明

本技能及其产出报告**仅为信息分析与研究辅助，不构成任何投资建议、要约或收益承诺**。

- 报告中全部数据以公司正式披露文件为一手锚点，数据库交叉核对仅作验证补充；标注「推算」「估算」的数字含假设成分，使用前请回溯其计算链
- 勾稽闭合仅证明财报内部自洽，**不代表科目真实**；审计非标意见、监管问询、期后违约等外部信号优先级高于任何等式
- 启发式检查（裸数字、排雷信号）存在误报与漏报，报告的每一张表、每一个结论都应经人工复核
- 因使用本工具产生的任何投资决策后果，由使用者自行承担
