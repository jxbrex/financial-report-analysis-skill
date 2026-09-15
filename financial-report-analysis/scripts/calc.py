#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc.py — financial-report-analysis 的计算自检门禁（Phase 7.5）

用法：
    python scripts/calc.py reports/xxx.json
    python scripts/calc.py reports/xxx.json --strict    # 警告也判失败

退出码：0 = QC 全绿，允许进入 Phase 8 写报告；1 = 存在 FAIL，禁止写报告。

校验六类：
  1. 结构    meta 必填、叶子 src 非空、数值类型合法、hist 末位 == cur
  2. 恒等式  资产 = 负债 + 权益；未分配利润滚动（A2）
  3. 桥闭合  净利桥 Σ = Δ归母净利；OCF 调节桥 Σ = OCF；收入三效应 Σ = Δ收入
  4. 比率    复算 ROE/毛利率/净现比/收现比/CCC/短债覆盖/增量费用效率，与 derived 比对
  5. recon   三态一致性：偏差≤阈值却报「无法解释」、偏差>阈值却报「闭合」均判 FAIL
  6. 核心科目覆盖度  核心科目提取完整度（季报等轻量场景允许低覆盖，只警告）

口径约定（与 references/frameworks.md、extraction-schema.md 一致）：
  - 全部金额单位「亿元」，比率为小数
  - ROE/净利率用归母口径、期末净资产（摊薄）
  - DSO/DIO/DPO 用平均余额口径：DSO = 平均应收 × 365 ÷ 营业收入
  - OCF 调节桥首项「净利润」填水平值（含少数股东），其余为调节项，Σ = OCF
  - 净利桥各项为同比贡献额（Δ），Σ = Δ归母净利

本脚本只做算术与一致性校验，不评价财务好坏；数字真伪靠出处链与双源核对。
"""

import argparse
import json
import sys

# Windows 控制台默认 GBK，emoji 与中文会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

FAIL, WARN, OK, SKIP = "FAIL", "WARN", "OK", "SKIP"

# recon 偏差阈值：闭合型 = |lhs-rhs|/|rhs| 上限；水平型 = lhs 超过 rhs 即异常
RECON_RULES = {
    "A1_cash":          ("closure", 0.10),
    "A2_retained":      ("closure", 0.02),
    "A3_indirect":      ("closure", 0.02),
    "A4_rev_cash":      ("closure", 0.10),
    "A5_dep_amort":     ("closure", 0.05),
    "A6_capex":         ("closure", 0.10),
    "A7_implied_rate":  ("level",   None),
    "A8_invest_income": ("level",   None),
    "B1_ar_roll":       ("closure", 0.05),
    "B2_inv_roll":      ("closure", 0.05),
    "B3_cip_roll":      ("closure", 0.05),
    "B4_goodwill_roll": ("closure", 0.01),
    # D 组（母公司单体勾稽）：manual 型只做结构校验，不做机械方向判定——
    # 判定是语境合取（占比低+集团现金充裕+分红/偿付受限），机械阈值会误报
    # 财务公司归集、销售公司集中收款等正常模式（见 extraction-schema.md 第四节）
    "D1_parent_cash":   ("manual",  None),
    "D2_parent_retained": ("manual", None),
    "D3_parent_other_ar": ("manual", None),
    "D4_parent_invest": ("manual",  None),
    "D5_parent_ocf":    ("manual",  None),
}

VERDICTS = {"闭合", "可解释", "无法解释"}

CORE_FIELDS = [
    ("income", "revenue"), ("income", "cost"), ("income", "np_at"), ("income", "np_total"),
    ("balance", "cash"), ("balance", "ar"), ("balance", "inventory"),
    ("balance", "total_assets"), ("balance", "total_liab"), ("balance", "equity_at"),
    ("cashflow", "ocf"),
]


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, code, msg):
        self.rows.append((level, code, msg))

    def counts(self):
        c = {FAIL: 0, WARN: 0, OK: 0, SKIP: 0}
        for lv, _, _ in self.rows:
            c[lv] = c.get(lv, 0) + 1
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


# ─────────────────────────── 1. 结构检查 ───────────────────────────

def walk_leaves(node, path, out):
    if isinstance(node, dict):
        if "cur" in node and ("src" in node or "prev" in node or "note" in node):
            out.append((path, node))
            return
        for k, v in node.items():
            walk_leaves(v, path + [k], out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk_leaves(v, path + [str(i)], out)


def check_structure(data, rep):
    meta = data.get("meta") or {}
    for k in ("company", "code", "period", "report_type", "unit", "source_md"):
        if not meta.get(k):
            rep.add(FAIL, "meta", f"meta.{k} 缺失")
    if meta.get("unit") and meta["unit"] != "亿元":
        rep.add(FAIL, "unit", f"meta.unit 必须为「亿元」，当前：{meta['unit']}")
    if not meta.get("unit"):
        rep.add(FAIL, "unit", "meta.unit 缺失")

    leaves = []
    for section in ("statements", "parent_statements", "notes"):
        walk_leaves(data.get(section) or {}, [section], leaves)

    bad_src, bad_type, bad_hist = 0, 0, 0
    for path, node in leaves:
        loc = ".".join(path)
        cur = node.get("cur")
        if cur is None:
            continue
        if isinstance(cur, str):
            bad_type += 1
            rep.add(FAIL, "type", f"{loc}.cur 是字符串「{cur}」——JSON 内禁止千位符/单位后缀")
            continue
        if not isinstance(cur, (int, float)) or isinstance(cur, bool):
            bad_type += 1
            rep.add(FAIL, "type", f"{loc}.cur 类型非法：{type(cur).__name__}")
            continue
        src = node.get("src")
        if not (isinstance(src, str) and src.strip()):
            bad_src += 1
            rep.add(FAIL, "src", f"{loc} 有数值但 src 为空——无出处的数字禁止入 JSON")
        hist = node.get("hist")
        if isinstance(hist, list) and hist:
            nums = [num(x) for x in hist]
            if any(n is None for n in nums):
                rep.add(FAIL, "type", f"{loc}.hist 含非数值元素")
            elif abs(nums[-1] - float(cur)) > max(0.005 * abs(float(cur)), 0.005):
                bad_hist += 1
                rep.add(FAIL, "hist", f"{loc}.hist 末位 {nums[-1]} ≠ cur {cur}（hist 必须旧→新且以本期收尾）")

    # derived.ratios 的趋势比率同样带 hist，末位必须 = cur。比率节点无 src（复算值），
    # 不能混入 walk_leaves（会误报 src 为空），故单独遍历、只查 hist 一致性
    for name, node in ((data.get("derived") or {}).get("ratios") or {}).items():
        if not isinstance(node, dict):
            continue
        cur = node.get("cur")
        hist = node.get("hist")
        if cur is None or not (isinstance(hist, list) and hist):
            continue
        nums = [num(x) for x in hist]
        if any(n is None for n in nums):
            rep.add(FAIL, "type", f"derived.ratios.{name}.hist 含非数值元素")
        elif abs(nums[-1] - float(cur)) > max(0.005 * abs(float(cur)), 0.005):
            bad_hist += 1
            rep.add(FAIL, "hist", f"derived.ratios.{name}.hist 末位 {nums[-1]} ≠ cur {cur}"
                                  f"（hist 必须旧→新且以本期收尾）")
    if not leaves:
        rep.add(FAIL, "structure", "statements/parent_statements/notes 下未找到任何叶子节点，schema 结构可能被破坏")
    else:
        rep.add(OK, "structure", f"叶子节点 {len(leaves)} 个；src 缺失 {bad_src}、类型错误 {bad_type}、hist 不一致 {bad_hist}")


def check_core_fields(data, rep):
    got = 0
    missing = []
    for sec, field in CORE_FIELDS:
        v = val(data, "statements", sec, field)
        if v is not None:
            got += 1
        else:
            missing.append(f"{sec}.{field}")
    ratio = got / len(CORE_FIELDS)
    if ratio >= 0.9:
        rep.add(OK, "core-fields", f"核心科目覆盖 {got}/{len(CORE_FIELDS)}")
    elif ratio >= 0.5:
        rep.add(WARN, "core-fields", f"核心科目覆盖 {got}/{len(CORE_FIELDS)}，缺：{', '.join(missing)}")
    else:
        rep.add(WARN, "core-fields", f"核心科目覆盖仅 {got}/{len(CORE_FIELDS)}（轻量报告可接受，年报应补齐）：{', '.join(missing)}")


# ─────────────────────────── 2. 恒等式 ───────────────────────────

def check_balance_identity(data, rep):
    ta = val(data, "statements", "balance", "total_assets")
    tl = val(data, "statements", "balance", "total_liab")
    eq = val(data, "statements", "balance", "equity_at")
    mi = val(data, "statements", "balance", "minority_eq") or 0.0
    if None in (ta, tl, eq):
        rep.add(SKIP, "A0", "资产=负债+权益：科目不全，跳过")
        return
    rhs = tl + eq + mi
    dev = rel_dev(ta, rhs)
    if dev is not None and dev <= 0.005:
        rep.add(OK, "A0", f"资产=负债+权益 闭合（偏差 {dev:.4%}）")
    else:
        rep.add(FAIL, "A0", f"资产 {ta:.2f} ≠ 负债+权益 {rhs:.2f}（偏差 {dev:.2%}）——提取有误或漏了少数股东权益")


def check_retained_roll(data, rep):
    """A2 未分配利润滚动：期末 = 期初 + 归母净利 − 提取盈余公积 − 分红。"""
    b = lambda f, k="cur": val(data, "statements", "balance", f, key=k)
    cur, prev = b("retained_cur"), b("retained_cur", "prev")
    np_at = val(data, "statements", "income", "np_at")
    if None in (cur, prev, np_at):
        rep.add(SKIP, "A2", "未分配利润滚动：科目不全，跳过（recon.A2_retained 若已填仍会被校验）")
        return
    surplus_draw = None
    s_cur, s_prev = b("surplus_reserve"), b("surplus_reserve", "prev")
    if s_cur is not None and s_prev is not None:
        surplus_draw = s_cur - s_prev
    div = b("dividend_paid") or 0.0
    rhs = prev + np_at - (surplus_draw or 0.0) - div
    dev = abs(cur - rhs) / max(abs(cur), 1e-9)
    if dev <= 0.02:
        rep.add(OK, "A2", f"未分配利润滚动闭合（偏差 {dev:.2%}）")
    else:
        note = "" if surplus_draw is not None else "（盈余公积提取额缺失，按 0 计）"
        rep.add(WARN, "A2", f"未分配利润滚动差 {cur - rhs:+.2f} 亿（偏差 {dev:.2%}）{note}"
                            f"——查前期差错更正/OCI 结转/中期分红，无法解释则立案")


# ─────────────────────────── 3. 桥闭合 ───────────────────────────

def sum_bridge(items):
    if not isinstance(items, list) or not items:
        return None, 0
    total, n = 0.0, 0
    for it in items:
        if not isinstance(it, dict):
            continue
        d = num(it.get("delta"))
        if d is None:
            return None, n
        total += d
        n += 1
    return total, n


def check_bridges(data, rep):
    derived = data.get("derived") or {}

    # 净利桥
    items = derived.get("np_bridge")
    total, n = sum_bridge(items)
    np_cur = val(data, "statements", "income", "np_at")
    np_prev = val(data, "statements", "income", "np_at", key="prev")
    if total is None:
        rep.add(SKIP, "bridge.np", f"净利桥未填或不完整（已填 {n} 项）")
    elif np_cur is None or np_prev is None:
        rep.add(SKIP, "bridge.np", "净利桥已填但缺归母净利两期值，无法校验")
    else:
        target = np_cur - np_prev
        tol = tol_bridge(target, np_cur)
        if abs(total - target) <= tol:
            rep.add(OK, "bridge.np", f"净利桥闭合：Σ{total:+.2f} = Δ归母净利 {target:+.2f}（容差 {tol:.2f}）")
        else:
            rep.add(FAIL, "bridge.np", f"净利桥不闭合：Σ{total:+.2f} vs Δ归母净利 {target:+.2f}，"
                                       f"差 {total - target:+.2f} 亿（容差 {tol:.2f}）")

    # OCF 调节桥（首项为净利润水平值，Σ = OCF）
    items = derived.get("ocf_bridge")
    total, n = sum_bridge(items)
    ocf = val(data, "statements", "cashflow", "ocf")
    if total is None:
        rep.add(SKIP, "bridge.ocf", f"OCF 调节桥未填或不完整（已填 {n} 项）")
    elif ocf is None:
        rep.add(SKIP, "bridge.ocf", "OCF 调节桥已填但缺经营现金流净额")
    else:
        tol = tol_bridge(ocf, val(data, "statements", "income", "np_total"))
        if abs(total - ocf) <= tol:
            rep.add(OK, "bridge.ocf", f"调节桥闭合：Σ{total:.2f} = OCF {ocf:.2f}（容差 {tol:.2f}）")
        else:
            rep.add(FAIL, "bridge.ocf", f"调节桥不闭合：Σ{total:.2f} vs OCF {ocf:.2f}，差 {total - ocf:+.2f} 亿")

    # 营运资本吞噬额自洽：share_of_np 必须 = amount ÷ 净利润（含少数股东）
    wc = derived.get("wc_devour") or {}
    amt, share = num(wc.get("amount")), num(wc.get("share_of_np"))
    np_total = val(data, "statements", "income", "np_total")
    if amt is not None and share is not None and np_total:
        expect = amt / np_total
        if abs(share - expect) <= max(0.02 * abs(expect), 0.005):
            rep.add(OK, "wc_devour", f"吞噬额占净利润比一致（{share:.4f} vs {expect:.4f}）")
        else:
            rep.add(FAIL, "wc_devour", f"share_of_np={share:.4f} 与 amount÷净利润={expect:.4f} 不符")
    elif amt is not None and share is None:
        rep.add(WARN, "wc_devour", "填了吞噬额但未填占净利润比")

    # 收入三效应
    rf = derived.get("rev_factors") or {}
    parts = [num(rf.get(k)) for k in ("volume", "price", "mix")]
    rev_cur = val(data, "statements", "income", "revenue")
    rev_prev = val(data, "statements", "income", "revenue", key="prev")
    if any(p is None for p in parts):
        rep.add(SKIP, "bridge.rev", "收入三效应未填齐（量/价/结构）——无量价数据时按降级路径留空即可")
    elif rev_cur is None or rev_prev is None:
        rep.add(SKIP, "bridge.rev", "收入三效应已填但缺两期收入")
    else:
        target = rev_cur - rev_prev
        total = sum(parts)
        tol = tol_bridge(target, rev_cur)
        if abs(total - target) <= tol:
            rep.add(OK, "bridge.rev", f"三效应闭合：Σ{total:+.2f} = Δ收入 {target:+.2f}（容差 {tol:.2f}）")
        else:
            rep.add(FAIL, "bridge.rev", f"三效应不闭合：Σ{total:+.2f} vs Δ收入 {target:+.2f}，差 {total - target:+.2f} 亿")


# ─────────────────────────── 4. 比率复算 ───────────────────────────

def avg(cur, prev):
    if cur is None or prev is None:
        return cur if prev is None else prev
    return (cur + prev) / 2.0


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
    st, noncur = S("balance", "st_debt"), S("balance", "noncur_due_1y")
    sell, sell_p = S("income", "sell_exp"), S("income", "sell_exp", key="prev")
    admin, admin_p = S("income", "admin_exp"), S("income", "admin_exp", key="prev")
    rd, rd_p = S("income", "rd_exp"), S("income", "rd_exp", key="prev")
    fin, fin_p = S("income", "fin_exp"), S("income", "fin_exp", key="prev")
    np_total = S("income", "np_total")
    income_tax = S("income", "income_tax")
    dep_amort = S("cashflow", "dep_amort")

    def safe_div(a, b):
        if a is None or b in (None, 0):
            return None
        return a / b

    gross = None if (rev is None or cost is None) else rev - cost
    gross_p = None if (rev_p is None or cost_p is None) else rev_p - cost_p
    exp_cur = None if any(x is None for x in (sell, admin, rd, fin)) else sell + admin + rd + fin
    exp_prev = None if any(x is None for x in (sell_p, admin_p, rd_p, fin_p)) else sell_p + admin_p + rd_p + fin_p

    dso = safe_div(avg(ar, ar_p) * 365, rev) if rev else None
    dio = safe_div(avg(inv, inv_p) * 365, cost) if cost else None
    # DPO 需要应付账款（+应付票据）；未提取则留空，CCC 随之不可算（见 schema balance.payable）
    ap, ap_p = S("balance", "payable"), S("balance", "payable", key="prev")
    dpo = safe_div(avg(ap, ap_p) * 365, cost) if (cost and ap is not None) else None
    ccc = None if any(x is None for x in (dso, dio, dpo)) else dso + dio - dpo

    short_debt = None if (st is None and noncur is None) else (st or 0) + (noncur or 0)
    cover = None
    if cash is not None and ocf is not None and short_debt:
        cover = (cash + ocf) / short_debt

    # 杠杆（中注协 X72/X71）：EBIT = 税前利润 + 财务费用
    ebt = None if (np_total is None or income_tax is None) else np_total + income_tax
    ebit = None if (ebt is None or fin is None) else ebt + fin
    # X33 非主营业务收入占比：四字段逐字段 null 按 0 计，全 null 才 None（schema 血泪清单 8）
    nm = [S("income", "non_op_income"), S("income", "other_biz_income"),
          S("income", "invest_income"), S("income", "fv_change_income")]
    non_main = None if all(x is None for x in nm) else safe_div(sum(x or 0 for x in nm), rev)

    return {
        "roe": safe_div(np_at, eq),
        "gross_margin": safe_div(gross, rev),
        "net_margin": safe_div(np_at, rev),
        "net_cash_ratio": safe_div(ocf, np_at),
        "cash_to_sales": safe_div(sales_cash, rev),
        "debt_to_assets": safe_div(tl, ta),
        "asset_turnover": safe_div(rev, avg(ta, ta_p)),
        "equity_multiplier": safe_div(ta, eq),
        "dso": dso, "dio": dio, "dpo": dpo, "ccc": ccc,
        "dfl": safe_div(ebit, ebt),
        "dol": safe_div(ebit + dep_amort, ebit) if (ebit is not None and dep_amort is not None) else None,
        "non_main_rev_share": non_main,
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
    }


def check_ratios(data, rep):
    calc = build_ratio_calcs(data)
    derived = ((data.get("derived") or {}).get("ratios")) or {}
    checked = compared = 0
    for name, expect in calc.items():
        node = derived.get(name)
        got = num(node.get("cur")) if isinstance(node, dict) else num(node)
        if expect is None and got is None:
            continue
        checked += 1
        if expect is None:
            rep.add(WARN, "ratio", f"{name}：derived 填了 {got} 但原始科目不足以复算——核对提取是否缺项")
            continue
        if got is None:
            rep.add(WARN, "ratio", f"{name}：可复算为 {expect:.4f} 但 derived 未填")
            continue
        compared += 1
        # 比率容差：相对 2% 或绝对 0.005（0.5pct）取宽
        if abs(got - expect) <= max(0.02 * abs(expect), 0.005):
            rep.add(OK, "ratio", f"{name} 复算一致（{got:.4f} vs {expect:.4f}）")
        else:
            rep.add(FAIL, "ratio", f"{name} 复算不符：derived={got:.4f}，重算={expect:.4f}"
                                   f"（差 {got - expect:+.4f}）")
    if checked == 0:
        rep.add(SKIP, "ratio", "derived.ratios 为空且无可复算科目")
    else:
        rep.add(OK, "ratio", f"比率校验 {compared}/{checked} 项完成比对")


# ─────────────────────────── 4b. 趋势比率逐期复算 ───────────────────────────

# 趋势比率复算公式表：(所需科目序列, 是否平均余额口径)
# 科目序列取 statements 对应叶子的 hist（缺 hist 时退化为 [cur]，只能复算最末一期）；
# 平均余额口径首期无期初余额，从第 2 期起算（与 build_ratio_calcs 公式完全一致）
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


def ratio_hist_expect(name, v):
    """按某期科目取值字典复算比率，公式与 build_ratio_calcs 一致；缺数返回 None。"""
    g = lambda *p: v.get(p)

    def safe_div(a, b):
        if a is None or b in (None, 0):
            return None
        return a / b

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
    # 各比率只取自己需要的序列，缺的科目不参与计算（avg 双缺返回 None，须先判空再乘）
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
    dpo = safe_div(ap_m * 365, cost) if (cost and ap is not None and ap_m is not None) else None
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


def check_ratio_hist(data, rep):
    """趋势比率逐期复算：对 derived.ratios 中带 hist 的比率，用 statements 的 hist
    序列逐期重算（公式与 build_ratio_calcs 完全一致），容差与 check_ratios 相同。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}
    n_ok = n_fail = n_skip = 0
    missing_hist = []
    for name, node in ratios.items():
        if not isinstance(node, dict):
            continue
        rh = [num(x) for x in node.get("hist") or []]
        if not rh:
            # 仅趋势比率（见 RATIO_HIST_SPECS）缺 hist 才算「口径断裂降级」；单期专用比率不序列化
            if name in RATIO_HIST_SPECS:
                missing_hist.append(name)
            continue
        spec = RATIO_HIST_SPECS.get(name)
        if spec is None:
            continue  # 单期专用比率不序列化，无 hist 可查
        fields, avg_based = spec
        ss = [series_of(data, sec, f) for sec, f in fields]
        # hist 旧→新且以 cur 收尾，比率与科目序列按尾部对齐逐期比对
        L = min([len(rh)] + [len(s) for s in ss])
        for j in range(L):
            v = {}
            for (sec, f), s in zip(fields, ss):
                i = len(s) - L + j
                v[(sec, f)] = s[i]
                # 平均余额口径还需上一期余额（期初），一并取入取值字典
                v[f"{f}_prev"] = s[i - 1] if i > 0 else None
            if avg_based and any(v[f"{f}_prev"] is None for _, f in fields):
                rep.add(SKIP, "ratio-hist", f"{name} 首期无期初余额，跳过（平均余额口径从第 2 期起算）")
                n_skip += 1
                continue
            expect = ratio_hist_expect(name, v)
            got = rh[len(rh) - L + j]
            if expect is None:
                rep.add(SKIP, "ratio-hist", f"{name} 该期科目序列不全，无法复算")
                n_skip += 1
                continue
            if abs(got - expect) <= max(0.02 * abs(expect), 0.005):
                n_ok += 1
            else:
                n_fail += 1
                rep.add(FAIL, "ratio-hist", f"{name}.hist 该期复算不符：填 {got:.4f}，重算 {expect:.4f}"
                                            f"（差 {got - expect:+.4f}）")
    if missing_hist and n_ok == 0 and n_fail == 0:
        rep.add(SKIP, "ratio-hist",
                f"趋势比率缺 hist（口径断裂等），趋势降级两期：{', '.join(missing_hist)}")
    else:
        parts = [f"比率历史复算 {n_ok} 期通过"]
        if n_fail:
            parts.append(f"{n_fail} 期不符")
        if n_skip:
            parts.append(f"{n_skip} 期跳过（首期无期初余额/科目序列不全）")
        if missing_hist:
            parts.append(f"{len(missing_hist)} 个比率缺 hist（口径断裂等），趋势降级两期："
                         f"{', '.join(missing_hist)}")
        rep.add(FAIL if n_fail else (OK if n_ok else SKIP), "ratio-hist", "；".join(parts))


# ─────────────────────────── 5. recon 三态一致性 ───────────────────────────

def check_recon(data, rep):
    recon = data.get("recon") or {}
    if not recon:
        rep.add(SKIP, "recon", "recon 块为空（批次二 articulation 落地后必填）")
        return
    for key, rule in RECON_RULES.items():
        node = recon.get(key)
        if not isinstance(node, dict):
            continue
        lhs, rhs = num(node.get("lhs")), num(node.get("rhs"))
        verdict = node.get("verdict")
        expl = node.get("explanation")
        if lhs is None or rhs is None:
            if verdict:
                rep.add(FAIL, key, f"填了 verdict=「{verdict}」但 lhs/rhs 缺失——无算据的判定不成立")
            else:
                rep.add(SKIP, key, "未填，跳过")
            continue
        src = node.get("src")
        if not (isinstance(src, str) and src.strip()):
            rep.add(FAIL, key, f"{key} 有 lhs/rhs 但 src 为空——勾稽中间量同样禁止无出处")
        if verdict not in VERDICTS:
            rep.add(FAIL, key, f"verdict 非法：「{verdict}」，必须是 闭合/可解释/无法解释 之一")
            continue
        if verdict != "闭合" and not (isinstance(expl, str) and expl.strip()):
            rep.add(FAIL, key, f"verdict=「{verdict}」但 explanation 为空")

        kind, thresh = rule
        if kind == "manual":
            # 结构校验（verdict 合法/非闭合必填 explanation/src 非空）已在上方完成；
            # 方向由分析师按合取条件判定，门禁不机械复核
            rep.add(OK, key, f"manual 型结构合法，判定「{verdict}」（lhs={lhs} / rhs={rhs}）")
        elif kind == "closure":
            dev = abs(lhs - rhs) / max(abs(rhs), 1e-9)
            closed = dev <= thresh
            if closed and verdict != "闭合":
                rep.add(FAIL, key, f"偏差 {dev:.2%} ≤ 阈值 {thresh:.0%} 却判「{verdict}」——过度立案")
            elif not closed and verdict == "闭合":
                rep.add(FAIL, key, f"偏差 {dev:.2%} > 阈值 {thresh:.0%} 却判「闭合」——掩盖异常")
            elif not closed and verdict == "无法解释":
                rep.add(WARN, key, f"无法解释偏差 {dev:.2%}（{lhs:.2f} vs {rhs:.2f}）——确认 signals 中有对应条目")
            else:
                rep.add(OK, key, f"偏差 {dev:.2%}，判定「{verdict}」一致")
        else:  # level：lhs 为计算值，rhs 为基准阈值
            breached = lhs > rhs
            if breached and verdict == "闭合":
                rep.add(FAIL, key, f"水平值 {lhs:.4f} 已超基准 {rhs:.4f} 却判「闭合」")
            elif not breached and verdict != "闭合":
                rep.add(FAIL, key, f"水平值 {lhs:.4f} 未超基准 {rhs:.4f} 却判「{verdict}」")
            else:
                rep.add(OK, key, f"水平值 {lhs:.4f} / 基准 {rhs:.4f}，判定「{verdict}」一致")


def check_signals(data, rep):
    sigs = data.get("signals")
    if not isinstance(sigs, list):
        rep.add(SKIP, "signals", "signals 块缺失")
        return
    bad = 0
    for i, s in enumerate(sigs):
        if not isinstance(s, dict):
            bad += 1
            continue
        for k in ("id", "level", "title", "source"):
            if not s.get(k):
                bad += 1
                rep.add(FAIL, "signals", f"signals[{i}] 缺 {k}")
                break
        if s.get("level") not in ("g", "y", "r"):
            bad += 1
            rep.add(FAIL, "signals", f"signals[{i}].level 必须是 g/y/r，当前「{s.get('level')}」")
    if not sigs:
        rep.add(WARN, "signals", "signals 为空——干净样本也应有 🟢 亮点条目")
    elif bad == 0:
        rep.add(OK, "signals", f"{len(sigs)} 条信号结构合法")


# ─────────────────────────── 7. 分部 / 断言 / 覆盖率 / 应付未付利息 ───────────────────────────

def check_segments(data, rep):
    """by_segment 自洽性：分部毛利率合理 + 收入占比合计≈1 + 加权毛利率≈整体（P1-17 机检）。"""
    segs = ((data.get("statements") or {}).get("income") or {}).get("by_segment") or []
    if not isinstance(segs, list) or not segs:
        rep.add(SKIP, "segments", "by_segment 未填（单产品公司可跳过）")
        return
    revs = []
    for i, s in enumerate(segs):
        if not isinstance(s, dict):
            continue
        rev, cost = num(s.get("rev_cur")), num(s.get("cost_cur"))
        if rev is None:
            continue
        if rev <= 0:
            rep.add(FAIL, "segments", f"by_segment[{i}]（{s.get('name','?')}）.rev_cur = {rev} 非正")
            continue
        if cost is not None:
            gm = (rev - cost) / rev
            if not (-0.5 <= gm <= 1.0):
                rep.add(FAIL, "segments", f"by_segment[{i}]（{s.get('name','?')}）毛利率 {gm:.2%} 超出合理区间"
                                          f"（rev={rev}, cost={cost}）")
        revs.append(rev)

    total_rev = val(data, "statements", "income", "revenue")
    if revs and total_rev:
        share = sum(revs) / total_rev
        if abs(share - 1.0) <= 0.03:
            rep.add(OK, "segments", f"{len(revs)} 个分部，收入占比合计 {share:.2%}（与整体一致）")
        else:
            rep.add(WARN, "segments", f"分部收入合计 {sum(revs):.2f} ÷ 整体收入 {total_rev:.2f} = {share:.2%}，"
                                      f"偏差 >3%（可能未含其他业务或口径不一致，须在报告中注明）")

    wsum = wrev = 0.0
    for s in segs:
        if not isinstance(s, dict):
            continue
        rev, cost = num(s.get("rev_cur")), num(s.get("cost_cur"))
        if rev and cost is not None:
            wsum += rev * ((rev - cost) / rev)
            wrev += rev
    if wrev:
        wgm = wsum / wrev
        overall = build_ratio_calcs(data).get("gross_margin")
        if overall is None:
            rep.add(SKIP, "segments", "分部加权毛利率可算，但缺整体毛利率可比")
        elif abs(wgm - overall) <= 0.02:
            rep.add(OK, "segments", f"分部加权毛利率 {wgm:.2%} ≈ 整体 {overall:.2%}（P1-17 四象限数据自洽）")
        else:
            rep.add(WARN, "segments", f"分部加权毛利率 {wgm:.2%} 与整体 {overall:.2%} 差 {abs(wgm-overall):.2%} >2%"
                                      f"——检查分部成本口径、内部交易抵销或成本分摊变更")


ASSERT_VERDICTS = {"通过", "不成立", "无法验证"}


def check_assertions(data, rep):
    """MD&A 断言验证表（text-mining.md 第七节）：结构校验，P1-12 落库机检。"""
    arr = data.get("assertions")
    if not isinstance(arr, list) or not arr:
        rep.add(SKIP, "assertions", "assertions 未填（未做断言验证或无可验证的因果表述）")
        return
    bad = 0
    for i, a in enumerate(arr):
        if not isinstance(a, dict):
            bad += 1
            rep.add(FAIL, "assertions", f"assertions[{i}] 不是对象")
            continue
        missing_keys = [k for k in ("id", "text", "verdict", "source") if not a.get(k)]
        if missing_keys:
            bad += 1
            rep.add(FAIL, "assertions", f"assertions[{i}] 缺 {'/'.join(missing_keys)}")
            continue
        if a["verdict"] not in ASSERT_VERDICTS:
            bad += 1
            rep.add(FAIL, "assertions", f"assertions[{i}].verdict 必须是 通过/不成立/无法验证，"
                                        f"当前「{a['verdict']}」")
        elif a["verdict"] == "不成立" and not (isinstance(a.get("evidence"), str) and a["evidence"].strip()):
            bad += 1
            rep.add(FAIL, "assertions", f"assertions[{i}] 判「不成立」但 evidence 为空——反证必须有据")
        elif a["verdict"] == "无法验证" and not (isinstance(a.get("missing"), str) and a["missing"].strip()):
            rep.add(WARN, "assertions", f"assertions[{i}] 判「无法验证」但未写 missing（缺什么数据）")
    if bad == 0:
        n_bad = sum(1 for a in arr if isinstance(a, dict) and a.get("verdict") == "不成立")
        rep.add(OK, "assertions", f"{len(arr)} 条断言结构合法（其中判「不成立」{n_bad} 条，应已进 signals）")


def check_recon_coverage(data, rep):
    """recon 覆盖率：非空时统计已执行的等式，提醒未做项（缺数合法，漏做不可）。"""
    recon = data.get("recon") or {}
    if not recon:
        rep.add(SKIP, "recon-coverage", "recon 为空，覆盖率不适用")
        return
    total = len(RECON_RULES)
    filled = [k for k in RECON_RULES if isinstance(recon.get(k), dict) and recon[k].get("verdict")]
    missing = [k for k in RECON_RULES if k not in filled]
    if not missing:
        rep.add(OK, "recon-coverage", f"{total} 条等式全部给出判定（{len(filled)}/{total}）")
    else:
        rep.add(WARN, "recon-coverage", f"recon 覆盖 {len(filled)}/{total}，未给判定：{', '.join(missing)}"
                                        f"——确认是附注未披露（合法）还是漏做（回 Phase 2.5 补）")


def check_interest_arrears(data, rep):
    """应付未付利息（A7 副算，P1-15）：为正说明计提利息未实际支付。"""
    node = (data.get("derived") or {}).get("interest_arrears")
    amt = num(node.get("cur")) if isinstance(node, dict) else num(node)
    if amt is None:
        rep.add(SKIP, "interest_arrears", "未填（缺 interest_paid 时可跳过）")
        return
    if amt > 0:
        rep.add(WARN, "interest_arrears", f"应付未付利息 +{amt:.2f} 亿（已计提未付）——单期可能是付息日错期，"
                                          f"连续 2 年为正且余额上升才构成资金链先行信号")
    else:
        rep.add(OK, "interest_arrears", f"应付未付利息 {amt:+.2f} 亿（无欠付）")


# ─────────────────────────── 主流程 ───────────────────────────

ICON = {FAIL: "🔴", WARN: "🟡", OK: "✅", SKIP: "⚪"}


def main():
    ap = argparse.ArgumentParser(description="financial-report-analysis 计算自检门禁")
    ap.add_argument("json_path", help="data.json 路径")
    ap.add_argument("--strict", action="store_true", help="警告也判失败")
    args = ap.parse_args()

    try:
        with open(args.json_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"🔴 文件不存在：{args.json_path}")
        return 1
    except json.JSONDecodeError as e:
        print(f"🔴 JSON 解析失败：{e}")
        return 1

    rep = Report()
    check_structure(data, rep)
    check_core_fields(data, rep)
    check_balance_identity(data, rep)
    check_retained_roll(data, rep)
    check_bridges(data, rep)
    check_ratios(data, rep)
    check_ratio_hist(data, rep)
    check_recon(data, rep)
    check_recon_coverage(data, rep)
    check_segments(data, rep)
    check_assertions(data, rep)
    check_interest_arrears(data, rep)
    check_signals(data, rep)

    meta = data.get("meta") or {}
    print(f"\n=== calc.py QC · {meta.get('company', '?')}（{meta.get('code', '?')}）"
          f" {meta.get('period', '?')} {meta.get('report_type', '?')} ===\n")
    order = {FAIL: 0, WARN: 1, OK: 2, SKIP: 3}
    for lv, code, msg in sorted(rep.rows, key=lambda r: (order[r[0]], r[1])):
        print(f"{ICON[lv]} [{lv:<4}] {code:<14} {msg}")

    c = rep.counts()
    failed = c[FAIL] + (c[WARN] if args.strict else 0)
    print(f"\n--- 汇总：FAIL {c[FAIL]} · WARN {c[WARN]} · OK {c[OK]} · SKIP {c[SKIP]} ---")
    if failed:
        print("❌ QC 未通过：修正上述 FAIL 后重跑，禁止带病写报告（Phase 8）。")
        return 1
    print("✅ QC 全绿：可进入 Phase 8 写报告。" + ("（--strict 模式）" if args.strict else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
