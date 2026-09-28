# -*- coding: utf-8 -*-
"""calc_models.py — fill 编排层（--fill 预填 + 填充速查表），v0.0.15 起不再含公式：
杜邦族 → calc_dupont.py；证据读数族 → calc_evidence.py；风险模型族 → calc_risk.py；
比率公式唯一定义处仍在 calc_common.py。本层只做「调各族 compute_* 预填 derived」
的编排与 fillsheet 产出。
"""

import pathlib

from calc_common import build_ratio_calcs, ratio_hist_series, RATIO_HIST_SPECS
from calc_dupont import compute_dupont, compute_dupont_dt, compute_dupont5y
from calc_evidence import compute_cycle_evidence, compute_threshold_check
from calc_risk import compute_altman, compute_ohlson, compute_stress, compute_cash_ts

R4 = lambda x: None if x is None else round(x, 4)


def _r4deep(x):
    """嵌套结构的递归 R4（dupont 下钻子块/dupont5y.percentile 用）。"""
    if isinstance(x, dict):
        return {k: _r4deep(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_r4deep(v) for v in x]
    return R4(x) if isinstance(x, float) else x

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
        rm = {"altman_z": (_filled({k: R4(v) if isinstance(v, float) else v for k, v in alt.items()},
                                   old_alt, "note") if alt else None),
              "ohlson_o": ({k: R4(v) if isinstance(v, float) else v for k, v in ohl.items()}
                           if ohl else None)}
        der["risk_models"] = rm
        n += 1
    st = compute_stress(data)
    if st:
        der["stress"] = _filled({"scenarios": [{k: (R4(v) if isinstance(v, float) else v)
                                                for k, v in sc.items()} for sc in st]},
                                der.get("stress") or {}, "note")
        n += 1
    cts = compute_cash_ts(data)
    if cts:
        der["cash_ts"] = _filled({k: _r4deep(v) for k, v in cts.items()},
                                 der.get("cash_ts") or {}, "note")
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
    L.append("\n## S1 杜邦双卡（v1.3）\n")
    fragile = "，双驱动护栏命中→标「双驱动（%s/%s）」" % (du.get("driver"), du.get("driver_second")) \
        if du.get("driver_fragile") else ""
    L.append(f"- 三效应（pct）：净利率 {du.get('margin_effect')} / 周转率 {du.get('turnover_effect')} / "
             f"杠杆 {du.get('leverage_effect')}；主驱动={du.get('driver')}{fragile}；"
             f"closure_gap={du.get('closure_gap')}")
    md = du.get("margin_drill") or {}
    if md:
        L.append(f"- 净利率下钻子行：经营 {md.get('op_effect')} · 税负 {md.get('tax_effect')} · "
                 f"利息 {md.get('interest_effect')} · 少数股东 {md.get('minority_effect')}（→#s3 净利桥）")
    td = du.get("turnover_drill") or {}
    if td:
        L.append(f"- 周转率下钻子行：Δ总资产前二={td.get('top1_subject')}({td.get('top1_share')})/"
                 f"{td.get('top2_subject')}({td.get('top2_share')})；应收存货类 {td.get('wc_share')} · "
                 f"产能类 {td.get('capex_share')}（→#s1 四维表）")
        # 份额超 ±150% = ΔTA 由大额对冲构成（如存货+71亿/货币资金−76亿对冲），读数仅示方向
        if any(abs(v) > 1.5 for v in (td.get("top1_share"), td.get("wc_share"),
                                      td.get("capex_share")) if isinstance(v, (int, float))):
            L.append("  ⚠️ 份额超 ±150%：Δ总资产系大额对冲构成，份额仅示方向，报告措辞勿写「X 成来自……」")
    ld = du.get("leverage_drill") or {}
    if ld:
        L.append(f"- 杠杆下钻子行：有息/权益 {ld.get('ib_to_equity_cur')}（上期 {ld.get('ib_prev')}→"
                 f"{ld.get('ib_cur')}）· 无息/权益 {ld.get('ni_to_equity_cur')}；无息占比 "
                 f"{ld.get('ni_share')} · ΔDFL {ld.get('dfl_delta')}；升档判定={ld.get('quality_upgrade')}"
                 f"（→#s7 健康检验）")
    dt = (data.get("derived") or {}).get("dupont_dt") or {}
    if dt.get("triggered"):
        L.append(f"- 扣非双版（触发）：主驱动={dt.get('driver')}，三效应 净利率 {dt.get('margin_effect')} / "
                 f"周转率 {dt.get('turnover_effect')} / 杠杆 {dt.get('leverage_effect')}")
    d5 = (data.get("derived") or {}).get("dupont5y") or {}
    if d5:
        L.append(f"- 五年归因（{d5.get('period_start')}→{d5.get('period_end')}）：净利率 "
                 f"{d5.get('margin_effect')} / 周转率 {d5.get('turnover_effect')} / 杠杆 "
                 f"{d5.get('leverage_effect')}；主驱动={d5.get('driver')}；closure_gap={d5.get('closure_gap')}")
        pg = d5.get("percentile") or {}
        L.append(f"- 因子分位（位置读数）：净利率 {pg.get('net_margin')} · 周转率 "
                 f"{pg.get('asset_turnover')} · 权益乘数 {pg.get('equity_multiplier')}")
        nm_h = (ratios.get("net_margin") or {}).get("hist") or []
        at_h = (ratios.get("asset_turnover") or {}).get("hist") or []
        em_h = (ratios.get("equity_multiplier") or {}).get("hist") or []
        roe_h = (ratios.get("roe") or {}).get("hist") or []
        L.append(f"- 右卡 A 表起止列取 hist 首末：净利率 {nm_h} / 周转率 {at_h} / "
                 f"权益乘数 {em_h} / ROE {roe_h}")
    cts = (data.get("derived") or {}).get("cash_ts") or {}
    if cts.get("ncr"):
        L.append("\n## S1 现金时序表（v1.3）\n")
        L.append(f"- periods={cts.get('periods')}")
        L.append(f"- 净现比 ncr={cts.get('ncr')}（均值 {cts.get('ncr_mean5')}，负值 "
                 f"{cts.get('ncr_neg_years')} 年）")
        L.append(f"- FCF÷归母净利={cts.get('fcf_to_np')}（均值 {cts.get('fcf_to_np_mean5')}，负值 "
                 f"{cts.get('fcf_neg_years')} 年）")
    cv = (data.get("derived") or {}).get("cycle_evidence") or {}
    if cv.get("periods"):
        L.append("\n## 周期定位证据表（v1.3）\n")
        L.append(f"- periods={cv.get('periods')}")
        L.append(f"- 收入增速={cv.get('rev_growth')}")
        L.append(f"- 毛利率={cv.get('gross_margin')}")
        L.append(f"- Capex 增速={cv.get('capex_growth')}")
        L.append(f"- meta.cycle_stage={((data.get('meta') or {}).get('cycle_stage'))}（分析师判定）")
    tk = (data.get("derived") or {}).get("threshold_check") or {}
    if tk:
        L.append("\n## 四线考核贴线检测（v1.3）\n")
        L.append(f"- 保壳线（ROE 贴 6.5% 且净利率 0~3%）：{tk.get('shell_line')}")
        L.append(f"- 再融资线（ROE 贴 10%）：{tk.get('refinance_line')}")
        L.append(f"- 激励线（公告取数）：{tk.get('incentive_line') or '无激励计划/未披露'}")
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
