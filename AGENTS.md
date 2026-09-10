# Financial Report Analysis 工作区

本仓库是「financial-report-analysis」技能的**唯一真源**，用户级目录
`C:/Users/rexji/.agents/skills/financial-report-analysis/` 只是部署副本。

## 结构

- `financial-report-analysis/` — 技能源（SKILL.md + references/ + assets/ + scripts/ + tests/），**只改这里**
  - `scripts/calc.py` — Phase 7.5 计算自检门禁（桥闭合/比率复算/勾稽三态），exit 0 才允许写报告
  - `tests/moutai_2025.json` — 茅台 2025 年报的 data.json 基准样本（calc.py 正例，应全绿）
- `reports/` — 测试产物。PDF/md 不入库；`贵州茅台-600519-年报-2025FY-20260904.html`
  是黄金样本，改流程/模板后用它做回归对比
- `deploy.cmd` — 部署：robocopy 镜像技能源到用户级 skills 目录

## 纪律

1. 改完技能 → 跑 `deploy.cmd` → 新会话才生效（技能列表在会话启动时加载）
2. 结构性改动（流程/模板/阈值）先拿黄金样本回归，再提交
3. **改 calc.py / extraction-schema.md 后必跑双例回归**：
   `python financial-report-analysis/scripts/calc.py financial-report-analysis/tests/moutai_2025.json` 须 exit 0；
   反例（改错比率/删 src/破坏桥闭合）须 exit 1
4. 全程中文（代码关键字除外）
