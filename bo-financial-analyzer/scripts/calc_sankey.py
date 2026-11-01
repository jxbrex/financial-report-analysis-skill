# -*- coding: utf-8 -*-
"""calc_sankey.py — 资金流向桑基图（S3 总览卡）的机械计算与闭合校验（v0.1.4）。

块定义见 references/extraction-schema.md 的 derived.sankey；形态与判读纪律见
references/factor-analysis.md 六·五节。compute_sankey 是公式唯一定义处，
fill（calc_models.py）与 check（calc.py）共用；符号路由（减项/加项数组）在
route_items——JS 绘图（drawSankey）不做符号判断。

debt: impair 符号启发式——impair_loss.cur 为负时按利润表原始符号（负=损失）翻正，
为正时视为已是「损失正计」直接采用；公司真为净转回（原始符号为正的小额收益）时会
误判为损失，届时把 impair_loss 的 note 口径与 sankey 块手工对齐。
"""

from calc_common import FAIL, WARN, OK, SKIP, num, tol_bridge

SANKEY_KEYS = ("rev", "cost", "gross", "tax_sur", "sell", "admin", "rd", "fin",
               "impair", "other_lump", "op", "nonop", "tax", "np", "np_at",
               "minority", "ocf", "capex", "fcf", "gap")


def _cur(blk, f):
    node = blk.get(f)
    return num(node.get("cur")) if isinstance(node, dict) else num(node)


def _period_values(data):
    """本期（累计口径）20 科目机械值；关键项缺失返回 None（降级）。"""
    inc = (data.get("statements") or {}).get("income") or {}
    cfs = (data.get("statements") or {}).get("cashflow") or {}
    rev, cost = _cur(inc, "revenue"), _cur(inc, "cost")
    if rev is None or cost is None:
        return None
    fees4 = [_cur(inc, "tax_surcharge"), _cur(inc, "sell_exp"),
             _cur(inc, "admin_exp"), _cur(inc, "rd_exp")]
    fin = _cur(inc, "fin_exp")
    if any(v is None for v in fees4) or fin is None:
        return None
    impair_raw = _cur(inc, "impair_loss")
    # 利润表未单列减值 = 不重大，按 0 计（other_biz_income 同款口径）；不减值不降级
    impair = 0.0 if impair_raw is None else (-impair_raw if impair_raw < 0 else impair_raw)
    np_total, np_at = _cur(inc, "np_total"), _cur(inc, "np_at")
    tax = _cur(inc, "income_tax")
    if any(v is None for v in (np_total, np_at, tax)):
        return None
    # 少数股东损益未单列 = 按恒等式差额归少数；营业外净额未单列 = 不重大按 0 计
    minority = _cur(inc, "minority_np")
    if minority is None:
        minority = np_total - np_at
    nonop = _cur(inc, "non_op_net")
    if nonop is None:
        nonop = 0.0
    op = _cur(inc, "op_profit")
    if op is None:
        op = np_total + tax - nonop  # 营业利润未单列时按「利润总额−营业外净额」推算
    ocf, capex = _cur(cfs, "ocf"), _cur(cfs, "capex")
    if ocf is None or capex is None:
        return None
    gross = rev - cost
    other_lump = op - (gross - sum(fees4) - fin - impair)
    return {"rev": rev, "cost": cost, "gross": gross,
            "tax_sur": fees4[0], "sell": fees4[1], "admin": fees4[2], "rd": fees4[3],
            "fin": fin, "impair": impair, "other_lump": other_lump,
            "op": op, "nonop": nonop, "tax": tax, "np": np_total, "np_at": np_at,
            "minority": minority, "ocf": ocf, "capex": capex,
            "fcf": ocf - capex, "gap": ocf - np_total}


def _unfit(v):
    """不适用降级判定（对当期值）：流向图形态不成立的情形。"""
    if v["rev"] <= 0 or v["gross"] <= 0 or v["op"] <= 0:
        return "收入/毛利/营业利润非正"
    if v["np"] <= 0 or v["np_at"] <= 0:
        return "净利润或归母非正（亏损期流向树不成立）"
    if v["ocf"] <= 0:
        return "经营现金流非正"
    if v["minority"] < 0:
        return "少数股东损益为负（分流形态不成立）"
    return None


def compute_sankey(data):
    """机械产出 derived.sankey（20 科目 + period_type + 单季差额时 cum 回填）。
    cum_prev 是输入字段（主线按上一累计期预填），本函数只读不写；
    不适用/缺原料返回 None（整块 null 降级）。"""
    der = data.get("derived") or {}
    meta = data.get("meta") or {}
    period = str(meta.get("period") or "")
    diff_mode = ("季报" in (meta.get("report_type") or "")) and period.endswith("0930")
    cum = _period_values(data)
    if cum is None:
        return None
    if not diff_mode:
        vals, pt, cum_prev, cum_out = cum, "本期", None, None
    else:
        prev_blk = (der.get("sankey") or {}).get("cum_prev") or {}
        pv = {k: num(prev_blk.get(k)) for k in SANKEY_KEYS}
        if any(pv[k] is None for k in SANKEY_KEYS):
            return None  # 三季报缺上一累计期原料 → 降级
        vals = {k: cum[k] - pv[k] for k in SANKEY_KEYS}
        pt, cum_prev, cum_out = "单季差额", pv, cum
    unfit = _unfit(vals)
    if unfit:
        return None
    out = {"period_type": pt}
    out.update(vals)
    out["cum"] = cum_out
    out["cum_prev"] = cum_prev
    return out


def route_items(v):
    """符号路由：减项盒（上排，从毛利分出）与加项盒（下排，汇入主流）。
    返回 (minus_items, plus_items)；fees 盒恒在首位且财务费用为正时并入其第五行。"""
    fees_val = v["tax_sur"] + v["sell"] + v["admin"] + v["rd"] + (v["fin"] if v["fin"] > 0 else 0)
    fees_lines = [["税金及附加", v["tax_sur"]], ["销售", v["sell"]],
                  ["管理", v["admin"]], ["研发", v["rd"]]]
    if v["fin"] > 0:
        fees_lines.append(["财务", v["fin"]])
    minus = [{"key": "fees", "label": "期间费用及税金", "value": fees_val, "lines": fees_lines}]
    if v["impair"] > 0:
        minus.append({"key": "impair", "label": "减值损失", "value": v["impair"], "lines": []})
    if v["other_lump"] < 0:
        minus.append({"key": "other_neg", "label": "其他损益净损失", "value": -v["other_lump"],
                      "lines": []})
    plus = []
    if v["fin"] < 0:
        plus.append({"key": "fin", "label": "财务净收益", "value": -v["fin"], "lines": []})
    if v["impair"] < 0:
        plus.append({"key": "impair_rev", "label": "减值净转回", "value": -v["impair"], "lines": []})
    if v["other_lump"] >= 0:
        plus.append({"key": "other", "label": "其他损益净额", "value": v["other_lump"], "lines": []})
    return minus, plus


def check_sankey(data, rep):
    """derived.sankey 自洽（schema v1.7）：选填块——缺省合法 SKIP；填则与
    compute_sankey 复算值全字段比对；单季差额口径加 cum−cum_prev 卡口。"""
    sk = (data.get("derived") or {}).get("sankey")
    if sk is None:
        rep.add(SKIP, "sankey", "sankey 未落库（选填块；不适用降级或缺原料合法）")
        return
    if not isinstance(sk, dict):
        rep.add(FAIL, "sankey", "derived.sankey 结构非法（应为对象或 null）")
        return
    expect = compute_sankey(data)
    if expect is None:
        rep.add(FAIL, "sankey", "sankey 已落库但当前数据形态应降级"
                                "（rev/毛利/营业利润/净利/归母/OCF 非正或关键项缺失）")
        return
    fails0 = rep.counts()[FAIL]
    if sk.get("period_type") != expect["period_type"]:
        rep.add(FAIL, "sankey",
                f"period_type={sk.get('period_type')!r} 与复算 {expect['period_type']!r} 不符")
    for k in SANKEY_KEYS:
        got, want = num(sk.get(k)), expect[k]
        if got is None or abs(got - want) > max(0.02 * abs(want), 0.005):
            rep.add(FAIL, "sankey", f"{k}={got} 与复算值 {want:.4f} 不符")
    if expect["period_type"] == "单季差额":
        cum, cp = sk.get("cum") or {}, sk.get("cum_prev") or {}
        ec = expect["cum"] or {}
        for k in SANKEY_KEYS:
            got = num(cum.get(k))
            if got is None or abs(got - ec[k]) > max(0.02 * abs(ec[k]), 0.005):
                rep.add(FAIL, "sankey", f"cum.{k}={got} 与 statements 复算 {ec[k]:.4f} 不符")
            c, p, v = num(cum.get(k)), num(cp.get(k)), num(sk.get(k))
            if c is None or p is None or v is None:
                rep.add(FAIL, "sankey", f"单季差额卡口缺值：{k}")
            elif abs((c - p) - v) > tol_bridge(c - p, v):
                rep.add(FAIL, "sankey", f"单季差额卡口：{k} 值 {v:.4f} ≠ cum−cum_prev {c - p:.4f}")
        rep.add(WARN, "sankey", "单季差额口径：cum_prev 为纯输入字段，门禁仅验自洽"
                                "——人工核对上一累计期出处")
    if not str(sk.get("src") or "").strip():
        rep.add(FAIL, "sankey", "src 为空（无出处数字禁止入 JSON）")
    if rep.counts()[FAIL] == fails0:
        rep.add(OK, "sankey", f"桑基图 {len(SANKEY_KEYS)} 科目复算自洽（{expect['period_type']}）")
