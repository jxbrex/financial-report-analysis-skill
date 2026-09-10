# Financial Report Analysis 工作区

本仓库是「financial-report-analysis」技能的**唯一真源**，用户级目录
`C:/Users/rexji/.agents/skills/financial-report-analysis/` 只是部署副本。

## 结构

- `financial-report-analysis/` — 技能源（SKILL.md + references/×9 + assets/ + scripts/ + tests/ + examples/），**只改这里**
  - `scripts/calc.py` — Phase 7.5 计算自检门禁（桥闭合/比率复算/勾稽三态），exit 0 才允许写报告
  - `tests/` — 金标准 fixtures + 回归入口：`moutai_2025.json`（干净样本，应零误报）、
    `kangdexin_2018.json`（造假样本，应命中）；`run_regression.py` 是唯一回归入口
  - `examples/` — 标杆样本报告（few-shot 参考；早期版本，结构以当前模板为准）
- `reports/` — 测试产物。PDF/md 不入库；`贵州茅台-600519-年报-2025FY-20260904.html`
  是黄金样本，改流程/模板后用它做回归对比
- `deploy.cmd` — 部署：robocopy 镜像技能源到用户级 skills 目录（examples/ 一并上线，供运行时 few-shot）

## 纪律

1. 改完技能 → 跑 `deploy.cmd` → 新会话才生效（技能列表在会话启动时加载）
2. **任何改动后先跑回归**：`python financial-report-analysis/tests/run_regression.py` 须 exit 0
   （它内含 calc.py 双例 + 断言：茅台零 WARN、康得新 signals≥11 且红色≥6、recon 命中≥3）
3. 改 `calc.py` / `extraction-schema.md` / 任一 fixture 后，回归是强制的，不许跳过
4. 结构性改动（流程/模板/阈值）先拿黄金样本与回归双绿，再提交
5. 全程中文（代码关键字除外）
