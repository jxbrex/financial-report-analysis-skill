# HANDOFF · 交接文档

> 版本 **0.0.22** · 截至 2026-10-01 · 本文档面向「下一个接手这个项目的人/AI 会话」
> 仓库：https://github.com/jxbrex/financial-report-analysis-skill（**私密**）
> 部署：`C:/Users/rexji/.agents/skills/financial-report-analysis/`（由 `deploy.cmd` 镜像）

---

## 一、这个项目是什么

一个**上市公司年报/半年报/季报/招股说明书分析技能**。用户把报告文件拖进对话，
技能把它转成 markdown、抽取结构化数据、跑勾稽验算与排雷、做因素分析与文字分析，
最后产出一份单文件自包含 HTML 报告。

核心设计：**四层分析引擎**，每层结论都能回溯到下层证据
```
数据层（extraction-schema.md 的 data.json）
  → 恒等式层（articulation.md 的过程勾稽）
    → 比率与基准层（frameworks.md）
      → 叙事层（text-mining.md 的断言验证）
```

---

## 二、技能构成与三道门禁

### 技能现在的构成（27 个源文件）

```
financial-report-analysis/
├── SKILL.md                    # 11 个 Phase（0→8，含 2.5 勾稽验算、7.5 QC 门禁）+ 版本记录
├── references/                 # 10 份方法库
│   ├── articulation.md         #   勾稽核对手册：A组8条恒等式+B组4条roll-forward+C组2条周期+D组5条母公司
│   ├── redflags.md             #   排雷信号库：四态判定分类 + 红/黄/亮点 + 审计交叉命中 + 人效三维
│   ├── frameworks.md           #   〇口径总则 + 公式库（含 ROIC/内生增长率）+ CCC + 周期定位 + 费用ROI + 四线考核
│   ├── factor-analysis.md      #   三因素分解 + 净利润桥 + OCF 调节桥 + 四象限
│   ├── text-mining.md          #   MD&A 三层读法 + 断言验证矩阵（F1/F2/F3）
│   ├── industry-profiles.md    #   八类商业模式调焦 + 客户价值五维 + 经销商压货三条件
│   ├── extraction-schema.md    #   data.json 数据契约（schema 1.4）
│   ├── data-sources.md         #   markitdown / tushare / 妙想 接口速查 + 港股路径 + OCR 降级
│   ├── report-types.md         #   年报/半年报/季报/招股书/港美股 差异
│   └── subagent-prompts.md     #   并行派发窗派单模板 ×5（v0.0.14）
├── assets/report-template.html # 10 章单文件报告模板（内联 SVG 绘图函数族、锚点 s0~s8 + review、置信度徽章）
├── scripts/                    # 14 个脚本
│   ├── calc.py                 #   Phase 7.5 数据层门禁入口（--fill / --min-recon / --strict）
│   ├── calc_common.py          #   共享层：取值助手 + 比率公式唯一定义处 + hist_periods/批量比对
│   ├── calc_dupont.py          #   杜邦族：连环替代三口径 / 因子下钻 / 五年归因与分位
│   ├── calc_evidence.py        #   周期证据 / 四线贴线 / peers 结构
│   ├── calc_risk.py            #   破产双模型 / 压力情景 / 现金时序
│   ├── calc_models.py          #   --fill 编排层 + fillsheet 产出（不含公式）
│   ├── check_html.py           #   Phase 8 报告层门禁入口（结构/硬规则族 + 主流程）
│   ├── check_html_common.py    #   报告机检共享助手
│   ├── check_html_text.py      #   呈现文本族 11+3 条检查（v0.0.19 拆出；PCTILE_LABEL 居此）
│   ├── check_html_t8.py        #   T8 数字回验整族（①级笔误检测 + hist_pool 豁免 + ②级行号回核 + v0.0.22 assert-trunc 断言填充截断）
│   ├── check_render.py         #   渲染测量门禁（headless Chrome/Edge，--png 分片截图；v0.0.22 起 empty-svg 关键 SVG 非空检测）
│   ├── gate.py                 #   三道门禁单入口
│   ├── md_clean.py             #   财报 md 确定性清洗 + 章节索引
│   └── ts_fetch.py             #   tushare HTTP 取数通道
├── tests/                      # 金标准 fixtures + 回归入口
│   ├── moutai_2025.json        #   干净样本（应零误报；schema 1.4）
│   ├── kangdexin_2018.json     #   造假样本（应命中；含 parent_statements + D 组判定）
│   ├── vanke_2026h1.json       #   连亏地产样本（v0.0.17 固化：扣非双版/双驱动真实触发）
│   ├── wanhua_2026h1.json      #   周期股样本（v0.0.18 固化：双驱动第二样本/ROIC·SGR 首验/白描分位锚点）
│   ├── md_clean_synth.md       #   md_clean 合成金标准（自包含，四类病理；v0.0.17 起不再依赖原始 md）
│   ├── t8_demo.html / t8_demo_bad.html  # T8 数字回验验收样例（正确版 / 改错版）
│   ├── dup_decl_demo.html      #   js-dup-decl 构造用例（const 顶层重复声明，v0.0.22）
│   ├── assert_trunc_demo.html/.json  #   assert-trunc 构造用例（断言填充截断，v0.0.22）
│   └── run_regression.py       #   唯一回归入口：116 条断言 + check_html/T8/渲染冒烟 + 构造用例
└── examples/                   # lookback-demo 构造样本（标杆样本 v0.0.18 退役：槽位归 fillsheet、文风归模板注释）
```

### 三道机器门禁 + 一条回归

1. **`scripts/calc.py`（数据层，Phase 7.5，写报告前）**
   校验：结构/出处、核心科目覆盖度、资产=负债+权益、未分配利润滚动、三座桥闭合
   （净利桥/OCF 调节桥/收入三效应）、比率复算（含 dfl/dol/non_main_rev_share/ocf_to_liab）
   与 5 期 hist 逐期复算、勾稽三态一致性（A/B 组 + D 组 manual 型）、分部自洽、
   断言结构、勾稽覆盖率、应付未付利息、信号结构。exit 0 才允许进入 Phase 8。
2. **`scripts/check_html.py`（报告层，Phase 8，交付前）**——v0.0.19 起呈现文本族拆至
   `check_html_text.py`（PCTILE_LABEL 居此、入口再导出保契约锁锚点）。
   校验：占位符漏填、裸数字（启发式）、数据来源标注、模板硬规则、必备要素
   （下期清单/免责声明）、章节编号、锚点完整性、s2 瘦身形态、s8 阈值形态、回看归因；
   `--json` 启用 **T8 数字回验**：①级 HTML↔data.json 笔误检测（独特值 0.5% 窗口 FAIL，
   v0.0.19 起 hist_pool 序列中间值豁免）+ ②级 data.json↔原文 md 行号回核；v0.0.18 起三条
   FAIL 规则（**internal-ref** 内部引用禁词 / **srcline-dup** 拼接纪律 / **percentile-map**
   分位白描映射）；v0.0.19 起加 **assertion-count**（FAIL：断言 figtitle 三态计数
   a+b+c=N 且与表内徽章/底稿 assertions 一致）与 **recon-label**（勾稽三态旧长标签）、
   **decimal-places**（可见数字 ≥3 位小数）两条 WARN；v0.0.21 起加 **gap-declaration**（FAIL：s4 ❓ 断言须进「数据缺口声明」行）；v0.0.22 起加 **js-dup-decl**（FAIL：数据槽顶层 const 重复声明——JS 团灭防线）与 **assert-trunc**（FAIL：断言 text/evidence 填充截断，--json）。exit 0 才允许交付。
3. **`python tests/run_regression.py`** —— 任何改动后必跑，**116 条断言**全绿才算没改坏
   （含 calc 四例 + check_html 冒烟 + T8 数字回验 + md_clean 合成样本 + 构造用例
   + fillsheet JS 槽形态冒烟）。

---

## 运维速查（历史轮提炼，长期有效）

> 从已归档轮次的「维护者注意」中提炼仍具操作价值的条目；原文在 supersede/ 对应文件。

- **check_render（Edge）**：`--dump-dom` 的 stdout 在本机为空，测量结果走 localhost HTTP
  回传 + screenshot 探针终止，勿改回 dump-dom；Edge 主进程先退、渲染子进程异步写盘/回调，
  `chrome_run` 的 `linger` 参数是修复，勿删（二·十五 1/2）
- `--png` 单章窗口高 = 章节实测高 + 40；换机器截图全红先查该机 Edge 异步写盘行为（二·十五）
- halo 只解可读性、不解几何重叠：L2 门禁保持 text-text 检测范围，勿扩成 text-bar（二·十四 L1）
- `check_s8_shape` 旧表兜底分支是存量 compat 非死代码，勿清理；`slot-length` 只测 s1 第一张表，
  杜邦表末列长文本不在范围（二·十五）
- masthead 分片含 fade 动画帧、非确定，像素 diff 永远不可比；视觉对比排除该分片（二·十七）
- 存量旧版式报告：check_render 窄视口必报 pageclip、T8①级 FAIL 15~28 处/份——均预期，
  不追溯不重出（纪律 7；二·十一 / 二·十七）
- 纪律 7「重出」范围 = 按现行全部规则重出，不止版式与数字（宁德 0922 补刀教训，二·十七末）
- 康得新 2014–2017 公开库为 2019 追溯重述值、当年年报对比列为原始值，不可拼接趋势；
  缺 hist 是合法状态（血泪清单 7；二·八）
- `hist_ye` 只对平均余额比率需要的 4 个 balance 科目定义；其他科目加了会被结构校验
  （末位=prev）约束，别乱加（二·十六）
- ts_fetch 无权限接口：anns_d / hk_income / hk_balancesheet / hk_cashflow /
  hk_fina_indicator / yc_cb / news；港股财务降级走妙想 mx_hk_finance_data（二·十三）
- 审计类 skill（thermo-nuclear-code-quality-review）为用户触发限定，模型侧调用被禁；
  skill 不在可用列表时不得用近义 skill 顶替（二·十八前置插曲）
- 茅台黄金样本（reports/ 顶层）为 v0.0.4 版式，仅作流程回归对比，不随模板重出（纪律 7）
- fill 的 note/src 是判断字段不许吞：v0.0.17 前 risk_models 块级 note 会被 --fill 吞掉（已修）；
  幂等回归已含字符串叶精确比对，凡动 fill/derived 结构必跑回归（二·二十四）
- robocopy `/XD __pycache__` 盲区：/MIR 不清理存量排除项——deploy.cmd 里的 for /d 存量清除行勿删（二·二十四）
- T8①级 0.5% 窗口会反向约束数字呈现粒度：两值撞窗时按更粗粒度呈现
  （万科 39.3699 vs 39.3991 → 39.4，二·二十二）
- L4 目检清单含「折线全部数据点在画布内」——check_render 的 overlap/clipped 测不到出界点
  （万科 ROE 线两点被顶出 SVG 的漏检教训，SKILL.md Phase 8 已落）
- T8① 会把断言表出处列的裸 L 行号当数字提取撞窗（长城轮 L873 vs 归母净资产 873.93）——
  断言表「出处」列写章节名不写裸行号，或行号与其他 json 值撞窗时按更粗粒度改写（长城轮实证）
- **js-dup-decl 判据=行首顶层 const 重名**（依赖数据槽顶格写的模板约定；函数内局部 const
  同名是合法块级作用域、不误报）——若未来模板改缩进声明会漏检（debt 注释在 check_html.py，v0.0.22）
- assert-trunc 口径：json assertions 的 text/evidence 前 15 字锚点定位 + 最长公共前缀判定
  「真前缀+…」即截断；底稿本身以「…」结尾或字段空串不判（v0.0.22）
- check_render empty-svg：空 SVG 无元素可测=几何门禁的结构性盲区（长城 JS 团灭实证），
  关键 SVG id 清单在 check_render.py `KEY_SVG_IDS`；降级删卡（hist<3 期等）不在页面不查（v0.0.22）
- 模板 demo 槽数据要有区分度：全 0 值多线/多段同点必致标签重叠（stackH v0.0.21、effline
  v0.0.22 两度实证）——demo 值取分散示例，别为「占位干净」填全 0
- deltaBars 端点柱按 st/en 固定槽位取 ends[0]/ends[1]——按 filter 后位置取会在
  SEG_ENDS=[null,X] 时把期末柱错位画到顶行（v0.0.21 热核实证）
- 回归各构造块独立跑 write_fillsheet，不复用前块文本（跨块隐式依赖静默断锚，v0.0.21）
- **勿对 fixture 直接跑 `calc.py --fill`**：--fill 会 json.dump 重写整文件（键序重排，
  git  diff 几千行、数值未变）——验证 fillsheet 产出用临时副本（v0.0.22 万华 fixture 误染
  已还原）
- 长城 2026H1 报告为事故留档样本（用户定案不修）：js-dup-decl 2 / assert-trunc 62 /
  empty-svg 5 命中属预期，勿追溯（v0.0.22）
- OCF 桥失守三层堵口勿回退（v0.0.20，卫星实证）：派单模板「补充资料」必提项+「换搜『将净利润
  调节为』、禁凭常识降级」护栏 / SKILL 门禁接线 --min-recon / calc 空桥且 OCF 已填 SKIP 升 WARN
  / check_html undisclosed 反向检索——任一被「优化」掉都会重开失守模式（原文在 supersede/v0.0.20）
- 查 tag 用 `git tag | sort -V`，别用 tail（字符串排序 v0.0.10 排在 v0.0.5 前的坑，二·二十一）
- 存量旧版式报告跑新 check_html 会出 internal-ref（内部引用禁词）与 percentile-map
  （分位白描）FAIL——纪律 7 不追溯不重出，属预期（v0.0.18；与 T8①级对旧报告的固有
  噪音同类）。万华 2026H1 报告即此形态（仅修了 6 处内容错误，版式留在 v0.0.15 代）；
  v0.0.19 起美的快照（v0.0.18 版式）再加 assertion-count FAIL（figtitle 8+1+2≠10 笔误
  留档）与 recon-label/decimal-places WARN，同属预期；v0.0.21 起再加 gap-declaration
  FAIL（❓2 无声明行，本轮评估定案）——undisclosed 零命中（存量 grep 验证一致）
- 分位白描映射 X/5（v0.0.19 起：五年从高到低第 X——0→5/5 / .25→4/5 / .5→3/5 / .75→2/5 /
  1→1/5；旧措辞「5 期中第 2 高」族退役）双写定义在 check_html_text.py `PCTILE_LABEL` 与
  calc_models.py `PCTILE_LABEL`（check_html.py 再导出保回归契约锁锚点）——改动必须同步
- combo 线序列支持 null 跳点（环比首期无值不画点、断点不硬连，v0.0.19，与 trendDual
  ROE 线同一约定）；check_html 拆分口径：呈现文本族（文风/标签/格式）归
  check_html_text.py，结构/硬规则族与主流程留 check_html.py
- 模板注释里的特性编号（F/T/L）与 HANDOFF/方法库有交叉引用——清理注释别全量机械删
  （v0.0.18 热核 F1 误删 spark 线色纪律一行的实证）
- decimal-places WARN 只屏蔽 srcline：inline style 里的 3+ 位小数（如 width:33.3333%）
  会误报——当前模板无此形态，将来引入再扩屏蔽面（v0.0.19 对抗评审备查）
- 万华轮效率基线（v0.0.18 效率治理对照）：全流程 53.3min，LLM 流式占 86%；
  Phase 8 填模板+门禁返工 19.5min、手写 16k token json 单步 311s、附注单代理 547s
  拖满 9.1min 并行窗口、grep 万科标杆 11 次。治理后（fillsheet 全槽位契约/派发窗
  6 代理分块落盘/两段填充半程门禁）下一份报告对比这四项指标

## 三、历史发现与轮次记录

已发布轮次的复盘与发现全部在 `handoff/supersede/`（索引见文末）；
「勾稽闭合≠科目真实」等长期认知已沉淀进 `references/articulation.md` 使用总则。

---

## 四、已知局限与未验证项（诚实清单）

**接手后最该先看的部分——只留真未完成项（v0.0.22 瘦身定案：已解决项的记在 supersede/，不堆删除线）：**

| # | 局限 | 影响 |
|---|---|---|
| 1 | **港股/美股路径只验证了数据源可用**（妙想返回腾讯 2024 三表），**从未跑完整流程** | 港股报告能否产出未知；币种陷阱（汇总表港元 vs 明细表人民币）未实战检验 |
| 2 | **季报/招股书两种报告类型未实测**（年报、半年报均已多份实战） | report-types.md 对季报/招股书的裁剪规则仍是纸面推演 |
| 3 | **industry-profiles.md 八类模式零实测** | 工程建造的合同资产勾稽、农业的生物资产盘点、经销商压货三条件、医药的研发资本化/license-out 勾稽都没在真实样本上跑过 |
| 4 | **P1-17 四象限未端到端跑过**（断言验证/周期定位/费用ROI 已在多份半年报实战） | 四象限只在茅台 fixture 验过分类正确 |
| 5 | **回看机制已落、真实数据实测待披露季** | 现存全部 watchlist（特变/移动/恒瑞 2026H1）跟踪线指向 2026Q3/2026FY、均未披露；真实首测须等披露季 |
| 6 | 康得新 **A5/B2/B3 三条等式因附注未披露而无法执行** | 换个披露更全的造假样本可验证这三条 |
| 7 | **存量旧版式报告不追溯**（纪律 7） | 新门禁对旧报告的 WARN/FAIL 全属预期：T8① 噪音、internal-ref、percentile-map、gap-declaration、js-dup-decl/assert-trunc/empty-svg（长城事故样本留档）同类 |
| 8 | **比率趋势数据依赖 tushare 可得性** | 世界线披露晚于库更新时当期 hist 取报告提取值；重述公司历史期口径断裂，趋势缺 hist 合法（schema 血泪 7） |
| 9 | **移动 json 的 src 行号与现行 md 不匹配**（T8②级 104/107 miss） | v0.0.4 底稿行号体系；下份移动报告重建底稿时按新 schema 修复 |
| 10 | **70% 升档阈值真实触发仍待样本**（长城无息 87% 达标但杠杆非主驱动、升档正确地未触发） | 首验场景：首份「杠杆为主驱动+无息>70%+|ΔDFL|<0.1」公司 |
| 11 | **N4 模板冻结计数**：连续两份新报告零结构性改动才重议 fill→render 脚本化 | v0.0.22 s1 图区改版后再次清零 |

---

## 四·五、当前未发布轮：v0.0.22（2026-10-01，长城·埃斯顿双报告复盘轮 + s1 图区改版）

> 触发：用户读埃斯顿/长城两份报告后反馈——长城「大量图表失效、断言残句、格式混乱」，
> 埃斯顿检验表行序不合理、s1 财务总览五年趋势可读性差。定位=两起填充事故 + 模板三处缺陷。
> 用户定案：长城报告不修（复盘样本留档）、埃斯顿报告不改（纪律 7），全部修订落在技能源。
> 本节发布后整节移入 supersede/。

### 长城报告事故复盘（两起填充事故，两条旧门禁缺口）

1. **JS 团灭（根因 A）**：填充把 `const OCF_END=104.36;` / `const SEG_ENDS=[923.35,1021.01];`
   插在模板占位行（`const OCF_END=0;` / `const SEG_ENDS=[0,0];`）前而**未删占位行**——const
   重复声明致整个 script 块 SyntaxError，trend/ncrline/双桥/堆叠条/spark 全空。
   旧门禁双漏：占位符检查只认 {{}} 形态；check_render 几何测量「空图无元素可测」。
   → 新门禁 **js-dup-decl**（check_html FAIL，判据=行首顶层 const 重名，依赖数据槽顶格写的
   模板约定；函数内局部 const 同名合法不误报）+ **empty-svg**（check_render：页面存在的关键
   SVG[trend/ncrline/capexbars/effline/ocfbridge/segbridge/dupontstack/holders] 子元素为 0
   即 exit 1；不存在不查=降级删卡合法）。
2. **断言截断（根因 B）**：s4 断言表 63 格以「…」结尾，62 处系填充方手工截断（json 底稿
   完整；1 格底稿本就空串属正确跳过）。T8 只验数字不验文本。
   → 新门禁 **assert-trunc**（check_html --json FAIL：json assertions text/evidence 前 15 字
   锚点定位 + 最长公共前缀判定，「真前缀+…」即截断；底稿本身以「…」结尾不判）。
3. 长城报告对新门禁的命中（js-dup-decl 2 / assert-trunc 62 / empty-svg 5）属**预期留档**，
   不追溯（纪律 7 同类）——该报告是复盘样本，新门禁的首个活教材。

### 埃斯顿报告复盘

1. **激励线「有计划」第二样本、新形态**：2025 计划二期累计净利线 2.2 亿、进度 2.18 亿
   （99.3% 贴线，含一次性重估助攻）；期后 9-29 新草案改扣非口径（2026-2028 累计 2/5.2/11 亿）
   明显更严。取数路径 mx 公告检索+股份支付附注交叉走通（承长城首验，流程可靠性再确认）。
2. **降级标题 bug（模板缺陷，填充方无责）**：扣非缺五期 hist 时右板正确降级单柱、
   figtitle/srcline 均规范注明，但 trendDual 面板标题硬编码「归母净利+扣非净利·线=ROE」
   不随降级变 → v0.0.22 标题随实际绘制序列动态生成。
3. WARN 人工确认闭环：bare-number 108（启发式，关键数字均有徽章/出处）；json-md 13 处均
   der 求和值（毛利/减值合计/折摊合计，成分在原文、和值不在——万科同型先例）；s2-shape
   2 条为四线考核卡徽章与排雷徽章语义不同的固有噪音。

### s1 图区改版（用户定案四项）与 s7 行序

1. **四维表「近5期趋势」spark 列退役**（64×16 不可读、单期指标无序列致半列空格、趋势已由
   图区覆盖）——表瘦身五列；SPARK 槽/spark() 函数/线色纪律全撤。
2. **趋势图卡改㗊字四宫格**（同日二次反馈定案：四图等大 2×2，grid2 窄屏单列）——
   左上 revchart=收入柱+毛利率线、右上 npchart=归母/扣非/经营现金流柱组+ROE 线
   （柱组 1~3 自适应、柱位不漂移，OCF 可负沿用负值柱约定；**标题随实际绘制序列动态生成**，
   同修埃斯顿降级标题 bug）、左下 effline=营运效率三线（EFF_TS 槽：DIO/DSO/CCC 同轴，
   CCC 可负画零轴实线；序列不足 2 个非空点整线不画）、右下 capexbars=Capex·研发双柱
   （TREND.rd=income.rd_exp hist，缺数降级单柱；研发费率折线需副轴否）。
   trendDual 拆为 _panelBars+_panelLine 模块级两件 + trendRev/trendNp 两入口；
   check_render KEY_SVG_IDS 新旧 id 并存（「存在才查」兼容存量报告）。
   fillsheet 同步：TREND 槽 +ocf/rd、EFF_TS 新槽、四维表段改五列。
3. **s7 检验表行序改固定主题序**（用户定案）：v0.0.14「判定分组置顶」废——分组重排
   破坏位置记忆、与四维表/断言表固定序不一致；行序=模板行序照抄，判定分布由徽章色扫读 +
   figtitle 汇总（「N 项：x 过 y 注意 z 异常」）传达。模板注释/SKILL.md/fillsheet 三处同步。

### 同日续三项（用户反馈定案）

4. **派发窗 ① 再拆 ①a/①b**（6→7 代理）：三表+母公司单代理连续两轮为窗口最慢
   （埃斯顿/长城实测）——①a 资产负债表+母公司 → statements_bs.json、①b 利润表+现金流量表
   （含补充资料）→ statements_ic.json；按顶层键切分，合并面干净。
5. **报告流程禁修技能源**（用户定案，废 v0.0.14 当场修）：撞技能 bug 只提示/绕过/记
   handoff 待办——绕过只许呈现层（手工补图/降级声明），禁止为过门禁改数据或 fixture；
   门禁 FAIL 确系技能 bug 误报时写明豁免才可带病交付。理由：多报告并行共享同一技能源，
   当场修互相污染（埃斯顿轮 ncrline 修复混入并行工作区实证）。SKILL.md Phase 8 +
   AGENTS.md 纪律 6 双落点。
6. **HANDOFF 瘦身治理**（用户定案）：478→362 行——「三个发现」节删（核心认知已入
   articulation.md 总则第 4 条）、局限表删已解决行（只留 11 项真未完成）、计划区只留
   未完成项；HANDOFF 本体=长期节 + 当前未发布轮 + 全部待完成，已发布轮次只住 supersede/。

### 验证

- 回归 112→116 全绿（+4：js-dup-decl 命中/不误报对照、assert-trunc 命中、EFF_TS/TREND
  槽合法 JS 锚）；四宫格改版后再跑仍 116 全绿。
- 模板 check_render 双视口 0 问题（empty-svg 新规则顺手抓到模板 HOLDERS demo 槽空数据
  误报——demo 槽填示例值修复，同「demo 全 0 必撞」教训同类）；长城真实数据填临时件
  四宫格目检成立（三柱组含 OCF 负值柱/CCC 负值零轴/双柱窄面板标签不撞）。
- 埃斯顿轮未提交改动（ncrline 均值标签避让——check_render 窄视口「1」与「均值-3.05」1px
  重叠修复，回归随本轮 116 全绿）随本轮一并提交，提交信息分段写明归属。

### 热核审计（用户触发，交叉审计：子代理审门禁/回归、主线审模板/fillsheet）

- **1 major 修（M1 门禁可绕过口子）**：assert-trunc 对「底稿 text/evidence 空串」全豁免——
  长城 A10 实证：提取代理留空 evidence、呈现层自撰文本再截断，比截断更糟（无底稿依据）。
  本轮落 WARN 止血（底稿空断言列清单强制回填；HTML 侧行定位脆，不做），下轮看形态评估升 FAIL。
  治本：派单模板 ③ 的 evidence 改必填（骨架示范原为 `""` 空串——12/13 报告命中说明是
  流程级缺口不是个例；subagent-prompts.md 已改）。
- **judo（模板侧自审）**：capexBars 删独立实现改复用 _panelBars/_panelTitle（四宫格等大后
  迷你条独立实现=近重复）；_panelBars 返回 drawnSubs 作序列绘制单一判定源（消 trendNp 双重
  判定）；_panelLine 删冗余 labels 参数。
- **10 minor 修**：empty-svg 选择器改 childElementCount（9 标签清单删除，全语料实测逐个
  一致）/ 单图命中措辞分支（防误导排障）/ 白名单 load-bearing 注释 / visible_text 归
  check_html_common 单一定义 / _unescape 换 stdlib html.unescape / ANCHOR_LEN 常量+死条件删 /
  命中明细加行号 / js-dup-decl 按 script_ranges 过滤+debt 补多声明者天花板 / 截断判据扩
  「...」三点形态 / 回归文件样板抽取（_block/run_check_html 泛化/_fillsheet_slot——921 行
  红线 92% 水位回购约 60 行）。
- **nit 修**：OK 措辞诚实化（含框架常量/0 个声明/无合格字段）/ 规则编号冲突消解
  （check_html 清单加 T8 族行）/ emptysvg 推字符串 / 窄屏汇总不重复报数 / tests README
  重写（2 fixture→4 fixture+4 demo 登记）/ fillsheet 生成物残留清理。
- **审计实证零误报面**：13 份存量报告 js-dup-decl 0 误报、assert-trunc 0 误报（万华 15 字段/
  卫星 68/埃斯顿 56 全 OK）；白名单删除实验证伪（万科A 会误报 spark-c2s/spark-dol——清单
  必须留）；全部建图函数空数据路径=「return 不画」（empty-svg 约定安全）。

### 遗留（下轮关注）

- N4 冻结计数**再次清零**（模板结构性改动：spark 列退役/㗊四宫格/右板柱组/capex 双柱）。
- **模板红线水位**：去注释约 985（v0.0.21 为 917；热核审计 judo——capexBars 复用
  _panelBars 删近重复实现——回收约 20 行）——贴近 1k 红线，下轮再加图先想瘦身。
- **长城留档件的读者预期**：reports/ 顶层长城报告图表全空（事故原样留档，用户定案不修）——
  打开它的人看到空图是事故本体，不是新 bug；下份长城报告产出时自然替换。
- 长城事故样本的 FAIL 命中属预期（见上）；下一份新报告起三条新门禁（js-dup-decl/
  assert-trunc/empty-svg）为交付硬门禁。
- 70% 升档三条件全满足样本仍待找（承 v0.0.21：长城无息 87% 达标但杠杆非主驱动）。


## 五、下一步工作计划

> 治理（v0.0.22 用户定案）：本节只留**未完成**事项；已完成任务的记录移入 supersede/
> 对应轮次文件，不堆删除线。HANDOFF 本体=长期节 + 当前未发布轮 + 全部待完成。

### 自我审核候选方向（未动工项）

**N4. 模板冻结评估 → fill→render 脚本化重议**
P8 写 HTML 347s（比亚迪轮解剖）是全流程最大单点之一。v0.0.14 否决脚本化的理由是
「模板每轮在变，维护税超收益」；**冻结计数 v0.0.22 再次清零**（s1 图区改版）：连续两份
真实报告产出时模板零结构性改动（注释级不算）即重议 fill→render 脚本化（fillsheet
已全槽位化，脚本化只剩映射一步）。模板行数口径：1k 红线按去注释行计（当前总行 1261、
去注释约 1009——贴红线，下轮加图先瘦身；纯代码文件按总行计）。

**N5. 新准则造假样本扩充（排雷库回归覆盖单一）**
康得新是 2018 旧准则样本，「抓漏报」金标准只有它一个——收入准则/金融工具准则切换后
的造假手法（如合同资产操纵、供应链融资藏债）无回归覆盖。留意下一个公开定性的造假案例
（处罚决定书+当年年报可得的），固化为第五个 fixture。

### P0（接着做，价值最高）

**任务 1：跑通港股/美股全流程（局限 1）**
- 建议标的：**腾讯 00700.HK 2024 或 2025 年报**——一石三鸟：首次跑通港股全流程 /
  首次用齐年报专属槽位（Q4 单季透视/股东户数/机构预期）/ 港股口径下验证 watchlist 与排雷四态
- 验收：`calc.py` exit 0 + `check_html.py` exit 0 + 章节齐全（s0~s8）+ 数字抽查 12 项与原文一致
- 注意：港股须核对币种与会计准则；A 股专属模块（股东户数/质押/热榜）置灰标注「仅 A 股」

**任务 2：季报 + 招股书各一次（局限 2）**
- 各挑一家熟悉的公司；季报走轻量版（P2/P4/P7 精简），招股书走专属模块
- 验收：两种类型各产出一份报告并通过两道门禁；发现 report-types.md 与实际不符处即修正

### P1（深度验证）

**任务 3：行业 profile 实测（局限 3）**
- 挑一家**工程建造**（验证合同资产/合同结算勾稽、完工百分比激进）或**农业养殖**（生物资产盘点）
- 验收：industry-profiles.md 中该模式的重点勾稽项被真实触发；该降级的信号确实降级（不误报）

**任务 4：回看模式真实数据实测（局限 5，等披露季）**
- 机制层（T6）已完成：schema review 子块 + 冻结纪律 + 模板归因列 + check_html review-shape +
  examples/lookback-demo 构造样本（✅/❌/⏳ 全形态 + 反面例 WARN 触发实测）
- 剩余：2026Q3/2026FY 披露后，对特变/移动/恒瑞之一做新报告，验收回顾章照抄 tripwire
  原文 + 逐条 ✅/❌/⏳ + 归因 + review 子块落库

---

## 六、工作纪律（改代码前必读）

1. **技能源只在 `financial-report-analysis/` 改**；用户级 skills 目录是部署副本，
   由 `deploy.cmd`（robocopy /MIR）覆盖 —— **绝不要直接改部署副本，会被覆盖掉**
2. **任何改动后先跑回归**：`python financial-report-analysis/tests/run_regression.py` 须 exit 0
3. **改 `calc.py` / `extraction-schema.md` / 任一 fixture 后，回归是强制的**
4. **禁止为了让测试变绿而改 fixture 数值** —— 先确认是门禁改坏了还是样本期望值需调整
5. 改完 → 跑 `deploy.cmd` → **新会话才生效**（技能列表在会话启动时加载）
6. 全程中文（代码关键字除外）
7. 提交信息写清「做了什么 + 为什么 + 怎么验证的」

---

## 七、快速上手（新会话第一件事）

```bash
# 1. 确认环境
cd "D:/KimiCodeProject/Financial Report Analysis"
python financial-report-analysis/tests/run_regression.py   # 应 116/116 通过

# 2. 部署（如需让技能在当前机器生效）
cmd //c deploy.cmd

# 3. 触发技能：把一份年报 PDF 拖进对话，说「分析这份报告」
```

产物落位（v0.2.0 目录治理后，见 AGENTS.md 纪律 6）：
成品 HTML 落 `reports/` 顶层（每公司只留最新版）；data.json 底稿落
`reports/archive/json/`；markitdown 转换的原始 md 与 PDF 落
`reports/archive/原始报告/`（PDF/md 不入库）。命名：
`{公司名}-{代码}-{报告类型}-{报告期}-{生成日}.html` + 同名 `.json`。

---

*本文档随项目演进更新；重大变更请同步 `AGENTS.md` 与 `SKILL.md` 的 version。*

## 归档索引（handoff/supersede/，定案：轮次落地发布后移入，本目录外只留最新版）

| 文件 | 覆盖 |
|---|---|
| `supersede/v0.0.2-v0.0.4_2026-09-10~13.md` | 初始~v0.0.4（v0.0.3 删跨维度评分体系、v0.0.4 审计修复与读法层前身） |
| `supersede/v0.0.5-v0.0.7_2026-09-14~15.md` | v0.0.5~v0.0.7（定位修正 T1–T11、读法层与图表重做、巨潮自取） |
| `supersede/v0.0.8-v0.0.9_2026-09-16~17.md` | v0.0.8~v0.0.9（tushare 去 MCP 化、呈现层门禁 L1–L5） |
| `supersede/v0.0.10-v0.0.11_2026-09-21~22.md` | v0.0.10~v0.0.11（平均余额口径定案、说人话、移动端可读性） |
| `supersede/v0.0.12-v0.0.16_2026-09-24~28.md` | v0.0.12~v0.0.16（TradingAgents 借鉴、云铝/比亚迪/万科三份首测报告、杜邦深化、热核整改、trendDual 负值柱回填） |
| `supersede/v0.0.17_2026-09-28.md` | v0.0.17（工程化还账 + 方法论补全 + 热核审计整改） |
| `supersede/v0.0.18_2026-09-29.md` | v0.0.18（万华首份周期股报告反馈轮：呈现层清洗 + 门禁补强 + 效率治理） |
| `supersede/v0.0.19_2026-09-30.md` | v0.0.19（美的反馈轮：呈现文本族拆分 + 三新机检 + 图表版面 + hist_pool 豁免 + 效率治理计时模板） |
| `supersede/v0.0.20_2026-09-30.md` | v0.0.20（卫星化学报告复核轮：OCF 桥失守模式根治 + s1 双卡改造 + 效率对照回填） |
| `supersede/v0.0.21_2026-10-01.md` | v0.0.21（卫星化学四项反馈定案轮：.wv 判词行 / 桥图端点柱 / SEG_ENDS 槽 / gap-declaration 机检 + 热核审计整改） |
