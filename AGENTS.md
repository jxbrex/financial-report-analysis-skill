# Financial Report Analysis 工作区

本仓库是「financial-report-analysis」技能的**唯一真源**，用户级目录
`C:/Users/rexji/.agents/skills/financial-report-analysis/` 只是部署副本。

> **接手第一步请读 `HANDOFF.md`** —— 含本轮工作、已知局限与未验证项、下一步工作计划。

## 结构

- `financial-report-analysis/` — 技能源（SKILL.md + references/×9 + assets/ + scripts/ + tests/ + examples/），**只改这里**
  - `scripts/calc.py` — Phase 7.5 计算自检门禁（桥闭合/比率复算/勾稽三态/分部自洽/断言结构），exit 0 才允许写报告
  - `scripts/check_html.py` — Phase 8 报告机检（占位符/裸数字启发式/数据来源/模板硬规则/必备要素/锚点/s8 阈值形态/回看归因；`--json` 启用 T8 数字回验：①级 HTML↔data.json 笔误检测（独特值 0.5% 窗口 FAIL）+ ②级 data.json↔原文 md 行号回核），exit 0 才允许交付
  - `tests/` — 金标准 fixtures + 回归入口：`moutai_2025.json`（干净样本，应零误报）、
    `kangdexin_2018.json`（造假样本，应命中）；`run_regression.py` 是唯一回归入口（含 check_html 冒烟）
  - `examples/` — 标杆样本报告（few-shot 参考；早期版本，结构以当前模板为准）
- `reports/` — 产出目录。顶层只放成品 HTML（每公司只留最新版；`贵州茅台-600519-年报-2025FY-20260904.html`
  是黄金样本，改流程/模板后用它做回归对比）；原始报告（PDF/md）存 `reports/archive/原始报告/`，
  data.json 底稿存 `reports/archive/json/`
- `deploy.cmd` — 部署：robocopy 镜像技能源到用户级 skills 目录（examples/ 一并上线，供运行时 few-shot）

## 纪律

1. 改完技能 → 跑 `deploy.cmd` → 新会话才生效（技能列表在会话启动时加载）
2. **任何改动后先跑回归**：`python financial-report-analysis/tests/run_regression.py` 须 exit 0
   （它内含 calc.py 双例 + 断言：茅台零 WARN、康得新 signals≥11 且红色≥6、recon 命中≥3）
3. 改 `calc.py` / `extraction-schema.md` / 任一 fixture 后，回归是强制的，不许跳过
4. 结构性改动（流程/模板/阈值）先拿黄金样本与回归双绿，再提交
5. 全程中文（代码关键字除外）
6. reports/ 目录治理：顶层仅成品 HTML（每公司最新版 + 茅台黄金样本永久保留）；原始报告入
   `archive/原始报告/`、data.json 入 `archive/json/`；被替换的旧版成品删除（git 历史可查），不另建旧版存档
7. 技能/模板更新后，reports/ 顶层存量成品**不随模板重出、不改版式**——报告是产出时点的
   快照，新版式只用于下一份新产出；用户明确要求重出除外。「黄金样本回归对比」指用其
   数据做临时验证，不替换顶层成品（v0.0.7 用户定案）

## 发布流程（版本定稿时一条链做完，不拆散等提示）

技能源改动验收通过（回归 exit 0 + check_html 全绿 + 版本号与 HANDOFF.md 已同步）后，
用户说「commit / 发布 / 上线 / 定稿 / 部署」任一词语，默认按序一次做完：

1. **回归**：`python financial-report-analysis/tests/run_regression.py` 须 exit 0
2. **提交**：相关改动一个 commit——技能源 + HANDOFF.md + reports 产物（html/json）+
   计划/修订文档；PDF/md 按 .gitignore 不入库。提交信息写清「做了什么 + 为什么 + 怎么验证的」
3. **打 tag**：annotated tag，版本号与 SKILL.md 的 `version` 一致，附变更摘要
4. **推送**：`git push origin main --tags`（remote：私密仓库 jxbrex/financial-report-analysis-skill）
5. **更新 latest release**：`gh release create <tag> --title "<tag>" --notes "<变更摘要>" --latest`；
   该 tag 已有 release 则改 `gh release edit <tag> --notes "<摘要>" --latest`
6. **部署**：`cmd //c deploy.cmd` 镜像技能源到用户级 skills 目录（新会话生效）
7. **回报**：commit 短号 + tag + release URL + deploy 结果

工作区存在未提交改动时先查明归属（哪一轮修订的遗留），在提交信息里分段说明，不许默默混收。
