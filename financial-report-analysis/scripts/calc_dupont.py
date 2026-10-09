# -*- coding: utf-8 -*-
"""calc_dupont.py — 杜邦族（v0.0.15 拆分自 calc_models.py）：连环替代当期/扣非/五年三口径
共用 `_chain`（公式只此一份）+ 因子下钻（margin/turnover/leverage drill）+ 五年累计归因 +
因子分位 + 双驱动护栏。compute_* 为公式唯一定义处，check_* 只做比对；
方法论与判读规则见 references/frameworks.md 第二节。
"""

from calc_common import (FAIL, OK, SKIP, num, val, safe_div, hist_periods, cmp_fields,
                         parts_sum)

# ─────────────────────────── 纯计算函数（公式唯一定义处） ───────────────────────────

def _chain(m0, m1, t0, t1, l0, l1, roe0, roe1):
    """连环替代核心（定序净利率→周转率→权益乘数）——compute_dupont / compute_dupont_dt /
    compute_dupont5y 共用，公式只此一份。任一因子缺失返回 None。
    双驱动护栏：第一、二大 |效应| 之比 <1.5 → driver_fragile=True（报告标「双驱动（X/Y）」）。"""
    if None in (m1, m0, t1, t0, l1, l0):
        return None
    em = (m1 - m0) * t0 * l0
    et = m1 * (t1 - t0) * l0
    el = m1 * t1 * (l1 - l0)
    prod1, prod0 = m1 * t1 * l1, m0 * t0 * l0
    gap = (roe1 - roe0) - (prod1 - prod0) if None not in (roe1, roe0) else None
    effects = {"净利率": em, "周转率": et, "杠杆": el}
    ranked = sorted(effects, key=lambda k: abs(effects[k]), reverse=True)
    first, second = abs(effects[ranked[0]]), abs(effects[ranked[1]])
    if first < 1e-12:
        # 三效应全零（ROE 未动）：主驱动不适用，禁止 stable sort 恒落「净利率」的无中生有
        return {"margin_effect": em, "turnover_effect": et, "leverage_effect": el,
                "roe_product_cur": prod1, "roe_product_prev": prod0, "closure_gap": gap,
                "driver": None, "driver_fragile": None, "effects_ratio": None,
                "driver_second": None}
    ratio = None if second < 1e-12 else first / second
    return {"margin_effect": em, "turnover_effect": et, "leverage_effect": el,
            "roe_product_cur": prod1, "roe_product_prev": prod0, "closure_gap": gap,
            "driver": ranked[0], "driver_fragile": (None if ratio is None else ratio < 1.5),
            "effects_ratio": ratio, "driver_second": ranked[1]}


def compute_dupont(data):
    """当期连环替代（ratios 的 cur/prev 两期）+ v1.3 三因子下钻。
    三因子 cur/prev 任一缺失返回 None。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}

    def rv(name, key):
        node = ratios.get(name) or {}
        return num(node.get(key)) if isinstance(node, dict) else num(node)

    out = _chain(rv("net_margin", "prev"), rv("net_margin", "cur"),
                 rv("asset_turnover", "prev"), rv("asset_turnover", "cur"),
                 rv("equity_multiplier", "prev"), rv("equity_multiplier", "cur"),
                 rv("roe", "prev"), rv("roe", "cur"))
    if out is None:
        return None
    out["margin_drill"] = compute_margin_drill(data)
    out["turnover_drill"] = compute_turnover_drill(data)
    out["leverage_drill"] = compute_leverage_drill(data, out)
    return out


def compute_margin_drill(data):
    """净利率恒等四项分解（v1.3，F-01/F-03）：
    np_at/rev ≡ EBIT/rev − fin_exp/rev − tax/rev − minority/rev，
    故 Δ净利率 = op_effect + tax_effect + interest_effect + minority_effect（严格闭合）。
    字段不齐返回 None。"""
    I = lambda f, key="cur": val(data, "statements", "income", f, key=key)
    rev1, rev0 = I("revenue"), I("revenue", key="prev")
    npa1, npa0 = I("np_at"), I("np_at", key="prev")
    npt1, npt0 = I("np_total"), I("np_total", key="prev")
    tax1, tax0 = I("income_tax"), I("income_tax", key="prev")
    fin1, fin0 = I("fin_exp"), I("fin_exp", key="prev")
    if None in (rev1, rev0, npa1, npa0, npt1, npt0, tax1, tax0, fin1, fin0) or not rev1 or not rev0:
        return None
    ebit = lambda npt, tax, fin, rev: (npt + tax + fin) / rev
    return {"op_effect": ebit(npt1, tax1, fin1, rev1) - ebit(npt0, tax0, fin0, rev0),
            "tax_effect": -(tax1 / rev1 - tax0 / rev0),
            "interest_effect": -(fin1 / rev1 - fin0 / rev0),
            "minority_effect": -((npt1 - npa1) / rev1 - (npt0 - npa0) / rev0)}


# 周转率资产堆积定位的科目集合（两期均提取才参与；标签供模板子行，分组供聚合份额）
TURNOVER_SUBJECTS = [
    ("ar", "应收账款", "wc"), ("ar_notes", "应收票据", "wc"), ("other_ar", "其他应收款", "wc"),
    ("inventory", "存货", "wc"), ("cip", "在建工程", "capex"), ("fixed_assets", "固定资产", "capex"),
    ("cash", "货币资金", "other"), ("restricted_cash", "受限资金", "other"),
    ("goodwill", "商誉", "other"), ("fin_assets", "金融资产", "other"),
    ("prepayment", "预付款项", "other"),
]


def compute_turnover_drill(data):
    """Δ总资产科目贡献定位（v1.3，F-01）：share 分母=Δ总资产（保留符号）。
    总资产基本未动（|ΔTA| < 1%·TA）时返回 None——定位无意义。"""
    B = lambda f, key="cur": val(data, "statements", "balance", f, key=key)
    ta1, ta0 = B("total_assets"), B("total_assets", key="prev")
    if None in (ta1, ta0) or not ta0 or abs(ta1 - ta0) < 0.01 * abs(ta0):
        return None
    dta = ta1 - ta0
    deltas = []
    for f, label, grp in TURNOVER_SUBJECTS:
        cur, prev = B(f), B(f, key="prev")
        if cur is None or prev is None:
            continue
        deltas.append((label, cur - prev, grp))
    if not deltas:
        return None
    ranked = sorted(deltas, key=lambda x: abs(x[1]), reverse=True)
    agg = {"wc": 0.0, "capex": 0.0}
    for _, d, grp in deltas:
        if grp in agg:
            agg[grp] += d
    return {"top1_subject": ranked[0][0], "top1_share": ranked[0][1] / dta,
            "top2_subject": ranked[1][0] if len(ranked) > 1 else "",
            "top2_share": (ranked[1][1] / dta) if len(ranked) > 1 else None,
            "wc_share": agg["wc"] / dta, "capex_share": agg["capex"] / dta}


def compute_leverage_drill(data, dupont=None):
    """有息/无息杠杆拆解 + 话语权型杠杆升档判定（v1.3，F-02）。
    有息 = st_debt+noncur_due_1y+lt_debt；无息 = payable+contract_liab（不含其他应付款，
    schema 无此字段——口径声明，不假装完整）；各自 null 按 0 计、全 null 才 None。
    quality_upgrade：杠杆为主驱动且 ni_share>0.7 且 |ΔDFL|<0.1 → True（经验阈值，
    随样本校准，报告只作提醒级呈现）；杠杆非主驱动 → None（不适用）。"""
    B = lambda f, key="cur": val(data, "statements", "balance", f, key=key)
    parts = lambda fields, key: parts_sum(data, fields, key)  # 口径唯一定义处在 calc_common

    ib1, ib0 = parts(("st_debt", "noncur_due_1y", "lt_debt"), "cur"), \
               parts(("st_debt", "noncur_due_1y", "lt_debt"), "prev")
    ni1, ni0 = parts(("payable", "contract_liab"), "cur"), parts(("payable", "contract_liab"), "prev")
    eq = B("equity_at")
    ratios = ((data.get("derived") or {}).get("ratios")) or {}
    dfl = ratios.get("dfl")
    dfl1, dfl0 = (num(dfl.get("cur")), num(dfl.get("prev"))) if isinstance(dfl, dict) \
        else (num(dfl), None)  # 裸数字节点只有 cur 可言，prev 按缺处理（不崩）
    dfl_delta = None if None in (dfl1, dfl0) else dfl1 - dfl0
    ni_share = None if ni1 is None or ib1 is None or not (ni1 + ib1) else ni1 / (ni1 + ib1)
    upgrade = None
    if (dupont or {}).get("driver") == "杠杆" and ni_share is not None and dfl_delta is not None:
        upgrade = ni_share > 0.7 and abs(dfl_delta) < 0.1
    return {"ib_cur": ib1, "ib_prev": ib0, "ni_cur": ni1, "ni_prev": ni0,
            "ib_to_equity_cur": safe_div(ib1, eq), "ni_to_equity_cur": safe_div(ni1, eq),
            "ni_share": ni_share, "dfl_delta": dfl_delta, "quality_upgrade": upgrade}


def compute_dupont_dt(data):
    """扣非口径双版归因（v1.3，F-04）：扣非净利率（np_dt÷rev）替换净利率因子重跑连环替代。
    触发条件：nonrecurring_share>0.2 或 |净利率−扣非净利率|>0.01。
    返回 {"triggered": False}（未触发）/ 完整结果（触发）/ {"triggered": None}（np_dt 未提取）。"""
    I = lambda f, key="cur": val(data, "statements", "income", f, key=key)
    B = lambda f, key="cur": val(data, "statements", "balance", f, key=key)
    np_dt1, np_dt0 = I("np_dt"), I("np_dt", key="prev")
    rev1, rev0 = I("revenue"), I("revenue", key="prev")
    if None in (np_dt1, np_dt0, rev1, rev0) or not rev1 or not rev0:
        return {"triggered": None}
    ratios = ((data.get("derived") or {}).get("ratios")) or {}

    def rv(name, key):
        node = ratios.get(name) or {}
        return num(node.get(key)) if isinstance(node, dict) else num(node)

    nm_dt1, nm_dt0 = np_dt1 / rev1, np_dt0 / rev0
    nm1 = rv("net_margin", "cur")
    share = num((ratios.get("nonrecurring_share") or {}).get("cur"))
    triggered = bool(share is not None and abs(share) > 0.2)
    if nm1 is not None and abs(nm1 - nm_dt1) > 0.01:
        triggered = True
    if not triggered:
        return {"triggered": False}
    eq1, eq0 = B("equity_at"), B("equity_at", key="prev")
    roe_dt1 = None if None in (np_dt1, eq1) or not eq1 else np_dt1 / eq1
    roe_dt0 = None if None in (np_dt0, eq0) or not eq0 else np_dt0 / eq0
    out = _chain(nm_dt0, nm_dt1, rv("asset_turnover", "prev"), rv("asset_turnover", "cur"),
                 rv("equity_multiplier", "prev"), rv("equity_multiplier", "cur"),
                 roe_dt0, roe_dt1)
    if out is None:
        return {"triggered": True}
    out["triggered"] = True
    return out




def _percentile(cur, hist):
    """因子分位（方案D）：cur 在 hist（含 cur）中的位置读数 (rank−1)/(n−1)。
    等值约定：并列取最小秩（ties → min-rank）。n=5 时离散步长 25%——呈现禁用统计显著性
    措辞。n<2 返回 None。"""
    vals = [x for x in hist if x is not None]
    n = len(vals)
    if n < 2 or cur is None:
        return None
    rank = 1 + sum(1 for x in vals if x < cur)
    return (rank - 1) / (n - 1)


def compute_dupont5y(data):
    """五年累计归因 + 因子分位（v1.3，方案 A+D）：ratios hist 首末两期端点间一次连环替代。
    三因子 hist 任一 <3 期返回 None（口径断裂合法 null）。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}

    def hist(name):
        node = ratios.get(name)
        if not isinstance(node, dict):
            return []  # 裸数字等畸形节点无 hist 可言，按缺序列处理（不崩）
        return [num(x) for x in (node.get("hist") or [])]

    mh, th, lh, rh = (hist(n) for n in
                      ("net_margin", "asset_turnover", "equity_multiplier", "roe"))
    if min(len(mh), len(th), len(lh)) < 3:
        return None
    n = min(len(mh), len(th), len(lh))
    mh, th, lh = mh[-n:], th[-n:], lh[-n:]
    out = _chain(mh[0], mh[-1], th[0], th[-1], lh[0], lh[-1],
                 rh[-n] if len(rh) >= n else None, rh[-1] if rh else None)
    if out is None:
        return None
    periods = hist_periods(data.get("meta") or {}, n)
    out["period_start"] = periods[0] if periods else ""
    out["period_end"] = periods[-1] if periods else ""
    out["roe_start"] = rh[-n] if len(rh) >= n else None
    out["roe_end"] = rh[-1] if rh else None
    out["percentile"] = {"net_margin": _percentile(mh[-1], mh),
                         "asset_turnover": _percentile(th[-1], th),
                         "equity_multiplier": _percentile(lh[-1], lh)}
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
    cmp_fields(bad, "dupont", du, c,
               ("margin_effect", "turnover_effect", "leverage_effect",
                "roe_product_cur", "roe_product_prev"))
    # effects_ratio 单独判：单驱动（第二大 |效应|≈0）或三效应全零时复算为 None，
    # null 是 schema 合法形态——只要求 derived 同填 null/缺失，不逼分析师造数
    er_got, er_exp = num(du.get("effects_ratio")), c["effects_ratio"]
    if er_exp is None:
        if er_got is not None:
            bad.append(f"effects_ratio={er_got} 但单驱动/三效应全零形态应为 null")
    elif er_got is None:
        bad.append("effects_ratio 未填")
    elif abs(er_got - er_exp) > 0.005:
        bad.append(f"effects_ratio 不符：derived={er_got} vs 重算={er_exp:.4f}")
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
    if du.get("driver_fragile") is not None and du.get("driver_fragile") != c["driver_fragile"]:
        bad.append(f"driver_fragile={du.get('driver_fragile')} 与重算 {c['driver_fragile']} 不符"
                   f"（effects_ratio={c['effects_ratio']}，双驱动护栏边界 1.5）")
    if du.get("driver_fragile") and not du.get("driver_second"):
        bad.append("driver_fragile=true 但 driver_second 未填——「双驱动（X/Y）」标签缺 Y")
    _check_drills(data, du, c, bad)
    if bad:
        for b in bad[:5]:
            rep.add(FAIL, "dupont", b)
    else:
        rep.add(OK, "dupont", f"连环替代复算一致（净利率 {c['margin_effect']:+.4f} / "
                              f"周转率 {c['turnover_effect']:+.4f} / 杠杆 {c['leverage_effect']:+.4f}，加和闭合）"
                              + ("（双驱动护栏命中）" if c["driver_fragile"] else ""))


def _check_drills(data, du, c, bad):
    """v1.3 因子下钻复算（F-01/02/03）：块缺失=老 json 合法 SKIP；填了就必须与复算一致。"""
    if not any(k in du for k in ("margin_drill", "turnover_drill", "leverage_drill")):
        return
    md, ce = du.get("margin_drill"), c.get("margin_drill")
    if md is not None:
        if ce is None:
            bad.append("margin_drill 已填但 income 字段不齐无法复算——无算据的下钻不成立")
        elif isinstance(md, dict):
            cmp_fields(bad, "margin_drill", md, ce,
                       ("op_effect", "tax_effect", "interest_effect", "minority_effect"))
            s = sum(num(md.get(k)) or 0 for k in
                    ("op_effect", "tax_effect", "interest_effect", "minority_effect"))
            ratios = ((data.get("derived") or {}).get("ratios")) or {}
            nm = ratios.get("net_margin")
            nm1 = num(nm.get("cur")) if isinstance(nm, dict) else num(nm)
            nm0 = num(nm.get("prev")) if isinstance(nm, dict) else None
            if None not in (nm1, nm0) and abs(s - (nm1 - nm0)) > 0.005:
                bad.append(f"margin_drill 四项加和 {s:+.4f} ≠ Δ净利率 {nm1 - nm0:+.4f}——恒等分解不闭合")
    td, ce = du.get("turnover_drill"), c.get("turnover_drill")
    if td is not None:
        if ce is None:
            bad.append("turnover_drill 已填但总资产未动（|ΔTA|<1%）或字段不齐——该块应整为 null")
        elif isinstance(td, dict):
            if td.get("top1_subject") != ce["top1_subject"]:
                bad.append(f"turnover_drill.top1=「{td.get('top1_subject')}」与重算「{ce['top1_subject']}」不符")
            cmp_fields(bad, "turnover_drill", td, ce,
                       ("top1_share", "top2_share", "wc_share", "capex_share"), tol=0.02)
    ld, ce = du.get("leverage_drill"), c.get("leverage_drill")
    if ld is not None:
        if ce is None:
            bad.append("leverage_drill 已填但无法复算")
        elif isinstance(ld, dict):
            cmp_fields(bad, "leverage_drill", ld, ce,
                       ("ib_cur", "ib_prev", "ni_cur", "ni_prev",
                        "ib_to_equity_cur", "ni_to_equity_cur", "ni_share", "dfl_delta"),
                       tol=lambda e: max(0.02 * abs(e), 0.005), skip_none=True)
            if ld.get("quality_upgrade") is not None and ld.get("quality_upgrade") != ce["quality_upgrade"]:
                bad.append(f"leverage_drill.quality_upgrade={ld.get('quality_upgrade')} 与重算 "
                           f"{ce['quality_upgrade']} 不符（话语权型杠杆升档判定）")


def check_dupont_dt(data, rep):
    dt = (data.get("derived") or {}).get("dupont_dt")
    if not isinstance(dt, dict):
        rep.add(SKIP, "dupont-dt", "derived.dupont_dt 未填（v1.3 前存量合法）")
        return
    c = compute_dupont_dt(data)
    if c.get("triggered") is None:
        # np_dt 未提取：触发条件无法判定——不判「未触发」（无法判定≠未触发）
        if dt.get("triggered"):
            rep.add(FAIL, "dupont-dt", "triggered=true 但 np_dt 未提取，扣非口径无法复算")
        else:
            rep.add(SKIP, "dupont-dt", "np_dt 未提取，扣非触发条件无法判定（合法缺省）")
        return
    if dt.get("triggered") in (None, False):
        if c.get("triggered") is True:
            rep.add(FAIL, "dupont-dt", "扣非触发条件命中（非经占比>20% 或口径差>1pct）但 dupont_dt "
                                       "未填——含非经的净利率被误读为主业改善的风险不提示")
        else:
            rep.add(OK, "dupont-dt", "扣非双版未触发，单版归因合法")
        return
    if c.get("triggered") is not True or c.get("margin_effect") is None:
        rep.add(FAIL, "dupont-dt", "triggered=true 但扣非口径分量不齐（np_dt/ratios 缺），无法复算")
        return
    bad = []
    cmp_fields(bad, "dupont_dt", dt, c, ("margin_effect", "turnover_effect", "leverage_effect"))
    if dt.get("driver") and dt.get("driver") != c["driver"]:
        bad.append(f"扣非口径 driver=「{dt.get('driver')}」与重算「{c['driver']}」不符")
    if bad:
        for b in bad[:5]:
            rep.add(FAIL, "dupont-dt", b)
    else:
        rep.add(OK, "dupont-dt", f"扣非双版复算一致（扣非主驱动={c['driver']}）")


def check_dupont5y(data, rep):
    d5 = (data.get("derived") or {}).get("dupont5y")
    if not isinstance(d5, dict) or all(d5.get(k) is None for k in
                                       ("margin_effect", "turnover_effect", "leverage_effect")):
        rep.add(SKIP, "dupont5y", "derived.dupont5y 未填（hist<3 期口径断裂等合法情形）")
        return
    c = compute_dupont5y(data)
    if c is None:
        rep.add(FAIL, "dupont5y", "dupont5y 已填但三因子 hist<3 期——口径断裂期不得造数")
        return
    bad = []
    cmp_fields(bad, "dupont5y", d5, c,
               ("margin_effect", "turnover_effect", "leverage_effect",
                "roe_start", "roe_end", "closure_gap"), skip_none=True)
    if abs(c["margin_effect"] + c["turnover_effect"] + c["leverage_effect"]
           - (c["roe_product_cur"] - c["roe_product_prev"])) > 1e-9:
        rep.add(FAIL, "dupont5y", "五年连环替代恒等式不闭合（实现错误）")
    if d5.get("driver") and d5.get("driver") != c["driver"]:
        bad.append(f"五年主驱动=「{d5.get('driver')}」与重算「{c['driver']}」不符")
    for key in ("period_start", "period_end"):
        if c.get(key) and d5.get(key) and d5.get(key) != c[key]:
            bad.append(f"dupont5y.{key}=「{d5.get(key)}」与按 meta.period 倒推的「{c[key]}」不符")
    pg, pc = d5.get("percentile") or {}, c.get("percentile") or {}
    for k in ("net_margin", "asset_turnover", "equity_multiplier"):
        got, e = num(pg.get(k)), pc.get(k)
        if e is None:
            continue
        if got is None:
            bad.append(f"percentile.{k} 未填")
        elif not (0 <= got <= 1):
            bad.append(f"percentile.{k}={got} 越界 [0,1]")
        elif abs(got - e) > 0.005:
            bad.append(f"percentile.{k} 不符：derived={got} vs 重算={e:.4f}")
    if bad:
        for b in bad[:5]:
            rep.add(FAIL, "dupont5y", b)
    else:
        rep.add(OK, "dupont5y", f"五年累计归因复算一致（{c['period_start']}→{c['period_end']}："
                                f"净利率 {c['margin_effect']:+.4f} / 周转率 {c['turnover_effect']:+.4f} / "
                                f"杠杆 {c['leverage_effect']:+.4f}），三因子分位已复算")


