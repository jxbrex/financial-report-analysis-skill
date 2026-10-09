# HANDOFF · 交接文档

> 版本 **0.1.1** · 截至 2026-10-09 · 本文档面向「下一个接手这个项目的人/AI 会话」
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

### 技能现在的构成（36 个源文件）

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
│   ├── extraction-schema.md    #   data.json 数据契约（schema 1.5）
│   ├── data-sources.md         #   markitdown / tushare / 妙想 接口速查 + 港股路径 + OCR 降级
│   ├── report-types.md         #   年报/半年报/季报/招股书/港美股 差异
│   └── subagent-prompts.md     #   并行派发窗派单模板 ×5（v0.0.14）
├── assets/report-template.html # 10 章单文件报告模板（内联 SVG 绘图函数族、锚点 s0~s8 + review、置信度徽章）
├── scripts/                    # 14 个脚本
│   ├── calc.py                 #   Phase 7.5 数据层门禁入口（--fill / --min-recon）
│   ├── calc_common.py          #   共享层：取值助手 + 比率公式唯一定义处 + hist_periods/批量比对
│   ├── calc_dupont.py          #   杜邦族：连环替代三口径 / 因子下钻 / 五年归因与分位
│   ├── calc_evidence.py        #   周期证据 / 四线贴线 / peers 结构
│   ├── calc_risk.py            #   破产双模型 / 压力情景 / 现金时序
│   ├── calc_models.py          #   --fill 编排层（v0.1.0 收窄：槽位移出）
│   ├── calc_slots.py           #   槽位契约层（v0.1.0 自 calc_models 拆出，1k 红线）：
│   │                             build_slots + write_fillsheet + _js_slots（JS 槽单一出处）+ _TXT 文本链
│   ├── render_report.py        #   Phase 8 fill→render（v0.1.0 N4）：模板+槽位 JSON→报告骨架，
│   │                             锚定填充断锚 exit 1；判断槽残留 {{}} 孔，一期半年报路径
│   ├── check_html.py           #   Phase 8 报告层门禁入口（结构/硬规则族 + 主流程）
│   ├── check_html_common.py    #   报告机检共享助手
│   ├── check_html_text.py      #   呈现文本族 15 条检查（v0.0.19 拆出；PCTILE_LABEL 居此）
│   ├── check_html_t8.py        #   T8 数字回验整族（①级笔误检测 + hist_pool 豁免 + ②级行号回核 + v0.0.22 assert-trunc 断言填充截断）
│   ├── check_render.py         #   渲染测量门禁（headless Chrome/Edge，--png 分片截图；v0.0.22 起 empty-svg 关键 SVG 非空检测）
│   ├── gate.py                 #   三道门禁单入口
│   ├── md_clean.py             #   财报 md 确定性清洗 + 章节索引
│   └── ts_fetch.py             #   tushare HTTP 取数通道
├── tests/                      # 金标准 fixtures + 回归入口（v0.1.0 起 +yinghe_2026h1.json 与
│   │                             fillsheet.golden.md：render 重放金标准）
│   ├── moutai_2025.json        #   干净样本（应零误报；schema 1.5）
│   ├── kangdexin_2018.json     #   造假样本（应命中；含 parent_statements + D 组判定）
│   ├── vanke_2026h1.json       #   连亏地产样本（v0.0.17 固化：扣非双版/双驱动真实触发）
│   ├── wanhua_2026h1.json      #   周期股样本（v0.0.18 固化：双驱动第二样本/ROIC·SGR 首验/白描分位锚点）
│   ├── md_clean_synth.md       #   md_clean 合成金标准（自包含，四类病理；v0.0.17 起不再依赖原始 md）
│   ├── t8_demo.html            #   T8 数字回验验收样例（改错版由回归运行时改数生成）
│   └── run_regression.py       #   唯一回归入口：177 条断言 + check_html/T8/渲染冒烟 + 构造用例
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
3. **`python tests/run_regression.py`** —— 任何改动后必跑，**177 条断言**全绿才算没改坏
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
- 海康轮效率数据点（v0.0.23 对照，64.5min / +11.2min vs 基线）：LLM 流式 74%；
  **最大单点=Phase 8 两段手写填充脚本 615s/30.2k tok**（万华 311s/16k 的近 2 倍——两段
  填充把最大单点复制了一份）；effline 重叠 3 轮返工约 3min（本轮修复后消除）；calc 3 轮
  FAIL（assertions verdict/source 空缺——派单骨架字段名 src→source 已修 + 偏差阈值内判
  「可解释」=过度立案，SKILL Phase 2.5 已补机械口径）；并行窗口 10.2min 双拖尾
  （①a 612s / ②b 600s，瓶颈=JSON 产出体量纯流式）；**mx 积分耗尽仅 40s 兜底切换、
  非关键路径**——但 ⑤ 号代理派单须预备 stock_finance_data 自算兜底；后半程首 token
  延迟 3-6s→10-18s（上下文膨胀），94 步框架开销 12.8min
- 海康轮 T8① 真实数值撞车两例（SMBG 增速 13.55 撞净利率上期 13.53、在建进度 45.20 撞
  毛利率上期 45.19——均 0.5% 窗口内同为真实披露值）：呈现层改增量表述/更粗粒度规避；
  若同类撞车频发，考虑 hist_pool 式「多真实数值」豁免
- effline 标签避让（v0.0.23）：同期堆栈（点上 -8 起、间距 17px 顺序下推、整组钳入
  绘图区）——11px 不够：文本盒高≈16px（font 9+halo 描边 2.5），实测仍撞 3-5px；
  **值域含 0/零轴仅在有负值时**——全正强拉 0 基线会把三条百天级线压进 62px 带成互撞温床
- 四宫格 grid2 直接子元素只许 svg（v0.0.23 新 FAIL 门禁 s1-grid4）：降级只许删 svg，
  takeaway/表格放 grid2 外——海康回填轮把 takeaway 留在 grid2 内撑破 2×2 㗊型的实证
- check_render svgclip（v0.0.25，赢合 segbridge「锂电池专用生产设备」长标签左端被视口
  裁切、三道门禁全绿漏检的实证补口）：SVG 内 text 出所属 svg 左右缘 >3px 即 FAIL；
  成因侧由 deltaBars 左标签宽自适应根除（L=最宽标签估算宽+12，下限 56）——存量旧版式
  报告若命中属预期噪音（纪律 7 不追溯），茅台 v0.0.4 快照实测 svgclip 0
- **render_report 锚定填充三前科（v0.1.0）**：re.S 下 `.*` 贪婪吞到文件尾（fill_js 行级
  正则必须传 flags=0，TREND 替换团灭 JS 尾部实证）；json 原文进 HTML 必过 _TXT 链
  （转义/剥 L 行号/截长小数——赢合 signals data 裸 < 实证）；pathlib write_text 在
  Windows 默认把 \n 翻成 CRLF——报告 HTML 输出须显式 newline="\n"（成品 LF 惯例；
  模板/fixture 本身是 CRLF 不受影响）
- 底稿文本字段（assertions.evidence 等）写内部工具名（mx_*/data.json 字样）会在 render
  机械照抄下撞 internal-ref 门禁——底稿措辞即对外口径，填底稿时自律（赢合 A6/A8 实证）
- check_render 渲染冒烟偶发 exit 1（Edge 异步写盘/回调迟到，单独重跑即绿）——
  回归里撞上先重跑再排查（v0.1.0 轮实证一次）
- JS 数据槽序列化唯一出口 `_jd`（calc_slots）：None→null + `</` 转义——新增 JS 槽必走；
  f-string 裸插 None 是 JS 未定义标识符、整页团灭（v0.1.1 第三起同类前科后根治）
- 「已修」以代码+回归为准、不以文档为准：四·七记录 _NO_SRC 词边界「已修」实际从未
  落码（git log -S 无），v0.1.1 才真正落地（词边界 + 位数≥3 双保险）
- fillsheet 金标准重生成流程（bug 修复改变合法输出形态时）：临时副本 --fill → diff 核对
  只有预期行 → cp 覆盖金标准——不是「为变绿改 fixture」，每行差异必须有归属（v0.1.1
  DUPONT_STACK 序列化形态演进即按此办理）
- avg() 缺 prev 返回 None（v0.1.1）：prev 缺失的失效会传导成 leverage_drill.ni_prev/
  hist_ye 脱钩 FAIL——如实指出修复点，不是误报；别再退回期末冒充平均
- check_html 构造片段断言别查 returncode：片段无页脚，required FAIL 是背景噪音——
  断言钉「[FAIL] 规则名」整段或规则行文案（v0.1.1 阳性⑨校准实证）
- md_clean 页码判据：跳空行后邻居是噪声才算页码（markitdown 段落间必隔空行，紧邻
  判不出）；孤立「|」不吞碎行（pre 落独立行+unmerged）
- T8① 窗口 0.15%（代码 check_html_t8.py:154）——文档曾三处写 0.5%，调参以代码为准
- ocf_drop 第 7 条降级路径：空 OCF 桥删 svg+brends+figtitle 声明；空桥 OCF_BRIDGE=[]
  配模板 `OCF_BRIDGE[0]?.[1]` 双保险

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
| 11 | **render 二期（年报专属路径未脚本化）**：Q4 卡/review 回看卡填充、预期对照表（schema expectations 块）、高管增减持块、big_moves 大动表提取——一期半年报路径全覆盖 | 年报/回看场景下这些槽位仍是手工孔（残留 {{}} 兼容现流程）；二期用真实年报样本（腾讯 00700 候选）回测 |

---

## 四·五、待发布轮：v0.0.24（2026-10-03~04，全库审计清理 + 四象限落地轮）

> 触发：ponytail-audit 全库过度工程审计（用户触发）→ 按风险分三档执行；四象限节用户定案
> 「补 schema 落地」；收尾前轮内热核审计抓出 1 Blocker + 5 Major 一并修复。

### 修订（全部落地，回归 119→133 全绿）

1. **三档清理（净删约 260 行，31 文件）**：
   - 一档（死资产）：examples/ 整目录退役（回看形态由模板 SLOT+schema 承载）；tests 三个
     demo 文件内联进回归（dup_decl 内联 / t8_demo_bad 运行时改数生成 / assert_trunc 内联）；
     死 import 与重复 import 块、ANNUALIZE「季报」死键、模板 .badge.rev 死 CSS、SKILL:455
     与 v0.0.19 小数纪律矛盾的过期残片、factor-analysis「schema 待补」失效承诺
   - 二档（回归脚本收编）：四例公共序言收 `_prologue()`、冒烟块循环化并计入断言
     （修「冒烟不计数」口径不一致，119→127）、t8 改错版运行时生成 + 着陆断言
   - 三档（收敛）：四个零接线 flag 全删（--warn-only/--strict×2/--scale）；文档复述按
     「唯一出处」原则收敛——模板注释管版面、references 管规则、schema 只管字段与落库约定
     （SKILL -43 / schema -15 / references -60 行）；frameworks.md 删 Beneish/Benford 后
     节号重编号（五~九→四~八）+ 12 处引用同步；SKILL 版本记录表压一句话短表
     （详情归 supersede/git tag 唯一真源）
2. **四象限落地（schema 1.5）**：`derived.segment_quadrant` 选填块（填则 calc 全字段复算
   比对、缺省合法 SKIP；边界等号归正侧、y_mode delta/level 降级、排名等值规则写死）；
   calc.py 新增 segment-quadrant 检查；fill 接线（compute_segment_quadrant 提取到
   calc_evidence.py，fill/check 共用——机械字段不再要求分析师手算）；万华/万科/茅台
   fixture 补锚点（茅台 by_segment 实为 2 条：茅台酒明星/系列酒衰退；万科地产衰退/物业
   明星；万华石化错位度 2 = 资源错配信号实证）；schema_version 1.4→1.5 六处同步；
   v1.5 构造用例 ×2（填错 quadrant 必 FAIL + 声明 delta 但 cost_prev null 不 crash）
3. **热核审计修复（本轮内闭环）**：
   - Blocker：check_segment_quadrant 按声明 y_mode 算 dm，声明 delta 但 cost_prev 缺 null
     时 TypeError 崩溃（门禁在该说话的场景说不出话）——compute/check 分层后消失
   - Major：nonlocal ok 副作用累积改 FAIL 计数差；load_moutai 同义 helper 删除
     （load_json(MOUTAI) 等价）；四处悬空引用清尾（README/HANDOFF 的 --strict 残留、
     AGENTS 的 examples/ 残留、SKILL 的「第九节」漏改 + Beneish 宣称脱节）；
     articulation A3 share_of_np 分母漂移修正（np_at→np_total，对齐 calc 既有行为）
   - Minor：QUADRANT dict 一处定义、check_render SCALE=2 常量、t8 着陆断言

### 验证

- 回归 132→133 全绿；fill 幂等四例全过（fixture 补齐后为 fill 不动点）；
- 黄金样本茅台 gate 对照：改动前后 FAIL 逐字一致（internal-ref/num-vs-json/required 三条
  均为报告产出后新增规则的旧快照现象，纪律 8 不重出）。

### 遗留（下轮关注）

- 审计清单未做项（用户未选）：data-sources.md OCR 降级路径、text-mining 姜富伟词典段、
  vanke derived.q4 全 null 块（其 note「半年报无 Q4 透视」是有意置灰声明，非死数据，
  确认保留）、run_regression Case 类与 _block 双汇报机制（用户定案不统一）。
- SKILL.md 为 CRLF/LF 混合行尾（488 CRLF + 少量 LF），Edit 跨行替换易失败——本轮用
  Python bytes 级补丁脚本处理；下轮可考虑一次性统一行尾。

## 四·六、待发布轮：v0.0.25（2026-10-06，赢合报告反馈轮）

> 触发：赢合科技 2026H1 报告交付后用户目检发现两处呈现缺陷，根因均在模板而非填充；
> 用户定案本轮修订为 **N4 前置清障**（「修订完上述两项，N4 死锁就可以做了」）。

### 修订（全部落地，回归 133→135 全绿）

1. **deltaBars 左标签区宽自适应**（模板 + 赢合报告同步）：`L=86` 固定值改为
   `max(56, 最宽标签估算宽+12)`（全角字 9.5px/半角 5.3px，steps+端点名参与）——
   赢合 segbridge「锂电池专用生产设备」9~10 全角字标签左端探出 SVG 视口被裁；
   check_render 溢出/裁剪判据对 svg 内元素免测（`closest('svg') continue`），纯盲区
2. **检验卡四组分组行**（模板 + 赢合报告同步）：四个固定主题组各起 `tr.group` 行
   （盈利与研发 / 偿债与压力 / 营运效率·费用 ROI / 披露项，组序=figtitle 汇总主题序），
   「大宗/税率/汇率敏感性」移入披露项组——v0.0.22「固定行序」定案升级为
   「分组行+组内固定序」，与四维表/断言表同型；10 行读数逐字未动
3. **check_render 补 svgclip 检测**（盲区补口，escapes→gate 传统）：SVG 内 text 出
   所属 svg 左右缘 >3px 即 🔴 FAIL（容差吸收 halo 描边 1.25px）；回归加构造用例
   （静态出界 text 必命中 + 赢合长标签 SEG_BRIDGE 端到端 0 问题）

### 验证

- 回归 135/135 全绿（+2 新断言：svgclip 阳性 / deltaBars 长标签修复锁）；
- 赢合报告 gate 全绿：FAIL 0，WARN 3 条与修订前基线逐字一致（bare-number 88 /
  json-md 8 / s2-shape 3 绿徽），渲染 svgclip 0；--png 分片目检 s3：segbridge 两条
  长标签完整、OCF 桥无回退；
- 茅台黄金样本 gate 对照：check_html FAIL 三条与基线逐字一致
  （internal-ref/num-vs-json/required 旧快照现象，纪律 8），渲染 svgclip 0——
  新检测对 v0.0.4 旧版式零误报。

### 遗留

- N4 已于本轮会话内经用户定案直接启动并落地（推翻「连续两份零改动」口径）——见四·七。

## 四·七、当前未发布轮：v0.1.0（2026-10-06，N4 fill→render 脚本化落地轮）

> 触发：v0.0.25 两项修复收尾后用户定案「现在就启动 N4，报告大框架问题不大了」——
> v0.0.23「连续两份零改动」口径就此作废。范围分期：一期=半年报路径全覆盖
> （赢合金标准回测），二期=年报专属（Q4/review/预期表，见局限 11）。

### 修订（全部落地，回归 135→144 全绿）

1. **render_report.py（新）**：模板 + fillsheet.json → 报告骨架。锚定填充
   （章节 id→表头文本→行标签→列位）；判断槽残留 {{}} 孔，check_html 占位符门禁
   语义不变（孔未清零不交付）。降级决策表一期 6 条（review 删卡+toc 联动 / Q4 非年报
   删卡 / 产能空删卡 / holders 降级文字行 / SEG 分部轴 / ncrline hist<3 声明）。
   模板零结构性改动（仅删 NCR figtitle 槽文本里的版本号禁词）。
2. **calc_models.py 拆 build_slots**：--fill 加产 {stem}.fillsheet.json（机器可读槽位
   契约，render 唯一数据源）；JS DATA 9 槽整行文本 _js_slots 单一出处（md/json 双路
   共用）；SEG_BRIDGE 无量价降级升级为 by_segment 机械生成（fillsheet md 的 SEG/
   HOLDERS 两段相应变化，金标准逐字锁）；文本链 _TXT=剥 L 行号→截长小数→HTML 转义
   （长城 T8① 撞窗 + decimal-places + 裸 < 三前科）。
3. **schema 1.6**：notes.shareholders.holder_ts 选填块（labels/num/px 等长、px 首期
   null）+ calc holder-ts 校验 + 派单模板④落库约定；赢合底稿回填 8 期（Tushare
   stk_holdernumber 精确户数）——原 holders 图数据 Phase 8 手工补、不回底稿的漏洞堵上。
4. **顺带修的存量问题**：赢合底稿两条断言 evidence 含内部工具名（mx_macro_data/
   data.json 字样）——internal-ref 禁词在机械照抄下暴露，底稿改对外口径；杜邦 ROE 行
   成品「效应比 2.02」与 derived 权威值 1.8891 不一致（render 按 1.89 呈现，成品疑笔误，
   下份报告复核）；预付增幅成品 438% vs 精确 437.4%（render 按 437% 呈现）。

### 验证（赢合重放金标准）

- 回归 135→144 全绿（+9：fillsheet 逐字锁/锚自检/槽文本/孔数区间/FAIL 仅占位符/
  T8①·internal-ref 零命中/渲染 0 问题等）；
- render 产物 vs 人工成品 diff：机械区逐项对齐，差异全部有归属（判断孔、srcline 扩写、
  第 4 条口径修正）；check_html：FAIL 仅 placeholder 一类；check_render 0 问题；
  分片截图目检 s3（桥图/净利桥/OCF 桥形态完整）。

### 遗留

- 二期清单（局限 11）；s2 观察行脚本全量生成、填孔阶段按 ≤6 条删减（s2-shape WARN
  是填孔动作提示，非缺陷）；bare-number WARN 孔阶段高于基线（徽章孔所致），填孔后回落；
  观察行/断言/期后的措辞精简是填孔阶段动作（render 照抄 json 原文，文字偏长属预期）。

### 热核审计（本轮内闭环，用户触发）

- **Blocker：calc_models.py 469→1050 行越 1k 红线**（纯代码文件按总行计，本项目明文
  纪律）——拆 calc_slots.py（槽位契约层：write_fillsheet/build_slots/_js_slots/_TXT 链/
  PCTILE_LABEL/ROW_LABEL/GOOD_UP），calc_models 收窄至 115 行纯 fill 编排层；
  PCTILE_LABEL 由 calc_models 再导出保回归契约锚点（check_html.py 同款先例）；
  拆分脚本切段曾重叠致助手块重复 + _r4deep 误入——语法检查+回归双锁抓回。
- **Major：ncrline hist<3 降级漏实现**（计划决策表 6 条只落 5 条——空骨架 svg 必撞
  empty-svg 门禁，结构性失守）：补 ncr_drop 布尔 + render 删 svg/figtitle 声明 +
  构造回归用例（ocf hist 砍 2 期 + 删 derived.cash_ts 旧块——fill 重算失败时旧块
  残留是构造陷阱）；断言须带 `<div class="figtitle">` 前缀防 srcline 原文误命中。
- **Major→Minor 降级：_NO_SRC 缺词边界**（「BL2」类文本会被误剥行号）——加
  `(?<![A-Za-z0-9])` 前置断言。
- **维持现状项（记录不修）**：write_fillsheet 的 md 段与 build_slots 的取值知识并存
  （md=原始精度说明书、slots=呈现完成态契约，刻意两路；一致性由 fillsheet 逐字金标准 +
  render 重放双锁兜底，calc_slots 模块头已写明边界）；render_report 661 行 19 filler
  未超 1k，锚定填充的固有形态不硬拆。



## 四·八、当前未发布轮：v0.1.1（2026-10-09，ponytail-audit 全库审计修复轮）

> 触发：用户触发 ponytail-audit 全库审计（v0.0.24 后第二轮）→ 20 条实证发现
> （6 个子代理分模块审计 + 主会话抽查核实，全部带「输入→错误结果」案例），
> 用户定案「全修」。本轮为专项修订轮，纪律 6「报告流程不修技能源」不适用。

### 修订（全部落地，回归 147→177 全绿）

1. **calc 族（8 修）**：effects_ratio=null 合法形态不再逼造数（移出 cmp_fields 单独判）；
   walk_leaves 孤儿 `{"cur":x}` 不再静默吞（含 cur 一律叶子）；avg() 缺 prev 返回 None
   （不再期末冒充平均，与序列路径同口径）+ hist_ye 非空但 prev 缺失判脱钩 FAIL +
   dpo 守卫三式对齐；derived.ratios 三畸形（字符串 cur/hist 含字符串/裸数字节点）结构
   检查报 type FAIL 不再 traceback；Altman/Ohlson 除零防护（休眠壳/两期净利均 0 走
   inputs 通道）；stress scenarios 条数校验（截断不再 zip 假通过）+ OK 消息复用 dol
   （不再第 4 次 build_ratio_calcs）；ratio-hist SKIP 消息补 n_skip
2. **calc_slots/render（9 修）**：JS 槽序列化唯一出口 `_jd`（None→null + `</` 转义——
   DUPONT_STACK `gap:None` / `OCF_END=None` 团灭两前科根治；分部名夹带 `</script>`
   注入封堵）；_NO_SRC 词边界+位数≥3 双保险（BL2/TL431/「L2 级」不再被啃字——四·七
   所谓「已修」从未落码实证）；recon_total 机械产出（不再手数）；s5 cip/s6 ratio 过
   _TXT 链；fill_meta 两锚显式计数入断锚；_rebuild 保 tr 属性；explain 不再二次截长
   （_trunc_num 双写删）；render 槽位新鲜度 WARN（底稿比 fillsheet.json 新即提醒）
3. **模板（5 修）**：`OCF_BRIDGE[0]?.[1]` 可选链（空桥不再 TypeError 团灭 4 图）；
   _panelBars/combo 主序列 null 跳柱不画（缺数≠0，幽灵 0 读数根治）+ combo 负值守卫；
   .grid3 死 CSS 删；ocf_drop 第 7 条降级路径（空 OCF 桥删 svg+brends+figtitle 声明，
   对齐 ncr_drop 模式）
4. **check_html 族（10 修）**：internal-ref 版本号 v0.0.x→v0.x.x（现行 v0.1.0 不再
   畅通）；dupont-stack 正则兼容 _jd 新形态/+ 号/gap=null（不再静默跳过）；
   gap-declaration 逐条覆盖判据（声明一半不算落实）；T8① 全角＞＜豁免；undisclosed
   跨单元格拼接不再拼假声明（标签换「，」）；hardrule style 注释豁免 + 协议相对外链
   封堵；placeholder/decimal-places inline style 屏蔽；T8② 回核键面补分部与 recon
   lhs/rhs；bare-number 连字符日期豁免；figtitle 复述判定边界感知
5. **md_clean（4 修）**：孤立「|」不吞 pre 碎行（落独立行+unmerged，不再静默丢+统计
   虚报）；文中独立数字行不再当页码误删（跳空行后邻居是噪声才算页码）；不变量二行
   集合快判（17MB 85s→0.8s）；build_index 不再双算
6. **ts_fetch（3 修）**：--params 逗号多值并入上一键（ts_code=A,B 不再 SystemExit）；
   fields/items 不等长判结构异常（不再静默截断当无数据）；非 JSON 响应转可读 FAIL；
   0 行提示「勿直接当无数据落底稿」
7. **gate（3 修）**：渲染 SKIP 时汇总改「两道硬门禁绿 + 渲染门禁跳过」（不再假全绿）；
   check_render 🔴 明细与 stderr 透传；--chrome 透传
8. **测试体系（147→177，+30 断言）**：calc 阳性 8 / check_html 阳性 11 / render 断锚
   +降级 6 / check_render 探测器阳性 2（empty-svg/overlap）/ md_clean 构造 2；
   _leaves bool 盲区修复+键集对称差先判；康得新 Altman 断言锚 OK 行+反证 bad≥1 锚；
   裸 assert ×3 改 raise；sys.path.insert 挪 main 首行；check_render --png 重名 id
   加序号+旧分片提示、linger 循环内重读日志
9. **文档一致性**：T8 0.5%→0.15% 三处（代码本是 0.15%，文档漂移）；HANDOFF 断言计数
   132/144→177、呈现文本族 11+3→15；SKILL 校验六类→八类、报告路径口径（技能工作区
   根 reports/）；SKILL.md 行尾统一 CRLF

### 验证

- 回归 147→177 全绿；金标准 fillsheet 唯一 diff = DUPONT_STACK 序列化形态
  （f-string→json.dumps，数值逐字一致，金标准按运维速查流程重生成）；
- 分模块修复各有实证探针（dupont-stack 三形态/hardrule 注释+协议相对/T8 全角/
  undisclosed 跨格/gap 逐条/md_clean 三构造/gate SKIP 与 svgclip 透传/ts_fetch
  参数解析/_jd·_NO_SRC·_TXT 单测）；
- 茅台黄金样本 gate 对照：check_html FAIL 三条与基线类别逐字一致（internal-ref
  1 处/num-vs-json 2 处/required 1 处，均为 v0.0.4 旧快照现象，纪律 7 不追溯），
  WARN 11 条全属旧版式固有噪音、无 v0.1.1 新规则贡献；渲染 svgclip 0、empty-svg 0
  （overlap 2 为旧版式固有）——本轮 10 条 check_html 修复对旧版式零误报零口径漂移。

### 遗留

- 无（审计 20 条全修；references 方法论正文、fixture 内部数据、tushare 真实接口、
  Altman/Ohlson 系数本地化依据属「未审计」而非「未修」，下轮审计可续）。

---

## 五、下一步工作计划

> 治理（v0.0.22 用户定案）：本节只留**未完成**事项；已完成任务的记录移入 supersede/
> 对应轮次文件，不堆删除线。HANDOFF 本体=长期节 + 当前未发布轮 + 全部待完成。

### 自我审核候选方向（未动工项）

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
- 机制层（T6）已完成：schema review 子块 + 冻结纪律 + 模板归因列 + check_html review-shape
  （examples/lookback-demo 构造样本已随清理轮退役，形态由模板 SLOT 与 schema 承载）
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
python financial-report-analysis/tests/run_regression.py   # 应 177/177 通过

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
| `supersede/v0.0.22_2026-10-01.md` | v0.0.22（长城·埃斯顿双报告复盘轮：三条新门禁 js-dup-decl/assert-trunc/empty-svg + s1 㗊四宫格 + 派发窗 7 代理 + 流程治理） |
| `supersede/v0.0.23_2026-10-01.md` | v0.0.23（海康反馈轮：effline 标签避让、s1-grid4 机检、s7 汇总口径、四维表评价列纪律） |
