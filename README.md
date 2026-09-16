# financial-report-analysis

> 上市公司年报 / 半年报 / 季报 / 招股说明书分析技能（Agent Skill）——输入一份定期报告，产出一份单文件自包含 HTML 分析报告。

[![版本](https://img.shields.io/badge/version-0.0.4-blue)](https://github.com/jxbrex/financial-report-analysis-skill/releases/latest)
[![回归](https://img.shields.io/badge/%E5%9B%9E%E5%BD%92-14%2F14%20%E7%BB%BF-brightgreen)](financial-report-analysis/tests/run_regression.py)

---

## 一、概述

本技能把「读财报」这件事变成一条可复算、可追溯、可证伪的流水线：

- **输入**：上市公司定期报告或招股说明书（PDF / DOCX / HTML），用户在对话中直接提供文件，或指定公告由技能定位下载
- **处理**：结构化抽取 → 勾稽验算 → 排雷扫描 → 因素分解 → 文字部分（MD&A）分析 → 外部数据交叉校验
- **产出**：单文件自包含 HTML 报告（10 章，锚点 `s0~s8`），落在当前工作目录 `reports/` 顶层，命名 `{公司名}-{代码}-{报告类型}-{报告期}-{生成日}.html`

核心立场：**财报分析的产出是「排除与揭示」——这份报告哪里可疑、哪里被解释清楚了，而不是给一个跨维度加权总分做质量排序**。技能与股票分析类 skill（如 stock-deep-analysis）完全独立：本技能只解读已发生事项，无条件未来断言与多空立场不在产出范围内。

## 二、整体逻辑与方法论

### 四层分析引擎（每层结论可回溯到下层证据）

```
数据层（extraction-schema.md 的 data.json）
  → 恒等式层（articulation.md 的过程勾稽）
    → 比率与基准层（frameworks.md）
      → 叙事层（text-mining.md 的断言验证）
```

- **数据层**：从报告原文抽取结构化 data.json，tushare / 东方财富双源核对，报告原文为一手锚点
- **恒等式层**：A 组 8 条恒等式（资产=负债+权益、现金勾稽、Capex 勾稽、收入-收现闭环等）+ B 组 4 条 roll-forward（应收/存货/固定资产/未分配利润滚动）+ C 组 2 条周期判定 + D 组 5 条母公司
- **比率与基准层**：杜邦分解、CCC 现金转换周期、应收/存货三维判定、费用 ROI、周期定位、四线考核
- **叙事层**：MD&A 三层读法、措辞对比、断言验证矩阵（F1/F2/F3 三态：✅ 通过 / ❓ 无法验证 / 🔴 不成立）

**最重要的认知：勾稽闭合 ≠ 科目真实**。造假者能在自己的账套里把等式做平（本仓库康得金标准样本中，A1 现金勾稽算术闭合，但 122 亿存款已被资金归集协议锁定不可用）。因此审计意见 / 独董异议 / 问询函 / 期后违约的信息优先级不低于任何等式。

### 分析流水线（Phase 0 → 8）

输入识别转换（长文档分章读取、扫描件 OCR 降级）→ 数据抽取 → **Phase 2.5 勾稽验算** → 排雷扫描（四态呈现：🔴 命中 / 🟡 观察 / ↩ 反向未触发）→ 文字部分分析（赛道重合度、断言验证）→ **Phase 7.5 计算自检门禁** → 因素分析（三座桥）→ 股东与期后 → 机构预期与回看 → **Phase 8 报告机检** → 交付

其中「三座桥」是因素分析的主干：

1. **收入桥**：量 / 价 / 结构三效应（无量价数据时降级为分部桥）
2. **净利润桥**：毛利 → 税金 → 费用 → 减值 → 投资 → 非经 → 所得税 → 少数股东，定位利润变化的第一驱动
3. **净利 → 经营现金流调节桥**（间接法）：回答「利润为什么没变成现金」，营运资本吞噬逐项量化

「真布局还是蹭热点」的判定（text-mining.md）：资本开支 / 产能订单 / 研发投入 / 收入贡献四问，两项以上有硬证据才算真布局；管理层点名的重点规模数字必须补**行业坐标**——同行对比、行业占比、口径说明，凑不齐就直说「缺乏可比基准」，不许只搬运管理层数字。

### 三道质量关（机器门禁，不是装饰）

| 门禁 | 位置 | 校验内容 | 失败后果 |
|---|---|---|---|
| `scripts/calc.py` | Phase 7.5，写报告前 | 结构/出处、核心科目覆盖、资产=负债+权益、未分配利润滚动、三座桥闭合、比率复算、勾稽三态一致性、分部自洽、断言结构、应付未付利息 | exit 非 0 禁止写报告 |
| `scripts/check_html.py` | Phase 8，交付前 | 占位符残留、裸数字启发式、数据来源标注、模板硬规则（禁外部资源/渐变/暗色）、必备要素（免责声明/跟踪清单）、章节编号、锚点完整性 | exit 非 0 禁止交付 |
| `tests/run_regression.py` | 任何改动后 | 金标准双例：茅台 2025（干净样本，须零误报）+ 康得新 2018（造假样本，须命中 ≥11 信号其中红 ≥6、recon 命中 ≥3），共 14 条断言 + check_html 冒烟 | 不绿不许提交 |

## 三、目录结构

```
Financial Report Analysis/          本仓库（技能唯一真源）
├── financial-report-analysis/      技能源——只改这里
│   ├── SKILL.md                    技能主文档：触发条件、何时不用、Phase 0~8 工作流、版本记录
│   ├── assets/
│   │   └── report-template.html    单文件报告模板（内联 SVG 绘图、锚点 s0~s8、置信度徽章体系）
│   ├── references/                 方法库 ×9
│   │   ├── extraction-schema.md    data.json 数据契约（每个字段的出处与校验规则）
│   │   ├── articulation.md         勾稽核对手册（A/B/C/D 四组恒等式与使用总则）
│   │   ├── factor-analysis.md      三因素分解、三座桥、四象限
│   │   ├── frameworks.md           公式库、CCC、周期定位、费用 ROI、四线考核
│   │   ├── redflags.md             排雷信号库（四态判定 + 红/黄/亮点 + 审计交叉命中）
│   │   ├── text-mining.md          MD&A 三层读法、断言验证矩阵、赛道重合度四问 + 行业坐标
│   │   ├── industry-profiles.md    七类商业模式调焦 + 各模式先行指标建议集
│   │   ├── data-sources.md         markitdown / tushare / 妙想接口速查、港股路径、OCR 降级
│   │   └── report-types.md         年报/半年报/季报/招股书/港美股的差异与裁剪规则
│   ├── scripts/
│   │   ├── calc.py                 Phase 7.5 数据层门禁
│   │   ├── check_html.py           Phase 8 报告层门禁
│   │   └── ts_fetch.py             tushare HTTP 取数（双源核对通道，token 读环境变量，无需 MCP）
│   ├── tests/
│   │   ├── moutai_2025.json        干净样本金标准（应零误报）
│   │   ├── kangdexin_2018.json     造假样本金标准（应命中）
│   │   └── run_regression.py       唯一回归入口（14 断言）
│   └── examples/                   标杆样本报告（few-shot 参考，结构以当前模板为准）
├── reports/                        产出目录。顶层只放成品 HTML（每公司最新版；PDF/md 不入库，json 入库）
│   ├── 贵州茅台-…-20260904.html     黄金样本（改流程/模板后用它做回归对比）
│   └── archive/
│       ├── 原始报告/               原始报告（PDF/md，不入库）
│       └── json/                   data.json 底稿（入库）
├── deploy.cmd                      部署：robocopy 镜像技能源到用户级 skills 目录
├── AGENTS.md                       工作区纪律 + 发布流程（一条链：回归→commit→tag→push→release→deploy）
├── HANDOFF.md                      交接文档：本轮工作、已知局限、下一步计划
└── 修订计划-*.md                    各轮修订的设计定案
```

用户级目录 `C:/Users/rexji/.agents/skills/financial-report-analysis/` 只是 `deploy.cmd` 的镜像副本，**绝不直接修改**。

## 四、环境

**运行时（使用技能分析报告）**

- 任意支持 Skill 机制的 Agent 会话（Kimi Code 等），操作系统 win32 / darwin / linux
- `markitdown` 技能：PDF/DOCX/HTML → Markdown 转换（必需）
- tushare：结构化财务数据双源核对——经 `scripts/ts_fetch.py` HTTP 通道调用，token 读环境变量
  `TUSHARE_TOKEN`，**无需 tushare MCP**（权限频控跟 token 走；`anns_d` 公告接口需专项权限，
  无权限时用妙想 `mx_finance_search_notice` 替代；未设置 token 时 A 股双源降级为妙想单源并标注）
- 妙想 mx-ds MCP：A股/港股/美股财务、公告、新闻检索（港股路径依赖它）
- `tesseract`（可选）：扫描版 PDF 的 OCR 降级路径；无则改用 HTML 版公告源
- 字体「朱雀仿宋」（可选）：报告视觉最优；未安装自动降级系统仿宋，不影响内容

**开发与自检**

- Python 3.x（`calc.py` / `check_html.py` / `run_regression.py` 仅依赖标准库）
- 部署脚本 `deploy.cmd` 为 Windows 批处理（robocopy）；macOS/Linux 可用任意目录同步命令等价替代

## 五、使用方式

```bash
# 1. 确认环境
python financial-report-analysis/tests/run_regression.py   # 应 14/14 通过

# 2. 部署到本机（如需）
cmd //c deploy.cmd

# 3. 触发分析：把一份年报/半年报/季报/招股书拖进对话，说「分析这份报告」
```

- 产出：`reports/{公司名}-{代码}-{报告类型}-{报告期}-{生成日}.html` 落 `reports/` 顶层，data.json 底稿落 `reports/archive/json/`；markitdown 转换的原始 md 落 `reports/archive/原始报告/`（PDF/md 不入库）
- 同一公司第二份报告自动进入**回看模式**：逐条核对上期跟踪清单的 if-then 触发线
- 裸数字检查等启发式输出的是「待人工确认清单」，关键结论以人工通读为准

## 六、已知边界（诚实清单）

- 港股/美股路径验证了数据源可用，未跑完整流程；半年报/季报/招股书三类报告的裁剪规则为纸面推演
- `check_html.py` 裸数字检查是启发式，会误报/漏报；`calc.py` 的 recon 覆盖率目前只是 WARN 不是硬门禁
- OCR 数据须在 data.json 标注 `[OCR]` 并抽查比对，禁止用低质量 OCR 直接产出报告
- 康得新样本有 3 条等式因附注未披露无法执行（A5/B2/B3），换一个披露更全的造假样本可补齐验证

## 七、版本与发布

版本记录见 `financial-report-analysis/SKILL.md` 末节。发布走 `AGENTS.md` 的一条链：
回归通过 → commit（说清做了什么/为什么/怎么验证）→ annotated tag → `git push origin main --tags`
→ `gh release create <tag> --latest` → `deploy.cmd` → 回报结果。

| 版本 | 日期 | 要点 |
|---|---|---|
| 0.0.2 | 2026-09-10 | 测试体系、回看模式、置信度徽章、HTML 机检 |
| 0.0.3 | 2026-09-11 | 删跨维度加权评分体系；朱雀仿宋字体；排雷四态；watchlist 定制化 |
| 0.0.4 | 2026-09-13 | 净利桥删图去重；正文纯黑；重点宣称数字补行业坐标 |

## 八、免责声明

本技能及其产出报告**仅为信息分析与研究辅助，不构成任何投资建议、要约或收益承诺**。

- 报告中全部数据以公司正式披露文件为一手锚点，数据库交叉核对仅作验证补充；标注「推算」「估算」的数字含假设成分，使用前请回溯其计算链
- 勾稽闭合仅证明财报内部自洽，**不代表科目真实**；审计非标意见、监管问询、期后违约等外部信号优先级高于任何等式
- 启发式检查（裸数字、排雷信号）存在误报与漏报，报告的每一张表、每一个结论都应经人工复核
- 因使用本工具产生的任何投资决策后果，由使用者自行承担
