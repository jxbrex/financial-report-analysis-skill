# 数据契约 extraction-schema（data.json）

> Phase 1 起，所有从报告中提取的数字**必须**写入 `reports/{公司}-{代码}-{类型}-{期}.json`；
> Phase 7.5 由 `scripts/calc.py` 机械校验；Phase 8 写报告时**数字只允许从 data.json 流入
> HTML，禁止对着 md 原文直读直写**。这是防幻觉的结构性约束：原文→JSON（可校验）→HTML。

## 一、单位与命名约定

- **统一单位：亿元**（`meta.unit` 固定 `亿元`）。原文是元/万元/百万元的，提取时即换算，
  `note` 里写明原始口径（如 `"原文：168,838,102,514.79 元"`）
- 比率统一用**小数**（毛利率 0.9118，不写 91.18）；百分数呈现是 HTML 层的事
- 增速用小数（0.15 = +15%）
- 日期用 `YYYY-MM-DD`；报告期用 `YYYYMMDD`
- 金额允许 `null` = 报告未披露；**禁止用 0 或编造值占位**

## 二、叶子结构（Metric）

绝大多数数值字段用同一结构：

```json
{ "cur": 1688.38, "prev": 1708.99, "hist": [1476.94, 1708.99, 1688.38],
  "level": "disc", "src": "L131 主要会计数据表", "note": "原文：168,838,102,514.79 元" }
```

| 键 | 含义 | 规则 |
|---|---|---|
| `cur` | 本期值（亿元） | 必填，未披露填 null |
| `prev` | 上期值 | 同上；招股书=上一完整年度 |
| `hist` | 多期数组，**旧→新** | 选填；趋势图与 P1-13 五期分析消费，缺省至少 3 期。趋势科目（见三）hist 深度 5 期，同类型滚动：年报对 FY、半年报对 H1；末位=cur |
| `hist_ye` | 各年 **12-31 年末**序列，**旧→新** | 选填，**仅半年报**给 balance 的 ar/inventory/payable/total_assets 填（平均余额比率的期初口径）；长度=hist，hist_ye[i]=第 i 期 H1 的上年末（12-31），末位=prev。年报不填（期初=hist 前一期天然正确）；缺此字段时 calc 退化为 hist 前一期（窗口错配，趋势不做） |
| `level` | **证据等级**：`disc` 披露 / `der` 推算 / `est` 估算 | P2-19：报告中的关键数字必须带对应徽章；`disc`=主表或附注直接披露，`der`=由两个以上披露值运算得到，`est`=含假设的测算。缺省视为 `disc` |
| `src` | 出处：行号或「章节名+表名」 | **必填**，calc.py 校验非空 |
| `note` | 原始口径/换算说明/异常备注 | 选填；`est` 必须在此写明假设 |

## 三、完整骨架

```json
{
  "meta": {
    "company": "贵州茅台", "code": "600519.SH", "market": "A股",
    "period": "20251231", "report_type": "年报", "disclose_date": "2026-04-16",
    "unit": "亿元", "source_md": "reports/xxx.md", "analyst_date": "2026-09-10",
    "market_cap_cur": null,
    "schema_version": "1.3",
    "currency": "CNY",
    "accounting_standard": "CAS",
    "industry_profile": "通用",
    "cycle_stage": null
  },

  "statements": {
    "income": {
      "revenue":      { "cur": null, "prev": null, "hist": [], "src": "" },
      "cost":         { "cur": null, "prev": null, "hist": [], "src": "" },
      "gross_profit": { "cur": null, "prev": null, "src": "", "note": "可由 revenue-cost 推算，填 derived" },
      "tax_surcharge":{ "cur": null, "prev": null, "src": "" },
      "sell_exp":     { "cur": null, "prev": null, "src": "" },
      "admin_exp":    { "cur": null, "prev": null, "src": "" },
      "rd_exp":       { "cur": null, "prev": null, "src": "" },
      "fin_exp":      { "cur": null, "prev": null, "src": "", "note": "可为负" },
      "interest_exp": { "cur": null, "prev": null, "src": "", "note": "财务费用附注中的利息支出" },
      "interest_inc": { "cur": null, "prev": null, "src": "", "note": "财务费用附注中的利息收入（redflags #2 利息收入与货币资金匹配用；A7 隐含利率取利息支出）" },
      "impair_loss":  { "cur": null, "prev": null, "src": "", "note": "资产+信用减值合计" },
      "invest_income":{ "cur": null, "prev": null, "src": "", "note": "投资收益（X33 非主业收入占比分子之一）" },
      "fv_change_income": { "cur": null, "prev": null, "src": "", "note": "公允价值变动收益（X33 分子之一）" },
      "non_op_income":{ "cur": null, "prev": null, "src": "", "note": "营业外收入毛额（X33 分子之一；与 non_op_net 收支净额并存，勿混）" },
      "other_biz_income": { "cur": null, "prev": null, "src": "", "note": "其他业务收入（附注口径，利润表未单列填 null；X33 复算时 null 按 0 计）" },
      "non_op_net":   { "cur": null, "prev": null, "src": "" },
      "np_total":     { "cur": null, "prev": null, "src": "", "note": "净利润（含少数股东）——OCF 调节桥起点" },
      "np_at":        { "cur": null, "prev": null, "hist": [], "src": "", "note": "归母净利" },
      "np_dt":        { "cur": null, "prev": null, "src": "", "note": "扣非归母" },
      "minority_np":  { "cur": null, "prev": null, "src": "" },
      "income_tax":   { "cur": null, "prev": null, "src": "" },
      "by_segment": [
        { "name": "茅台酒", "basis": "product", "rev_cur": null, "rev_prev": null, "cost_cur": null, "cost_prev": null,
          "vol_cur": null, "vol_prev": null, "vol_unit": "吨", "price_cur": null, "price_prev": null,
          "price_unit": "万元/吨", "intercompany_eliminated": null, "src": "" }
      ]
    },
    "balance": {
      "cash":             { "cur": null, "prev": null, "src": "" },
      "restricted_cash":  { "cur": null, "prev": null, "src": "", "note": "货币资金附注受限明细合计" },
      "ar":               { "cur": null, "prev": null, "hist": [], "hist_ye": [], "src": "", "note": "应收账款" },
      "ar_notes":         { "cur": null, "prev": null, "src": "", "note": "应收票据+应收款项融资" },
      "other_ar":         { "cur": null, "prev": null, "src": "", "note": "其他应收款" },
      "inventory":        { "cur": null, "prev": null, "hist": [], "hist_ye": [], "src": "" },
      "contract_liab":    { "cur": null, "prev": null, "src": "" },
      "payable":          { "cur": null, "prev": null, "hist": [], "hist_ye": [], "src": "", "note": "应付账款+应付票据（DPO/CCC 计算必需；先款后货型公司可为 0）" },
      "fixed_assets":     { "cur": null, "prev": null, "src": "", "note": "固定资产净值（A6 Capex 勾稽用）" },
      "cip":              { "cur": null, "prev": null, "src": "", "note": "在建工程" },
      "goodwill":         { "cur": null, "prev": null, "src": "" },
      "st_debt":          { "cur": null, "prev": null, "src": "", "note": "短期借款" },
      "noncur_due_1y":    { "cur": null, "prev": null, "src": "", "note": "一年内到期非流动负债" },
      "lt_debt":          { "cur": null, "prev": null, "src": "", "note": "长期借款+应付债券+租赁负债" },
      "total_assets":     { "cur": null, "prev": null, "hist": [], "hist_ye": [], "src": "" },
      "total_liab":       { "cur": null, "prev": null, "hist": [], "src": "" },
      "equity_at":        { "cur": null, "prev": null, "hist": [], "src": "", "note": "归母净资产" },
      "minority_eq":      { "cur": null, "prev": null, "src": "" },
      "retained_cur":     { "cur": null, "prev": null, "src": "", "note": "未分配利润（A2 滚动勾稽）" },
      "surplus_reserve":  { "cur": null, "prev": null, "src": "", "note": "盈余公积（A2 用其本期提取额）" },
      "dividend_paid":    { "cur": null, "prev": null, "src": "", "note": "本年实际分配现金股利（归母股东口径）=「分配股利、利润或偿付利息支付的现金」− 利息实付（interest_paid）− 子公司支付给少数股东的股利；拆分不可得时置 null 并在 note 声明（v1.4 起支撑内生增长率）" },
      "prepayment":       { "cur": null, "prev": null, "src": "", "note": "预付款项（采购侧资产；A4 收入-收现闭环不用此项，相关的是预收/合同负债）" },
      "fin_assets":       { "cur": null, "prev": null, "src": "", "note": "交易性金融资产+长期股权投资+其他非流动金融资产（A8 用）" },
      "payable_construction": { "cur": null, "prev": null, "src": "", "note": "应付工程设备款（A6 用，常未单列，可 null）" },
      "total_cur_assets": { "cur": null, "prev": null, "src": "", "note": "流动资产合计（Altman X1 / Ohlson 营运资金用；v1.2）" },
      "total_cur_liab":   { "cur": null, "prev": null, "src": "", "note": "流动负债合计（Altman X1 / Ohlson 用；v1.2）" }
    },
    "cashflow": {
      "ocf":         { "cur": null, "prev": null, "hist": [], "src": "" },
      "sales_cash":  { "cur": null, "prev": null, "src": "", "note": "销售商品提供劳务收到的现金" },
      "capex":       { "cur": null, "prev": null, "hist": [], "src": "", "note": "购建固定资产等支付的现金" },
      "dep_amort":   { "cur": null, "prev": null, "src": "", "note": "折旧+摊销（补充资料）" },
      "wage_cash":   { "cur": null, "prev": null, "src": "", "note": "支付给职工的现金（人效三维）" },
      "interest_paid": { "cur": null, "prev": null, "src": "", "note": "分配股利利润或偿付利息支付的现金中的利息部分" }
    }
  },

  "parent_statements": {
    "_": "母公司单体报表关键科目（articulation.md D 组勾稽用；与 statements 合并口径并列，src 注明母公司报表页码；未做 D 组分析时整块可缺省）",
    "cash":         { "cur": null, "prev": null, "src": "", "note": "母公司货币资金（D1：÷合并货币资金，长期 <10% 且集团现金充裕 → 资金沉淀子公司）" },
    "retained_cur": { "cur": null, "prev": null, "src": "", "note": "母公司未分配利润（D2：不足以覆盖拟分红 → 分红能力受子公司制约）" },
    "other_ar":     { "cur": null, "prev": null, "src": "", "note": "母公司其他应收款（D3：占合并大头 → 内部往来资金池）" },
    "invest_income":{ "cur": null, "prev": null, "src": "", "note": "母公司投资收益（D4：÷母公司净利润占比高 → 纯控股平台）" },
    "ocf":          { "cur": null, "prev": null, "src": "", "note": "母公司经营现金流净额（D5：常年为负而合并为正 → 靠子公司分红/借款维持）" },
    "np_total":     { "cur": null, "prev": null, "src": "", "note": "母公司净利润（D4 分母）" }
  },

  "notes": {
    "ar_aging": [
      { "bucket": "1年以内", "cur": null, "prev": null, "prov_rate_cur": null, "prov_rate_prev": null, "src": "" }
    ],
    "ar_writeoff":   { "cur": null, "src": "", "note": "本年实际核销额" },
    "ar_provision":  { "cur": null, "prev": null, "charged": null, "reversed": null, "src": "",
                       "note": "cur/prev=坏账准备余额；charged=本期计提额、reversed=本期转回额（B1 核销率判定「核销>当年计提」必需；倒挤：charged = Δ余额 + 核销 + 转回）" },
    "ar_factoring":  { "cur": null, "src": "", "note": "保理/证券化出表金额" },
    "inventory_mix": [
      { "name": "原材料", "cur": null, "prev": null, "src": "" },
      { "name": "在产品", "cur": null, "prev": null, "src": "" },
      { "name": "库存商品", "cur": null, "prev": null, "src": "" }
    ],
    "inventory_provision": { "cur": null, "prev": null, "cur_reversed": null, "src": "",
                             "note": "cur_reversed=本期转回额（大额转回=黄色信号）" },
    "cip_projects": [
      { "name": "", "budget": null, "invested_cur": null, "progress": null, "transferred": null,
        "src": "", "note": "transferred=本年转固额" }
    ],
    "goodwill_test": { "growth_assumption": "", "discount_rate": "", "src": "" },
    "audit": { "opinion": "标准无保留", "kam": [ { "topic": "", "mapped_accounts": [], "src": "" } ],
               "fee_cur": null, "fee_prev": null, "auditor_changed": false, "src": "" },
    "employees": { "headcount_cur": null, "headcount_prev": null, "src": "" },
    "subsequent_events": [ { "date": "", "event": "", "verifies": "", "src": "" } ],
    "shareholders": { "holder_num_cur": null, "holder_num_prev": null, "top10_changes": [],
                      "pledge_ratio": null, "src": "" },
    "capacity": [ { "product": "", "capacity": null, "output": null, "utilization": null, "src": "" } ]
  },

  "peers": [
    { "name": "同业A", "code": "", "gross_margin": null, "rd_ratio": null, "debt_to_assets": null,
      "net_margin": null, "asset_turnover": null, "equity_multiplier": null, "roe": null, "src": "" }
  ],

  "derived": {
    "ratios": {
      "roe": { "cur": null, "prev": null, "hist": [] }, "gross_margin": { "cur": null, "prev": null, "hist": [] },
      "net_margin": { "cur": null, "prev": null, "hist": [] }, "net_cash_ratio": { "cur": null, "prev": null, "hist": [] },
      "cash_to_sales": { "cur": null, "prev": null, "hist": [] }, "debt_to_assets": { "cur": null, "prev": null, "hist": [] },
      "asset_turnover": { "cur": null, "prev": null, "hist": [] }, "equity_multiplier": { "cur": null, "prev": null, "hist": [] },
      "dso": { "cur": null, "prev": null, "hist": [] }, "dio": { "cur": null, "prev": null, "hist": [] },
      "dpo": { "cur": null, "prev": null, "hist": [] }, "ccc": { "cur": null, "prev": null, "hist": [] },
      "dfl": { "cur": null, "prev": null, "hist": [], "note": "财务杠杆=(np_total+income_tax+fin_exp)÷(np_total+income_tax)，即 EBIT÷税前利润（X72）" },
      "dol": { "cur": null, "prev": null, "hist": [], "note": "经营杠杆=(EBIT+dep_amort)÷EBIT，即 EBITDA÷EBIT（X71）；高=固定成本重，收入小降利润大降" },
      "short_debt_cover": { "cur": null },
      "incr_expense_eff": { "cur": null, "note": "Δ毛利÷Δ期间费用" },
      "incr_sales_eff":   { "cur": null, "note": "Δ收入÷Δ销售费用" },
      "nonrecurring_share": { "cur": null, "note": "非经÷归母净利" },
      "non_main_rev_share": { "cur": null, "note": "(营业外收入+其他业务收入+投资收益+公允价值变动)÷营业收入（X33 收入结构口径；与 nonrecurring_share 的利润调整口径不同源，勿混）" },
      "ocf_to_liab": { "cur": null, "note": "OCF÷平均总负债（X6）；人话：照现在的造血能力，还清全部负债 ≈ 1/x 年" },
      "roic": { "cur": null, "note": "v1.4 投入资本回报率=NOPAT÷平均投入资本（有息负债+归母权益，期初取 prev；有息=null 按 0、全 null 才整块 null）：NOPAT=EBIT×(1−有效税率)，EBT≤0 时有效税率按 0（亏损期无税盾）；期间口径不年化（同 ROE 约定）；去杠杆口径——与含杠杆的 ROE 并列读，ROE−ROIC 差值大=回报靠杠杆撑；单期指标（上期需 T-2 投入资本，不可得）" },
      "sustainable_growth": { "cur": null, "note": "v1.4 内生增长率=留存率×ROE（留存率=1−dividend_paid÷np_at）：成长质量的可持续性读数——不依赖外部融资时利润能支撑的增速；np_at≤0 或 dividend_paid 未提取时置 null（亏损期符号无解读意义）" }
    },
    "dupont": { "driver": "净利率|周转率|杠杆", "margin_effect": null, "turnover_effect": null,
                "leverage_effect": null, "roe_product_cur": null, "roe_product_prev": null,
                "closure_gap": null, "driver_fragile": null, "effects_ratio": null,
                "driver_second": null,
                "margin_drill": { "op_effect": null, "tax_effect": null,
                                  "interest_effect": null, "minority_effect": null },
                "turnover_drill": { "top1_subject": "", "top1_share": null,
                                    "top2_subject": "", "top2_share": null,
                                    "wc_share": null, "capex_share": null },
                "leverage_drill": { "ib_cur": null, "ib_prev": null, "ni_cur": null, "ni_prev": null,
                                    "ib_to_equity_cur": null, "ni_to_equity_cur": null,
                                    "ni_share": null, "dfl_delta": null, "quality_upgrade": null },
                "src": "",
                "note": "连环替代（定序：净利率→周转率→权益乘数），三效应加和恒等于三因子积的 Δ；closure_gap = ΔROE摊薄 − Δ三因子积（周转率平均余额口径 vs ROE 期末口径之差），报告 srcline 如实标注；缺同口径上期（口径断裂）整块 null。"
                        "v1.3 因子下钻（子行只放证据，判断在 figtitle/takeaway）："
                        "margin_drill=净利率恒等四项分解 op/tax/interest/minority（ΔEBIT率 −Δ财务费用率 −Δ有效税负率 −Δ少数股东率，加和恒等于 Δ净利率）；"
                        "turnover_drill=Δ总资产科目贡献前二 + 聚合份额（wc_share=Δ应收类+Δ存货 ÷ Δ总资产，capex_share=Δ在建+Δ固定资产 ÷ Δ总资产；|ΔTA|/TA<1% 时整块 null=总资产未动，定位无意义；不含其他应付款等未提取科目，口径声明在报告 srcline）；"
                        "leverage_drill=有息 ib=st_debt+noncur_due_1y+lt_debt（null 按 0 计，三字段全 null 才整块 null）/ 无息 ni=payable+contract_liab（同规则；不含其他应付款）；"
                        "quality_upgrade=话语权型杠杆升档判定：杠杆为主驱动且 ni_share>0.7 且 |dfl_delta|<0.1 → true，杠杆非主驱动时 null（不适用）——阈值为 v0.0.15 经验起点，随样本校准，只触发提醒级呈现；"
                        "driver_fragile=双驱动护栏：第一、二大 |效应| 之比 effects_ratio<1.5 → true，报告标「双驱动（X/Y）」替代单一主驱动" },
    "dupont_dt": { "driver": null, "margin_effect": null, "turnover_effect": null,
                   "leverage_effect": null, "roe_product_cur": null, "roe_product_prev": null,
                   "closure_gap": null, "triggered": null, "src": "",
                   "note": "v1.3 扣非口径双版归因（F-04）：扣非净利率（np_dt÷revenue）替换净利率因子重跑连环替代；"
                           "触发条件 nonrecurring_share>0.2 或 |净利率−扣非净利率|>0.01——未触发时 triggered=false 其余 null（不占版面）；"
                           "触发时全字段机械可复算（roe 两版同口径摊薄值，closure_gap 同 dupont 语义）" },
    "dupont5y": { "margin_effect": null, "turnover_effect": null, "leverage_effect": null,
                  "roe_start": null, "roe_end": null, "closure_gap": null,
                  "driver": null, "driver_fragile": null, "effects_ratio": null,
                  "driver_second": null,
                  "period_start": "", "period_end": "",
                  "percentile": { "net_margin": null, "asset_turnover": null, "equity_multiplier": null },
                  "src": "",
                  "note": "v1.3 五年累计归因（方案A）+ 因子分位（方案D）：ratios hist 首末两期端点间一次连环替代，定序与 dupont 一致；"
                          "period_start/end 由 meta.period 与 report_type 按同类型滚动倒推（年报对 FY、半年报对 H1）；"
                          "percentile=(rank(cur,hist)−1)÷(len(hist)−1)，n=5 为位置读数（离散步长 25%），呈现禁用统计显著性措辞、周期股须挂周期定位解读；"
                          "hist<3 期整块 null（口径断裂合法，报告降级两期归因）" },
    "cycle_evidence": { "rev_growth": [], "gross_margin": [], "capex_growth": [], "periods": [],
                        "src": "",
                        "note": "v1.3 周期定位证据读数（frameworks.md 第六节）：收入增速/毛利率/Capex 增速逐期序列（旧→新，与 ratios hist 对齐），"
                                "让 meta.cycle_stage 的阶段判定从「声明」变「可核验前提」；本块只供读数，stage 判定仍是分析师判断（填 meta.cycle_stage）；"
                                "hist<2 期（增速不可算）整块 null" },
    "threshold_check": {
      "shell_line":     { "roe": null, "target": 0.065, "net_margin": null, "hit": null },
      "refinance_line": { "roe": null, "target": 0.10, "hit": null },
      "incentive_line": { "target_desc": "", "actual": null, "target": null, "ratio": null,
                          "share_payment": null, "hit": null, "src": "" },
      "note": "v1.3 四线考核贴线检测（frameworks.md 第八节）：保壳线=ROE 贴 6.5% 且净利率落 0~3% 收入区间；"
              "再融资线=ROE 贴 10%；贴线=实际÷目标 ∈ [0.95,1.05]；incentive_line 的 target 取自股权激励公告"
              "（src 必填，mx_finance_search_notice 查「股权激励计划/考核目标/行权条件」），share_payment=本期股份支付摊销"
              "（激励压低当期利润的读数参考，未披露填 null）；无激励计划时 incentive_line 全 null。"
              "Q4 集中度见 derived.q4，本块不重复" },
    "risk_models": { "altman_z": { "cur": null, "zone": null, "annualized": null },
                     "ohlson_o": { "cur": null, "prob": null, "level": null },
                     "note": "v1.2 破产风险双模型并列（frameworks.md 第三节，谨慎使用、金融/地产跳过置 null）；市值取 meta.market_cap_cur（亿元），缺失时 altman_z 整块 null——宁可空值不给错值；interim 报告 annualized=true（流量项按〇口径总则年化）" },
    "stress": { "scenarios": [ { "p": 0.1, "np_stressed": null, "cover_stressed": null },
                               { "p": 0.2, "np_stressed": null, "cover_stressed": null },
                               { "p": 0.3, "np_stressed": null, "cover_stressed": null } ],
                "note": "v1.2 流动性压力情景（frameworks.md 第九节）：受压EBIT=EBIT×(1−p×DOL)，受压税前=受压EBIT−fin_exp，受压净利=受压税前×(1−有效税率)，受压短债覆盖=(cash+ocf×(1−p))÷(st_debt+noncur_due_1y)；est 估算口径，不进 T8①" },
    "cash_ts": { "ncr_mean5": null, "ncr_neg_years": null, "fcf_to_np_mean5": null, "fcf_neg_years": null,
                 "ncr": [], "fcf_to_np": [], "periods": [],
                 "note": "v1.2 现金验证时序读数（frameworks.md 第五节）：净现比与 FCF=OCF−capex 的 5 期均值/负值年数，分母用归母净利 np_at；"
                         "v1.3 扩逐期数组 ncr/fcf_to_np/periods（S1 现金时序表数据源，旧→新与 ratios hist 对齐；"
                         "fcf_to_np 需 capex hist ≥3 期，不足则整块为空数组——不足 3 期的逐期读数无趋势意义，不凑数）；"
                         "hist <3 期整块 null（口径断裂合法）" },
    "q4": { "rev": null, "np": null, "rev_share": null, "gm_q4": null, "gm_q1q3": null,
            "impair_share": null, "exp_ratio_q4": null, "exp_ratio_q1q3": null, "src": "" },
    "rev_factors": { "volume": null, "price": null, "mix": null, "src": "",
                     "note": "三效应，单位亿元；之和必须=Δ收入" },
    "np_bridge": [ { "item": "毛利", "delta": null }, { "item": "税金及附加", "delta": null },
                   { "item": "期间费用", "delta": null }, { "item": "减值", "delta": null },
                   { "item": "投资/公允", "delta": null }, { "item": "非经", "delta": null },
                   { "item": "所得税", "delta": null }, { "item": "少数股东", "delta": null } ],
    "ocf_bridge": [ { "item": "净利润", "delta": null }, { "item": "折旧摊销", "delta": null },
                    { "item": "减值", "delta": null }, { "item": "递延税", "delta": null },
                    { "item": "Δ应收", "delta": null }, { "item": "Δ存货", "delta": null },
                    { "item": "Δ应付", "delta": null }, { "item": "其他营运资本", "delta": null } ],
    "wc_devour": { "amount": null, "share_of_np": null, "note": "营运资本吞噬额（正数=被吞掉的金额）；share_of_np 分母用净利润（含少数股东，与调节桥起点自洽）；跨到 redflags #3 净现比时该条用归母口径，差异如实标注" },
    "interest_arrears": { "cur": null, "note": "应付未付利息 = 利息费用 − 现金流量表实际付息（A7 副算，P1-15）；连续 2 年为正且上升 = 资金链先行信号" }
  },

  "recon": {
    "A1_cash":        { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "A2_retained":    { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "A3_indirect":    { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "A4_rev_cash":    { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "A5_dep_amort":   { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "A6_capex":       { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "A7_implied_rate":{ "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "A8_invest_income":{ "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "B1_ar_roll":     { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "B2_inv_roll":    { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "B3_cip_roll":    { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "B4_goodwill_roll":{ "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "D1_parent_cash": { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "D2_parent_retained": { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "D3_parent_other_ar": { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "D4_parent_invest": { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" },
    "D5_parent_ocf":  { "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" }
  },

  "assertions": [
    { "id": "A1", "text": "管理层断言原文（如：收入下降主要系系列酒结构调整）",
      "account": "涉及科目", "verdict": "通过",
      "evidence": "数字检验结论（判「不成立」时必填反证）", "missing": "判「无法验证」时必填缺什么数据",
      "source": "MD&A 章节/行号" }
  ],

  "signals": [
    { "id": "R1", "level": "r", "verdict": "命中", "type": "signal", "title": "存贷双高",
      "data": "货币资金/总资产=x% 且 有息负债/总资产=y%",
      "concern": "一边囤现金一边付高息借钱——最可能是资金受限/被归集/虚构",
      "evidence": "原文引用", "source": "资产负债表+货币资金附注" },
    { "id": "R2", "level": "g", "verdict": "反向未触发", "type": "signal", "title": "非经常性损益撑利润",
      "data": "扣非/归母 = 118%，非经为反向拖累", "evidence": "…", "source": "非经常性损益表" }
  ],

  "watchlist": [
    { "indicator": "合同负债增速 vs 收入增速（剪刀差）", "current": "合同负债 -12% vs 收入 +8%",
      "tripwire": "若合同负债增速连续两期低于收入增速，则需求端走弱成立",
      "upper": "-5%", "upper_meaning": "高于 -5% 则打款意愿修复",
      "lower": "-20%", "lower_meaning": "跌破 -20% 则需求走弱确认",
      "source": "资产负债表「合同负债」及其上期数", "badge": "der",
      "review": { "verdict": null, "actual": null, "attribution": null } }
  ]
}
```

**`source_md` 契约（v0.0.13）**：新报告指向 `scripts/md_clean.py` 产出的
`{stem}.clean.md`（唯一工作副本；T8② 行号回核对其执行）；v0.0.13 前的存量 json 仍指
原始 md——快照不回改，两种文件在 `reports/archive/原始报告/` 共存。

**趋势比率 hist 规则**（三、derived.ratios 骨架）：
- 14 个趋势比率（roe/gross_margin/net_margin/net_cash_ratio/cash_to_sales/debt_to_assets/
  asset_turnover/equity_multiplier/dso/dio/dpo/ccc/dfl/dol）hist 为 **5 期同类型滚动**（年报对 FY、
  半年报对 H1），旧→新；**末位必须等于 cur**（报告提取值）；prev = 倒数第 2 期
- avg 类比率（asset_turnover/dso/dio/dpo/ccc）首期无期初余额不可机复算，由 calc.py 跳过；
  **期初一律取「该期所在年度的上一年 12-31」**（平均余额窗口必须与收入期间匹配）——
  年报期初=hist 前一期（天然满足）；半年报期初=hist_ye 同位元素（hist_ye[i]=第 i 期 H1 的上年末），
  缺 hist_ye 时退化为 hist 前一期（期初=上年 6-30，窗口错配，该期趋势不做）
- 历史重述（如康得新 2019 追溯重述）致口径断裂时允许缺 hist 并在 note 说明，
  报告趋势降级两期呈现
- 单期专用比率（short_debt_cover/incr_expense_eff/incr_sales_eff/nonrecurring_share/non_main_rev_share/ocf_to_liab）不序列化

**`peers[]` 字段说明**（v1.3，S7 同业表数据源）：
- 同业数字同样**禁止只进 HTML 不进 JSON**——T8① 数字回验覆盖 S7 表格
- 取数：`mx_ashare_finance_data` 批量指标（3~5 家同业，SKILL.md 取数清单）；比率用小数，
  口径尽量与本公司一致（净利率归母、ROE 摊薄），口径不可对齐的在报告 srcline 声明
- `src` 必填（取数接口+日期）；calc.py 只做结构校验（src 非空 FAIL、比率超合理区间 WARN），
  外部取数无公式可复算，真伪靠双源核对纪律

**`signals[]` 字段说明**：
- `verdict ∈ 命中/观察/未触发/反向未触发`（**呈现四态**，判定标准见 redflags.md 第一节课后「判定分类」）；
  `level ∈ g/y/r`（**严重度**，用于计数与排序）。两者对应：命中→`r`、观察→`y`、
  未触发→`g`、反向未触发→`g`（不是风险，但含信息量）。报告正文按四态分层呈现（v0.2.0 起）：
  命中逐条展开；观察两行形态（担心→本案）、上限 6 条（v0.0.7 起，取代单行 ≤30 字）；
  反向未触发不再有可见行，与未触发一并压入表末 total 汇总行（四计数 + data.json signals 块指引）
- `concern`（v0.0.7，**选填不 FAIL**，calc.py 不校验）：一句话「担心什么」——三问①
  （这信号若是真雷，经营上意味着什么），供报告 s2「担心 → 本案」列的「担心」半行；
  `evidence` 对应「本案」半行。观察/命中条目应填
- `severity`（v1.2，**选填，试点期仅 #4 应收/#5 存货两条信号填**）：0~1 连续严重度，
  `min(1, (实际超幅 − 阈值) ÷ 参考窗)`（参考窗 40pct，见 redflags.md 〇节）；只用于
  观察行排序 / 汇总行措辞 / watchlist 优先级，**禁止加总总分**；calc.py 校验 ∈[0,1]
- `type ∈ signal/assertion`（`signal` = 财务信号；`assertion` = MD&A 断言不实，
  见 text-mining.md 第七节）
- ⚠️ redflags.md 使用纪律第 2 条「红色信号 ≥2 条即提示财务真实性风险聚集」**只统计
  `type=signal`** 的红色条目——归因不实与财务真实性是两类问题，不可混计。`type` 缺省视为 `signal`；
  `verdict` 缺省按 `level` 反推（r→命中 / y→观察 / g→未触发）。

**`watchlist[]` 字段说明**（P2-18 下期跟踪清单落库）：
- `indicator`：先行指标名，取自 industry-profiles.md 中该 `meta.industry_profile` 模式的
  「先行指标建议集」（3~5 项）；无法归类时用通用缺省集并在报告声明理由
- `current`：当前读数（字符串，含单位与期次）
- `tripwire`：**条件化触发线，必须是 if-then 形态**（「若 X 连续两期……则 Y 成立」），
  **禁止无条件预测**——方向性判断的合法形态见 SKILL.md「何时不用」
- `upper` / `upper_meaning` / `lower` / `lower_meaning`（T5，**选填但至少给一侧**）：
  上下阈值带，形态 `毛利率 45.2% → >46% 证实提价逻辑 / <43% 成本承压`；阈值必须有依据
  （历史中枢 / 同业水平 / 管理层指引），依据写进 `source` 或 `note`；确实无法数字化阈值的
  指标允许只保留 `tripwire` 的 if-then 句式
- `source`：数据来源；`badge ∈ disc/der/est`：读数证据等级，与报告徽章一致
- 下期回看（SKILL.md Phase 0 第 5 条）直接消费本块，逐条核对 `tripwire` 是否触发

**`review` 子块（T6 冻结/归档语义）**：
- **产出后 watchlist 原字段（`indicator/current/tripwire/upper/lower`）只读、禁止回改**——
  预测登记不得事后改写；回看结果**只追加** `review` 子块
- `verdict ∈ 兑现/未兑现/待观察`（对应回顾章 ✅/❌/⏳）；`actual`：下期实际读数
  （含单位与期次）；`attribution`：**未兑现必填**误差归因——`假设错 / 时点错 / 口径错`
  （可组合，须附一句依据）
- 回看报告「上期跟踪回顾」章第一列必须**照抄原 `tripwire` 原文**，禁止美化改写

**`assertions[]` 字段说明**（P1-12 断言验证表落库）：
`verdict ∈ 通过/不成立/无法验证`；判「不成立」**必须**填 `evidence`（反证数字）；
判「无法验证」**必须**填 `missing`（缺什么数据）。calc.py 会机械校验这三条规则。
判「不成立」的断言应同时在 `signals` 落一条 `type=assertion` 的条目。

## 四、recon 块的填写规则（配合 articulation.md）

- `lhs`/`rhs`：等式两边的计算值（亿元），**calc.py 会重算偏差**
- `verdict`：三态之一 `闭合` / `可解释` / `无法解释`
- `explanation`：非「闭合」时必填，写合理解释或风险定性
- calc.py 判定逻辑：偏差率 ≤ 阈值 → verdict 必须是 `闭合`；超阈值且 verdict=`闭合` → **FAIL**
  （防止「算出来不平却硬说平」）；超阈值且 verdict=`无法解释` → 自动要求 signals 里有对应条目

**D 组（D1–D5，母公司单体勾稽）是 manual 型**，calc.py **只做结构校验**
（verdict 合法 / 非「闭合」必填 explanation / src 非空），**不做机械方向判定**——
D 组判定是语境合取（如 D1 须同时满足「占比低 + 集团现金充裕 + 分红/偿付受限」），
机械阈值会误报财务公司归集、销售公司集中收款等正常模式。lhs/rhs 填写约定：

| key | lhs | rhs（参考基准） |
|---|---|---|
| D1_parent_cash | 母公司货币资金 ÷ 合并货币资金 | 0.10 |
| D2_parent_retained | 母公司未分配利润（亿元） | 本年拟分红额（亿元） |
| D3_parent_other_ar | 母公司其他应收款 ÷ 合并其他应收款 | 0.50 |
| D4_parent_invest | 母公司投资收益 ÷ 母公司净利润 | 0.50 |
| D5_parent_ocf | 母公司经营现金流净额（亿元） | 0 |

verdict 由分析师按 articulation.md D 组判读规则综合给出；命中须在 signals 落对应条目。

## 五、字段级提取锚点速查

| 字段 | md 中 Grep 锚点 | tushare 对照 |
|---|---|---|
| revenue | `营业收入`（主要会计数据表） | `income.total_revenue`（注意：total_revenue 含利息收入等，白酒等纯销售型两者≈相等） |
| np_at | `归属于上市公司股东的净利润` | `income.n_income_attr_p` |
| np_total | `净利润`（利润表倒数第三行） | `income.n_income` |
| ocf | `经营活动产生的现金流量净额` | `cashflow.n_cashflow_act` |
| sales_cash | `销售商品、提供劳务收到的现金` | `cashflow.c_fr_sale_sg` |
| capex | `购建固定资产、无形资产和其他长期资产支付的现金` | `cashflow.c_pay_acq_const_fiolta` |
| dep_amort | `固定资产折旧`/`补充资料` | `cashflow.prov_depr_assets`+`amort_intang_assets` |
| cash | `货币资金` | `balancesheet.money_cap` |
| restricted_cash | `使用受限`/`受限`（货币资金附注） | 无——只能来自原文 |
| ar | `应收账款` | `balancesheet.accounts_receiv` |
| total_assets | `资产总计` | `balancesheet.total_assets` |
| total_liab | `负债合计` | `balancesheet.total_liab` |
| equity_at | `归属于上市公司股东的所有者权益` | `balancesheet.total_hldr_eqy_exc_min_int` |
| payable | `应付账款`（+应付票据） | `balancesheet.acct_payable` |
| cost | `营业成本` | `income.oper_cost` |
| inventory | `存货` | `balancesheet.inventories` |
| cip | `在建工程` | `balancesheet.cip` |
| contract_liab | `合同负债` | `balancesheet.contract_liab` |
| st_debt | `短期借款` | `balancesheet.st_borr` |
| lt_debt | `长期借款`+`应付债券` | `balancesheet.lt_borr`+`st_bonds_payable` |
| retained | `未分配利润` | `balancesheet.undistr_porfit` |
| rd_exp | `研发投入`（MD&A 专节，注意含资本化） | `income.rd_exp`（仅费用化部分） |
| ar_aging | `应收账款`附注内`账龄` | 无——只能来自原文 |
| inventory_mix | `存货`附注内`原材料`/`在产品`/`库存商品` | 无——只能来自原文 |
| fv_change_income | `公允价值变动收益`（利润表） | `income.fv_value_chg_gain` |
| non_op_income | `营业外收入`（利润表） | `income.non_oper_income` |
| other_biz_income | `营业收入`附注内`其他业务收入` | 无直接对照——附注口径 |
| parent_statements.* | `母公司资产负债表`/`母公司利润表`/`母公司现金流量表` | 无——只能来自原文 |
| kam | `关键审计事项` | 无——只能来自原文 |
| total_cur_assets | `流动资产合计`（合并资产负债表） | `balancesheet.total_cur_assets` |
| total_cur_liab | `流动负债合计`（合并资产负债表） | `balancesheet.total_cur_liab` |
| market_cap_cur | 无——行情数据 | `daily_basic.total_mv`（万元，**÷1e4 转亿元**后填入） |

## 六、常见坑（血泪清单）

1. **单位**：报表附注常用「万元」，主表用「元」，MD&A 常用「亿元」——每提取一个数先看表头单位
2. **含税口径**：收现比分子含增值税销项，正常值 ≈1.13×收入（一般纳税人），不要按 1.0 判异常
3. **研发费用两处披露**：利润表 `研发费用`（费用化）≠ MD&A「研发投入合计」（含资本化），
   两者都要进 JSON（`rd_exp` + `note` 里记资本化率）
4. **财务公司为负的「有息负债」**：吸收存款及同业存放是经营负债，不进 lt_debt/st_debt（茅台案例）
5. **少数股东**：OCF 调节桥起点是 `np_total`（含少数股东），净利桥终点是 `np_at`——两桥起点不同，别混
6. **hist 顺序**：旧→新。趋势图直接消费，反了图就反了
7. **历史重述断口径**：康得新 2019 年追溯重述后，公开库（tushare）2014–2017 为重述值、
   当年年报对比列为原始值，两者不可混用拼接趋势；遇此情况趋势比率缺 hist 是正当状态，
   note 写明，不得混口径
8. **non_main_rev_share 的 null 口径**：四个分子字段（non_op_income/other_biz_income/
   invest_income/fv_change_income）逐字段 null 按 0 计（利润表未单列=不重大），
   全 null 才算「未提取」；note 必须标注哪个字段是按 0 计。禁止把「未提取」当 0 填报后
   又在 note 里隐身
9. **市值单位陷阱**（v1.2，TradingAgents-CN 实证坑）：tushare `daily_basic.total_mv` 单位是
   **万元**，`market_cap_cur` 入库前必须 ÷1e4 转**亿元**（与全局 unit 一致）——TradingAgents
   曾把亿元当元直接算 Altman X4，X4 被压低 1 亿倍；本契约单位写死亿元，calc.py 复算
   拦截
