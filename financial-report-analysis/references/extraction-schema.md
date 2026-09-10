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
| `hist` | 多期数组，**旧→新** | 选填；趋势图与 P1-13 五期分析消费，缺省至少 3 期 |
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
    "schema_version": "1.0",
    "currency": "CNY",
    "accounting_standard": "CAS",
    "industry_profile": "通用",
    "cycle_stage": null
  },

  "statements": {
    "income": {
      "revenue":      { "cur": null, "prev": null, "hist": [], "src": "" },
      "cost":         { "cur": null, "prev": null, "src": "" },
      "gross_profit": { "cur": null, "prev": null, "src": "", "note": "可由 revenue-cost 推算，填 derived" },
      "tax_surcharge":{ "cur": null, "prev": null, "src": "" },
      "sell_exp":     { "cur": null, "prev": null, "src": "" },
      "admin_exp":    { "cur": null, "prev": null, "src": "" },
      "rd_exp":       { "cur": null, "prev": null, "src": "" },
      "fin_exp":      { "cur": null, "prev": null, "src": "", "note": "可为负" },
      "interest_exp": { "cur": null, "prev": null, "src": "", "note": "财务费用附注中的利息支出" },
      "interest_inc": { "cur": null, "prev": null, "src": "", "note": "财务费用附注中的利息收入（redflags #2 利息收入与货币资金匹配用；A7 隐含利率取利息支出）" },
      "impair_loss":  { "cur": null, "prev": null, "src": "", "note": "资产+信用减值合计" },
      "invest_income":{ "cur": null, "prev": null, "src": "" },
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
      "ar":               { "cur": null, "prev": null, "src": "", "note": "应收账款" },
      "ar_notes":         { "cur": null, "prev": null, "src": "", "note": "应收票据+应收款项融资" },
      "other_ar":         { "cur": null, "prev": null, "src": "", "note": "其他应收款" },
      "inventory":        { "cur": null, "prev": null, "src": "" },
      "contract_liab":    { "cur": null, "prev": null, "src": "" },
      "payable":          { "cur": null, "prev": null, "src": "", "note": "应付账款+应付票据（DPO/CCC 计算必需；先款后货型公司可为 0）" },
      "fixed_assets":     { "cur": null, "prev": null, "src": "", "note": "固定资产净值（A6 Capex 勾稽用）" },
      "cip":              { "cur": null, "prev": null, "src": "", "note": "在建工程" },
      "goodwill":         { "cur": null, "prev": null, "src": "" },
      "st_debt":          { "cur": null, "prev": null, "src": "", "note": "短期借款" },
      "noncur_due_1y":    { "cur": null, "prev": null, "src": "", "note": "一年内到期非流动负债" },
      "lt_debt":          { "cur": null, "prev": null, "src": "", "note": "长期借款+应付债券+租赁负债" },
      "total_assets":     { "cur": null, "prev": null, "src": "" },
      "total_liab":       { "cur": null, "prev": null, "src": "" },
      "equity_at":        { "cur": null, "prev": null, "src": "", "note": "归母净资产" },
      "minority_eq":      { "cur": null, "prev": null, "src": "" },
      "retained_cur":     { "cur": null, "prev": null, "src": "", "note": "未分配利润（A2 滚动勾稽）" },
      "surplus_reserve":  { "cur": null, "prev": null, "src": "", "note": "盈余公积（A2 用其本期提取额）" },
      "dividend_paid":    { "cur": null, "prev": null, "src": "", "note": "本年实际分配现金股利" },
      "prepayment":       { "cur": null, "prev": null, "src": "", "note": "预付款项（采购侧资产；A4 收入-收现闭环不用此项，相关的是预收/合同负债）" },
      "fin_assets":       { "cur": null, "prev": null, "src": "", "note": "交易性金融资产+长期股权投资+其他非流动金融资产（A8 用）" },
      "payable_construction": { "cur": null, "prev": null, "src": "", "note": "应付工程设备款（A6 用，常未单列，可 null）" }
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

  "derived": {
    "ratios": {
      "roe": { "cur": null, "prev": null }, "gross_margin": { "cur": null, "prev": null },
      "net_margin": { "cur": null, "prev": null }, "net_cash_ratio": { "cur": null, "prev": null },
      "cash_to_sales": { "cur": null, "prev": null }, "debt_to_assets": { "cur": null, "prev": null },
      "asset_turnover": { "cur": null, "prev": null }, "equity_multiplier": { "cur": null, "prev": null },
      "dso": { "cur": null, "prev": null }, "dio": { "cur": null, "prev": null },
      "dpo": { "cur": null, "prev": null }, "ccc": { "cur": null, "prev": null },
      "short_debt_cover": { "cur": null },
      "incr_expense_eff": { "cur": null, "note": "Δ毛利÷Δ期间费用" },
      "incr_sales_eff":   { "cur": null, "note": "Δ收入÷Δ销售费用" },
      "nonrecurring_share": { "cur": null, "note": "非经÷归母净利" }
    },
    "dupont": { "driver": "净利率|周转率|杠杆", "src": "" },
    "fscore": { "items": [true,false,null], "score": null },
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
    "B4_goodwill_roll":{ "lhs": null, "rhs": null, "verdict": "", "explanation": "", "src": "" }
  },

  "assertions": [
    { "id": "A1", "text": "管理层断言原文（如：收入下降主要系系列酒结构调整）",
      "account": "涉及科目", "verdict": "通过",
      "evidence": "数字检验结论（判「不成立」时必填反证）", "missing": "判「无法验证」时必填缺什么数据",
      "source": "MD&A 章节/行号" }
  ],

  "signals": [
    { "id": "R1", "level": "r", "type": "signal", "title": "存贷双高", "data": "货币资金/总资产=x% 且 有息负债/总资产=y%",
      "evidence": "原文引用", "source": "资产负债表+货币资金附注" }
  ]
}
```

**`signals[]` 字段说明**：`level ∈ g/y/r`（严重度）；`type ∈ signal/assertion`
（`signal` = 财务信号；`assertion` = MD&A 断言不实，见 text-mining.md 第七节）。
⚠️ redflags.md 使用纪律第 2 条「红色信号 ≥2 条即提示财务真实性风险聚集」**只统计
`type=signal`** 的红色条目——归因不实与财务真实性是两类问题，不可混计。`type` 缺省视为 `signal`。

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
| inventory | `存货` | `balancesheet.inventories` |
| cip | `在建工程` | `balancesheet.cip` |
| contract_liab | `合同负债` | `balancesheet.contract_liab` |
| st_debt | `短期借款` | `balancesheet.st_borr` |
| lt_debt | `长期借款`+`应付债券` | `balancesheet.lt_borr`+`st_bonds_payable` |
| retained | `未分配利润` | `balancesheet.undistr_porfit` |
| rd_exp | `研发投入`（MD&A 专节，注意含资本化） | `income.rd_exp`（仅费用化部分） |
| ar_aging | `应收账款`附注内`账龄` | 无——只能来自原文 |
| inventory_mix | `存货`附注内`原材料`/`在产品`/`库存商品` | 无——只能来自原文 |
| kam | `关键审计事项` | 无——只能来自原文 |

## 六、常见坑（血泪清单）

1. **单位**：报表附注常用「万元」，主表用「元」，MD&A 常用「亿元」——每提取一个数先看表头单位
2. **含税口径**：收现比分子含增值税销项，正常值 ≈1.13×收入（一般纳税人），不要按 1.0 判异常
3. **研发费用两处披露**：利润表 `研发费用`（费用化）≠ MD&A「研发投入合计」（含资本化），
   两者都要进 JSON（`rd_exp` + `note` 里记资本化率）
4. **财务公司为负的「有息负债」**：吸收存款及同业存放是经营负债，不进 lt_debt/st_debt（茅台案例）
5. **少数股东**：OCF 调节桥起点是 `np_total`（含少数股东），净利桥终点是 `np_at`——两桥起点不同，别混
6. **hist 顺序**：旧→新。趋势图直接消费，反了图就反了
