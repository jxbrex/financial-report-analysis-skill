# 子代理派单 prompt 模板（Phase 0 并行派发窗用）

> v0.0.14 新增（比亚迪轮复盘：现场手写 5 份派单 prompt 花 105s，模板化后≈填空）。
> v0.0.18：② 拆为 ②a/②b 两个代理（万华轮附注单代理 547s 拖满 9.1m 并行窗口）；
> 产出改**分块落盘** `_chunks/{stem}/`（治主线一次性手写 16k token data.json 的 311s 单点）。
> v0.0.22：① 拆为 ①a/①b 两个代理（三表+母公司单代理连续两轮为窗口最慢——埃斯顿/长城轮
> 实测；按顶层键切分合并面干净：①a 拿 balance+parent_statements，①b 拿 income+cashflow）。
> 用法：派发前把【槽位】填上实际值，**再按公司特点加一条专属任务**（模板只兜底通用面，
> 针对性靠这一句，不许省略——如「该公司本期有大额定增，单独核对募集资金流向」）。
> 季报/轻量版可裁剪 ②b④⑤；招股书把 ⑤ 的「期后」替换为「募投项目与发行前后股权」。

## 七个模板共享的硬约束（每次派发时原样附上）

- 你只读源文件（clean md / 外部接口）；**产出写入指定 `_chunks/{stem}/xxx.json`，不写其他文件**
- 输入：`{clean_md 路径}` + `{stem}.index.json`（先读索引，按行区间切片 Read，禁整文件盲读）
- 单位统一换算为**亿元**（原文千元/万元列报的自己换算并注明）；每个值带 `src`（clean md 行号，L 前缀）
- 未披露填 null，禁止用 0 或编造值占位；数字照原文抄，禁千位符
- 只覆盖分配给你的 schema 块，越界字段留给别的代理（字段归属见各模板）
- 分块 json 顶层键必须是指定 schema 块名，键名严格按 `references/extraction-schema.md`；
  完成后回传**压缩摘要**（字段=值+出处，供主线核对），不回传原文段落

## ①a 资产负债表 + 母公司提取 → `_chunks/{stem}/statements_bs.json`

提取【公司名】（【代码】）【报告期】【报告类型】的合并资产负债表与母公司三表关键科目：
资产负债表（货币资金/应收/存货/合同负债/商誉/在建工程/有息负债四科目/总资产/归母净资产），
本期+上期+hist 最小 5 期（旧→新）；
母公司：货币资金/未分配利润/其他应收款/投资收益/经营现金流净额（D 组勾稽用）。
用 index.json 的「财务报告」章节定位切片。
落盘骨架：`{"statements": {"balance": {}}, "parent_statements": {…}}`

## ①b 利润表 + 现金流量表提取 → `_chunks/{stem}/statements_ic.json`

提取【公司名】（【代码】）【报告期】【报告类型】的合并利润表与现金流量表关键科目：
利润表（营业收入/营业成本/归母净利/扣非净利/研发费用）、现金流量表（经营现金流净额/
销售商品收到现金/购建固定资产支付现金），本期+上期+hist 最小 5 期（旧→新）；
**另必提「现金流量表补充资料」**（间接法调节表全项照录：净利润/减值/折旧摊销各行列/处置报废/
公允价值/财务费用/投资损益/递延税/存货的减少/经营性应收/经营性应付/其他，本期+上期，
压缩表回传）——它是 derived.ocf_bridge 与 dep_amort 的原料，A3/A5/A6 勾稽全指它；
A 股半年报同样强制披露（report-types.md），找不到先换关键词搜「将净利润调节为」，
确认真未披露才可报缺，禁止凭「半年报不强制」的常识直接降级（卫星化学 2026H1 漏提教训）。
用 index.json 的「财务报告」章节定位切片。
落盘骨架：`{"statements": {"income": {}, "cashflow": {}}}`

## ②a 资产负债附注提取 → `_chunks/{stem}/notes_bs.json`

提取【公司名】（【代码】）【报告期】：应收账款账龄与坏账准备（`ar_aging/ar_writeoff/ar_provision/
ar_factoring`）/存货明细（`inventory_mix/inventory_provision`）/在建工程明细与转固
（`cip_projects`：项目名/预算/累计投入/进度/本期转固）/商誉构成与减值测试（`goodwill_test`）。
用 index.json 的「附注」关键块定位切片。
落盘骨架：`{"notes": {"ar_aging": …, "inventory_mix": …, "cip_projects": […], "goodwill_test": …}}`

## ②b 损益与经营附注提取 → 压缩表回传（Phase 4 桥原料，不落盘）

提取【公司名】（【代码】）【报告期】：收入构成（分产品/分地区）/成本构成/研发费用明细/
长短期借款结构（利率与期限分布）。这些是收入桥/净利桥/隐含利率的原料，
无独立 schema 块——按「字段=值+出处」压缩表回传，供主线 Phase 4 算桥。

## ③ MD&A 断言与语气 → `_chunks/{stem}/assertions.json`

读【公司名】（【代码】）【报告期】MD&A 全文，按 text-mining.md 三层读法提取管理层断言：
每条落 `statement`（原句压缩）/断言类型/可证伪性/验证路径（对应哪个报表科目可验）。
重点关注：经营计划中的量化承诺、对异常波动的解释性措辞、与上期措辞的语气迁移。
落盘骨架：`{"assertions": [{"id": "A1", "text": "…", "account": "…", "verdict": null, "evidence": "…", "source": "L…"}]}`
（字段名是 **source** 不是 src——calc 卡口按 schema 认 source；verdict 留 null，验证判定归主线
Phase 5，**主线回填 verdict（通过/不成立/无法验证）后才跑 calc**——verdict/source 空缺直接 FAIL
（v0.0.23 海康轮首轮返工实证）；**text/evidence 必填不许留空**——evidence 写
验证证据或「缺什么数、去哪拿」；v0.0.22 热核审计：12/13 报告存在底稿空 evidence，长城 A10
呈现层因此自撰文本截断出院——assert-trunc 对底稿空字段出 WARN 点名）

## ④ 产能/在建/股东/户数 → `_chunks/{stem}/notes_ops.json`

提取【公司名】（【代码】）【报告期】：主要产品产能/产量/产能利用率（`capacity` 数组）；
股东户数本期/上期（`shareholders.holder_num_cur/prev`）、户数时序 ≥3 期落
`shareholders.holder_ts`（{labels[],num[],px[]}：labels=期末日 YYYY-MM、num=户数（户）、
px=环比增减% 首期 null——Tushare stk_holdernumber 取数，v0.1.0 起 render 直接消费画 holders 图）、
前十大股东变动
（`shareholders.top10_changes`）、控股股东质押比例（`shareholders.pledge_ratio`）。
用 index.json 定位「股东情况」与经营数据章节。
落盘骨架：`{"notes": {"capacity": […], "shareholders": {…}}}`

## ⑤ 期后事项/同业/机构预期 → `_chunks/{stem}/notes_ext.json`

① 期后：用 mx_finance_search_notice 检索【公司名】【报告期】期末至今日的公告，
提取大额收款/退货/质押/减持/诉讼/违约/分红兑付（`subsequent_events`：
date/event/verifies/src）；无重大事项则明确回传「已检查，无重大期后事项」。
② 同业：用 mx 工具取【所属申万行业】3~5 家可比公司同报告期关键指标
（收入/归母净利/毛利率/净利率/周转率/权益乘数/ROE——v0.0.15 起扩杜邦四列），
落 `peers` 块（src=取数接口+日期必填），注明币种与会计准则差异。
③ 机构预期：券商一致预期/目标价（若有，压缩表回传即可）。
落盘骨架：`{"notes": {"subsequent_events": […]}, "peers": […]}`
