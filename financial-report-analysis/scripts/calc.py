#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc.py — financial-report-analysis 的计算自检门禁（Phase 7.5）

用法：
    python scripts/calc.py reports/xxx.json

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
from pathlib import Path

# Windows 控制台默认 GBK，emoji 与中文会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


from calc_common import (FAIL, WARN, OK, SKIP, Report, num, val, rel_dev,
                         tol_bridge, RATIO_HIST_SPECS, build_ratio_calcs,
                         ratio_hist_series)
from calc_dupont import check_dupont, check_dupont_dt, check_dupont5y
from calc_evidence import check_cycle_evidence, check_threshold_check, check_peers, compute_segment_quadrant
from calc_risk import check_risk_models, check_stress, check_cash_ts
from calc_sankey import check_sankey
from calc_models import fill_derived
from calc_slots import write_fillsheet, build_slots

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



# ─────────────────────────── 1. 结构检查 ───────────────────────────

def walk_leaves(node, path, out):
    if isinstance(node, dict):
        # 含 cur 的 dict 一律视为数据叶子——只写 {"cur": x} 的孤儿节点也必须
        # 落入叶子集（src 缺失由 check_structure 报 FAIL），不得静默吞掉
        if "cur" in node:
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
        # hist_ye（半年报平均余额比率的期初口径）：末位必须 = prev（本期期初）
        hye = node.get("hist_ye")
        prev = node.get("prev")
        if isinstance(hye, list) and hye:
            nums_ye = [num(x) for x in hye]
            if any(n is None for n in nums_ye):
                rep.add(FAIL, "type", f"{loc}.hist_ye 含非数值元素")
            elif not isinstance(prev, (int, float)) or isinstance(prev, bool):
                # prev 缺失/畸形而 hist_ye 非空：声称有期初序列却无 prev，口径脱钩不许静默
                bad_hist += 1
                rep.add(FAIL, "hist", f"{loc}.hist_ye 非空但 prev 缺失或非数值"
                                      f"（hist_ye 末位必须是本期期初=prev，二者不许脱钩）")
            elif abs(nums_ye[-1] - float(prev)) > max(0.005 * abs(float(prev)), 0.005):
                bad_hist += 1
                rep.add(FAIL, "hist", f"{loc}.hist_ye 末位 {nums_ye[-1]} ≠ prev {prev}"
                                      f"（hist_ye 末位必须是本期期初=prev）")

    # derived.ratios 的趋势比率同样带 hist，末位必须 = cur。比率节点无 src（复算值），
    # 不能混入 walk_leaves（会误报 src 为空），故单独遍历、只查 hist 一致性
    for name, node in ((data.get("derived") or {}).get("ratios") or {}).items():
        if not isinstance(node, dict):
            # 裸数字节点合法（check_ratios 兼容）；字符串等其他类型是畸形，必须报
            if node is not None and num(node) is None:
                rep.add(FAIL, "type", f"derived.ratios.{name} 类型非法：{type(node).__name__}"
                                      f"（比率节点应为对象或数值）")
            continue
        cur = node.get("cur")
        if cur is not None and (not isinstance(cur, (int, float)) or isinstance(cur, bool)):
            rep.add(FAIL, "type", f"derived.ratios.{name}.cur 类型非法：{type(cur).__name__}"
                                  f"（比率必须数值，禁止「5.2%」类字符串）")
            continue
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

    # holder_ts（schema 1.6 选填块，v0.1.0 N4）：labels/num/px 三数组等长非空、
    # num 数值（户）、px 首期 null 余数值——holders 图的数据契约（≥3 期才画图）
    hts = ((data.get("notes") or {}).get("shareholders") or {}).get("holder_ts")
    if hts is not None:
        ls, ns, ps = hts.get("labels") or [], hts.get("num") or [], hts.get("px") or []
        if not ls or not (len(ls) == len(ns) == len(ps)):
            rep.add(FAIL, "holder-ts",
                    f"holder_ts 三数组须等长非空：labels={len(ls)} num={len(ns)} px={len(ps)}")
        elif any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in ns):
            rep.add(FAIL, "holder-ts", "holder_ts.num 含非数值元素（户数，单位=户）")
        elif any(p is not None and (not isinstance(p, (int, float)) or isinstance(p, bool))
                 for p in ps):
            rep.add(FAIL, "holder-ts", "holder_ts.px 含非数值元素（环比 %，首期 null）")
        elif ps[0] is not None:
            rep.add(FAIL, "holder-ts", "holder_ts.px 首期必须 null（无环比基期）")
        else:
            rep.add(OK, "holder-ts", f"holder_ts {len(ls)} 期等长合法")


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
        rtype = (data.get("meta") or {}).get("report_type") or ""
        if ocf is not None and "季报" not in rtype:
            rep.add(WARN, "bridge.ocf", f"OCF 调节桥未填或不完整（已填 {n} 项）但经营现金流净额已填"
                                        "——回原文确认「现金流量表补充资料」是否真未披露"
                                        "（年报/半年报/招股书均强制披露，换搜「将净利润调节为」复核），勿凭常识降级")
        else:
            rep.add(SKIP, "bridge.ocf", f"OCF 调节桥未填或不完整（已填 {n} 项）"
                                        + ("（季报无附注，A3 裁剪属常态）" if "季报" in rtype else ""))
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

def check_ratio_hist(data, rep):
    """趋势比率逐期复算：逐期对齐逻辑委托 calc_common.ratio_hist_series（唯一定义处，
    与 --fill 预填共用），容差与 check_ratios 相同。"""
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
        if RATIO_HIST_SPECS.get(name) is None:
            continue  # 单期专用比率不序列化，无 hist 可查
        series = ratio_hist_series(data, name)
        for k in range(min(len(rh), len(series))):
            got = rh[len(rh) - 1 - k]
            expect = series[len(series) - 1 - k]
            if got is None:
                # hist 含非数值元素（结构检查已报 type FAIL）——跳过，不重复报也不崩
                n_skip += 1
                continue
            if expect is None:
                rep.add(SKIP, "ratio-hist", f"{name} 首期无期初余额/科目序列不全，跳过复算")
                n_skip += 1
                continue
            if abs(got - expect) <= max(0.02 * abs(expect), 0.005):
                n_ok += 1
            else:
                n_fail += 1
                rep.add(FAIL, "ratio-hist", f"{name}.hist 该期复算不符：填 {got:.4f}，重算 {expect:.4f}"
                                            f"（差 {got - expect:+.4f}）")
    if missing_hist and n_ok == 0 and n_fail == 0:
        msg = f"趋势比率缺 hist（口径断裂等），趋势降级两期：{', '.join(missing_hist)}"
        if n_skip:
            msg += f"；另有 {n_skip} 期跳过（首期无期初余额/科目序列不全/hist 含非数值）"
        rep.add(SKIP, "ratio-hist", msg)
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
        sev = s.get("severity")
        if sev is not None and (not isinstance(sev, (int, float)) or isinstance(sev, bool)
                                or not (0 <= sev <= 1)):
            bad += 1
            rep.add(FAIL, "signals", f"signals[{i}].severity={sev} 非法——必须 ∈ [0,1] 数值")
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


def check_segment_quadrant(data, rep):
    """derived.segment_quadrant 自洽（schema v1.5）：选填块——填则全字段与
    compute_segment_quadrant 复算值比对，缺省合法 SKIP。公式/边界规则见
    factor-analysis.md 第六节与 extraction-schema.md；容差与 check_ratios 同规。"""
    sq = (data.get("derived") or {}).get("segment_quadrant")
    if sq is None:
        rep.add(SKIP, "segment-quadrant", "segment_quadrant 未落库（选填块；现算或不适用合法）")
        return
    expect = compute_segment_quadrant(data)
    if expect is None:
        rep.add(SKIP, "segment-quadrant", "by_segment<2 条（单产品裁剪路径，整块应缺省）")
        return
    fails0 = rep.counts()[FAIL]
    rows, erows = sq.get("rows") or [], expect["rows"]
    if len(rows) != len(erows):
        rep.add(FAIL, "segment-quadrant", f"rows 条数 {len(rows)} ≠ by_segment {len(erows)}")
        return

    def _cmp(field, got, want, label):
        if want is None:
            if got is not None:
                rep.add(FAIL, "segment-quadrant", f"{label} {field} 应为 null（口径不可算），实际 {got}")
        elif got is None or abs(got - want) > max(0.02 * abs(want), 0.005):
            rep.add(FAIL, "segment-quadrant",
                    f"{label} {field}={got} 与复算值 {want:.4f} 不符")

    _cmp("x0", num(sq.get("x0")), expect["x0"], "整体")
    _cmp("y0", num(sq.get("y0")), expect["y0"], "整体")
    ym = sq.get("y_mode")
    if ym != expect["y_mode"]:
        rep.add(FAIL, "segment-quadrant",
                f"y_mode={ym} 与数据形态不符（prev 齐备应 {expect['y_mode']}）")
    for i, (row, erow) in enumerate(zip(rows, erows)):
        if row.get("name") != erow["name"]:
            rep.add(FAIL, "segment-quadrant",
                    f"rows[{i}].name={row.get('name')!r} 与 by_segment 序不符（应 {erow['name']!r}）")
            continue
        label = f"分部「{erow['name']}」"
        for f in ("g", "m", "dm", "w", "p", "p_minus_w"):
            _cmp(f, num(row.get(f)), erow[f], label)
        for f in ("rank_gap", "quadrant"):
            if row.get(f) != erow[f]:
                rep.add(FAIL, "segment-quadrant",
                        f"{label} {f}={row.get(f)} 与复算 {erow[f]} 不符")
    if rep.counts()[FAIL] == fails0:
        rep.add(OK, "segment-quadrant", f"四象限 {len(rows)} 行全字段复算自洽（y_mode={ym}）")


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


# --min-recon auto 校准表（v0.1.2）：A 股三档见 report-types.md；港股半年报 8 = 蜜雪 2026H1
# 实测结构性上限（无直接法收现 A4/B1、无存货增加额附注 B2、无在建工程科目 B3、无母公司
# 单体报表 D 组）——13 是 A 股披露假设，港股照套会把合法缺披露误升 FAIL。
# v0.1.3：港股年报 12 = 阿里巴巴 2026FY 实测上限——年报比半年报多出 B4（商誉附注年度披露）
# 与 D 组 4/5（附注 30 母公司简明财务资料，S-X 4-08(e)(3) 披露），仍缺 A4/B1/B2/B3/D3。
# 未实证组合不入表；auto 查不到时退回 WARN 态并提示显式给数。
AUTO_MIN_RECON = {("A股", "年报"): 15, ("A股", "半年报"): 13, ("A股", "季报"): 8,
                  ("港股", "半年报"): 8, ("港股", "年报"): 12}


def check_recon_coverage(data, rep, min_recon=None):
    """recon 覆盖率：非空时统计已执行的等式，提醒未做项（缺数合法，漏做不可）。
    min_recon（--min-recon）给定时未达标由 WARN 升 FAIL——建议阈值见 report-types.md
    （年报 ≥15/17、半年报 ≥13、季报 ≥8）；recon 为空仍 SKIP（无法区分不适用与漏做）。"""
    recon = data.get("recon") or {}
    if not recon:
        rep.add(SKIP, "recon-coverage", "recon 为空，覆盖率不适用")
        return
    total = len(RECON_RULES)
    filled = [k for k in RECON_RULES if isinstance(recon.get(k), dict) and recon[k].get("verdict")]
    missing = [k for k in RECON_RULES if k not in filled]
    if not missing:
        rep.add(OK, "recon-coverage", f"{total} 条等式全部给出判定（{len(filled)}/{total}）")
    elif min_recon is not None and len(filled) < min_recon:
        rep.add(FAIL, "recon-coverage", f"recon 覆盖 {len(filled)}/{total} 未达 --min-recon {min_recon}，"
                                        f"未给判定：{', '.join(missing)}——逐条补判定或写明附注未披露")
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
    ap.add_argument("--fill", action="store_true",
                    help="预填 derived 机械字段（ratios/杜邦族/cycle_evidence/threshold_check/risk_models/stress/cash_ts/segment_quadrant/单期八项）"
                         "并产出 {stem}.fillsheet.md 填充速查表；判断字段（桥/rev_factors/recon/notes）不动")
    ap.add_argument("--min-recon", type=lambda s: s if s == "auto" else int(s),
                    default=None, metavar="N|auto",
                    help="recon 已判定等式条数下限（A 股：年报 15、半年报 13、季报 8；港股半年报 8）；"
                         "auto = 按 meta.market+report_type 查校准表（v0.1.2，未知组合退回 WARN 态）；"
                         "未达标时 recon-coverage 由 WARN 升 FAIL（v0.0.17，任务 5）")
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

    if args.fill:
        n_filled = fill_derived(data)
        src = Path(args.json_path)
        src.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sheet_path = src.parent / (src.stem + ".fillsheet.md")
        write_fillsheet(data, sheet_path)
        # v0.1.0（N4）：机器可读槽位契约，render_report.py 的唯一数据源
        slots_path = src.parent / (src.stem + ".fillsheet.json")
        slots_path.write_text(json.dumps(build_slots(data), ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
        print(f"✍️ --fill：预填 {n_filled} 个机械字段 → {src.name}；速查表 → {sheet_path.name}；"
              f"槽位 JSON → {slots_path.name}")

    rep = Report()
    check_structure(data, rep)
    check_core_fields(data, rep)
    check_balance_identity(data, rep)
    check_retained_roll(data, rep)
    check_bridges(data, rep)
    check_ratios(data, rep)
    check_ratio_hist(data, rep)
    check_dupont(data, rep)
    check_dupont_dt(data, rep)
    check_dupont5y(data, rep)
    check_cycle_evidence(data, rep)
    check_threshold_check(data, rep)
    check_peers(data, rep)
    check_risk_models(data, rep)
    check_stress(data, rep)
    check_cash_ts(data, rep)
    check_recon(data, rep)
    min_recon = args.min_recon
    if min_recon == "auto":
        _mk = ((data.get("meta") or {}).get("market"), (data.get("meta") or {}).get("report_type"))
        min_recon = AUTO_MIN_RECON.get(_mk)
        if min_recon is None:
            print(f"🟡 --min-recon auto：校准表无「{_mk[0] or '?'}/{_mk[1] or '?'}」组合，"
                  f"退回 WARN 态——请按报告实际显式给数字")
        else:
            print(f"ℹ️ --min-recon auto：{_mk[0]}{_mk[1]} → recon 覆盖下限 {min_recon}")
    check_recon_coverage(data, rep, min_recon=min_recon)
    check_segments(data, rep)
    check_segment_quadrant(data, rep)
    check_sankey(data, rep)
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
    failed = c[FAIL]
    print(f"\n--- 汇总：FAIL {c[FAIL]} · WARN {c[WARN]} · OK {c[OK]} · SKIP {c[SKIP]} ---")
    if failed:
        print("❌ QC 未通过：修正上述 FAIL 后重跑，禁止带病写报告（Phase 8）。")
        return 1
    print("✅ QC 全绿：可进入 Phase 8 写报告。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
