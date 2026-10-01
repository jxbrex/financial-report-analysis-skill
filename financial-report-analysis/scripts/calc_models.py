# -*- coding: utf-8 -*-
"""calc_models.py — fill 编排层（--fill 预填 + 填充速查表），v0.0.15 起不再含公式：
杜邦族 → calc_dupont.py；证据读数族 → calc_evidence.py；风险模型族 → calc_risk.py；
比率公式唯一定义处仍在 calc_common.py。本层只做「调各族 compute_* 预填 derived」
的编排与 fillsheet 产出。
"""

import json
import pathlib
import statistics

from calc_common import build_ratio_calcs, ratio_hist_series, RATIO_HIST_SPECS
from calc_dupont import compute_dupont, compute_dupont_dt, compute_dupont5y
from calc_evidence import compute_cycle_evidence, compute_threshold_check
from calc_risk import compute_altman, compute_ohlson, compute_stress, compute_cash_ts

R4 = lambda x: None if x is None else round(x, 4)
# 呈现两位小数（fillsheet 机械槽位：原始精度留 json，报告可见数字 ≤2 位，v0.0.19）
R2 = lambda x: None if x is None else round(x, 2)

# 分位白描映射：(rank−1)/(n−1)，n=5 离散步长 0.25 → X/5（五年从高到低第 X，v0.0.19）。
# 与 check_html_text.py PCTILE_LABEL 双写互指（跨家族 import 会造成 calc↔check_html 耦合，
# 故保持双写 + 回归一致性断言锁契约，改动必须同步）
PCTILE_LABEL = {0.0: "5/5", 0.25: "4/5", 0.5: "3/5", 0.75: "2/5", 1.0: "1/5"}


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
                                                for k, v in sc.items()} for sc in st]},
                                der.get("stress") or {}, "note")
        n += 1
    cts = compute_cash_ts(data)
    if cts:
        der["cash_ts"] = _filled({k: _r4deep(v) for k, v in cts.items()},
                                 der.get("cash_ts") or {}, "note")
        n += 1
    return n


def write_fillsheet(data, path):
    """填充速查表：P8 机械槽位的值+徽章+语义色+JS 槽数组，模型照抄不进算术。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}
    L = []
    L.append("# 填充速查表（calc.py --fill 产出——机械槽位照抄，判断槽位自己写）\n")
    L.append("> 徽章：der=两数运算；语义色：up=利好/dn=利空/不染=语境中性（方向语义表）。")
    L.append("> **本表是 Phase 8 唯一槽位契约（v0.0.18）**：填充只看本表，不需要对照 examples 标杆；"
             "数值一律从本表复制，禁凭记忆手写（check_html T8① 会回验 HTML↔json 一致性）。")
    L.append("\n## S1 四维表（本期 / 上期 / 较上期；v0.0.22 起 spark 趋势列退役，"
             "五期序列改由 EFF_TS/trend 图区呈现）\n")
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
        _p2 = lambda x: "—" if x is None else f"{x * 100:+.2f}pct"
        _rd = None
        if d5.get("roe_start") is not None and d5.get("roe_end") is not None:
            _rd = (d5["roe_end"] - d5["roe_start"]) * 100
        L.append(f"- 五年累计列照抄（v0.0.19 统一口径：该因子对 ΔROE 的累计贡献，±x.xxpct 两位小数，"
                 f"三因子行可加、合计=Δ三因子积；禁止填因子自身水平变化）：净利率 "
                 f"{_p2(d5.get('margin_effect'))} / 周转率 {_p2(d5.get('turnover_effect'))} / "
                 f"杠杆 {_p2(d5.get('leverage_effect'))}；ROE 行 ΔROE="
                 f"{'—' if _rd is None else f'{_rd:+.2f}pct'}；口径差 {_p2(d5.get('closure_gap'))}"
                 f" 写 ROE 行读法列")
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
    _hist = lambda node: (node or {}).get("hist") or []
    _r2l = lambda arr: [R2(x) for x in arr]
    _m = lambda x: '—' if x is None else R2(x)
    if cts.get("ncr"):
        L.append("\n## S1 NCR_TS 槽（JS 区粘贴；v0.0.20 现金时序卡表格改双折线图——"
                 "fcf 短序列前置 null 跳点；fcf 均值与负值年数写进卡 takeaway 判定语）\n")
        L.append(f"const NCR_TS={{labels:{json.dumps(cts.get('periods') or [], ensure_ascii=False)},"
                 f"ncr:{json.dumps(_r2l(cts.get('ncr') or []))},"
                 f"fcf:{json.dumps(_r2l(cts.get('fcf_to_np') or []))},"
                 f"mean:{json.dumps(R2(cts.get('ncr_mean5')))}}};")
        L.append(f"- takeaway 判定语素材：净现比均值 {_m(cts.get('ncr_mean5'))}（OCF 为负 "
                 f"{cts.get('ncr_neg_years')} 年）· FCF 均值 {_m(cts.get('fcf_to_np_mean5'))}（FCF 为负 "
                 f"{cts.get('fcf_neg_years')} 年）")
        L.append("- figtitle 纪律（v0.0.21 用户定案）：提及 FCF 线须写白指标含义——"
                 "「FCF=经营现金流−资本开支，即维持生产后真正可自由支配的现金」，指标名不解释=低信息量")
    cv = (data.get("derived") or {}).get("cycle_evidence") or {}
    if cv.get("periods"):
        L.append("\n## 周期定位判词声明行素材（v0.0.21：判定句挂趋势图卡 .wv 大字声明行"
                 "——srcline 小字降权过度用户定案；「周期定位：X（一句注解）」，非周期股填"
                 "「非周期行业」；三线读数留底稿不进报告）\n")
        L.append(f"- meta.cycle_stage={((data.get('meta') or {}).get('cycle_stage'))}（分析师判定）"
                 f" · 三线读数（底稿备查）：收入增速={cv.get('rev_growth')} / "
                 f"毛利率={cv.get('gross_margin')} / Capex 增速={cv.get('capex_growth')}")
    tk = (data.get("derived") or {}).get("threshold_check") or {}
    if tk:
        L.append("\n## 四线考核贴线检测（v1.3）\n")
        L.append(f"- 保壳线（ROE 贴 6.5% 且净利率 0~3%）：{tk.get('shell_line')}")
        L.append(f"- 再融资线（ROE 贴 10%）：{tk.get('refinance_line')}")
        L.append(f"- 激励线（公告取数）：{tk.get('incentive_line') or '无激励计划/未披露'}")
    rm = (data.get("derived") or {}).get("risk_models") or {}
    st = (data.get("derived") or {}).get("stress") or {}
    L.append("\n## S7 健康检验数值行\n")
    L.append("- 行序纪律（v0.0.22 用户定案）：固定主题序=模板行序照抄，不按判定重排——"
             "判定分布由徽章色 + figtitle 汇总（「N 项：x 过 y 注意 z 异常」）传达")
    L.append(f"- 短债覆盖 {ratios.get('short_debt_cover', {}).get('cur')} 倍 · "
             f"X6 {ratios.get('ocf_to_liab', {}).get('cur')}")
    L.append(f"- Altman {rm.get('altman_z') or 'null（市值缺）'} · Ohlson {rm.get('ohlson_o') or 'null'}")
    L.append(f"- 压力情景 {st.get('scenarios') or 'null'}")
    L.append(f"- 增量费用效率 {ratios.get('incr_expense_eff', {}).get('cur')} · "
             f"获客效率 {ratios.get('incr_sales_eff', {}).get('cur')}")
    L.append(f"- ROIC（去杠杆，vs ROE 看杠杆撑多少） {ratios.get('roic', {}).get('cur')} · "
             f"内生增长率（亏损期 null） {ratios.get('sustainable_growth', {}).get('cur')}")

    # ── v0.0.18 契约补全：剩余机械槽位（照抄）+ 判断槽位清单 ──
    meta = data.get("meta") or {}
    stmts = data.get("statements") or {}
    inc, cfs = stmts.get("income") or {}, stmts.get("cashflow") or {}
    notes = data.get("notes") or {}
    _v = lambda blk, f, k="cur": (blk.get(f) or {}).get(k)
    _yoy = lambda c, p: "—" if not c or not p else f"{(c - p) / abs(p) * 100:+.1f}%"

    L.append("\n## 页眉页脚槽（meta 照抄）\n")
    L.append(f"- 公司名={meta.get('company')} · 代码={meta.get('code')} · 上市地={meta.get('market')} · "
             f"报告期={meta.get('period')} · 报告类型={meta.get('report_type')} · "
             f"披露日期={meta.get('disclose_date')} · 生成日期={meta.get('analyst_date')} · "
             f"单位={meta.get('unit')}")

    L.append("\n## S1 KPI 行（statements 照抄；金额一律 R2 两位小数——原始精度留 json，"
             "报告可见数字 ≤2 位小数，v0.0.19）\n")
    roe_n = ratios.get("roe") or {}
    roe_d = None if roe_n.get("cur") is None or roe_n.get("prev") is None \
        else (roe_n["cur"] - roe_n["prev"]) * 100
    L.append(f"- 营业收入 {R2(_v(inc, 'revenue'))} 亿（同比 {_yoy(_v(inc, 'revenue'), _v(inc, 'revenue', 'prev'))}）"
             f" <span class=\"badge disc\">披露</span>")
    L.append(f"- 归母净利 {R2(_v(inc, 'np_at'))} 亿（同比 {_yoy(_v(inc, 'np_at'), _v(inc, 'np_at', 'prev'))}） disc · "
             f"经营现金流 {R2(_v(cfs, 'ocf'))} 亿 · 净现比 {R2((cts.get('ncr') or [None])[-1])} der")
    L.append(f"- ROE {'—' if roe_n.get('cur') is None else f'{roe_n['cur'] * 100:.2f}%'}"
             f"（较上期 {'—' if roe_d is None else f'{roe_d:+.1f}pct'}） der · "
             f"扣非对照 {R2(_v(inc, 'np_dt'))}（差 >1pct 时该行染 dn 色）")

    L.append("\n## S1 TREND 槽（JS 区粘贴；np_dt/roe 缺 hist 留空数组；**gm 填百分数**"
             "（绘图不做 ×100，填小数会显示成 0.2%），**roe 存小数**（绘图 ×100）；"
             "金额序列一律 R2 两位小数，v0.0.19；capex=四宫格右下 Capex·研发双柱图，v0.0.20；"
             "ocf=npchart 经营现金流柱（可负）、rd=右下图研发费用柱，v0.0.22）\n")
    labels = cts.get("periods") or cv.get("periods") or []
    _aln = lambda arr: ([None] * (len(labels) - len(arr)) + arr)[-len(labels):] \
        if labels and arr else arr
    _gm_pct = [round(x * 100, 2) if x is not None else None
               for x in _aln(_hist(ratios.get("gross_margin")))]
    L.append(f"const TREND={{labels:{json.dumps(labels, ensure_ascii=False)},"
             f"rev:{json.dumps(_r2l(_aln(_hist(inc.get('revenue')))))},"
             f"np:{json.dumps(_r2l(_aln(_hist(inc.get('np_at')))))},"
             f"np_dt:{json.dumps(_r2l(_aln(_hist(inc.get('np_dt')))))},"
             f"ocf:{json.dumps(_r2l(_aln(_hist(cfs.get('ocf')))))},"
             f"roe:{json.dumps(_aln(_hist(roe_n)))},"
             f"gm:{json.dumps(_gm_pct)},"
             f"capex:{json.dumps(_r2l(_aln(_hist(cfs.get('capex')))))},"
             f"rd:{json.dumps(_r2l(_aln(_hist(inc.get('rd_exp')))))}}};")

    L.append("\n## S1 EFF_TS 槽（JS 区粘贴；v0.0.22 营运效率三线图——接替退役的四维表 "
             "spark 列；dio/dso/ccc 单位均为天，CCC 可负；某序列不足 2 个非空点整线不画）\n")
    L.append(f"const EFF_TS={{labels:{json.dumps(labels, ensure_ascii=False)},"
             f"dio:{json.dumps(_r2l(_aln(_hist(ratios.get('dio')))))},"
             f"dso:{json.dumps(_r2l(_aln(_hist(ratios.get('dso')))))},"
             f"ccc:{json.dumps(_r2l(_aln(_hist(ratios.get('ccc')))))}}};")

    if du:
        _p1 = lambda x: None if x is None else round(x * 100, 1)
        L.append("\n## S1 DUPONT_STACK 槽（JS 区粘贴；gap≠0 必须保留第四段，不许视觉隐瞒）\n")
        L.append(f"const DUPONT_STACK={{steps:[['净利率',{_p1(du.get('margin_effect'))}],"
                 f"['周转率',{_p1(du.get('turnover_effect'))}],['杠杆',{_p1(du.get('leverage_effect'))}]],"
                 f"gap:{_p1(du.get('closure_gap'))}}};")
    if d5:
        pg = d5.get("percentile") or {}
        L.append("\n## S1 杜邦右卡分位白描（照抄进「五年位置」列 badge disc；禁贴档位标签）\n")
        L.append(f"- 净利率「{PCTILE_LABEL.get(pg.get('net_margin'), pg.get('net_margin'))}」 · "
                 f"周转率「{PCTILE_LABEL.get(pg.get('asset_turnover'), pg.get('asset_turnover'))}」 · "
                 f"权益乘数「{PCTILE_LABEL.get(pg.get('equity_multiplier'), pg.get('equity_multiplier'))}」")

    sig = data.get("signals") or []
    if sig:
        L.append("\n## S2 信号计数与勾稽异常\n")
        cnt = {}
        for s in sig:
            cnt[s.get("verdict")] = cnt.get(s.get("verdict"), 0) + 1
        L.append(f"- 四计数：命中 {cnt.get('命中', 0)} · 观察 {cnt.get('观察', 0)} · "
                 f"反向 {cnt.get('反向未触发', 0)} · 未触发 {cnt.get('未触发', 0)}（已检 {len(sig)} 项）")
        obs = [f"{s.get('id')}「{s.get('title')}」" for s in sig if s.get("verdict") == "观察"]
        L.append(f"- 观察行候选（挑 ≤6 条写「担心→本案」，素材=该条 concern/evidence）："
                 + ("；".join(obs) if obs else "无"))
    rec = data.get("recon") or {}
    abn = [(k, v) for k, v in rec.items()
           if isinstance(v, dict) and v.get("verdict") and "闭合" not in str(v.get("verdict"))]
    if abn:
        L.append(f"- 勾稽异常行（⚠️/🔴 才进正文；✅ 闭合 {len(rec) - len(abn)} 条一行汇总）：")
        for k, v in abn:
            L.append(f"  · {k} [{v.get('verdict')}] lhs={v.get('lhs')} rhs={v.get('rhs')}：{v.get('explanation')}")
    elif rec:
        L.append(f"- 勾稽全部闭合（{len(rec)} 条），正文一行汇总即可")

    L.append("\n## S3 SEG_BRIDGE / SEG_ENDS 槽（JS 区粘贴；SEG_ENDS=端点柱数据 v0.0.21，"
             "端点行 .brends：基期收入→合计→本期收入）\n")
    rf = (data.get("derived") or {}).get("rev_factors") or {}
    if any(rf.get(k) is not None for k in ("volume", "price", "mix")):
        seg = [["量效应", rf.get("volume") or 0], ["价效应", rf.get("price") or 0],
               ["结构效应", rf.get("mix") or 0]]
        L.append(f"const SEG_BRIDGE={json.dumps(seg, ensure_ascii=False)};")
    else:
        L.append(f"// 无量价（rev_factors 全 null）→ 分部轴降级，各分部贡献照 rev_factors.note 手填：")
        L.append(f"// {rf.get('note') or '（note 未填分部拆解，回 Phase 7 补）'}")
        L.append("const SEG_BRIDGE=[['分部A',0],['分部B',0],['其他',0]];")
    L.append(f"const SEG_ENDS={json.dumps([R2(_v(inc, 'revenue', 'prev')), R2(_v(inc, 'revenue'))])};")
    L.append(f"// 端点行（.brends 与 SEG_ENDS 同源）：基期收入 {R2(_v(inc, 'revenue', 'prev'))} 亿 →（合计 "
             f"{None if _v(inc, 'revenue') is None or _v(inc, 'revenue', 'prev') is None else round(_v(inc, 'revenue') - _v(inc, 'revenue', 'prev'), 2)} 亿）"
             f"→ 本期收入 {R2(_v(inc, 'revenue'))} 亿")

    npb = (data.get("derived") or {}).get("np_bridge") or []
    if npb:
        L.append("\n## S3 净利桥（照抄：本期/上期/贡献额Δ；— 表示该环节无直接字段，照利润表对应行）\n")
        def _sumf(fields, k):
            """多字段合计（如期间费用四费）：全 None → None；部分 None 按 0 计。"""
            vals = [_v(inc, f, k) for f in fields]
            if not any(v is not None for v in vals):
                return None
            return round(sum(v or 0 for v in vals), 4)

        def _gp(k):
            """毛利=revenue−cost（gross_profit 常未单列，推算口径）。"""
            a, b = _v(inc, "revenue", k), _v(inc, "cost", k)
            return round(a - b, 4) if a is not None and b is not None else None
        _abs = {
            "毛利": (_gp("cur"), _gp("prev")),
            "税金及附加": (_v(inc, "tax_surcharge"), _v(inc, "tax_surcharge", "prev")),
            "期间费用（销售/管理/研发/财务）": (_sumf(("sell_exp", "admin_exp", "rd_exp", "fin_exp"), "cur"),
                                          _sumf(("sell_exp", "admin_exp", "rd_exp", "fin_exp"), "prev")),
            "减值（信用+资产）": (_v(inc, "impair_loss"), _v(inc, "impair_loss", "prev")),
            "投资/公允/资产处置": (_sumf(("invest_income", "fv_change_income"), "cur"),
                              _sumf(("invest_income", "fv_change_income"), "prev")),
            "其他收益（政府补助等）": (_v(inc, "other_biz_income"), _v(inc, "other_biz_income", "prev")),
            "非经（营业外收支净）": (_v(inc, "non_op_net"), _v(inc, "non_op_net", "prev")),
            "所得税": (_v(inc, "income_tax"), _v(inc, "income_tax", "prev")),
            "少数股东": (_v(inc, "minority_np"), _v(inc, "minority_np", "prev")),
        }
        L.append("| 环节 | 本期 | 上期 | 贡献额Δ |")
        L.append("|---|---|---|---|")
        for x in npb:
            a, b = _abs.get(x.get("item"), (None, None))
            L.append(f"| {x.get('item')} | {a if a is not None else '—'} | "
                     f"{b if b is not None else '—'} | {x.get('delta'):+} |")
        L.append("- 模板行归并指引：「投资/公允/资产处置」「其他收益」「非经（营业外）」三项"
                 "对应模板「非经常性损益」一行（或按公司习惯拆行），Σ 须等于 Δ归母净利；"
                 "期间费用备注列写销售/管理/研发/财务逐项Δ（income 同名字段取）")

    ob = (data.get("derived") or {}).get("ocf_bridge") or []
    if ob:
        L.append("\n## S3 OCF_BRIDGE 槽（JS 区粘贴；项数纪律 ≤6 根+「其他」，已按 |Δ| 归并）\n")
        items = [(x.get("item"), x.get("delta")) for x in ob
                 if isinstance(x.get("delta"), (int, float))]
        if items:
            head, rest = items[0], sorted(items[1:], key=lambda t: -abs(t[1]))
            top, tail = rest[:5], rest[5:]
            rows = [[head[0], round(head[1], 2)]] + [[n, round(v, 2)] for n, v in top]
            if tail:
                rows.append(["其他", round(sum(v for _, v in tail), 2)])
            L.append(f"const OCF_BRIDGE={json.dumps(rows, ensure_ascii=False)};")
            L.append(f"const OCF_END={R2(_v(cfs, 'ocf'))};")
            adj = round(sum(v for _, v in items[1:]), 2)
            L.append(f"// 端点行：净利润 {round(head[1], 2)} 亿 →（调节净额 {adj:+} 亿）→ "
                     f"经营现金流净额 {R2(_v(cfs, 'ocf'))} 亿")

    cip = notes.get("cip_projects") or []
    if cip:
        L.append("\n## S5 在建工程行（照抄；判定=进度 vs 计划工期、连续两年进度增量）\n")
        for p in cip:
            L.append(f"- {p.get('name')}：预算 {p.get('budget')} · 累计投入 {p.get('invested_cur')} · "
                     f"进度 {p.get('progress')} · 本期转固 {p.get('transferred')}（{p.get('note') or ''}）")

    sh = notes.get("shareholders") or {}
    if sh:
        L.append("\n## S6 股东结构\n")
        hn_c, hn_p = sh.get("holder_num_cur"), sh.get("holder_num_prev")
        L.append(f"- 户数：本期 {hn_c} · 上期 {hn_p}"
                 f"（万户呈现 ÷10000；HOLDERS 时序 ≥3 期从 Tushare stk_holdernumber 补；"
                 f"px=户数环比增减 %，首期无环比填 null 跳点，可整列留空）")
        L.append(f"const HOLDERS={{labels:[],num:[],px:[]}};")
        L.append("- 降级联动：户数时序补不齐 3 期时，图卡降级为两期文字行（本期/上期+变动解读），"
                 "不硬画两点图")
        L.append(f"- 前十大变动（照抄进表）：{sh.get('top10_changes')}")
        L.append(f"- 质押率 {sh.get('pledge_ratio')}（>70% 徽章化并进 s2 风险清单）")

    prs = data.get("peers") or []
    if prs:
        L.append("\n## S7 peers 表（照抄；中位数行已算好，本公司 vs 中位数自己减）\n")
        L.append("| 公司 | 毛利率 | 研发费率 | 资产负债率 | 净利率 | 周转率 | 权益乘数 | ROE |")
        L.append("|---|---|---|---|---|---|---|---|")
        cols = ("gross_margin", "rd_ratio", "debt_to_assets", "net_margin",
                "asset_turnover", "equity_multiplier", "roe")
        for p in prs:
            L.append(f"| {p.get('name')} | " + " | ".join(str(p.get(c)) for c in cols) + " |")
        med = {c: round(statistics.median([p[c] for p in prs if isinstance(p.get(c), (int, float))]), 4)
               for c in cols if any(isinstance(p.get(c), (int, float)) for p in prs)}
        L.append("| 中位数 | " + " | ".join(str(med.get(c, "—")) for c in cols) + " |")

    wl = data.get("watchlist") or []
    if wl:
        L.append("\n## S8 跟踪清单卡（逐条照抄；figtitle 自己写结论式）\n")
        for w in wl:
            L.append(f"- 【{w.get('indicator')}】读数 {w.get('current')}（badge {w.get('badge')}）· "
                     f">{w.get('upper')} {w.get('upper_meaning')} / <{w.get('lower')} {w.get('lower_meaning')} · "
                     f"依据 {w.get('source')}")

    L.append("\n## 判断槽位清单（fillsheet 不给值，自己写；写法约束在模板注释）\n")
    L.append("- S0 亮点/风险 TOP3、lede、分歧锚、异常线索追查（锚点指向下方各章）")
    L.append("- 全部 figtitle（结论式：标题即判断，数字只许在表格里）与 takeaway（一句话读法）")
    L.append("- S1 指标表「评价」列注脚（≤15 字）；阶段判定行（只放结论，依据进 takeaway）")
    L.append("- S2 观察行「担心→本案」（signals[].concern/evidence 压缩，禁「属正常波动」式空话）")
    L.append("- S3 lede（第一驱动）；S4 全章（断言验证素材=assertions 块，措辞/语气自己读；"
             "❓ 断言逐条进「数据缺口声明」行——v0.0.21 集中落点，机检 gap-declaration）")
    L.append("- S5 lede；S6 figtitle；S7 预期对照表（券商一致预期取 Tushare report_rc）")
    L.append("- S8 各卡 figtitle；页脚")

    pathlib.Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")
