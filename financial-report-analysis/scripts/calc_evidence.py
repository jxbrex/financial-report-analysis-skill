# -*- coding: utf-8 -*-
"""calc_evidence.py — 证据读数族（v0.0.15 拆分自 calc_models.py）：周期定位证据读数 /
四线考核贴线检测 / 同业 peers 结构校验（外部取数无公式可复算，只做结构卡口）。
"""

from calc_common import (FAIL, WARN, OK, SKIP, num, series_of, hist_periods, cmp_series)

def compute_cycle_evidence(data):
    """周期定位证据读数（v1.3，F-07）：收入增速/毛利率/Capex 增速逐期序列（旧→新）。
    读数层证据供 meta.cycle_stage 判定可核验；hist<2 期（增速不可算）返回 None。
    三条线长度不一时前置补 null 右对齐（末位=当期），与 periods 等长——防表行错位。"""
    rev_h = [x for x in series_of(data, "income", "revenue") if x is not None]
    cap_h = [x for x in series_of(data, "cashflow", "capex") if x is not None]
    ratios = ((data.get("derived") or {}).get("ratios")) or {}
    gm_node = ratios.get("gross_margin")
    gm_h = [num(x) for x in (gm_node.get("hist") or [])] if isinstance(gm_node, dict) else []
    if len(rev_h) < 2 and len(cap_h) < 2:
        return None
    n = max(len(rev_h), len(cap_h), len(gm_h))

    def yoy(h):
        return [None if i == 0 or not h[i - 1] else h[i] / h[i - 1] - 1 for i in range(len(h))]

    def align(seq):
        # 右对齐到 n（末位=当期）；序列缺/太短则前置补 null（该线该期无数，非 0）
        return [None] * (n - len(seq)) + seq if 0 < len(seq) < n else seq

    periods = hist_periods(data.get("meta") or {}, n)
    return {"rev_growth": align(yoy(rev_h)) if len(rev_h) >= 2 else [],
            "gross_margin": align(gm_h),
            "capex_growth": align(yoy(cap_h)) if len(cap_h) >= 2 else [],
            "periods": periods or []}


def compute_threshold_check(data):
    """四线考核贴线检测（v1.3，F-08）：保壳线/再融资线机械判定（贴线=实际÷目标∈[0.95,1.05]，
    保壳线另需净利率落 0~3% 合取）；激励线需公告取数，本函数只留结构（机算部分由分析师填数后
    check 复算 ratio）。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}
    roe_node, nm_node = ratios.get("roe"), ratios.get("net_margin")
    # 裸数字节点合法（check_ratios 兼容），取其值；字符串等畸形由结构检查报 FAIL
    roe = num(roe_node.get("cur")) if isinstance(roe_node, dict) else num(roe_node)
    nm = num(nm_node.get("cur")) if isinstance(nm_node, dict) else num(nm_node)
    if roe is None:
        return None

    def hit(v, target):
        return v is not None and 0.95 <= v / target <= 1.05

    return {"shell_line": {"roe": roe, "target": 0.065, "net_margin": nm,
                           "hit": hit(roe, 0.065) and nm is not None and 0 <= nm <= 0.03},
            "refinance_line": {"roe": roe, "target": 0.10, "hit": hit(roe, 0.10)}}




# ─────────────────────────── 薄校验（比对 derived 与复算值） ───────────────────────────

def check_cycle_evidence(data, rep):
    cv = (data.get("derived") or {}).get("cycle_evidence")
    if not isinstance(cv, dict) or not any(cv.get(k) for k in
                                           ("rev_growth", "gross_margin", "capex_growth")):
        rep.add(SKIP, "cycle-evidence", "derived.cycle_evidence 未填（hist 不足等合法情形）")
        return
    c = compute_cycle_evidence(data)
    if c is None:
        rep.add(FAIL, "cycle-evidence", "cycle_evidence 已填但收入/Capex hist 均不足 2 期——口径断裂期不得造数")
        return
    bad = []
    for key in ("rev_growth", "gross_margin", "capex_growth"):
        cmp_series(bad, f"cycle_evidence.{key}", cv.get(key), c.get(key))
    if c.get("periods") and cv.get("periods") and cv["periods"] != c["periods"]:
        bad.append(f"cycle_evidence.periods 与按 meta.period 倒推的 {c['periods']} 不符")
    if bad:
        for b in bad[:5]:
            rep.add(FAIL, "cycle-evidence", b)
    else:
        rep.add(OK, "cycle-evidence", "周期定位证据读数复算一致（阶段判定可核验）")


def check_threshold_check(data, rep):
    tc = (data.get("derived") or {}).get("threshold_check")
    if not isinstance(tc, dict):
        rep.add(SKIP, "threshold-check", "derived.threshold_check 未填（v1.3 前存量合法）")
        return
    c = compute_threshold_check(data)
    bad = []
    for line in ("shell_line", "refinance_line"):
        node = tc.get(line)
        if node is None:
            continue
        if c is None:
            bad.append(f"{line} 已填但 ROE 缺失无法复算")
            continue
        e = c[line]
        if num(node.get("roe")) is None or abs(num(node.get("roe")) - e["roe"]) > 0.005:
            bad.append(f"{line}.roe 不符：derived={node.get('roe')} vs ratios.roe={e['roe']:.4f}")
        if node.get("hit") is not None and node.get("hit") != e["hit"]:
            bad.append(f"{line}.hit={node.get('hit')} 与重算 {e['hit']} 不符"
                       f"（贴线=实际÷目标∈[0.95,1.05]）")
    inc = tc.get("incentive_line")
    if isinstance(inc, dict) and any(inc.get(k) not in (None, "") for k in
                                     ("target_desc", "actual", "target", "ratio", "share_payment")):
        sp = inc.get("share_payment")
        if sp is not None and num(sp) is None:
            bad.append(f"incentive_line.share_payment={sp!r} 非数值——摊销额必须是数字或 null")
        actual, target = num(inc.get("actual")), num(inc.get("target"))
        if actual is None or target is None:
            bad.append("incentive_line 填了部分字段但 actual/target 不齐"
                       "（只查到公告未填读数时 target_desc/src 也不许单独存在）")
        else:
            expect = actual / target if target else None
            if expect is not None and num(inc.get("ratio")) is not None \
                    and abs(num(inc.get("ratio")) - expect) > 0.005:
                bad.append(f"incentive_line.ratio={inc.get('ratio')} ≠ actual÷target={expect:.4f}")
            if expect is not None and inc.get("hit") is not None \
                    and inc.get("hit") != (0.95 <= expect <= 1.05):
                bad.append(f"incentive_line.hit={inc.get('hit')} 与 ratio={expect:.4f} 的贴线判定不符")
            if not (isinstance(inc.get("src"), str) and inc.get("src").strip()):
                bad.append("incentive_line 有数值但 src 为空——考核目标必须注明公告出处")
    if bad:
        for b in bad[:5]:
            rep.add(FAIL, "threshold-check", b)
    else:
        hits = [ln for ln in ("shell_line", "refinance_line")
                if isinstance(tc.get(ln), dict) and tc[ln].get("hit")]
        rep.add(OK, "threshold-check",
                f"贴线检测复算一致（命中：{', '.join(hits) if hits else '无'}）")


def check_peers(data, rep):
    """peers 同业块（v1.3，F-11）：外部取数无公式可复算，只做结构校验
    （src 非空 FAIL、比率超合理区间 WARN）——真伪靠双源核对纪律。"""
    peers = data.get("peers")
    if not isinstance(peers, list) or not peers:
        rep.add(SKIP, "peers", "peers 未填（v1.3 前存量/同业不可得合法）")
        return
    # 常见带非硬界：区间外只 WARN（如 pre-revenue  biotech 研发费率可 >100%，须人工核对口径）
    RANGES = {"gross_margin": (-1, 1), "rd_ratio": (0, 1), "debt_to_assets": (0, 1),
              "net_margin": (-1, 1), "asset_turnover": (0, 10), "equity_multiplier": (1, 50),
              "roe": (-1, 1)}
    bad = 0
    for i, p in enumerate(peers):
        if not isinstance(p, dict):
            rep.add(FAIL, "peers", f"peers[{i}] 不是对象")
            bad += 1
            continue
        if not p.get("name"):
            rep.add(FAIL, "peers", f"peers[{i}].name 为空")
            bad += 1
        if not (isinstance(p.get("src"), str) and p.get("src").strip()):
            rep.add(FAIL, "peers", f"peers[{i}]（{p.get('name', '?')}）src 为空——同业数字同样禁止无出处")
            bad += 1
        for k, (lo, hi) in RANGES.items():
            v = num(p.get(k))
            if v is not None and not (lo <= v <= hi):
                rep.add(WARN, "peers", f"peers[{i}]（{p.get('name', '?')}）.{k}={v} 超合理区间 "
                                       f"[{lo},{hi}]——核对单位（应为小数）与口径")
    if bad == 0:
        rep.add(OK, "peers", f"{len(peers)} 家同业结构合法（杜邦四列+原三指标）")




# 四象限标签（等号归正侧：g≥x0 增长侧、m≥y0 高毛利侧——schema v1.5 约定）
QUADRANT = {(True, True): "明星", (True, False): "以量换价",
            (False, True): "现金牛/潜力", (False, False): "衰退"}


def compute_segment_quadrant(data):
    """收入-毛利业务组合四象限（factor-analysis.md 第六节）机械复算，fill/check 共用。
    by_segment <2 条返回 None（单产品裁剪路径）；x0=Σrev_cur÷Σrev_prev−1，
    任一分部 rev_prev 为 null 则 x0/g/quadrant 全 null；y_mode=delta 要求
    rev_prev/cost_prev 全部非 null，否则 level（dm 同 null）；rows 与 by_segment 同序。"""
    segs = ((data.get("statements") or {}).get("income") or {}).get("by_segment") or []
    if not isinstance(segs, list) or len(segs) < 2:
        return None
    revs = [num(s.get("rev_cur")) for s in segs]
    costs = [num(s.get("cost_cur")) for s in segs]
    prevs = [num(s.get("rev_prev")) for s in segs]
    costps = [num(s.get("cost_prev")) for s in segs]
    srev = sum(r or 0 for r in revs)
    sprofit = sum((r or 0) - (c or 0) for r, c in zip(revs, costs))
    prev_ok = all(p is not None for p in prevs)
    delta_ok = prev_ok and all(c is not None for c in costps)
    x0 = (srev / sum(prevs) - 1) if prev_ok and sum(prevs) else None
    y0 = (1 - sum(c or 0 for c in costs) / srev) if srev else None
    ws = [(r / srev if r is not None and srev else None) for r in revs]
    ps = [(((r or 0) - (c or 0)) / sprofit if sprofit else None) for r, c in zip(revs, costs)]

    def _rank(vals):
        order = sorted(range(len(vals)),
                       key=lambda i: (-(vals[i] if vals[i] is not None else float("-inf")),
                                      segs[i].get("name") or ""))
        rk = [0] * len(vals)
        for pos, i in enumerate(order):
            rk[i] = pos + 1
        return rk

    w_rank, p_rank = _rank(ws), _rank(ps)
    rows = []
    for i in range(len(segs)):
        rev, cost, prev = revs[i], costs[i], prevs[i]
        g = (rev / prev - 1) if (rev is not None and prev) else None
        m = ((rev - cost) / rev) if (rev and cost is not None) else None
        dm = (m - (prev - costps[i]) / prev) if (delta_ok and m is not None and prev) else None
        q = None if None in (g, m, x0, y0) else QUADRANT[(g >= x0, m >= y0)]
        rows.append({"name": segs[i].get("name"), "g": g, "m": m, "dm": dm,
                     "w": ws[i], "p": ps[i], "quadrant": q,
                     "rank_gap": abs(w_rank[i] - p_rank[i]),
                     "p_minus_w": (ps[i] - ws[i]) if (ps[i] is not None and ws[i] is not None) else None})
    return {"y_mode": "delta" if delta_ok else "level", "x0": x0, "y0": y0, "rows": rows}
