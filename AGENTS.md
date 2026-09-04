# Financial Report Analysis 工作区

本仓库是「financial-report-analysis」技能的**唯一真源**，用户级目录
`C:/Users/rexji/.agents/skills/financial-report-analysis/` 只是部署副本。

## 结构

- `financial-report-analysis/` — 技能源（SKILL.md + references/ + assets/），**只改这里**
- `reports/` — 测试产物。PDF/md 不入库；`贵州茅台-600519-年报-2025FY-20260904.html`
  是黄金样本，改流程/模板后用它做回归对比
- `deploy.cmd` — 部署：robocopy 镜像技能源到用户级 skills 目录

## 纪律

1. 改完技能 → 跑 `deploy.cmd` → 新会话才生效（技能列表在会话启动时加载）
2. 结构性改动（流程/模板/阈值）先拿黄金样本回归，再提交
3. 全程中文（代码关键字除外）
