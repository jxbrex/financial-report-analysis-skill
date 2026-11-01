# tests/ — 金标准回归样本

Phase 7.5/8 门禁的冻结样本。跑法（任意目录均可）：
`python tests/run_regression.py`（加 `--verbose` 附带 calc.py 原始输出）。

## 四个 fixture 各测什么

| 文件 | 样本 | 用途 | 期望值 |
|---|---|---|---|
| `moutai_2025.json` | 茅台 2025 年报 | 干净样本，抓**误报** | exit 0 · FAIL 0 · WARN 0；recon 无未闭合条目 |
| `kangdexin_2018.json` | 康得新 2018 年报 | 造假样本，抓**漏报** | exit 0 · FAIL 0；signals ≥11 条且红色 ≥6；recon 命中 ≥3 |
| `vanke_2026h1.json` | 万科 2026 半年报 | 连亏地产样本（v0.0.17 固化） | 扣非双版/双驱动真实触发；WARN==2 |
| `wanhua_2026h1.json` | 万华 2026 半年报 | 周期股样本（v0.0.18 固化） | 双驱动第二样本/ROIC·SGR/白描分位锚点；WARN==2 |

断言明细以 `run_regression.py` 为准（含 calc 四例 + check_html/T8/渲染冒烟 + 构造用例）。

## 构造用例（门禁规则的正面/反面样本）

| 文件 | 验证的规则 |
|---|---|
| `md_clean_synth.md` | md_clean 合成金标准（自包含，四类病理） |
| `t8_demo.html` | T8 数字回验（改错版由回归运行时改数生成，不落文件） |

js-dup-decl / assert-trunc / internal-ref / srcline-dup / percentile-map 等其余构造用例
均内联在 `run_regression.py` 中（`_run_html_str` 临时件模式）。

`*.fillsheet.md` 是 `calc.py --fill` 的生成物（gitignored），回归会自行产出，勿提交、勿对 fixture 直接跑 --fill（会重排 json 整文件）。

## 怎么新增 fixture

照抄现有结构，改四处，其余键可留空：

1. `meta`：company/code/period/report_type/unit 必填，`unit` 必须为「亿元」
2. `statements`：income/balance/cashflow 三表；叶子写 `{cur, prev, hist, src}`——有数值就必须有 src，`hist` 旧→新且末位等于 `cur`
3. `derived`：ratios（会复算比对）、np_bridge（Σ=Δ归母净利）、ocf_bridge（Σ=OCF）、rev_factors（Σ=Δ收入）、wc_devour
4. `recon`：`{lhs, rhs, verdict, explanation, src}`，verdict ∈ 闭合/可解释/无法解释；`signals`：`{id, level(g/y/r), title, source}`

新样本在 `run_regression.py` 里加一条 `check_xxx`，再登记进 main 的循环。

## 纪律

**改 `scripts/calc.py` 或 `references/extraction-schema.md` 后必须跑本回归，四例必须全绿。** 反例自检：改错一个比率、删掉某个 `src`、破坏任一桥闭合，门禁都应 exit 1；若本脚本仍全绿，说明门禁被改钝了——修 calc.py，不要改 fixture 数值。
