# Financial Report Analysis 工作区

本仓库是「financial-report-analysis」技能的**唯一真源**，用户级目录
`C:/Users/rexji/.agents/skills/financial-report-analysis/` 只是部署副本。

> **接手第一步请读 `handoff/HANDOFF.md`** —— 含本轮工作、已知局限与未验证项、下一步工作计划；
> 已发布轮次的历史记录在 `handoff/supersede/`（子目录外只留最新版，2026-09-24 用户定案）。

## 结构

- `financial-report-analysis/` — 技能源（SKILL.md + references/×10 + assets/ + scripts/ + tests/ + examples/），**只改这里**
  - `scripts/calc.py` — Phase 7.5 计算自检门禁（桥闭合/比率复算/勾稽三态/分部自洽/断言结构），exit 0 才允许写报告；
    模块布局（v0.0.12 起 1k 红线整改、v0.0.15 再拆）：`calc_common.py`（共享助手 + 比率公式唯一定义处 +
    hist_periods/批量比对助手）+ `calc_dupont.py`（杜邦族：连环替代三口径/因子下钻/五年归因与分位）+
    `calc_evidence.py`（周期证据/四线贴线/peers 结构）+ `calc_risk.py`（破产双模型/压力情景/现金时序）+
    `calc_models.py`（fill 编排层，不含公式），入口仍是 calc.py
  - `scripts/check_html.py` — Phase 8 报告机检（占位符/裸数字启发式/数据来源/模板硬规则/必备要素/锚点/s8 阈值形态/回看归因 + v0.0.12 起缩写首现展开/OCF 桥项数/归因 figtitle 前瞻与复述/检验卡判定列四条 WARN + v0.0.15 起 s1 杜邦双卡形态/ΔROE 堆叠条数据槽比对 + v0.0.18 起 internal-ref 内部引用禁词/srcline-dup 拼接纪律/percentile-map 分位白描映射三条 FAIL + v0.0.19 起 assertion-count 断言计数 FAIL 与 recon-label 三态措辞/decimal-places 小数位两条 WARN + v0.0.21 起 gap-declaration ❓断言进数据缺口声明行 FAIL + v0.0.22 起 js-dup-decl 数据槽 const 重复声明 FAIL 与 assert-trunc 断言填充截断 FAIL + v0.0.23 起 s1-grid4 四宫格纯 svg FAIL）；exit 0 才允许交付；
    模块布局：`check_html_common.py`（共享助手）+ `check_html_text.py`（呈现文本族 15 条检查，v0.0.19 拆出——加规则前置约定触发；PCTILE_LABEL 居此，check_html.py 再导出保契约锁锚点）+ `check_html_t8.py`（T8 数字回验：`--json` 启用，①级 HTML↔data.json 笔误检测（独特值 0.5% 窗口 FAIL + v0.0.19 hist_pool 序列中间值豁免）+ ②级 data.json↔原文 md 行号回核），入口仍是 check_html.py
- `scripts/check_render.py` — 渲染测量门禁（可选但默认执行）：headless Chrome/Edge 真渲染后测量 SVG 文本重叠/HTML 溢出 .sheet/横向裁剪 + v0.0.22 起 empty-svg 关键 SVG 非空检测（长城 JS 团灭事故补口）；`--png` 按章分片截图供 Phase 8 视觉验收；找不到浏览器声明跳过 exit 0，发现问题 exit 1
- `scripts/gate.py` — 三道门禁单入口（v0.0.13）：calc → check_html --json → check_render 一条命令，统一退出码
- `scripts/md_clean.py` — 财报 md 一次性确定性清洗（v0.0.13）：拼回 PDF 拆碎的逻辑表行、删重复分隔行与页眉页脚，产出 clean md 唯一工作副本 + 章节索引 sidecar；内置数字/文字双不变量，违反 exit 1
  - `tests/` — 金标准 fixtures + 回归入口：`moutai_2025.json`（干净样本，应零误报）、
    `kangdexin_2018.json`（造假样本，应命中）、`vanke_2026h1.json`（连亏地产样本，
    扣非双版/双驱动真实触发）、`wanhua_2026h1.json`（周期股样本，双驱动第二样本/
    ROIC·SGR 首验/白描分位锚点；v0.0.18 固化）、`md_clean_synth.md`（md_clean 合成金标准，自包含）；
    `run_regression.py` 是唯一回归入口（119 断言，含 check_html/T8/渲染冒烟与构造用例）
  - `examples/` — 构造样本（lookback-demo 回看机制演示）；标杆样本 v0.0.18 起退役
    （槽位契约归 fillsheet、文风示范归模板注释「真实示范」条目，不再随模板改动维护副本）
- `reports/` — 产出目录。顶层只放成品 HTML（每公司只留最新版；`贵州茅台-600519-年报-2025FY-20260904.html`
  是黄金样本，改流程/模板后用它做回归对比）；原始报告（PDF/md）存 `reports/archive/原始报告/`，
  data.json 底稿存 `reports/archive/json/`
- `deploy.cmd` — 部署：robocopy 镜像技能源到用户级 skills 目录

## 纪律

1. 改完技能 → 跑 `deploy.cmd` → 新会话才生效（技能列表在会话启动时加载）
2. **任何改动后先跑回归**：`python financial-report-analysis/tests/run_regression.py` 须 exit 0
   （它内含 calc.py 四例 + 断言：茅台零 WARN、康得新 signals≥11 且红色≥6、recon 命中≥3、
   万科 WARN==2 且扣非双版/双驱动真实触发、万华 WARN==2 且双驱动第二样本+白描分位锚点）
3. 改 `calc.py` / `extraction-schema.md` / 任一 fixture 后，回归是强制的，不许跳过
4. 结构性改动（流程/模板/阈值）先拿黄金样本与回归双绿，再提交
5. 全程中文（代码关键字除外）
6. 报告流程撞上技能 bug：**只提示、只绕过、只记账（写 handoff 待办），不修技能源**——
   多份报告并行共享同一技能源，当场修互相污染（v0.0.22 用户定案）；绕过只许呈现层，
   禁止为过门禁改数据/fixture；技能修订只在专门修订轮做
7. reports/ 目录治理：顶层仅成品 HTML（每公司最新版 + 茅台黄金样本永久保留）；原始报告入
   `archive/原始报告/`、data.json 入 `archive/json/`；被替换的旧版成品删除（git 历史可查），不另建旧版存档
8. 技能/模板更新后，reports/ 顶层存量成品**不随模板重出、不改版式**——报告是产出时点的
   快照，新版式只用于下一份新产出；用户明确要求重出除外。「黄金样本回归对比」指用其
   数据做临时验证，不替换顶层成品（v0.0.7 用户定案）
9. 工作区文件及时清理：阶段性文档（修订计划 / 临时脚本 / 一次性验证产物）在其对应
   版本落地后即删除——git 历史可查，不另建存档；工作区根目录只留长期文件
   （AGENTS.md / README.md / deploy.cmd / 技能源 / reports/ / handoff/）。
   修订的定案结论以 handoff/HANDOFF.md 为唯一真源，修订计划文档本身不作长期留存
   （2026-09-17 用户定案；v0.0.3 / v0.0.5 / v0.0.7 三份旧修订计划已按此条清理）。
   **HANDOFF 归档制（2026-09-24 用户定案，长期执行）**：`handoff/HANDOFF.md` 只留
   最新版（长期节 + 当前未发布轮 + 运维速查），轮次记录**落地发布后**整节移入
   `handoff/supersede/`（按版本区间一个文件），其中仍具操作价值的「维护者注意」
   提炼进活文档「运维速查」节后再移；子目录外永不堆积历史轮

## 发布流程（版本定稿时一条链做完，不拆散等提示）

技能源改动验收通过（回归 exit 0 + check_html 全绿 + 版本号与 handoff/HANDOFF.md 已同步）后，
用户说「commit / 发布 / 上线 / 定稿 / 部署」任一词语，默认按序一次做完：

1. **回归**：`python financial-report-analysis/tests/run_regression.py` 须 exit 0
2. **提交**：相关改动一个 commit——技能源 + handoff/ + reports 产物（html/json）+
   计划/修订文档；PDF/md 按 .gitignore 不入库。提交信息写清「做了什么 + 为什么 + 怎么验证的」
3. **打 tag**：annotated tag，版本号与 SKILL.md 的 `version` 一致，附变更摘要
4. **推送**：`git push origin main --tags`（remote：私密仓库 jxbrex/financial-report-analysis-skill）
5. **更新 latest release**：`gh release create <tag> --title "<tag>" --notes "<变更摘要>" --latest`；
   该 tag 已有 release 则改 `gh release edit <tag> --notes "<摘要>" --latest`
6. **部署**：`cmd //c deploy.cmd` 镜像技能源到用户级 skills 目录（新会话生效）
7. **回报**：commit 短号 + tag + release URL + deploy 结果

工作区存在未提交改动时先查明归属（哪一轮修订的遗留），在提交信息里分段说明，不许默默混收。
