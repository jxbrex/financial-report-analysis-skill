# HANDOFF · 交接文档

> 版本 **0.1.1** · 截至 2026-10-10 · 本文档面向「下一个接手这个项目的人/AI 会话」
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
- **蜜雪轮效率数据点（港股首跑，73.3min 对照基线：万华 53.3 / 海康 64.5）**：LLM 流式 66.6min
  （占 91%，万华 86%）；两大单点=①主线方法库全量重读+62KB json 合成 27.2min（港股首跑
  特有：六份 references 逐个核对 IFRS 映射，非常规报告不该全量重读——技能修订轮考虑按
  report_type 预裁剪阅读清单）②三段手写填充脚本 71KB 纯流式约 14min（232 孔，海康同款
  瓶颈复现）；并行窗 8.3min（最慢 ①b 497s 同形态拖尾）；前台并行派发主线阻塞 8min
  空等（可考虑 background 派发+主线读库重叠）；返工 4 处≈5min（ts_fetch hk_daily
  ts_code 过滤失效×2→改 mx 取市值 / p2 脚本锚点差两字重跑 / incentive_line 部分字段
  FAIL / OCF 桥合并项算术笔误 0.018 亿被容差放过、交付前自查抓回）
- **港股首跑实测（蜜雪 2026H1，2026-10-10，三道门禁绿）**：①md_clean 索引对港式章节名
  零识别（index 空），子代理派单改用锚点+Grep；②recon 结构性上限 8/17（无直接法收现
  A4/B1、无存货增加额附注 B2、无在建工程科目 B3、无母公司单体报表 D 组），
  `--min-recon` 港股中报按 8 校准（13 是 A 股假设）；③权益变动表 PDF 文本逆序可数字
  反读解码（权益构成逐项交叉勾稽还原，A2 因此可执行）；④妙想港股汇总表为港元折算
  （汇率偏高约 5%，疑年末/均价口径），取数只用 F9 明细表人民币口径；⑤render/fillsheet
  的 OCF 桥端点行与标签硬编码「净利润」，港股间接法主表起点是税前利润——报告呈现层
  手工改「税前利润」，技能修订轮再参数化（待办）；⑥check_html 两处既有 WARN 基线
  港股同款命中：s1-v15-shape 因子分位表无降级豁免（hist<3 合法降级仍报待确认）、
  s2-shape 把四线卡 ✅ 判定徽章计入绿徽——属技能缺口非报告缺陷，人工确认豁免

## 三、历史发现与轮次记录

已发布轮次的复盘与发现全部在 `handoff/supersede/`（索引见文末）；
「勾稽闭合≠科目真实」等长期认知已沉淀进 `references/articulation.md` 使用总则。

---

## 四、已知局限与未验证项（诚实清单）

**接手后最该先看的部分——只留真未完成项（v0.0.22 瘦身定案：已解决项的记在 supersede/，不堆删除线）：**

| # | 局限 | 影响 |
|---|---|---|
| 1 | ~~港股全流程未跑过~~ **港股半年报已首验**（蜜雪 2026H1，2026-10-10 三道门禁绿） | 残留：港股**年报**专属槽位（Q4/review 卡）未验；美股全流程未验证；港股 recon 上限 8/17 与 OCF 桥起点口径待技能修订轮参数化（运维速查末条） |
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

## 五、下一步工作计划

> 治理（v0.0.22 用户定案）：本节只留**未完成**事项；已完成任务的记录移入 supersede/
> 对应轮次文件，不堆删除线。HANDOFF 本体=长期节 + 当前未发布轮 + 全部待完成。

### 自我审核候选方向（未动工项）

**N5. 新准则造假样本扩充（排雷库回归覆盖单一）**
康得新是 2018 旧准则样本，「抓漏报」金标准只有它一个——收入准则/金融工具准则切换后
的造假手法（如合同资产操纵、供应链融资藏债）无回归覆盖。留意下一个公开定性的造假案例
（处罚决定书+当年年报可得的），固化为第五个 fixture。

### P0（接着做，价值最高）

**任务 1：跑通港股/美股全流程（局限 1）**——港股半年报已首验（蜜雪 2026H1）
- 剩余建议标的：**腾讯 00700.HK 2025 年报**——补验港股年报专属槽位（Q4 单季透视/股东户数/机构预期）与回看机制；美股路径仍待首验
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
| `supersede/v0.0.24-v0.1.1_2026-10-03~09.md` | v0.0.24~v0.1.1（全库审计清理+四象限 schema 1.5 / 赢合反馈轮 deltaBars+svgclip / N4 fill→render 脚本化+schema 1.6 / v0.1.1 审计 20 项修复） |
