# -*- coding: utf-8 -*-
"""calc_models.py — fill 编排层（--fill 预填 derived），v0.0.15 起不再含公式：
杜邦族 → calc_dupont.py；证据读数族 → calc_evidence.py；风险模型族 → calc_risk.py；
比率公式唯一定义处仍在 calc_common.py；槽位契约（fillsheet/build_slots）v0.1.0 起
归 calc_slots.py。本层只做「调各族 compute_* 预填 derived」的编排。
"""

import json
import pathlib

from calc_common import build_ratio_calcs, ratio_hist_series, RATIO_HIST_SPECS, compute_interest_arrears
from calc_dupont import compute_dupont, compute_dupont_dt, compute_dupont5y
from calc_evidence import compute_cycle_evidence, compute_threshold_check, compute_segment_quadrant
from calc_risk import compute_altman, compute_ohlson, compute_stress, compute_cash_ts
from calc_sankey import compute_sankey
# 再导出保回归契约锁锚点（check_html.py 同款先例）：PCTILE_LABEL 双写之一现居 calc_slots
from calc_slots import PCTILE_LABEL, write_fillsheet, build_slots  # noqa: F401

R4 = lambda x: None if x is None else round(x, 4)

def _r4deep(x):
    """嵌套结构的递归 R4（dupont 下钻子块/dupont5y.percentile 用）。"""
    if isinstance(x, dict):
        return {k: _r4deep(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_r4deep(v) for v in x]
    return R4(x) if isinstance(x, float) else x

_SINGLE_ITEMS = ("short_debt_cover", "incr_expense_eff", "incr_sales_eff",
                 "nonrecurring_share", "non_main_rev_share", "ocf_to_liab",
                 "roic", "sustainable_growth")


def _filled(new, old, *keep):
    """fill 语义：机械字段整体换新，keep 列出的判断/出处字段保留旧值不覆盖。"""
    return {**new, **{k: old[k] for k in keep if k in old}}


def fill_derived(data):
    """预填 derived 机械字段（判断字段 rev_factors/桥/recon/notes 不动）。返回改动计数。"""
    der = data.setdefault("derived", {})
    ratios = der.setdefault("ratios", {})
    calc = build_ratio_calcs(data)
    n = 0
    for name in RATIO_HIST_SPECS:
        cur = calc.get(name)
        series = [x for x in (ratio_hist_series(data, name) or []) if x is not None]
        old = ratios.get(name)
        old = old if isinstance(old, dict) else {}  # 裸数字等畸形节点不崩，按未填处理
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
            old = ratios.get(name)
            old = old if isinstance(old, dict) else {}
            ratios[name] = {**old, "cur": R4(v)}
            n += 1
    # 各模型族机械块：compute_* 是公式唯一定义处，fill 只编排、保留下钻块的 src/note
    for key, compute in (("dupont", compute_dupont), ("dupont_dt", compute_dupont_dt),
                         ("dupont5y", compute_dupont5y), ("cycle_evidence", compute_cycle_evidence)):
        out = compute(data)
        if key == "dupont_dt" and (not out or out.get("triggered") is None):
            continue  # 扣非双版：无法判定（np_dt 缺）时不落块
        if out:
            der[key] = _filled({k: _r4deep(v) for k, v in out.items()},
                               der.get(key) or {}, "src", "note")
            n += 1
    tc = compute_threshold_check(data)
    if tc:
        old = der.get("threshold_check") or {}
        inc = (old.get("incentive_line") or {}) if isinstance(old.get("incentive_line"), dict) else {}
        der["threshold_check"] = _filled({**{k: _r4deep(v) for k, v in tc.items()},
                                          **({"incentive_line": inc} if inc else {})},
                                         old, "note")
        n += 1
    alt, _ = compute_altman(data)
    ohl, _ = compute_ohlson(data)
    if alt or ohl:
        old = der.get("risk_models") or {}
        old_alt = old.get("altman_z") if isinstance(old.get("altman_z"), dict) else {}
        old_ohl = old.get("ohlson_o") if isinstance(old.get("ohlson_o"), dict) else {}
        rm = {"altman_z": (_filled({k: R4(v) if isinstance(v, float) else v for k, v in alt.items()},
                                   old_alt, "note") if alt else None),
              "ohlson_o": (_filled({k: R4(v) if isinstance(v, float) else v for k, v in ohl.items()},
                                   old_ohl, "note") if ohl else None)}
        # 块级 note 也是判断字段（万科轮实证：地产适用性声明被 fill 吞掉）——保留不覆盖
        der["risk_models"] = _filled(rm, old, "note")
        n += 1
    st = compute_stress(data)
    if st:
        der["stress"] = _filled({"scenarios": [{k: (R4(v) if isinstance(v, float) else v)
                                                for k, v in sc.items()} for sc in st[0]]},
                                der.get("stress") or {}, "note")
        n += 1
    cts = compute_cash_ts(data)
    if cts:
        der["cash_ts"] = _filled({k: _r4deep(v) for k, v in cts.items()},
                                 der.get("cash_ts") or {}, "note")
        n += 1
    sq = compute_segment_quadrant(data)
    if sq:
        der["segment_quadrant"] = _filled({k: _r4deep(v) for k, v in sq.items()},
                                          der.get("segment_quadrant") or {}, "src", "note")
        n += 1
    sk = compute_sankey(data)
    if sk:
        der["sankey"] = _filled({k: _r4deep(v) for k, v in sk.items()},
                                der.get("sankey") or {}, "src", "note", "cum_prev")
        if not der["sankey"].get("src") and sk.get("period_type") == "本期":
            der["sankey"]["src"] = "合并利润表/合并现金流量表（机械复算）"
        n += 1
    else:
        old_sk = der.get("sankey")
        if isinstance(old_sk, dict) and old_sk.get("rev") is not None:
            # 已计算块遭遇降级形态（如转亏/现金流转负）→ 置 null 触发降级卡；
            # 无 rev 的部分预填块（Q3 cum_prev 种子）保留不吞
            der["sankey"] = None
            n += 1
    ia = compute_interest_arrears(data)
    old_ia = der.get("interest_arrears")
    old_ia = old_ia if isinstance(old_ia, dict) else {}
    if ia is not None:
        der["interest_arrears"] = _filled({"cur": R4(ia)}, old_ia, "note")
        n += 1
    elif old_ia.get("cur") is not None:
        der["interest_arrears"] = _filled({"cur": None}, old_ia, "note", "src", "level")
        n += 1
    return n
