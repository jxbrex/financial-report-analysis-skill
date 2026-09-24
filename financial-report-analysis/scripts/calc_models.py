# -*- coding: utf-8 -*-
"""calc_models.py — calc.py 的模型复算层（v0.0.12）：杜邦连环替代 / 破产双模型 /
流动性压力情景 / 现金时序读数。四个检查都由 calc.py 主流程挂载。
"""

import math

from calc_common import (FAIL, WARN, OK, SKIP, num, val, series_of,
                         build_ratio_calcs)


# ───────────────────── 4c. 杜邦连环替代 / 破产模型 / 压力情景 / 现金时序 ─────────────────────

# 中期报告流量年化因子（frameworks.md 〇 口径总则；复算本身即口径卡口——
# derived 填了未年化的流量分量就会复算不符 FAIL）
ANNUALIZE = {"年报": 1.0, "半年报": 2.0, "一季报": 4.0, "三季报": 4.0 / 3.0, "季报": 4.0 / 3.0}


def check_dupont(data, rep):
    """杜邦连环替代（定序：净利率→周转率→权益乘数，三效应加和恒等于三因子积的 Δ）：
    复算 derived.dupont 三效应/两期三因子积/口径差/主驱动；全部 null（口径断裂等）→ SKIP。"""
    du = (data.get("derived") or {}).get("dupont")
    if not isinstance(du, dict) or all(du.get(k) is None for k in
                                       ("margin_effect", "turnover_effect", "leverage_effect")):
        rep.add(SKIP, "dupont", "derived.dupont 未填（缺同口径上期等合法情形）")
        return
    ratios = ((data.get("derived") or {}).get("ratios")) or {}

    def rv(name, key):
        node = ratios.get(name) or {}
        return num(node.get(key)) if isinstance(node, dict) else num(node)

    m1, m0 = rv("net_margin", "cur"), rv("net_margin", "prev")
    t1, t0 = rv("asset_turnover", "cur"), rv("asset_turnover", "prev")
    l1, l0 = rv("equity_multiplier", "cur"), rv("equity_multiplier", "prev")
    if None in (m1, m0, t1, t0, l1, l0):
        rep.add(FAIL, "dupont", "derived.dupont 已填但三因子 cur/prev 不齐——无算据的归因不成立")
        return
    em = (m1 - m0) * t0 * l0
    et = m1 * (t1 - t0) * l0
    el = m1 * t1 * (l1 - l0)
    prod1, prod0 = m1 * t1 * l1, m0 * t0 * l0
    bad = []
    for key, expect in (("margin_effect", em), ("turnover_effect", et), ("leverage_effect", el),
                        ("roe_product_cur", prod1), ("roe_product_prev", prod0)):
        got = num(du.get(key))
        if got is None:
            bad.append(f"{key} 未填")
        elif abs(got - expect) > 0.005:
            bad.append(f"{key} 不符：derived={got:.4f} vs 重算={expect:.4f}")
    if abs(em + et + el - (prod1 - prod0)) > 1e-9:
        rep.add(FAIL, "dupont", "连环替代恒等式不闭合（实现错误）")
    roe1, roe0 = rv("roe", "cur"), rv("roe", "prev")
    if roe1 is not None and roe0 is not None:
        gap_expect = (roe1 - roe0) - (prod1 - prod0)
        gap_got = num(du.get("closure_gap"))
        if gap_got is None:
            bad.append("closure_gap 未填（口径差必须标注，不许让三效应加和≈ΔROE 的假象过关）")
        elif abs(gap_got - gap_expect) > 0.005:
            bad.append(f"closure_gap 不符：derived={gap_got:.4f} vs 重算={gap_expect:.4f}")
    driver = du.get("driver")
    if driver:
        effects = {"净利率": em, "周转率": et, "杠杆": el}
        top = max(effects, key=lambda k: abs(effects[k]))
        if driver != top:
            bad.append(f"driver=「{driver}」与最大 |贡献| 因子「{top}」不符")
    if bad:
        for b in bad[:5]:
            rep.add(FAIL, "dupont", b)
    else:
        rep.add(OK, "dupont", f"连环替代复算一致（净利率 {em:+.4f} / 周转率 {et:+.4f} / "
                              f"杠杆 {el:+.4f}，加和闭合）")


def check_risk_models(data, rep):
    """破产风险双模型（frameworks.md 第三节，谨慎使用）：Altman Z + Ohlson O 复算。
    市值缺失 → Altman 合法 null（宁可空值不给错值）；填了但可复算 → FAIL。"""
    rm = (data.get("derived") or {}).get("risk_models")
    if not isinstance(rm, dict):
        rep.add(SKIP, "risk-models", "derived.risk_models 未填")
        return
    B = lambda f: val(data, "statements", "balance", f)
    I = lambda f, key="cur": val(data, "statements", "income", f, key=key)
    meta = data.get("meta") or {}
    factor = ANNUALIZE.get(meta.get("report_type"))
    ta, tl = B("total_assets"), B("total_liab")
    tca, tcl = B("total_cur_assets"), B("total_cur_liab")
    retained, surplus = B("retained_cur"), B("surplus_reserve")
    np_total, tax, fin = I("np_total"), I("income_tax"), I("fin_exp")
    rev = I("revenue")
    mcap = meta.get("market_cap_cur")
    ebit = None if None in (np_total, tax, fin) else np_total + tax + fin
    inputs_full = None not in (ta, tl, tca, tcl, retained, surplus, ebit, rev)

    # ── Altman Z（X4 市值/总负债，市值单位=亿元；中期报告流量项年化） ──
    node = rm.get("altman_z") or {}
    z_got = num(node.get("cur"))
    if factor is None:
        rep.add(WARN, "risk-models", f"report_type=「{meta.get('report_type')}」不在年化因子表，"
                                     f"破产模型口径无法校验")
    elif z_got is None:
        if mcap is None:
            rep.add(SKIP, "risk-models", "市值缺失（meta.market_cap_cur 未填），Altman 合法 null")
        elif not inputs_full:
            rep.add(SKIP, "risk-models", "Altman 分量字段不齐（流动资产/流动负债等），合法 null")
        else:
            rep.add(FAIL, "risk-models", "Altman 分量齐全但 altman_z.cur 未填——漏做")
    else:
        if mcap is None:
            rep.add(FAIL, "risk-models", "市值缺失却填了 Altman Z——禁止无 X4 硬算（宁可空值不给错值）")
        elif not inputs_full:
            rep.add(FAIL, "risk-models", "Altman 分量字段不齐却填了 z 值")
        else:
            rev_ann = rev * factor
            x1 = (tca - tcl) / ta
            x2 = (retained + surplus) / ta
            x3 = ebit / ta
            x4 = mcap / tl
            x5 = rev_ann / ta
            z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
            zone = "安全" if z > 2.99 else ("灰色" if z > 1.81 else "危险")
            if abs(z_got - z) > max(0.02 * abs(z), 0.05):
                rep.add(FAIL, "risk-models", f"Altman Z 复算不符：derived={z_got} vs 重算={z:.4f}")
            elif node.get("zone") != zone:
                rep.add(FAIL, "risk-models", f"Altman zone=「{node.get('zone')}」与 Z={z:.2f} 应判「{zone}」不符")
            elif bool(node.get("annualized")) != (factor != 1.0):
                rep.add(FAIL, "risk-models", f"annualized={node.get('annualized')} 与 report_type "
                                             f"「{meta.get('report_type')}」（因子×{factor:g}）不符")
            else:
                rep.add(OK, "risk-models", f"Altman Z={z:.2f}（{zone}区）复算一致"
                                           + (f"（流量项已年化 ×{factor:g}）" if factor != 1.0 else ""))

    # ── Ohlson O（简化六因子；ln 的总资产单位=亿元；X6 缺对比期净利则整块 null） ──
    node = rm.get("ohlson_o") or {}
    o_got = num(node.get("cur"))
    np_prev = I("np_total", key="prev")
    if o_got is None:
        if not inputs_full or np_prev is None:
            rep.add(SKIP, "risk-models", "Ohlson 分量字段不齐（含对比期净利润），合法 null")
        else:
            rep.add(FAIL, "risk-models", "Ohlson 分量齐全但 ohlson_o.cur 未填——漏做")
    else:
        if not inputs_full or np_prev is None:
            rep.add(FAIL, "risk-models", "Ohlson 分量字段不齐却填了值")
        else:
            wc = tca - tcl
            x6 = (np_total - np_prev) / (abs(np_total) + abs(np_prev))
            o = (-1.32 - 0.407 * math.log(ta) + 6.03 * tl / ta - 1.43 * wc / ta
                 + 0.0757 * tcl / tca - 1.72 * (1 if tl > ta else 0) - 0.521 * x6)
            prob = 1.0 / (1.0 + math.exp(-o))
            level = "高" if prob > 0.5 else ("中" if prob > 0.15 else "低")
            bad = []
            if abs(o_got - o) > 0.01:
                bad.append(f"O 复算不符：derived={o_got} vs 重算={o:.4f}")
            prob_got = num(node.get("prob"))
            if prob_got is None or abs(prob_got - prob) > 0.005:
                bad.append(f"prob 不符：derived={prob_got} vs 重算={prob:.4f}")
            if node.get("level") != level:
                bad.append(f"level=「{node.get('level')}」与 prob={prob:.3f} 应判「{level}」不符")
            if bad:
                for b in bad:
                    rep.add(FAIL, "risk-models", "Ohlson " + b)
            else:
                rep.add(OK, "risk-models", f"Ohlson O={o:.2f}、破产概率 {prob:.3f}（{level}）复算一致")


def check_stress(data, rep):
    """流动性压力情景（frameworks.md 第九节）：DOL/DFL 传导三情景复算。
    受压EBIT=EBIT×(1−p×DOL)；受压税前=受压EBIT−fin_exp；受压净利=受压税前×(1−有效税率)，
    受压税前 ≤0 时不再计税收抵免（保守）；受压短债覆盖=(cash+ocf×(1−p))÷短债。"""
    st = (data.get("derived") or {}).get("stress")
    if not isinstance(st, dict) or not isinstance(st.get("scenarios"), list):
        rep.add(SKIP, "stress", "derived.stress 未填")
        return
    I = lambda f: val(data, "statements", "income", f)
    B = lambda f: val(data, "statements", "balance", f)
    C = lambda f: val(data, "statements", "cashflow", f)
    np_total, tax, fin = I("np_total"), I("income_tax"), I("fin_exp")
    cash, ocf = B("cash"), C("ocf")
    st_debt, noncur = B("st_debt"), B("noncur_due_1y")
    short_debt = None if (st_debt is None and noncur is None) else (st_debt or 0) + (noncur or 0)
    # DOL 复用全脚本唯一定义处（ratio_hist_expect，经 build_ratio_calcs 委托）——
    # 禁止内联重算（v0.0.9 热核审计修掉的「公式双份维护」模式）
    dol = build_ratio_calcs(data).get("dol")
    if None in (np_total, tax, fin, cash, ocf, dol) or not short_debt:
        rep.add(SKIP, "stress", "压力情景输入不齐（DOL 分量/现金/短债缺），合法跳过")
        return
    ebit = np_total + tax + fin
    ebt = np_total + tax
    tax_rate = min(max(tax / ebt, 0.0), 0.35) if ebt > 0 else 0.0
    bad = []
    for sc in st["scenarios"]:
        p = num((sc or {}).get("p"))
        if p not in (0.1, 0.2, 0.3):
            bad.append(f"情景 p={p} 非法（只允许 0.1/0.2/0.3）")
            continue
        ebit_s = ebit * (1 - p * dol)
        ebt_s = ebit_s - fin
        np_s = ebt_s * (1 - tax_rate) if ebt_s > 0 else ebt_s
        cover_s = (cash + ocf * (1 - p)) / short_debt
        np_got, cover_got = num(sc.get("np_stressed")), num(sc.get("cover_stressed"))
        if np_got is None or abs(np_got - np_s) > max(0.02 * abs(np_s), 0.5):
            bad.append(f"p={p} 受压净利不符：derived={np_got} vs 重算={np_s:.2f}")
        if cover_got is None or abs(cover_got - cover_s) > max(0.02 * abs(cover_s), 0.05):
            bad.append(f"p={p} 受压短债覆盖不符：derived={cover_got} vs 重算={cover_s:.2f}")
    if bad:
        for b in bad[:6]:
            rep.add(FAIL, "stress", b)
    else:
        np_10 = num(st["scenarios"][0].get("np_stressed"))
        rep.add(OK, "stress", f"三情景复算一致（p=10% 受压净利 {np_10:.1f} 亿，DOL={dol:.2f}）")


def check_cash_ts(data, rep):
    """现金验证时序读数（frameworks.md 第五节）：净现比/FCF 覆盖的 5 期均值与负值年数。
    hist <3 期（口径断裂等）→ 整块必须 null，填了 → FAIL。"""
    ct = (data.get("derived") or {}).get("cash_ts")
    if not isinstance(ct, dict):
        rep.add(SKIP, "cash-ts", "derived.cash_ts 未填")
        return
    ocf_h = series_of(data, "cashflow", "ocf")
    np_h = series_of(data, "income", "np_at")
    capex_h = series_of(data, "cashflow", "capex")
    filled = any(ct.get(k) is not None for k in ("ncr_mean5", "ncr_neg_years",
                                                 "fcf_to_np_mean5", "fcf_neg_years"))
    n = min(len(ocf_h), len(np_h))
    if n < 3:
        if filled:
            rep.add(FAIL, "cash-ts", f"hist 仅 {n} 期（<3）却填了时序读数——口径断裂期不得造数")
        else:
            rep.add(SKIP, "cash-ts", f"hist 仅 {n} 期（<3），时序读数合法 null")
        return
    ocf_h, np_h = ocf_h[-n:], np_h[-n:]
    ncr = [o / p for o, p in zip(ocf_h, np_h) if p]
    bad = []
    got = num(ct.get("ncr_mean5"))
    if got is None or abs(got - sum(ncr) / len(ncr)) > 0.005:
        bad.append(f"ncr_mean5 不符：derived={got} vs 重算={sum(ncr) / len(ncr):.4f}")
    neg = sum(1 for o in ocf_h if o < 0)
    if num(ct.get("ncr_neg_years")) != neg:
        bad.append(f"ncr_neg_years 不符：derived={ct.get('ncr_neg_years')} vs 重算={neg}")
    # FCF 部分：capex hist 不足时 fcf 两键必须 null，填了 → FAIL
    m = min(len(ocf_h), len(np_h), len(capex_h))
    fcf_keys_filled = ct.get("fcf_to_np_mean5") is not None or ct.get("fcf_neg_years") is not None
    if m < 3:
        if fcf_keys_filled:
            bad.append(f"capex hist 仅 {m} 期（<3）却填了 FCF 读数")
    else:
        fcf = [o - c for o, c in zip(ocf_h[-m:], capex_h[-m:])]
        npw = np_h[-m:]
        fcf_np = [f / p for f, p in zip(fcf, npw) if p]
        got = num(ct.get("fcf_to_np_mean5"))
        if got is None or abs(got - sum(fcf_np) / len(fcf_np)) > 0.005:
            bad.append(f"fcf_to_np_mean5 不符：derived={got} vs 重算={sum(fcf_np) / len(fcf_np):.4f}")
        fneg = sum(1 for f in fcf if f < 0)
        if num(ct.get("fcf_neg_years")) != fneg:
            bad.append(f"fcf_neg_years 不符：derived={ct.get('fcf_neg_years')} vs 重算={fneg}")
    if bad:
        for b in bad:
            rep.add(FAIL, "cash-ts", b)
    else:
        rep.add(OK, "cash-ts", f"时序读数复算一致（净现比 {n} 期均值 {sum(ncr) / len(ncr):.4f}）")

