def _f2(x):
    return "—" if not isinstance(x, (int, float)) or isinstance(x, bool) else f"{x:,.2f}"


def _pct(x):
    return "—" if not isinstance(x, (int, float)) or isinstance(x, bool) else f"{x * 100:.2f}%"


def _yoy(cur, prev):
    if not isinstance(cur, (int, float)) or not isinstance(prev, (int, float)) or not prev:
        return "—"
    return f"{(cur - prev) / abs(prev) * 100:+.2f}%"


def _latest_reviewed(ipo):
    months = {"q1": 3, "h1": 6, "q2": 6, "q3": 9, "h2": 12, "q4": 12, "fy": 12}
    candidates = []
    prefix = "reviewed_financials_"
    for key, block in ipo.items():
        if not key.startswith(prefix) or not isinstance(block, dict):
            continue
        suffix = key[len(prefix):].lower()
        year = int(suffix[:4]) if len(suffix) >= 4 and suffix[:4].isdigit() else -1
        candidates.append((year, months.get(suffix[4:], 0), key, suffix, block))
    if not candidates:
        return {}, "", None
    _, _, _, suffix, block = max(candidates, key=lambda x: x[:3])
    year = int(suffix[:4]) if len(suffix) >= 4 and suffix[:4].isdigit() else None
    label = suffix[4:].upper() if year is not None else suffix.upper()
    return block, label or "最近审阅期", year


def build_ipo_slots(data):
    meta = data.get("meta") or {}
    if meta.get("report_type") != "招股书":
        return {}
    extract = (data.get("notes") or {}).get("operating_extract") or {}
    ipo = extract.get("ipo") or {}
    terms = ipo.get("issue_terms") or {}
    plan = ipo.get("use_of_proceeds_plan") or {}
    final = ipo.get("use_of_proceeds_final") or {}
    post = extract.get("post_listing_validation") or {}
    post_data = post.get("data") or {}
    listing = post_data.get("listing_announcement") or {}
    actual_net = listing.get("net_proceeds_actual")
    actual_net = actual_net / 1e8 if isinstance(actual_net, (int, float)) else None
    expected_net = final.get("net_proceeds")
    planned_raise = plan.get("planned_raise")
    shortfall = final.get("shortfall_vs_planned_raise")
    if shortfall is None and isinstance(planned_raise, (int, float)) and isinstance(expected_net, (int, float)):
        shortfall = planned_raise - expected_net

    issue_rows = [
        {"item": "发行价", "value": f"{_f2(terms.get('issue_price'))} 元/股", "note": terms.get("pricing_method") or "招股说明书披露"},
        {"item": "发行股数", "value": f"{_f2(terms.get('shares_offered'))} 万股", "note": "不含超额配售（如适用）"},
        {"item": "发行后总股本", "value": f"{_f2(terms.get('post_issue_total_shares'))} 万股", "note": "按本次发行方案"},
        {"item": "发行后市盈率", "value": f"{_f2(terms.get('pe_post'))} 倍", "note": terms.get("pe_note") or "招股书披露口径"},
        {"item": "预计总募资 / 净募资", "value": f"{_f2(final.get('gross_proceeds'))} / {_f2(expected_net)} 亿元", "note": "招股书预计口径，不等同验资实际值"},
        {"item": "拟投入募集资金", "value": f"{_f2(planned_raise)} 亿元", "note": f"预计净额与拟募差额 {_f2(shortfall)} 亿元" if shortfall is not None else "差额未披露"},
    ]
    plan_rows = []
    for p in plan.get("projects") or []:
        benefit = p.get("benefit_assumption") or "未披露IRR/回收期等收益测算"
        capacity = p.get("capacity") or "未披露量化产能"
        plan_rows.append({
            "name": p.get("name") or "未命名项目", "total": _f2(p.get("total_investment")),
            "raised": _f2(p.get("planned_raise")), "period": p.get("build_period") or "未披露",
            "benefit": benefit, "capacity": capacity,
        })
    equity_rows = []
    shareholding = ipo.get("shareholding_pre_post") or {}
    for row in shareholding.get("table") or []:
        equity_rows.append({
            "holder": row.get("holder") or "未披露", "pre": _pct(row.get("pre_pct")),
            "post": _pct(row.get("post_pct")),
        })

    reviewed, period_label, reviewed_year = _latest_reviewed(ipo)
    prev_year = reviewed_year - 1 if reviewed_year is not None else None
    balance_scope = f"较{prev_year}年末" if prev_year is not None else "较上年末"
    flow_scope = f"同比{prev_year}{period_label}" if prev_year is not None else "同比上年同期"
    current_period = f"{reviewed_year}{period_label}" if reviewed_year is not None else "最近审阅期"
    interim_rows = []
    groups = (
        ("balance", balance_scope, (("total_assets", "总资产"), ("total_liab", "总负债"), ("equity_at", "归母权益"))),
        ("income", flow_scope, (("revenue", "营业收入"), ("np_at", "归母净利润"), ("np_dt", "扣非归母净利润"))),
        ("cashflow", flow_scope, (("ocf", "经营现金流净额"),)),
    )
    for group, scope, fields in groups:
        block = reviewed.get(group) or {}
        for key, label in fields:
            node = block.get(key) or {}
            cur, prev = node.get("cur"), node.get("prev")
            if isinstance(cur, (int, float)) and isinstance(prev, (int, float)):
                interim_rows.append({"item": label, "cur": _f2(cur), "prev": _f2(prev),
                                     "change": _yoy(cur, prev), "scope": scope})
    interim_note = f"{current_period}为审阅数据、非审计；资产负债表{balance_scope}，利润与现金流{flow_scope}。"
    if not interim_rows:
        interim_note = "期后审阅数据未结构化披露；不补数、不与年度主表混算。"
    rev_node = (reviewed.get("income") or {}).get("revenue") or {}
    np_node = (reviewed.get("income") or {}).get("np_at") or {}
    rev_g = _yoy(rev_node.get("cur"), rev_node.get("prev"))
    np_g = _yoy(np_node.get("cur"), np_node.get("prev"))
    interim_title = "期后增收不增利，利润压力先于收入暴露" if rev_g.startswith("+") and np_g.startswith("-") else "期后财务按同口径核验，审阅与审计分层"

    post_rows = []
    q3 = post_data.get("q3_report") or {}
    post_year = str(q3.get("date") or q3.get("report_date") or "")[:4]
    if not post_year.isdigit():
        post_year = str(meta.get("analyst_date") or "")[:4]
    post_prefix = f"{post_year}年" if post_year.isdigit() else "上市后"
    for key, label in (("revenue", "营业收入"), ("np_at", "归母净利润"), ("np_dt", "扣非归母净利润"), ("ocf", "经营现金流净额")):
        node = (q3.get("9m") or {})
        cur, prev = node.get(f"{key}_cur"), node.get(f"{key}_prev")
        if isinstance(cur, (int, float)) and isinstance(prev, (int, float)):
            post_rows.append({"item": f"{post_prefix}前9月{label}", "cur": _f2(cur / 1e8),
                              "prev": _f2(prev / 1e8), "change": _yoy(cur, prev), "scope": "未审"})
    if isinstance(actual_net, (int, float)) and isinstance(expected_net, (int, float)):
        post_rows.insert(0, {"item": "实际净募资（万元）", "cur": _f2(actual_net * 1e4),
                             "prev": _f2(expected_net * 1e4),
                             "change": f"较预计 {(actual_net - expected_net) * 1e4:+.2f} 万元", "scope": "验资"})
    post_note = "上市后三季报为未审数据；实际募资与经营业绩只作期后核验，不回改招股书预计口径。"
    if not post_data:
        post_note = "未取得上市后实际数据；未作期后兑现核验，不以预计数冒充实际数。"
    return {
        "issue": {"price_raw": terms.get("issue_price")},
        "planned_raise_raw": planned_raise, "expected_net_raw": expected_net,
        "actual_net_raw": actual_net, "issue_rows": issue_rows, "plan_rows": plan_rows,
        "equity_rows": equity_rows, "interim_rows": interim_rows, "interim_note": interim_note,
        "interim_title": interim_title, "post_rows": post_rows, "post_note": post_note,
        "issue_title": "净募资低于拟投计划，差额需自筹" if isinstance(shortfall, (int, float)) and shortfall > 0 else "发行与募资口径分列核验",
        "plan_title": "募投项目已列明，收益测算未披露" if any(not p.get("benefit_assumption") for p in plan.get("projects") or []) else "募投项目与收益假设并列核验",
        "equity_title": "发行摊薄原股东比例，控制权变化另看合计口径",
        "missing": not ipo,
    }
