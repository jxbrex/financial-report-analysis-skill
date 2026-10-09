# -*- coding: utf-8 -*-
"""calc_common.py — calc.py 的共享层：级别常量、Report、取值/比率公式族。
全脚本比率公式唯一定义处（ratio_hist_expect）在此；被 calc.py 与 calc_models.py 引用。
"""

FAIL, WARN, OK, SKIP = "FAIL", "WARN", "OK", "SKIP"


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, code, msg):
        self.rows.append((level, code, msg))

    def counts(self):
        c = {FAIL: 0, WARN: 0, OK: 0, SKIP: 0}
        for lv, _, _ in self.rows:
            c[lv] += 1
        return c


def num(x):
    """数值或 None；字符串数字（含千位符）一律视为格式错误，由结构检查另行报错。"""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def leaf(d, *path):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def val(d, *path, key="cur"):
    node = leaf(d, *path)
    if isinstance(node, dict):
        return num(node.get(key))
    return num(node)


def rel_dev(a, b):
    if a is None or b is None:
        return None
    denom = max(abs(b), 1e-9)
    return abs(a - b) / denom


def tol_bridge(delta_total, base):
    """桥闭合容差：2% 的桥总量 与 0.5% 的基准量 取大者。"""
    t = 0.0
    if delta_total is not None:
        t = max(t, 0.02 * abs(delta_total))
    if base is not None:
        t = max(t, 0.005 * abs(base))
    return max(t, 0.01)


def safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b



# ─── 比率公式族（全脚本唯一定义处） ───

def avg(cur, prev):
    """平均余额：任一端缺失返回 None（不可算）——不得以期末冒充平均，
    与 ratio_hist_series 的逐期口径一致（单期/逐期同规则，v0.1.1 修复退化分支）。"""
    if cur is None or prev is None:
        return None
    return (cur + prev) / 2.0


def parts_sum(data, fields, key="cur"):
    """balance 科目组合计：null 按 0 计、全 null 才 None（有息/无息负债口径唯一定义处，
    calc_common ROIC 与 calc_dupont leverage_drill 共用——v0.0.17 热核审计整改）。"""
    vs = [val(data, "statements", "balance", f, key=key) for f in fields]
    return None if all(v is None for v in vs) else sum(v or 0.0 for v in vs)


def build_ratio_calcs(data):
    S = lambda *p, key="cur": val(data, "statements", *p, key=key)
    rev, rev_p = S("income", "revenue"), S("income", "revenue", key="prev")
    cost, cost_p = S("income", "cost"), S("income", "cost", key="prev")
    np_at = S("income", "np_at")
    np_dt = S("income", "np_dt")
    ocf = S("cashflow", "ocf")
    sales_cash = S("cashflow", "sales_cash")
    cash = S("balance", "cash")
    ta, ta_p = S("balance", "total_assets"), S("balance", "total_assets", key="prev")
    tl, tl_p = S("balance", "total_liab"), S("balance", "total_liab", key="prev")
    eq = S("balance", "equity_at")
    ar, ar_p = S("balance", "ar"), S("balance", "ar", key="prev")
    inv, inv_p = S("balance", "inventory"), S("balance", "inventory", key="prev")
    # DPO 需要应付账款（+应付票据）；未提取则留空，CCC 随之不可算（见 schema balance.payable）
    ap, ap_p = S("balance", "payable"), S("balance", "payable", key="prev")
    st, noncur = S("balance", "st_debt"), S("balance", "noncur_due_1y")
    sell, sell_p = S("income", "sell_exp"), S("income", "sell_exp", key="prev")
    admin, admin_p = S("income", "admin_exp"), S("income", "admin_exp", key="prev")
    rd, rd_p = S("income", "rd_exp"), S("income", "rd_exp", key="prev")
    fin, fin_p = S("income", "fin_exp"), S("income", "fin_exp", key="prev")
    np_total = S("income", "np_total")
    income_tax = S("income", "income_tax")
    dep_amort = S("cashflow", "dep_amort")

    gross = None if (rev is None or cost is None) else rev - cost
    gross_p = None if (rev_p is None or cost_p is None) else rev_p - cost_p
    exp_cur = None if any(x is None for x in (sell, admin, rd, fin)) else sell + admin + rd + fin
    exp_prev = None if any(x is None for x in (sell_p, admin_p, rd_p, fin_p)) else sell_p + admin_p + rd_p + fin_p

    short_debt = None if (st is None and noncur is None) else (st or 0) + (noncur or 0)
    cover = None
    if cash is not None and ocf is not None and short_debt:
        cover = (cash + ocf) / short_debt

    # X33 非主营业务收入占比：四字段逐字段 null 按 0 计，全 null 才 None（schema 血泪清单 8）
    nm = [S("income", "non_op_income"), S("income", "other_biz_income"),
          S("income", "invest_income"), S("income", "fv_change_income")]
    non_main = None if all(x is None for x in nm) else safe_div(sum(x or 0 for x in nm), rev)

    # N1 ROIC（去杠杆口径，v0.0.17）：NOPAT÷平均投入资本；NOPAT=EBIT×(1−有效税率)，
    # EBT≤0 时有效税率按 0（亏损期无税盾可抵）；投入资本=有息负债+归母权益
    # （有息=st_debt+noncur_due_1y+lt_debt，null 按 0、全 null 才 None——与 leverage_drill 同口径）；
    # 期间口径不年化（与本体系 ROE 同约定）；ROIC 上期需 T-2 投入资本，不可得故只算当期
    eq_p = S("balance", "equity_at", key="prev")
    ebt = None if (np_total is None or income_tax is None) else np_total + income_tax
    ebit = None if (ebt is None or fin is None) else ebt + fin
    tax_rate = None if ebt is None else (income_tax / ebt if ebt > 0 else 0.0)
    nopat = None if (ebit is None or tax_rate is None) else ebit * (1 - tax_rate)
    ib = parts_sum(data, ("st_debt", "noncur_due_1y", "lt_debt"))
    ib_p = parts_sum(data, ("st_debt", "noncur_due_1y", "lt_debt"), key="prev")
    ic = None if (ib is None or eq is None) else ib + eq
    ic_p = None if (ib_p is None or eq_p is None) else ib_p + eq_p
    roic = None if (nopat is None or ic is None) else safe_div(nopat, avg(ic, ic_p))
    # N2 内生增长率（v0.0.17）：留存率×ROE；np_at≤0（亏损期符号无解读意义）或分红未提取 → None；
    # roe 取下方 out 的唯一定义处复算值（不另写公式），故 sgr 在 out 构建后计算并入
    dv = S("cashflow", "dividend_paid")

    # 14 项趋势比率委托 ratio_hist_expect（当期取值字典含上期余额）——
    # 全脚本比率公式只此一份，杜绝双份维护漂移
    trend_v = {
        ("income", "np_at"): np_at, ("balance", "equity_at"): eq,
        ("income", "revenue"): rev, ("income", "cost"): cost,
        ("cashflow", "ocf"): ocf, ("cashflow", "sales_cash"): sales_cash,
        ("balance", "total_liab"): tl, ("balance", "total_assets"): ta,
        ("balance", "ar"): ar, ("balance", "inventory"): inv,
        ("balance", "payable"): ap, ("income", "np_total"): np_total,
        ("income", "income_tax"): income_tax, ("income", "fin_exp"): fin,
        ("cashflow", "dep_amort"): dep_amort,
        "total_assets_prev": ta_p, "ar_prev": ar_p,
        "inventory_prev": inv_p, "payable_prev": ap_p,
    }
    out = {name: ratio_hist_expect(name, trend_v) for name in RATIO_HIST_SPECS}
    roe_cur = out.get("roe")
    sgr = None
    if dv is not None and np_at is not None and np_at > 0 and roe_cur is not None:
        sgr = (1 - dv / np_at) * roe_cur
    out.update({
        "non_main_rev_share": non_main,
        "roic": roic,
        "sustainable_growth": sgr,
        "ocf_to_liab": safe_div(ocf, avg(tl, tl_p)),
        "short_debt_cover": cover,
        "incr_expense_eff": (None if (gross is None or gross_p is None or exp_cur is None or exp_prev is None
                                      or (exp_cur - exp_prev) == 0)
                             else (gross - gross_p) / (exp_cur - exp_prev)),
        "incr_sales_eff": (None if (rev is None or rev_p is None or sell is None or sell_p is None
                                    or (sell - sell_p) == 0)
                           else (rev - rev_p) / (sell - sell_p)),
        "nonrecurring_share": (None if (np_at is None or np_dt is None or np_at == 0)
                               else (np_at - np_dt) / np_at),
    })
    return out



RATIO_HIST_SPECS = {
    "roe":               ([("income", "np_at"), ("balance", "equity_at")], False),
    "gross_margin":      ([("income", "revenue"), ("income", "cost")], False),
    "net_margin":        ([("income", "np_at"), ("income", "revenue")], False),
    "net_cash_ratio":    ([("cashflow", "ocf"), ("income", "np_at")], False),
    "debt_to_assets":    ([("balance", "total_liab"), ("balance", "total_assets")], False),
    "equity_multiplier": ([("balance", "total_assets"), ("balance", "equity_at")], False),
    "cash_to_sales":     ([("cashflow", "sales_cash"), ("income", "revenue")], False),
    "asset_turnover":    ([("income", "revenue"), ("balance", "total_assets")], True),
    "dso":               ([("balance", "ar"), ("income", "revenue")], True),
    "dio":               ([("balance", "inventory"), ("income", "cost")], True),
    "dpo":               ([("balance", "payable"), ("income", "cost")], True),
    "ccc":               ([("balance", "ar"), ("balance", "inventory"), ("balance", "payable"),
                           ("income", "revenue"), ("income", "cost")], True),
    "dfl":               ([("income", "np_total"), ("income", "income_tax"), ("income", "fin_exp")], False),
    "dol":               ([("income", "np_total"), ("income", "income_tax"), ("income", "fin_exp"),
                           ("cashflow", "dep_amort")], False),
}


def series_of(data, sec, field):
    """科目多期序列：hist 优先；无 hist 时退化为 [cur]（只能覆盖最末一期）。"""
    node = leaf(data, "statements", sec, field) or {}
    vals = [num(x) for x in node.get("hist") or []]
    if not vals:
        c = num(node.get("cur"))
        vals = [c] if c is not None else []
    return vals


def series_of_ye(data, sec, field):
    """科目年末序列（hist_ye）：半年报平均余额比率的期初口径（各年 12-31）。
    末位=prev（cur 期的期初）。无 hist_ye 返回 []（年报形态，期初退化为 hist 前一期）。"""
    node = leaf(data, "statements", sec, field) or {}
    return [num(x) for x in node.get("hist_ye") or []]


def ratio_hist_expect(name, v):
    """按某期科目取值字典复算比率（全脚本比率公式唯一定义处）；缺数返回 None。"""
    g = lambda *p: v.get(p)

    if name == "roe":
        return safe_div(g("income", "np_at"), g("balance", "equity_at"))
    if name == "gross_margin":
        rev, cost = g("income", "revenue"), g("income", "cost")
        return None if (rev is None or cost is None) else safe_div(rev - cost, rev)
    if name == "net_margin":
        return safe_div(g("income", "np_at"), g("income", "revenue"))
    if name == "net_cash_ratio":
        return safe_div(g("cashflow", "ocf"), g("income", "np_at"))
    if name == "debt_to_assets":
        return safe_div(g("balance", "total_liab"), g("balance", "total_assets"))
    if name == "equity_multiplier":
        return safe_div(g("balance", "total_assets"), g("balance", "equity_at"))
    if name == "cash_to_sales":
        return safe_div(g("cashflow", "sales_cash"), g("income", "revenue"))

    # 杠杆（X72/X71，非平均口径）：EBIT = 税前利润 + 财务费用
    if name in ("dfl", "dol"):
        np_t, tax, fin = g("income", "np_total"), g("income", "income_tax"), g("income", "fin_exp")
        ebt = None if (np_t is None or tax is None) else np_t + tax
        ebit = None if (ebt is None or fin is None) else ebt + fin
        if name == "dfl":
            return safe_div(ebit, ebt)
        dep = g("cashflow", "dep_amort")
        return safe_div(ebit + dep, ebit) if (ebit is not None and dep is not None) else None

    # 以下均为平均余额口径（余额取本期与上期均值），CCC 由 dso+dio-dpo 复合；
    # 各比率只取自己需要的序列，缺的科目不参与计算（avg 任一端缺返回 None，须先判空再乘）
    rev, cost = g("income", "revenue"), g("income", "cost")
    ta, ta_p = g("balance", "total_assets"), v.get("total_assets_prev")
    ar, ar_p = g("balance", "ar"), v.get("ar_prev")
    inv, inv_p = g("balance", "inventory"), v.get("inventory_prev")
    ap, ap_p = g("balance", "payable"), v.get("payable_prev")
    ar_m = avg(ar, ar_p)
    inv_m = avg(inv, inv_p)
    ap_m = avg(ap, ap_p)
    dso = safe_div(ar_m * 365, rev) if (rev and ar_m is not None) else None
    dio = safe_div(inv_m * 365, cost) if (cost and inv_m is not None) else None
    dpo = safe_div(ap_m * 365, cost) if (cost and ap_m is not None) else None
    if name == "asset_turnover":
        return safe_div(rev, avg(ta, ta_p))
    if name == "dso":
        return dso
    if name == "dio":
        return dio
    if name == "dpo":
        return dpo
    if name == "ccc":
        return None if any(x is None for x in (dso, dio, dpo)) else dso + dio - dpo
    return None



def ratio_hist_series(data, name):
    """某趋势比率的逐期复算序列（旧→新，与科目 hist 尾部对齐）；不可算期为 None。
    逐期对齐逻辑（hist_ye 期初/退化规则）全脚本唯一定义处——calc.py 的 check_ratio_hist
    与 --fill 预填共用，禁止第二份实现。"""
    spec = RATIO_HIST_SPECS.get(name)
    if spec is None:
        return None
    fields, avg_based = spec
    ss = [series_of(data, sec, f) for sec, f in fields]
    if not ss or not min(len(s) for s in ss):
        return []
    yes = ([series_of_ye(data, sec, f) for sec, f in fields]
           if avg_based else [[] for _ in fields])
    prev_fields = [f for sec, f in fields if sec == "balance"] if avg_based else []
    L = min(len(s) for s in ss)
    out = []
    for j in range(L):
        v = {}
        for (sec, f), s, ye in zip(fields, ss, yes):
            i = len(s) - L + j
            v[(sec, f)] = s[i]
            if avg_based and sec == "balance":
                use_ye = bool(ye) and len(ye) >= len(s)
                v[f"{f}_prev"] = (ye[i + len(ye) - len(s)] if use_ye
                                  else (s[i - 1] if i > 0 else None))
        if prev_fields and any(v.get(f"{f}_prev") is None for f in prev_fields):
            out.append(None)
            continue
        out.append(ratio_hist_expect(name, v))
    return out


# ─── 期间标签与批量比对助手（v0.0.15，被杜邦/证据/风险三族共用） ───

# 期间标签倒推：同类型滚动（年报对 FY、半年报对 H1……），period 的 MMDD 与 report_type 必须一致
_PERIOD_SUFFIX = {"年报": ("1231", ""), "半年报": ("0630", "H1"),
                  "一季报": ("0331", "Q1"), "三季报": ("0930", "Q3")}


def hist_periods(meta, n):
    """从 meta.period/report_type 倒推 n 期同类型期间标签（旧→新）。无法推导返回 None。"""
    period = str(meta.get("period") or "")
    rt = meta.get("report_type")
    if rt not in _PERIOD_SUFFIX or len(period) != 8 or not period.isdigit():
        return None
    md, suffix = _PERIOD_SUFFIX[rt]
    if period[4:8] != md:
        return None
    y = int(period[:4])
    return [f"{y - (n - 1 - i)}{suffix}" for i in range(n)]


def cmp_fields(bad, label, node, exp, keys, tol=0.005, skip_none=False):
    """扁平数值字段批量比对（derived vs 复算值）——各族 check_* 复用的唯一比对助手。
    e=None（无法复算）时 skip_none=True 跳过、否则记「无法复算」；got=None（未填）记「未填」；
    tol 为数值或 callable(expected→容差)。返回 bad（追加式）。"""
    for k in keys:
        got, e = num(node.get(k)), exp.get(k)
        if e is None:
            if not skip_none:
                bad.append(f"{label}.{k} 无法复算")
            continue
        t = tol(e) if callable(tol) else tol
        if got is None:
            bad.append(f"{label}.{k} 未填")
        elif abs(got - e) > t:
            bad.append(f"{label}.{k} 不符：derived={got} vs 重算={e:.4f}")
    return bad


def cmp_series(bad, label, got, exp, tol=0.005):
    """逐期数组比对（长度一致 + 逐元素，双 None 跳过，首处不符即停）——
    cycle_evidence / cash_ts 等时序块复用。"""
    got, exp = got or [], exp or []
    if len(got) != len(exp):
        bad.append(f"{label} 长度 {len(got)} ≠ 重算 {len(exp)}（须与 periods 对齐）")
        return bad
    for i, (g, x) in enumerate(zip(got, exp)):
        gn = num(g)
        if gn is None and x is None:
            continue
        if gn is None or x is None or abs(gn - x) > tol:
            bad.append(f"{label}[{i}] 不符：derived={g} vs 重算={x}")
            break
    return bad
