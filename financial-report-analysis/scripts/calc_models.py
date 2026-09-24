# -*- coding: utf-8 -*-
"""calc_models.py — calc.py 的模型复算层（v0.0.12 起，v0.0.13 加预填）。

四个模型检查（杜邦连环替代 / 破产双模型 / 压力情景 / 现金时序）均为
「纯计算函数 compute_* + 薄校验 check_*」结构：compute_* 是公式唯一定义处，
check_* 只比对 derived 与复算值；`calc.py --fill` 用同一批 compute_* 预填
derived 机械字段并产出填充速查表——模型不再手算公式，校验首遍即绿。
"""

import math
import pathlib

from calc_common import (FAIL, WARN, OK, SKIP, num, val, series_of,
                         build_ratio_calcs, ratio_hist_series, RATIO_HIST_SPECS)

# 中期报告流量年化因子（frameworks.md 〇 口径总则；复算本身即口径卡口——
# derived 填了未年化的流量分量就会复算不符 FAIL）
ANNUALIZE = {"年报": 1.0, "半年报": 2.0, "一季报": 4.0, "三季报": 4.0 / 3.0, "季报": 4.0 / 3.0}


# ─────────────────────────── 纯计算函数（公式唯一定义处） ───────────────────────────

def compute_dupont(data):
    """连环替代三效应（定序净利率→周转率→权益乘数）+ 两期三因子积 + 口径差 + 主驱动。
    三因子 cur/prev 任一缺失返回 None。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}

    def rv(name, key):
        node = ratios.get(name) or {}
        return num(node.get(key)) if isinstance(node, dict) else num(node)

    m1, m0 = rv("net_margin", "cur"), rv("net_margin", "prev")
    t1, t0 = rv("asset_turnover", "cur"), rv("asset_turnover", "prev")
    l1, l0 = rv("equity_multiplier", "cur"), rv("equity_multiplier", "prev")
    roe1, roe0 = rv("roe", "cur"), rv("roe", "prev")
    if None in (m1, m0, t1, t0, l1, l0):
        return None
    em = (m1 - m0) * t0 * l0
    et = m1 * (t1 - t0) * l0
    el = m1 * t1 * (l1 - l0)
    prod1, prod0 = m1 * t1 * l1, m0 * t0 * l0
    gap = (roe1 - roe0) - (prod1 - prod0) if None not in (roe1, roe0) else None
    effects = {"净利率": em, "周转率": et, "杠杆": el}
    return {"margin_effect": em, "turnover_effect": et, "leverage_effect": el,
            "roe_product_cur": prod1, "roe_product_prev": prod0, "closure_gap": gap,
            "driver": max(effects, key=lambda k: abs(effects[k]))}


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
    """现金验证时序读数：净现比/FCF 覆盖的均值与负值年数（分母归母净利）。
    hist <3 期返回 None（口径断裂合法 null）。"""
    ocf_h = [x for x in series_of(data, "cashflow", "ocf") if x is not None]
    np_h = [x for x in series_of(data, "income", "np_at") if x is not None]
    capex_h = [x for x in series_of(data, "cashflow", "capex") if x is not None]
    n = min(len(ocf_h), len(np_h))
    if n < 3:
        return None
    ocf_h, np_h = ocf_h[-n:], np_h[-n:]
    ncr = [o / p for o, p in zip(ocf_h, np_h) if p]
    out = {"ncr_mean5": sum(ncr) / len(ncr), "ncr_neg_years": sum(1 for o in ocf_h if o < 0),
           "fcf_to_np_mean5": None, "fcf_neg_years": None}
    m = min(n, len(capex_h))
    if m >= 3:
        fcf = [o - c for o, c in zip(ocf_h[-m:], capex_h[-m:])]
        fcf_np = [f / p for f, p in zip(fcf, np_h[-m:]) if p]
        out["fcf_to_np_mean5"] = sum(fcf_np) / len(fcf_np)
        out["fcf_neg_years"] = sum(1 for f in fcf if f < 0)
    return out


# ─────────────────────────── 薄校验（比对 derived 与复算值） ───────────────────────────

def check_dupont(data, rep):
    du = (data.get("derived") or {}).get("dupont")
    if not isinstance(du, dict) or all(du.get(k) is None for k in
                                       ("margin_effect", "turnover_effect", "leverage_effect")):
        rep.add(SKIP, "dupont", "derived.dupont 未填（缺同口径上期等合法情形）")
        return
    c = compute_dupont(data)
    if c is None:
        rep.add(FAIL, "dupont", "derived.dupont 已填但三因子 cur/prev 不齐——无算据的归因不成立")
        return
    bad = []
    for key in ("margin_effect", "turnover_effect", "leverage_effect",
                "roe_product_cur", "roe_product_prev"):
        got = num(du.get(key))
        if got is None:
            bad.append(f"{key} 未填")
        elif abs(got - c[key]) > 0.005:
            bad.append(f"{key} 不符：derived={got:.4f} vs 重算={c[key]:.4f}")
    if abs(c["margin_effect"] + c["turnover_effect"] + c["leverage_effect"]
           - (c["roe_product_cur"] - c["roe_product_prev"])) > 1e-9:
        rep.add(FAIL, "dupont", "连环替代恒等式不闭合（实现错误）")
    if c["closure_gap"] is not None:
        gap_got = num(du.get("closure_gap"))
        if gap_got is None:
            bad.append("closure_gap 未填（口径差必须标注，不许让三效应加和≈ΔROE 的假象过关）")
        elif abs(gap_got - c["closure_gap"]) > 0.005:
            bad.append(f"closure_gap 不符：derived={gap_got:.4f} vs 重算={c['closure_gap']:.4f}")
    if du.get("driver") and du.get("driver") != c["driver"]:
        bad.append(f"driver=「{du.get('driver')}」与最大 |贡献| 因子「{c['driver']}」不符")
    if bad:
        for b in bad[:5]:
            rep.add(FAIL, "dupont", b)
    else:
        rep.add(OK, "dupont", f"连环替代复算一致（净利率 {c['margin_effect']:+.4f} / "
                              f"周转率 {c['turnover_effect']:+.4f} / 杠杆 {c['leverage_effect']:+.4f}，加和闭合）")


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
    if bad:
        for b in bad:
            rep.add(FAIL, "cash-ts", b)
    else:
        rep.add(OK, "cash-ts", f"时序读数复算一致（净现比均值 {exp['ncr_mean5']:.4f}）")


# ─────────────────────────── --fill 预填 + 填充速查表（v0.0.13） ───────────────────────────

R4 = lambda x: None if x is None else round(x, 4)

# 方向语义（frameworks.md 方向语义表）：True=升为好 / False=降为好 / None=语境中性
GOOD_UP = {"gross_margin": True, "net_margin": True, "debt_to_assets": False,
           "dio": False, "dso": False, "cash_to_sales": True, "ccc": False,
           "dol": None, "dfl": None, "non_main_rev_share": None}
ROW_LABEL = {"gross_margin": "毛利率", "net_margin": "净利率", "debt_to_assets": "资产负债率",
             "dio": "存货周转天数", "dso": "应收周转天数", "cash_to_sales": "收现比",
             "ccc": "现金转换周期 CCC", "dol": "经营杠杆 DOL", "dfl": "财务杠杆 DFL",
             "non_main_rev_share": "非主营业务收入占比"}


_SINGLE_ITEMS = ("short_debt_cover", "incr_expense_eff", "incr_sales_eff",
                 "nonrecurring_share", "non_main_rev_share", "ocf_to_liab")


def fill_derived(data):
    """预填 derived 机械字段（判断字段 rev_factors/桥/recon/notes 不动）。返回改动计数。"""
    der = data.setdefault("derived", {})
    ratios = der.setdefault("ratios", {})
    calc = build_ratio_calcs(data)
    n = 0
    for name in RATIO_HIST_SPECS:
        cur = calc.get(name)
        series = [x for x in (ratio_hist_series(data, name) or []) if x is not None]
        old = ratios.get(name) or {}
        if cur is None and not series:
            continue
        node = dict(old)
        if cur is not None:
            node["cur"] = R4(cur)
            n += 1
        # hist 只补不缩：存量 hist 比可算序列长时保留（多出部分是分析师口径判断，
        # 如「2021 应收未单列按 0 计」），fill 不覆盖判断
        if series and len(series) >= len(old.get("hist") or []):
            node["hist"] = [R4(x) for x in series]
            if len(series) >= 2:
                node["prev"] = R4(series[-2])
                n += 1
        ratios[name] = node
    for name in _SINGLE_ITEMS:
        v = calc.get(name)
        if v is not None:
            old = ratios.get(name) or {}
            ratios[name] = {**old, "cur": R4(v)}
            n += 1
    du = compute_dupont(data)
    if du:
        old = der.get("dupont") or {}
        der["dupont"] = {**{k: R4(v) if isinstance(v, float) else v for k, v in du.items()},
                         **{k: old[k] for k in ("src", "note") if k in old}}
        n += 1
    alt, _ = compute_altman(data)
    ohl, _ = compute_ohlson(data)
    if alt or ohl:
        old = der.get("risk_models") or {}
        rm = {"altman_z": ({**{k: R4(v) if isinstance(v, float) else v for k, v in alt.items()},
                            **{k: old.get("altman_z", {})[k] for k in ("note",)
                               if isinstance(old.get("altman_z"), dict) and k in old.get("altman_z", {})}}
                           if alt else None),
              "ohlson_o": ({k: R4(v) if isinstance(v, float) else v for k, v in ohl.items()}
                           if ohl else None)}
        der["risk_models"] = rm
        n += 1
    st = compute_stress(data)
    if st:
        old = der.get("stress") or {}
        der["stress"] = {"scenarios": [{k: (R4(v) if isinstance(v, float) else v)
                                        for k, v in sc.items()} for sc in st],
                         **{k: old[k] for k in ("note",) if k in old}}
        n += 1
    cts = compute_cash_ts(data)
    if cts:
        old = der.get("cash_ts") or {}
        der["cash_ts"] = {**{k: (R4(v) if isinstance(v, float) else v) for k, v in cts.items()},
                          **{k: old[k] for k in ("note",) if k in old}}
        n += 1
    return n


def _spark_key(name):
    return {"gross_margin": "gm", "net_margin": "nm", "debt_to_assets": "da",
            "cash_to_sales": "c2s"}.get(name, name)


def write_fillsheet(data, path):
    """填充速查表：P8 机械槽位的值+徽章+语义色+SPARK 数组，模型照抄不进算术。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}
    L = []
    L.append("# 填充速查表（calc.py --fill 产出——机械槽位照抄，判断槽位自己写）\n")
    L.append("> 徽章：der=两数运算；语义色：up=利好/dn=利空/不染=语境中性（方向语义表）。")
    L.append("\n## S1 四维表（本期 / 上期 / 较上期 / SPARK hist）\n")
    L.append("| 指标 | 本期 | 上期 | 较上期 | 语义色 | badge |")
    L.append("|---|---|---|---|---|---|")
    for name, label in ROW_LABEL.items():
        node = ratios.get(name) or {}
        cur, prev = node.get("cur"), node.get("prev")
        d = None if (cur is None or prev is None) else cur - prev
        good = GOOD_UP[name]
        if d is None or good is None:
            cls = "不染"
        else:
            cls = "up" if (d > 0) == good else "dn"
        arrow = "—" if d is None else ("▲" if d > 0 else ("▼" if d < 0 else "→"))
        dv = "—" if d is None else f"{arrow} {abs(d):.4f}"
        L.append(f"| {label} | {cur} | {prev} | {dv} | {cls} | der |")
    L.append("\nSPARK 槽（JS 区粘贴）：")
    for name in ROW_LABEL:
        hist = (ratios.get(name) or {}).get("hist") or []
        L.append(f"- `SPARK.{_spark_key(name)}` = {hist}")
    du = (data.get("derived") or {}).get("dupont") or {}
    L.append("\n## S1 杜邦归因表 + 变迁表\n")
    L.append(f"- 三效应（pct）：净利率 {du.get('margin_effect')} / 周转率 {du.get('turnover_effect')} / "
             f"杠杆 {du.get('leverage_effect')}；主驱动={du.get('driver')}；"
             f"closure_gap={du.get('closure_gap')}")
    nm_h = (ratios.get("net_margin") or {}).get("hist") or []
    at_h = (ratios.get("asset_turnover") or {}).get("hist") or []
    em_h = (ratios.get("equity_multiplier") or {}).get("hist") or []
    roe_h = (ratios.get("roe") or {}).get("hist") or []
    L.append(f"- 变迁表列值：净利率 {nm_h} / 周转率 {at_h} / 权益乘数 {em_h} / ROE {roe_h}")
    rm = (data.get("derived") or {}).get("risk_models") or {}
    st = (data.get("derived") or {}).get("stress") or {}
    L.append("\n## S7 健康检验数值行\n")
    L.append(f"- 短债覆盖 {ratios.get('short_debt_cover', {}).get('cur')} 倍 · "
             f"X6 {ratios.get('ocf_to_liab', {}).get('cur')}")
    L.append(f"- Altman {rm.get('altman_z') or 'null（市值缺）'} · Ohlson {rm.get('ohlson_o') or 'null'}")
    L.append(f"- 压力情景 {st.get('scenarios') or 'null'}")
    L.append(f"- 增量费用效率 {ratios.get('incr_expense_eff', {}).get('cur')} · "
             f"获客效率 {ratios.get('incr_sales_eff', {}).get('cur')}")
    pathlib.Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")
