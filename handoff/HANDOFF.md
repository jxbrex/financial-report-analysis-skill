# HANDOFF · 交接文档

> 版本 **0.1.4** · 截至 2026-10-22 · 本文档面向「下一个接手这个项目的人/AI 会话」
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
│   └── run_regression.py       #   唯一回归入口：189 条断言 + check_html/T8/渲染冒烟 + 构造用例
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
3. **`python tests/run_regression.py`** —— 任何改动后必跑，**189 条断言**全绿才算没改坏
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
- **蜜雪轮效率数据点（港股首跑，73.3min 对照基线：万华 53.3 / 海康 64.5）**：LLM 流式 66.6min
  （占 91%，万华 86%）；两大单点=①主线方法库全量重读+62KB json 合成 27.2min（港股首跑
  特有：六份 references 逐个核对 IFRS 映射，非常规报告不该全量重读——技能修订轮考虑按
  report_type 预裁剪阅读清单）②三段手写填充脚本 71KB 纯流式约 14min（232 孔，海康同款
  瓶颈复现）；并行窗 8.3min（最慢 ①b 497s 同形态拖尾）；前台并行派发主线阻塞 8min
  空等（可考虑 background 派发+主线读库重叠）；返工 4 处≈5min（ts_fetch hk_daily
  ts_code 过滤失效×2→改 mx 取市值 / p2 脚本锚点差两字重跑 / incentive_line 部分字段
  FAIL / OCF 桥合并项算术笔误 0.018 亿被容差放过、交付前自查抓回）
- **港股首跑实测（蜜雪 2026H1，2026-10-10，三道门禁绿）**：①md_clean 索引对港式章节名
  零识别（index 空），子代理派单改用锚点+Grep——**v0.1.2 已修**（港式章节名精确整行匹配
  +页眉去重 + 港式主表入 blocks，蜜雪 md 实测 11 节/5 块）；②recon 结构性上限 8/17
  （无直接法收现 A4/B1、无存货增加额附注 B2、无在建工程科目 B3、无母公司单体报表 D 组），
  ~~`--min-recon` 港股中报按 8 校准~~——**v0.1.2 已参数化**（`--min-recon auto` 按
  meta.market+report_type 查校准表）；③权益变动表 PDF 文本逆序可数字
  反读解码（权益构成逐项交叉勾稽还原，A2 因此可执行）；④妙想港股汇总表为港元折算
  （汇率偏高约 5%，疑年末/均价口径），取数只用 F9 明细表人民币口径；⑤render/fillsheet
  的 OCF 桥端点行与标签硬编码「净利润」，港股间接法主表起点是税前利润——
  ~~技能修订轮再参数化~~ **v0.1.2 已修**（端点行/端点柱标签取 ocf_bridge 首行科目名剥括号注）；
  ⑥check_html 两处既有 WARN 基线港股同款命中：s1-v15-shape 因子分位表无降级豁免、
  s2-shape 把四线卡 ✅ 判定徽章计入绿徽——**v0.1.2 已修**（分位降级声明行豁免 +
  四线考核表整表剔除再数徽章），蜜雪 WARN 3→1、赢合/海康同款误报同步消除
- **桑基图卡（v0.1.4）三坑**：①fill_js 元组漏注册新 JS 槽=不断锚、静默画零值图
  （勘察标记的最易漏点——加槽四件套=_js_slots + write_fillsheet + fill_js + 模板调用区注册）；
  ②支流末端必须伸进**不透明**盒体——半透明流带（fill-opacity）盖不住线帽端头
  （宁德轮「直角茬」实证）；③模板 JS 运行时错误用 node shim 全脚本复现定位最快
  （grossH 漏声明 ReferenceError 实证——症状是「报错点之后的图全空」而非全局团灭，
  与 js-dup-decl 的整段 SyntaxError 团灭形态不同）
- **桑基符号路由只在 calc_sankey.route_items**（财务费用正→并入费用盒 / 其他损益负→挪减项侧 /
  减值净转回→加项），drawSankey 只画不判；改符号规则改 calc 勿改 JS
- **fill 幂等金标准的连锁**：新增 fill 自动产出的 derived 块时，可算 fixture 必须同步落块
  （否则幂等 diff 破，万华轮实证）；茅台 WARN==0 硬锚要求新校验缺省只许 SKIP 不许 WARN
- **阿里轮实测（港股年报首验，2026FY，全流程 136min vs 蜜雪 73.3min——体量 3 倍+两处技能盲区返工）**：
  ①US GAAP 映射要点：fin_exp 填「利息费用−利息收入」净额（可为负，schema 允许——DFL/DOL/ROIC 的
  EBIT 依赖它）；OCF 桥起点=净利润（v0.1.2 参数化生效）；无收现行/无扣非/无在建工程科目——
  cash_to_sales、dpo/ccc、dupont_dt 结构性 null 合法；②**非日历年财年（3-31 止）连锁三坑**
  （labels 空致五图团灭 / 期次误标 2026Q1 / 五年表头锚退化致 render 崩溃）——**v0.1.3 已修**
  （hist_periods 产 FY 标签 + _period_label 年报一律 FY + labels 取最长序列），不再需手工补丁；③**夹层权益（mezzanine）**：阿里 78.45 亿使「资产=负债+归母权益+NCI」偏差 0.41% 恰在
  0.5% 容差内——更大夹层会破 A0，注意；④mx 港股汇总表港元折算偏高勿用（蜜雪同款再现）；
  mx **MCP 通道**积分中途耗尽——注意妙想两条通道额度独立：MCP 耗尽≠skill 直连
  （mx_data.py / mkapi2 端点 + MX_APIKEY）耗尽，本轮先误信全灭、后实测 skill 通道照常
  （港股查询成功）；再兜底 yahoo_finance（BABA/PDD）补五年明细+双源核对有效；
  ⑤D 组港股年报可执行 4/5（附注 30 母公司简明报表 S-X 披露），recon 上限 12/17（A4/B1/B2/B3/D3
  结构性不可执行），`--min-recon auto` 初版退回 WARN 态、显式给 12 通过（v0.1.3 起 auto 直接识别）；
  ⑥四象限在港股分部口径的适配：分部无成本披露→cost=rev−经调整EBITA 倒挤（der 标注），
  calc 两条 WARN（合计 108.5% 抵消前/加权 EBITA 率 vs 毛利率口径差）为预期口径差；
  ⑦内部引用门禁实录：底稿 evidence 别写 mx_*/「xx.md」字样（render _TXT 剥 L 行号会留断句）

## 三、历史发现与轮次记录

已发布轮次的复盘与发现全部在 `handoff/supersede/`（索引见文末）；
「勾稽闭合≠科目真实」等长期认知已沉淀进 `references/articulation.md` 使用总则。

---

## 四、已知局限与未验证项（诚实清单）

**接手后最该先看的部分——只留真未完成项（v0.0.22 瘦身定案：已解决项的记在 supersede/，不堆删除线）：**

| # | 局限 | 影响 |
|---|---|---|
| 1 | ~~港股全流程未跑过~~ **港股半年报已首验**（蜜雪 2026H1）+ **港股年报已首验**（阿里巴巴 09988 2026FY，2026-10-10 三道门禁绿；US GAAP 准则、人民币呈报、3-31 财年止） | 残留：美股全流程未验证；render 年报二期（见 11） |
| 2 | ~~**季报/招股书两种报告类型未实测**~~ **季报已首验**（中国移动 600941 2026Q3，2026-10-21 三道门禁绿 + 已视觉验收；report-types.md 季报裁剪规则总体符实） | 残留：招股书未实测；季报路径三处技能缺口见 N6 |
| 3 | **industry-profiles.md 八类模式零实测** | 工程建造的合同资产勾稽、农业的生物资产盘点、经销商压货三条件、医药的研发资本化/license-out 勾稽都没在真实样本上跑过 |
| 4 | ~~**P1-17 四象限未端到端跑过**~~ **已首验**（阿里 2026FY：四分部 delta 口径全字段复算自洽；港股分部无成本披露→EBITA 倒挤成本口径适配，calc 两条口径 WARN 预期内） | 断言验证/周期定位/费用ROI 此前已多份实战 |
| 5 | ~~**回看机制已落、真实数据实测待披露季**~~ **回看模式已首验**（移动 H1→Q3，2026-10-21：5 条 watchlist 照抄 tripwire 原文，1 未兑现含归因+4 待观察，review 子块按冻结纪律落库） | 阿里 watchlist 待 FY2027 中报回看；特变/恒瑞待 2026FY |
| 6 | 康得新 **A5/B2/B3 三条等式因附注未披露而无法执行** | 换个披露更全的造假样本可验证这三条 |
| 7 | **存量旧版式报告不追溯**（纪律 7） | 新门禁对旧报告的 WARN/FAIL 全属预期：T8① 噪音、internal-ref、percentile-map、gap-declaration、js-dup-decl/assert-trunc/empty-svg（长城事故样本留档）同类 |
| 8 | **比率趋势数据依赖 tushare 可得性** | 世界线披露晚于库更新时当期 hist 取报告提取值；重述公司历史期口径断裂，趋势缺 hist 合法（schema 血泪 7） |
| 9 | **移动 json 的 src 行号与现行 md 不匹配**（T8②级 104/107 miss） | v0.0.4 底稿行号体系；下份移动报告重建底稿时按新 schema 修复 |
| 10 | **70% 升档阈值真实触发仍待样本**（长城无息 87% 达标但杠杆非主驱动、升档正确地未触发） | 首验场景：首份「杠杆为主驱动+无息>70%+|ΔDFL|<0.1」公司 |
| 11 | **render 二期（年报专属路径未脚本化）**：Q4 卡/review 回看卡填充、预期对照表（schema expectations 块）、高管增减持块、big_moves 大动表提取——一期半年报路径全覆盖 | 阿里 2026FY 实测：245 残留孔手工填充（含 Q4 卡 5 行/期后徽章列 7 处/big_moves/高管增减持/预期对照），可行但最重单点；二期回测样本可继续用腾讯 00700 或直接基于阿里 fillsheet 沉淀 |

---

## 四·九、当前未发布轮：v0.1.2（2026-10-10，蜜雪港股首跑反馈轮）

> 触发：蜜雪轮记账的五项技能缺口（运维速查末条①②⑤⑥ + 效率治理）用户定案「都修吧」。
> 专项修订轮，回归 177→189 全绿（+12 构造断言）。

### 修订（全部落地）

1. **OCF 桥起点标签参数化**：calc_slots `brends_ocf` 与模板端点柱标签由硬编码「净利润」
   改为取 `derived.ocf_bridge` 首行科目名（剥括号注）——港股间接法起点「税前利润」自动正确，
   A 股五例 fixture 首行均「净利润」，产出逐字不变（金标准零 diff）
2. **`--min-recon auto`**：calc.py 加 AUTO_MIN_RECON 校准表（meta.market+report_type 查表：
   A 股 15/13/8，港股半年报 8=蜜雪实测结构性上限；未知组合退回 WARN 态并提示显式给数），
   gate.py 透传去 type=int 限制
3. **check_html 两缺口**：s1-v15-shape 分位表降级声明行豁免（「分位不可用/分位需/分位卡降级」
   行不计缺白描）；s2-shape 数徽章前整表剔除四线贴线考核卡（表头「检测线」锚）——
   该卡固定 3 枚 badge g 是赢合/海康/蜜雪三份现行版式的共同误报源
4. **md_clean 港式索引**：HK_SECTION_NAMES 精确整行匹配 + 去重取首现（港式章节无编号、
   以页眉形式整篇重复）；BLOCK_KEYS 补港式主表/附注（中期簡明前缀两态）——蜜雪 md 实测
   索引 0 → 11 节/5 块
5. **SKILL.md 流程治理**：方法库阅读按 report_type 预裁剪（港美股路径 A 股专属条目跳读，
   蜜雪全量重读 27.2min 实证）；派发窗改 run_in_background 后台派发（前台阻塞 8min 实证）；
   Phase 7.5 指令改 `--min-recon auto`

### 验证

- 回归 177→189 全绿（+12：OCF 标签 fill/模板契约、auto 三方向、分位豁免正负、
  四线卡剔除正负、港式 md 索引三断言）；
- 蜜雪真实产物端到端：check_html WARN 3→1（s1-v15/s2-shape 转 OK，仅剩 bare-number
  人工确认类），calc `--min-recon auto` 正确识别「港股半年报 → 8」；
- 赢合/海康（现行版式）s2-shape 误报同步消除；茅台黄金样本（v0.0.4 旧版式）两条规则
  输出与基线逐字一致（「未找到章节」WARN，零口径漂移）。

---

## 四·十、当前未发布轮：v0.1.3（2026-10-10，阿里港股年报首验反馈轮）

> 触发：阿里巴巴 09988 2026FY 年报首验（三道门禁绿）撞出的四处技能缺口
> （局限 12/13/14 + md_clean US GAAP 章节名），用户定案「顺手修掉」。
> 报告轮+修订轮合并执行，回归 189 全绿（零新增断言——全部为存量路径修复）。

### 修订（全部落地）

1. **非日历年财年支持**（hist_periods 盲区三连锁，局限 12）：
   ①calc_common `hist_periods` 年报不再卡 12-31 月结，非日历年财年产 FY 形态标签
   （FY2022=截至 2022-03-31；A 股 12-31 路径零漂移）；②calc_slots `_period_label` 加
   report_type 参数，年报一律 FY（修阿里 period=20260331 误标「2026Q1」致 render
   文件名错+五年表头锚退化崩溃）；③`_js_slots` 趋势图 labels 改取最长 hist 序列期数
   （修「cash_ts 4 期截断 rev 5 期」隐患），空 labels 致 empty-svg 团灭链路根除
2. **T8② 单位换算补百万元档**（×1e2，局限 13）：港股/美股年报百万元列报（阿里实证
   ②级 207/233 miss → 修后 28 miss，命中率 88%）
3. **stackH 钳位撞车去重**（模板 JS，局限 14）：负向窄段同钳左缘且同奇偶层时标签
   重叠——钳位后同层同 x 登记去重右移 92px（阿里产物补丁移植入模板）
4. **分位白描 X/N**（calc_slots `_pctile_label` + check_html_text `check_percentile_map`
   同步感知窗口期数）：n<5 窗口按 X=N−v·(N−1) 白描（阿里四年窗口 0.6667→「2/4」）；
   n=5 走 PCTILE_LABEL 契约锁映射不变；窗口期数本地推导不落库（幂等纪律，回归零漂移）
5. **`--min-recon auto` 补（港股，年报）=12**（阿里实测上限：D 组 4/5+B4 多出半年报）
6. **md_clean 补 US GAAP 港式章节名**（「合併利潤表/合併資產負債表/合併現金流量表」等
   合併*前缀族 + 業務概覽/公司治理報告等年报章节名）——阿里 md 索引 4 节/1 块 → 11 节/6 块，
   与蜜雪半年报齐平；clean.md 重跑逐字一致（幂等）
7. **data-sources.md 补港美股取数兜底链**（妙想积分场景）：妙想两条通道额度独立——
   mx_* MCP 与 skill 直连（mx_data.py / mkapi2 端点 + MX_APIKEY）互不占用，MCP 耗尽先切
   skill 直连（阿里轮实测港股查询成功）；再兜底 yahoo_finance（`get_financial_statement`
   年度三表近四年，双重上市标的同账同源；PDD 毛利率/阿里 FY2023 现金流实证有效）
8. **T8② 千位符数字解析修复**（ponytail 复核时构造断言抓出）：`PLAIN_NUM_RE` 匹配
   「131,530」整体但 `float()` 拒逗号静默跳过——②级回核对财报千位符数字整体失明
   （A 股同病）；改去逗号再解析，一行修复

### 验证

- ponytail-review 复核（用户触发）：Must fix 无；Should fix 两条（缺防回退断言/分位窗口
  期数三处内联重复）已当场修掉——顺带抓出第 8 条千位符失明（构造断言的价值实证）；
- 回归 189→**199 全绿**（+10 条 v0.1.3 构造断言：FY 标签三方向/分位 X:N 双口径/百万档
  命中与不误报/auto 港股年报=12/labels 最长序列+前置 null 对齐）；
- 阿里端到端临时复验（不碰成品）：fill 自动产 p_start=FY2023/分位「2/4」/labels 五期；
  render 直接产正确文件名与期次标签、stackH 补丁随模板产出；
- 阿里成品报告在修订后门禁链下三道全绿（成品分位 badge 同步 1/4 口径）；
- ②级 miss 残留 28/233 逐条确认：全部为 der 推算值（原文本无此数）+ 范围型 src 超
  ±2 行号窗——两类均属可解释，候选项「②级跳过 level=der 叶子」记入后续评估。

---

## 四·十一、当前未发布轮：v0.1.4（2026-10-22，桑基图卡模板化）

> 触发：宁德 2026Q3 季报轮，用户拿来别家工具的桑基图要求「我们的报告也要有」——
> 先按纪律 6 以一次性呈现层补图落地成品，经用户 6 轮视觉迭代定稿形态
> （盒式节点/费用盒 2×2/支流汇入主流/现金流横条双段同规格居中/第三段按体量/汇流平滑），
> 用户定案「写到 skill 里去」。回归 189→**209 全绿**（+13 条桑基断言 + 复审轮
> 补 7 条：茅台 gap<0 分流形态 render 重放 3 条 + 桑基降级构造用例 4 条）。

### 修订（全部落地）

1. **derived.sankey 选填块（schema 1.7）**：20 科目 + period_type（本期/单季差额）+
   单季差额 cum/cum_prev 卡口；不适用降级（rev/毛利/营业利润/净利/归母/OCF 非正、
   少数股东为负、Q3 缺上一累计期原料）整块 null 合法；income 加三选填叶
   （other_income/disposal_income/op_profit，桑基明细行原料，①b 派单模板同步补三项选提）
2. **calc_sankey.py 新模块**：compute_sankey（公式唯一定义处，fill/check 共用）+
   route_items 符号路由（减项/加项数组唯一出处，JS 只画不判）+ check_sankey 复算比对
   （容差复用 tol_bridge）；缺省只 SKIP 不 WARN（茅台 WARN==0 硬锚不破）。
   **坑（回归抓出）**：减值/营业外/少数股东未单列的公司（茅台/康得新实证）一度被误降级——
   未单列减值按 0 计、少数股东按恒等式差额推算、营业外净额按 0 计
3. **模板 drawSankey + S3 插卡**（净利桥后、OCF 桥前）：盒式节点/流带∝金额/双比例尺
   （S=264/rev、S2=min(S,54/gross)——高毛利率公司毛利扇出溢出防御）/加项支流汇入主流
   /②段净调整负=分流·正=双源汇入（净利盒+净调整绿盒→横条）/③段盒高∝体量
   （k=106/max(capex,|fcf|)）+FCF 按符号变色；降级=render s3.sankey_drop 删 svg 换声明卡
4. **JS 槽链**：calc_slots.build_sankey_slot（负载唯一出处，_js_slots 与 check_html 共用）
   + fill_js 元组注册 + fillsheet SANKEY 段 + srcline 机械槽（口径随 period_type 变化）
5. **机检**：check_html 规则 24 sankey-slot（FAIL，仅 --json；无槽无图→不适用，
   静态 svg 无槽→一次性补图豁免）；check_render KEY_SVG_IDS 加 sankey
6. **Q3 单季差额通用取数**（data-sources 二·五 从 Q4 专属升级；tushare 上一累计期字段
   实测对照：biz_tax_surchg/oth_income/operate_profit/c_pay_acq_const_fiolta；
   资产处置收益 tushare 无字段走原文）
7. **文档登记**：factor-analysis.md 新六·五节、report-types 三类型适用声明、
   SKILL.md Phase 1/2/4/8 登记 + 版本 0.1.4

### 验证

- 回归 189→**202 全绿**：calc 阳性⑨（桑基改值必 exit 1）+ check_html 阳性⑫⑬
  （槽正确判 OK/改值必 FAIL）+ 赢合 render 重放（fillsheet 逐字锁 golden 仅多 SANKEY 段、
  断锚 exit 0、check_html 仅 placeholder FAIL、check_render 0 问题）；
- 幂等金标准连锁：茅台/康得新/万华 fixture 同步落 sankey 块（可算公司都该有块），
  万科连亏样本合法无块（降级 SKIP）；
- 宁德端到端预验（临时副本，不碰成品）：手画 25 数与 compute_sankey 复算逐位一致，
  破坏测试双卡口同时命中；
- 赢合产物渲染画出**双源汇入分支**（净调整 +6.45 为正）与**小 capex 盒高塌缩**（0.28 亿）——
  两分支非宁德形态，属新增覆盖；
- 模板 JS 运行时验证：node shim 全脚本跑通（grossH 漏声明 ReferenceError 实证被抓，
  该 bug 曾致 holders 图空白）；
- **ponytail-review 复审（2026-10-22 用户触发，发现已当场修复）**：①单季差额口径下
  其他损益明细行误从 cum 子块取数（cum 只有 20 个短键）→ 明细行全丢，修为 cur 读
  statements、prev 读 cum_prev；②加项盒明细行无上限（4 明细+残差=5 行溢出 58px 盒），
  槽侧封顶 4 行；③drawSankey 双源汇入分支横条带厚度误用 ocf 口径（应 np 口径）+
  三处流带落点封边 cap 越界细条；④fill 幂等盲区：已计算的 sankey 块遭遇降级形态
  （转亏）时旧块残留不降——fill 现置 null（无 rev 的部分预填种子块保留不吞）。

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

**任务 1：跑通港股/美股全流程（局限 1）**——港股半年报（蜜雪 2026H1）与**港股年报（阿里巴巴 2026FY，2026-10-10 三道门禁绿）均已首验**
- 剩余：美股路径仍待首验；回看机制真实数据验证待「同公司第二份报告」（阿里 watchlist 已落库，FY2027 中报可回看）
- 阿里轮验收实证：calc exit 0（--min-recon 12 显式）+ check_html exit 0 + check_render 0 问题 + 章节齐全（s0~s8，review 无上期降级删除）+ 数字抽查 12 项与原文一致 + 已视觉验收（--png 分片）

**任务 2：季报 + 招股书各一次（局限 2）**
- ~~季报走轻量版~~ **季报已完成**（移动 2026Q3：P2/P4/P7 精简路径可行；勾稽实测上限 7/17、render 季报路径三缺口见 N6）；剩余：招股书走专属模块
- 验收：招股书包类型产出一份报告并通过两道门禁；发现 report-types.md 与实际不符处即修正

**任务 2·补（N6）：季报路径三处技能缺口（移动 Q3 首验实证，专项修订轮修）**
- ①`_PERIOD_SUFFIX`（calc_common.py）缺「季报」键 → hist_periods 返回 None →
  dupont5y.period_start/end 空串 → render s1.d5 表头定位串退化为 `<tr><th>因子</th><th>`
  匹配左卡（4 列）IndexError；同因 TREND/NCR_TS/EFF_TS 的 labels 空数组（empty-svg 隐患）。
  本轮绕过：fillsheet.json 手填 p_start/p_end + 三组 labels
- ②`--min-recon auto` 校准表按 meta.market 精确串匹配，长串市场名（「A股（红筹，香港注册；
  港股 941.HK）」）miss 退回 WARN 态；**季报实测结构性上限 7/17**（A3/A5/B1/B2/B3/D 组
  无附注/无母公司报表不可执行）——校准表 A 股季报=8 对无商誉/在建的公司高估 1 条，
  显式给 7 通过（B4 商誉简化 roll 做了才到 7）
- ③render 季报路径呈现缺口三小处：review 回看卡与导航链接整卡缺失（手工插回）；
  X6 行读数「（半年口径）」硬编码（季报应为三季口径）；S5 在建表首行 demo 文案
  「期末余额为零」不感知实际余额——均手工修正，二期随年报路径一起脚本化

**任务 2·补 2（N6 二验：宁德时代 300750 2026Q3，2026-10-21，三道门禁全绿 + 已视觉验收）**：
与移动同窗口并行的第二份季报（纪律 6 场景实证：双报告共享技能源，各自绕过未当场修）。
N6 三处缺口全部复现（同根因、同绕过）；增量发现：
- ②变体：宁德 recon 结构性可执行仅 **4/17**（A2/A4/A7/A8——A1 缺受限资金明细、
  A6 缺折旧摊销，比移动 7 条还低；季报可执行条数随公司披露 4~7 浮动），校准表
  「A股季报=8」对宁德高估 4 条；市场名「A股（创业板）+H股（03750.HK）」同样 miss
  退回 WARN 态（未显式给数，WARN 人工确认合法）
- ④新增：**calc Altman 对三季报 interim 年化（×4/3）未接入**——meta.market_cap_cur
  已填 11,988.28 亿仍判「分量字段不齐」合法 null；Ohlson 正常（O=-1.63、P=0.164 中档）。
  手算 Altman Z≈2.26（三季报 ×4/3 年化，灰色区）备查，未入报告（T8① 无源）
- ⑤新增：SGR 对 est 级 dividend_paid 不采纳置 null（季报分红拆分天然 est）——
  「未提取置 null」与「est 不可用」的口径边界待修订轮定夺
- 回看第二例：半年报 5 条 tripwire → ❌ 2（库存 DIO、capex 节奏）/⏳ 3（合同负债、
  碳酸锂、产能利用率）；❌ 主归因=「时点错」（触发窗口后移），review 子块已冻结落库
- 效率：全流程约 140min（含首验排障 render IndexError/labels/Altman + 双份并行争用；
  对照半年报基线 53-65min）

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
python financial-report-analysis/tests/run_regression.py   # 应 189/189 通过

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
| `supersede/v0.0.24-v0.1.1_2026-10-03~09.md` | v0.0.24~v0.1.1（全库审计清理+四象限 schema 1.5 / 赢合反馈轮 deltaBars+svgclip / N4 fill→render 脚本化+schema 1.6 / v0.1.1 审计 20 项修复） |
