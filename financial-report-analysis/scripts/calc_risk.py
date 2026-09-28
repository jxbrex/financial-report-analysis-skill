# -*- coding: utf-8 -*-
"""calc_risk.py — 风险模型族（v0.0.12 起，v0.0.15 拆分自 calc_models.py）：
破产双模型（Altman Z + Ohlson O）+ 流动性压力情景 + 现金验证时序。
"""

import math

from calc_common import (FAIL, WARN, OK, SKIP, num, val, series_of,
                         build_ratio_calcs, hist_periods, cmp_series)

# 中期报告流量年化因子（frameworks.md 〇 口径总则；复算本身即口径卡口——
# derived 填了未年化的流量分量就会复算不符 FAIL）
ANNUALIZE = {"年报": 1.0, "半年报": 2.0, "一季报": 4.0, "三季报": 4.0 / 3.0, "季报": 4.0 / 3.0}

def compute_altman(data):
    """Altman Z（X4 市值/总负债，市值单位=亿元；中期报告流量项年化）。
    返回 (dict, None) 或 (None, 原因码 no-mcap / inputs)。"""
    B = lambda f: val(data, "statements", "balance", f)
    I = lambda f: val(data, "statements", "income", f)
    meta = data.get("meta") or {}
    factor = ANNUALIZE.get(meta.get("report_type"))
    ta, tl = B("total_assets"), B("total_liab")
    tca, tcl = B("total_cur_assets"), B("total_cur_liab")
    retained, surplus = B("retained_cur"), B("surplus_reserve")
    np_total, tax, fin = I("np_total"), I("income_tax"), I("fin_exp")
    rev, mcap = I("revenue"), meta.get("market_cap_cur")
    ebit = None if None in (np_total, tax, fin) else np_total + tax + fin
    if mcap is None:
        return None, "no-mcap"
    if None in (ta, tl, tca, tcl, retained, surplus, ebit, rev) or factor is None:
        return None, "inputs"
    x1 = (tca - tcl) / ta
    x2 = (retained + surplus) / ta
    x3 = ebit / ta
    x4 = mcap / tl
    x5 = rev * factor / ta
    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    zone = "安全" if z > 2.99 else ("灰色" if z > 1.81 else "危险")
    return {"cur": z, "zone": zone, "annualized": factor != 1.0}, None


def compute_ohlson(data):
    """Ohlson O 简化六因子（ln 总资产按亿元；X6 缺对比期净利则整块不执行）。
    返回 (dict, None) 或 (None, 原因码 inputs)。"""
    B = lambda f: val(data, "statements", "balance", f)
    I = lambda f, key="cur": val(data, "statements", "income", f, key=key)
    ta, tl = B("total_assets"), B("total_liab")
    tca, tcl = B("total_cur_assets"), B("total_cur_liab")
    np_total, np_prev = I("np_total"), I("np_total", key="prev")
    if None in (ta, tl, tca, tcl, np_total, np_prev):
        return None, "inputs"
    x6 = (np_total - np_prev) / (abs(np_total) + abs(np_prev))
    o = (-1.32 - 0.407 * math.log(ta) + 6.03 * tl / ta - 1.43 * (tca - tcl) / ta
         + 0.0757 * tcl / tca - 1.72 * (1 if tl > ta else 0) - 0.521 * x6)
    prob = 1.0 / (1.0 + math.exp(-o))
    level = "高" if prob > 0.5 else ("中" if prob > 0.15 else "低")
    return {"cur": o, "prob": prob, "level": level}, None


def compute_stress(data):
    """流动性压力三情景（DOL 经 build_ratio_calcs 委托，公式唯一定义处在那）。
    受压税前 ≤0 时不再计税收抵免（保守）。输入不齐返回 None。"""
    I = lambda f: val(data, "statements", "income", f)
    B = lambda f: val(data, "statements", "balance", f)
    C = lambda f: val(data, "statements", "cashflow", f)
    np_total, tax, fin = I("np_total"), I("income_tax"), I("fin_exp")
    cash, ocf = B("cash"), C("ocf")
    st_debt, noncur = B("st_debt"), B("noncur_due_1y")
    short_debt = None if (st_debt is None and noncur is None) else (st_debt or 0) + (noncur or 0)
    dol = build_ratio_calcs(data).get("dol")
    if None in (np_total, tax, fin, cash, ocf, dol) or not short_debt:
        return None
    ebit = np_total + tax + fin
    ebt = np_total + tax
    tax_rate = min(max(tax / ebt, 0.0), 0.35) if ebt > 0 else 0.0
    out = []
    for p in (0.1, 0.2, 0.3):
        ebit_s = ebit * (1 - p * dol)
        ebt_s = ebit_s - fin
        np_s = ebt_s * (1 - tax_rate) if ebt_s > 0 else ebt_s
        out.append({"p": p, "np_stressed": np_s,
                    "cover_stressed": (cash + ocf * (1 - p)) / short_debt})
    return out


def compute_cash_ts(data):
    """现金验证时序读数：净现比/FCF 覆盖的均值与负值年数（分母归母净利）+
    v1.3 逐期数组 ncr/fcf_to_np/periods（S1 现金时序表数据源）。
    hist <3 期返回 None（口径断裂合法 null）。"""
    ocf_h = [x for x in series_of(data, "cashflow", "ocf") if x is not None]
    np_h = [x for x in series_of(data, "income", "np_at") if x is not None]
    capex_h = [x for x in series_of(data, "cashflow", "capex") if x is not None]
    n = min(len(ocf_h), len(np_h))
    if n < 3:
        return None
    ocf_h, np_h = ocf_h[-n:], np_h[-n:]
    ncr = [o / p if p else None for o, p in zip(ocf_h, np_h)]
    ncr_ok = [x for x in ncr if x is not None]
    out = {"ncr_mean5": sum(ncr_ok) / len(ncr_ok) if ncr_ok else None,
           "ncr_neg_years": sum(1 for o in ocf_h if o < 0),
           "fcf_to_np_mean5": None, "fcf_neg_years": None,
           "ncr": ncr, "fcf_to_np": [],
           "periods": hist_periods(data.get("meta") or {}, n) or []}
    m = min(n, len(capex_h))
    if m >= 3:
        fcf = [o - c for o, c in zip(ocf_h[-m:], capex_h[-m:])]
        fcf_np = [f / p if p else None for f, p in zip(fcf, np_h[-m:])]
        fcf_ok = [x for x in fcf_np if x is not None]
        out["fcf_to_np_mean5"] = sum(fcf_ok) / len(fcf_ok) if fcf_ok else None
        out["fcf_neg_years"] = sum(1 for f in fcf if f < 0)
        # fcf 序列比 ncr 短（capex hist 不足）时前置补 null，保持与 periods 对齐；
        # capex hist<3 期时 fcf_to_np 整块为空数组（与均值同门槛——不足 3 期的
        # 逐期读数无趋势意义，不凑数）
        out["fcf_to_np"] = [None] * (n - m) + fcf_np
    return out




# ─────────────────────────── 薄校验（比对 derived 与复算值） ───────────────────────────

def check_risk_models(data, rep):
    rm = (data.get("derived") or {}).get("risk_models")
    if not isinstance(rm, dict):
        rep.add(SKIP, "risk-models", "derived.risk_models 未填")
        return
    alt, alt_why = compute_altman(data)
    node = rm.get("altman_z") or {}
    z_got = num(node.get("cur"))
    if z_got is None:
        if alt is None:
            rep.add(SKIP, "risk-models", "市值缺失（meta.market_cap_cur 未填），Altman 合法 null"
                    if alt_why == "no-mcap" else "Altman 分量字段不齐，合法 null")
        else:
            rep.add(FAIL, "risk-models", "Altman 分量齐全但 altman_z.cur 未填——漏做")
    elif alt is None:
        rep.add(FAIL, "risk-models", "市值缺失却填了 Altman Z——禁止无 X4 硬算（宁可空值不给错值）"
                if alt_why == "no-mcap" else "Altman 分量字段不齐却填了 z 值")
    else:
        bad = []
        if abs(z_got - alt["cur"]) > max(0.02 * abs(alt["cur"]), 0.05):
            bad.append(f"Altman Z 复算不符：derived={z_got} vs 重算={alt['cur']:.4f}")
        if node.get("zone") != alt["zone"]:
            bad.append(f"Altman zone=「{node.get('zone')}」与 Z={alt['cur']:.2f} 应判「{alt['zone']}」不符")
        if bool(node.get("annualized")) != alt["annualized"]:
            meta = data.get("meta") or {}
            bad.append(f"annualized={node.get('annualized')} 与 report_type "
                       f"「{meta.get('report_type')}」不符")
        for b in bad:
            rep.add(FAIL, "risk-models", b)
        if not bad:
            rep.add(OK, "risk-models", f"Altman Z={alt['cur']:.2f}（{alt['zone']}区）复算一致"
                                       + (f"（流量项已年化）" if alt["annualized"] else ""))
    ohl, ohl_why = compute_ohlson(data)
    node = rm.get("ohlson_o") or {}
    o_got = num(node.get("cur"))
    if o_got is None:
        if ohl is None:
            rep.add(SKIP, "risk-models", "Ohlson 分量字段不齐（含对比期净利润），合法 null")
        else:
            rep.add(FAIL, "risk-models", "Ohlson 分量齐全但 ohlson_o.cur 未填——漏做")
    elif ohl is None:
        rep.add(FAIL, "risk-models", "Ohlson 分量字段不齐却填了值")
    else:
        bad = []
        if abs(o_got - ohl["cur"]) > 0.01:
            bad.append(f"O 复算不符：derived={o_got} vs 重算={ohl['cur']:.4f}")
        prob_got = num(node.get("prob"))
        if prob_got is None or abs(prob_got - ohl["prob"]) > 0.005:
            bad.append(f"prob 不符：derived={prob_got} vs 重算={ohl['prob']:.4f}")
        if node.get("level") != ohl["level"]:
            bad.append(f"level=「{node.get('level')}」与 prob={ohl['prob']:.3f} 应判「{ohl['level']}」不符")
        for b in bad:
            rep.add(FAIL, "risk-models", "Ohlson " + b)
        if not bad:
            rep.add(OK, "risk-models", f"Ohlson O={ohl['cur']:.2f}、破产概率 {ohl['prob']:.3f}"
                                       f"（{ohl['level']}）复算一致")


def check_stress(data, rep):
    st = (data.get("derived") or {}).get("stress")
    if not isinstance(st, dict) or not isinstance(st.get("scenarios"), list):
        rep.add(SKIP, "stress", "derived.stress 未填")
        return
    exp = compute_stress(data)
    if exp is None:
        rep.add(SKIP, "stress", "压力情景输入不齐（DOL 分量/现金/短债缺），合法跳过")
        return
    bad = []
    for sc, e in zip(st["scenarios"], exp):
        p = num((sc or {}).get("p"))
        if p != e["p"]:
            bad.append(f"情景 p={p} 非法（只允许 0.1/0.2/0.3）")
            continue
        np_got, cover_got = num(sc.get("np_stressed")), num(sc.get("cover_stressed"))
        if np_got is None or abs(np_got - e["np_stressed"]) > max(0.02 * abs(e["np_stressed"]), 0.005):
            bad.append(f"p={p} 受压净利不符：derived={np_got} vs 重算={e['np_stressed']:.2f}")
        if cover_got is None or abs(cover_got - e["cover_stressed"]) > max(0.02 * abs(e["cover_stressed"]), 0.005):
            bad.append(f"p={p} 受压短债覆盖不符：derived={cover_got} vs 重算={e['cover_stressed']:.2f}")
    if bad:
        for b in bad[:6]:
            rep.add(FAIL, "stress", b)
    else:
        rep.add(OK, "stress", f"三情景复算一致（p=10% 受压净利 {exp[0]['np_stressed']:.1f} 亿，"
                              f"DOL={build_ratio_calcs(data).get('dol'):.2f}）")


def check_cash_ts(data, rep):
    ct = (data.get("derived") or {}).get("cash_ts")
    if not isinstance(ct, dict):
        rep.add(SKIP, "cash-ts", "derived.cash_ts 未填")
        return
    exp = compute_cash_ts(data)
    filled = any(ct.get(k) is not None for k in ("ncr_mean5", "ncr_neg_years",
                                                 "fcf_to_np_mean5", "fcf_neg_years"))
    if exp is None:
        if filled:
            rep.add(FAIL, "cash-ts", "hist 不足 3 期却填了时序读数——口径断裂期不得造数")
        else:
            rep.add(SKIP, "cash-ts", "hist 不足 3 期，时序读数合法 null")
        return
    bad = []
    for k in ("ncr_mean5", "fcf_to_np_mean5"):
        got, e = num(ct.get(k)), exp[k]
        if e is None:
            continue
        if got is None or abs(got - e) > 0.005:
            bad.append(f"{k} 不符：derived={got} vs 重算={e:.4f}")
    for k in ("ncr_neg_years", "fcf_neg_years"):
        if exp[k] is not None and num(ct.get(k)) != exp[k]:
            bad.append(f"{k} 不符：derived={ct.get(k)} vs 重算={exp[k]}")
    # v1.3 逐期数组复算（S1 现金时序表数据源）：填了就必须与复算一致
    for k in ("ncr", "fcf_to_np"):
        got = ct.get(k)
        if isinstance(got, list) and got:
            cmp_series(bad, f"cash_ts.{k}", got, exp.get(k))
    if ct.get("periods") and exp.get("periods") and ct["periods"] != exp["periods"]:
        bad.append(f"cash_ts.periods 与按 meta.period 倒推的 {exp['periods']} 不符")
    if bad:
        for b in bad:
            rep.add(FAIL, "cash-ts", b)
    else:
        rep.add(OK, "cash-ts", f"时序读数复算一致（净现比均值 {exp['ncr_mean5']:.4f}）")

