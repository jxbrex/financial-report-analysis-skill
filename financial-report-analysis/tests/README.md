# tests/ — 金标准回归样本

Phase 7.5 门禁 `scripts/calc.py` 的冻结样本。跑法（任意目录均可）：
`python tests/run_regression.py`（加 `--verbose` 附带 calc.py 原始输出）。

## 两个 fixture 各测什么

| 文件 | 样本 | 用途 | 期望值 |
|---|---|---|---|
| `moutai_2025.json` | 茅台 2025 年报 | 干净样本，抓**误报** | exit 0 · FAIL 0 · WARN 0 · OK 24 · SKIP 2；recon 无未闭合条目 |
| `kangdexin_2018.json` | 康得新 2018 年报 | 造假样本，抓**漏报** | exit 0 · FAIL 0 · WARN 3 · OK 30 · SKIP 1；signals 11 条（9 红 1 黄 1 绿）；recon 命中 3（A4 收现缺口 20.05%、A6 capex 异常 326.6%、B1 应收 roll 缺口 12.9%） |

断言 = calc.py 退出码 + 上表阈值（干净样本零 WARN、零未闭合勾稽；造假样本 signals ≥ 11、红色 ≥ 6、recon 命中 ≥ 3）；OK/SKIP 数只供人读，不作断言。

## 怎么新增 fixture

照抄现有结构，改四处，其余键可留空：

1. `meta`：company/code/period/report_type/unit 必填，`unit` 必须为「亿元」
2. `statements`：income/balance/cashflow 三表；叶子写 `{cur, prev, hist, src}`——有数值就必须有 src，`hist` 旧→新且末位等于 `cur`
3. `derived`：ratios（会复算比对）、np_bridge（Σ=Δ归母净利）、ocf_bridge（Σ=OCF）、rev_factors（Σ=Δ收入）、wc_devour
4. `recon`：`{lhs, rhs, verdict, explanation, src}`，verdict ∈ 闭合/可解释/无法解释；`signals`：`{id, level(g/y/r), title, source}`

新样本在 `run_regression.py` 里加一条 `check_xxx`，再登记进 main 的循环。

## 纪律

**改 `scripts/calc.py` 或 `references/extraction-schema.md` 后必须跑本回归，双例必须全绿。** 反例自检：改错一个比率、删掉某个 `src`、破坏任一桥闭合，门禁都应 exit 1；若本脚本仍全绿，说明门禁被改钝了——修 calc.py，不要改 fixture 数值。
