# -*- coding: utf-8 -*-
"""calc_slots.py — 槽位契约层（v0.1.0 自 calc_models 拆出，1k 红线）：
write_fillsheet（人读速查表 md）+ build_slots（机读槽位 json）+ _js_slots（JS DATA 槽
单一出处）+ 呈现格式化助手与文本链（_TXT=剥 L 行号→截长小数→HTML 转义）。
debt: 非 JS 槽的取值知识（四维表行序/peers 列/桥归并）在 write_fillsheet 的 md 段与
build_slots 并存——md 是原始精度说明书、slots 是呈现完成态契约，两路刻意分开；
一致性由双锁兜底：fillsheet.md 金标准逐字断言 + 赢合 render 重放断言。
"""

import json
import pathlib
import re
import statistics
from html import escape as _htmlesc

# 呈现两位小数（fillsheet 机械槽位：原始精度留 json，报告可见数字 ≤2 位，v0.0.19）
R2 = lambda x: None if x is None else round(x, 2)

# 分位白描映射：(rank−1)/(n−1)，n=5 离散步长 0.25 → X/5（五年从高到低第 X，v0.0.19）。
# 与 check_html_text.py PCTILE_LABEL 双写互指（跨家族 import 会造成 calc↔check_html 耦合，
# 故保持双写 + 回归一致性断言锁契约，改动必须同步）
PCTILE_LABEL = {0.0: "5/5", 0.25: "4/5", 0.5: "3/5", 0.75: "2/5", 1.0: "1/5"}

# 通用取值助手（模块级，v0.1.0：write_fillsheet 与 build_slots 共用）
_v = lambda blk, f, k="cur": ((blk or {}).get(f) or {}).get(k)
_yoy = lambda c, p: "—" if not c or not p else f"{(c - p) / abs(p) * 100:+.1f}%"
# json 原文文本进 HTML 前必须转义（赢合 signals data 含「<1% 阈值」裸 < 实证）；
# JS DATA 槽不经过此（script 内 < 合法，SVG text 走 textContent）
_E = lambda s: _htmlesc(str(s or ""), quote=False)
# srcline/卡面来源文本剥 L 行号（长城实证：裸 L 行号会被 T8① 当数字提取撞窗；
# 行号是底稿内部引用，srcline 纪律只写对外来源）。
# 词边界+位数双保险（v0.1.1）：L 前紧贴字母数字（BL2/TL431 型号型）不剥；
# L 后 <3 位数字（「L2 级辅助驾驶」型）不剥——真实行号引用都在 3 位以上
_NO_SRC = lambda s: re.sub(r"(?<![A-Za-z0-9])[（(]?L\d{3,}[-\d, L]*[）)]?", "", str(s or "")).strip(" ；;，,")
# 长小数截两位（decimal-places 门禁：可见数字 ≤2 位；行号整数不受影响）
_trunc2 = lambda s: re.sub(r"\d+\.\d{3,}", lambda m: f"{float(m.group(0)):.2f}", s)
# json 原文进 HTML 文本槽的完整链：剥 L 行号 → 截长小数 → 转义
_TXT = lambda s: _E(_trunc2(_NO_SRC(s)))
# 数值/文本混合字段的转义：文本过 _TXT 链，数值直通（_TXT 会把数值 0 吞成空串）
_TXTV = lambda x: _TXT(x) if isinstance(x, str) else x


def _jd(x):
    """JS 槽 JSON 序列化唯一出口：json.dumps + `</` 转义——底稿原文（分部名/期间标签）
    夹带 `</script>` 会提前闭合脚本块团灭整页 JS；`<\\/` 在 JSON/JS 字符串里等价 `<`。"""
    return json.dumps(x, ensure_ascii=False).replace("</", "<\\/")


# 方向语义（frameworks.md 方向语义表）：True=升为好 / False=降为好 / None=语境中性
GOOD_UP = {"gross_margin": True, "net_margin": True, "debt_to_assets": False,
           "dio": False, "dso": False, "cash_to_sales": True, "ccc": False,
           "dol": None, "dfl": None, "non_main_rev_share": None}
ROW_LABEL = {"gross_margin": "毛利率", "net_margin": "净利率", "debt_to_assets": "资产负债率",
             "dio": "存货周转天数", "dso": "应收周转天数", "cash_to_sales": "收现比",
             "ccc": "现金转换周期 CCC", "dol": "经营杠杆 DOL", "dfl": "财务杠杆 DFL",
             "non_main_rev_share": "非主营业务收入占比"}


def write_fillsheet(data, path):
    """填充速查表：P8 机械槽位的值+徽章+语义色+JS 槽数组，模型照抄不进算术。
    JS DATA 槽文本由 _js_slots 单一产出（v0.1.0：与 fillsheet.json/render 同源）。"""
    ratios = ((data.get("derived") or {}).get("ratios")) or {}
    js = _js_slots(data)
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
        L.append(js["NCR_TS"])
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
             "判定分布由徽章色 + figtitle 汇总传达；figtitle 汇总口径（v0.0.23 用户定案）="
             "计数 + 按固定主题逐类点到（盈利与研发 / 偿债与压力 / 营运效率·费用 ROI / 披露项），"
             "各类不缺席、营运效率类必须有名字（海康 2026H1 漏报实证）")
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
    L.append(js["TREND"])

    L.append("\n## S1 EFF_TS 槽（JS 区粘贴；v0.0.22 营运效率三线图——接替退役的四维表 "
             "spark 列；dio/dso/ccc 单位均为天，CCC 可负；某序列不足 2 个非空点整线不画）\n")
    L.append(js["EFF_TS"])

    if du:
        L.append("\n## S1 DUPONT_STACK 槽（JS 区粘贴；gap≠0 必须保留第四段，不许视觉隐瞒）\n")
        L.append(js["DUPONT_STACK"])
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
    if not any(rf.get(k) is not None for k in ("volume", "price", "mix")):
        L.append(f"// 无量价（rev_factors 全 null）→ 分部轴降级：各分部 Δ 由 by_segment 机械生成"
                 f"（分部合计≠Δ总收入时补「其他」桶闭合）；{rf.get('note') or '（rev_factors.note 未填）'}")
    L.append(js["SEG_BRIDGE"])
    L.append(js["SEG_ENDS"])
    L.append(f"// 端点行（.brends 与 SEG_ENDS 同源）：{js['brends_seg']}")

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
            L.append(js["OCF_BRIDGE"])
            L.append(js["OCF_END"])
            L.append(f"// 端点行：{js['brends_ocf']}")

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
        L.append(js["HOLDERS"])
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
    L.append("- S1 指标表「评价」列注脚（≤15 字，写本期 vs 上期变动的原因/定性，"
             "禁「五年 H1 最高」族五年位置断言——v0.0.23 用户定案，五年表述归趋势图卡/杜邦分位卡）；"
             "阶段判定行（只放结论，依据进 takeaway）")
    L.append("- S2 观察行「担心→本案」（signals[].concern/evidence 压缩，禁「属正常波动」式空话）")
    L.append("- S3 lede（第一驱动）；S4 全章（断言验证素材=assertions 块，措辞/语气自己读；"
             "❓ 断言逐条进「数据缺口声明」行——v0.0.21 集中落点，机检 gap-declaration）")
    L.append("- S5 lede；S6 figtitle；S7 预期对照表（券商一致预期取 Tushare report_rc）")
    L.append("- S8 各卡 figtitle；页脚")

    pathlib.Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────
# build_slots / _js_slots（v0.1.0，N4 fill→render 脚本化）：机器可读槽位契约，
# render_report.py 的唯一数据源。取值与 write_fillsheet 同源（fill 后的 derived/
# statements 权威值）；JS DATA 槽整行文本由 _js_slots 单一产出、md 与 json 双路
# 共用（JS 槽是 T8① 回验最密集处，禁止双写）。呈现格式化在此完成（render 零算术）。
# debt: 四维表/peers/桥等非 JS 槽的取值表达式与 write_fillsheet 的 md 段并存
# （md 是说明书、slots 是数据），一致性由赢合重放金标准回归锁。
# ──────────────────────────────────────────────────────────────────────────

def _js_slots(data):
    """JS DATA 区 9 槽整行文本（含 SEG 分部轴降级与 HOLDERS 时序）+ 双桥端点行文本。
    一切 JSON 序列化走 _jd（None→null、`</` 转义）——f-string 裸插 None 是 JS 未定义
    标识符，整段 script 报错即全图团灭（v0.1.1 修复）。"""
    der = data.get("derived") or {}
    meta = data.get("meta") or {}
    stmts = data.get("statements") or {}
    inc, cfs = stmts.get("income") or {}, stmts.get("cashflow") or {}
    ratios = der.get("ratios") or {}
    _v = lambda blk, f, k="cur": (blk.get(f) or {}).get(k)
    _hist = lambda node: (node or {}).get("hist") or []
    _r2l = lambda arr: [R2(x) for x in arr]

    out = {}
    cts = der.get("cash_ts") or {}
    if cts.get("ncr"):
        out["NCR_TS"] = (f"const NCR_TS={{labels:{_jd(cts.get('periods') or [])},"
                         f"ncr:{_jd(_r2l(cts.get('ncr') or []))},"
                         f"fcf:{_jd(_r2l(cts.get('fcf_to_np') or []))},"
                         f"mean:{_jd(R2(cts.get('ncr_mean5')))}}};")
    else:
        out["NCR_TS"] = "const NCR_TS={labels:[],ncr:[],fcf:[],mean:null};"

    cv = der.get("cycle_evidence") or {}
    labels = cts.get("periods") or cv.get("periods") or []
    _aln = lambda arr: ([None] * (len(labels) - len(arr)) + arr)[-len(labels):] \
        if labels and arr else arr
    _gm_pct = [round(x * 100, 2) if x is not None else None
               for x in _aln(_hist(ratios.get("gross_margin")))]
    out["TREND"] = (f"const TREND={{labels:{_jd(labels)},"
                    f"rev:{_jd(_r2l(_aln(_hist(inc.get('revenue')))))},"
                    f"np:{_jd(_r2l(_aln(_hist(inc.get('np_at')))))},"
                    f"np_dt:{_jd(_r2l(_aln(_hist(inc.get('np_dt')))))},"
                    f"ocf:{_jd(_r2l(_aln(_hist(cfs.get('ocf')))))},"
                    f"roe:{_jd(_aln(_hist(ratios.get('roe'))))},"
                    f"gm:{_jd(_gm_pct)},"
                    f"capex:{_jd(_r2l(_aln(_hist(cfs.get('capex')))))},"
                    f"rd:{_jd(_r2l(_aln(_hist(inc.get('rd_exp')))))}}};")
    out["EFF_TS"] = (f"const EFF_TS={{labels:{_jd(labels)},"
                     f"dio:{_jd(_r2l(_aln(_hist(ratios.get('dio')))))},"
                     f"dso:{_jd(_r2l(_aln(_hist(ratios.get('dso')))))},"
                     f"ccc:{_jd(_r2l(_aln(_hist(ratios.get('ccc')))))}}};")

    du = der.get("dupont") or {}
    _p1 = lambda x: None if x is None else round(x * 100, 1)
    out["DUPONT_STACK"] = ("const DUPONT_STACK=" + _jd(
        {"steps": [["净利率", _p1(du.get("margin_effect"))],
                   ["周转率", _p1(du.get("turnover_effect"))],
                   ["杠杆", _p1(du.get("leverage_effect"))]],
         "gap": _p1(du.get("closure_gap"))}) + ";")

    # SEG_BRIDGE：量价齐→三效应；全 null→by_segment 分部轴（v0.1.0 机械化，原手填指引退役）；
    # 分部合计 ≠ Δ总收入时补「其他」桶闭合（calc bridge 卡口要求 Σ=Δ收入）
    rf = der.get("rev_factors") or {}
    _by_volume = any(rf.get(k) is not None for k in ("volume", "price", "mix"))
    rev_d = None
    if _v(inc, "revenue") is not None and _v(inc, "revenue", "prev") is not None:
        rev_d = _v(inc, "revenue") - _v(inc, "revenue", "prev")
    if _by_volume:
        seg = [["量效应", rf.get("volume") or 0], ["价效应", rf.get("price") or 0],
               ["结构效应", rf.get("mix") or 0]]
    else:
        seg = [[s.get("name"), R2((s.get("rev_cur") or 0) - (s.get("rev_prev") or 0))]
               for s in (inc.get("by_segment") or [])
               if s.get("rev_cur") is not None and s.get("rev_prev") is not None]
        if seg and rev_d is not None:
            rest = round(rev_d - sum(v for _, v in seg), 2)
            if abs(rest) > 0.005:
                seg.append(["其他", rest])
    out["SEG_BRIDGE"] = f"const SEG_BRIDGE={_jd(seg)};"
    out["SEG_ENDS"] = f"const SEG_ENDS={_jd([R2(_v(inc, 'revenue', 'prev')), R2(_v(inc, 'revenue'))])};"
    out["brends_seg"] = (f"基期收入 {_F2(_v(inc, 'revenue', 'prev'))} 亿 →"
                         f"（{'三效应合计' if _by_volume else '分部合计'} {rev_d:+.2f} 亿）→ "
                         f"本期收入 {_F2(_v(inc, 'revenue'))} 亿" if rev_d is not None else "")

    ob = der.get("ocf_bridge") or []
    items = [(x.get("item"), x.get("delta")) for x in ob
             if isinstance(x.get("delta"), (int, float))]
    if items:
        head, rest = items[0], sorted(items[1:], key=lambda t: -abs(t[1]))
        top, tail = rest[:5], rest[5:]
        rows = [[head[0], round(head[1], 2)]] + [[n, round(v, 2)] for n, v in top]
        if tail:
            rows.append(["其他", round(sum(v for _, v in tail), 2)])
        out["OCF_BRIDGE"] = f"const OCF_BRIDGE={_jd(rows)};"
        out["OCF_END"] = f"const OCF_END={_jd(R2(_v(cfs, 'ocf')))};"
        adj = round(sum(v for _, v in items[1:]), 2)
        out["brends_ocf"] = (f"净利润 {head[1]:.2f} 亿 →（调节净额 {adj:+.2f} 亿）→ "
                             f"经营现金流净额 {_F2(_v(cfs, 'ocf'))} 亿")
    else:
        out["OCF_BRIDGE"] = "const OCF_BRIDGE=[];"
        out["OCF_END"] = f"const OCF_END={_jd(R2(_v(cfs, 'ocf')))};"
        out["brends_ocf"] = ""

    # HOLDERS（schema 1.6 holder_ts）：num 户→万户 R2、px 环比 R1、首期 null；
    # 缺块/不足 3 期时空骨架（render 联动降级两期文字行）
    hts = ((data.get("notes") or {}).get("shareholders") or {}).get("holder_ts") or {}
    hl, hn, hp = hts.get("labels") or [], hts.get("num") or [], hts.get("px") or []
    if len(hl) >= 3 and len(hl) == len(hn) == len(hp):
        out["HOLDERS"] = (f"const HOLDERS={{labels:{_jd(hl)},"
                          f"num:{_jd([round(x / 10000, 2) for x in hn])},"
                          f"px:{_jd([None if p is None else round(p, 1) for p in hp])}}};")
    else:
        out["HOLDERS"] = "const HOLDERS={labels:[],num:[],px:[]};"
    return out


# ── build_slots 呈现格式化助手（箭头 delta / pct / 语义色，口径=报告可见数字纪律）──
_F2 = lambda x: None if x is None else f"{x:.2f}"
_PCT2 = lambda x: None if x is None else f"{x * 100:.2f}%"


def _arrow(d, scale=1, nd=2, suffix=""):
    """±delta 呈现：「▼ -6.96pct」「▲ +0.12」「▼ -11.11 天」；d None → 「—」。"""
    if d is None:
        return "—"
    a = "▲" if d > 0 else ("▼" if d < 0 else "→")
    sign = "+" if d > 0 else ("-" if d < 0 else "")
    return f"{a} {sign}{abs(d) * scale:.{nd}f}{suffix}"


def _cls_of(key, d):
    """方向语义色（GOOD_UP 表；d None 或语境中性 → 不染）。"""
    good = GOOD_UP.get(key)
    if d is None or good is None or d == 0:
        return ""
    return "up" if (d > 0) == good else "dn"


def _period_label(period):
    """20260630→2026H1 / 20261231→2026FY / 0331→Q1 / 0930→Q3。"""
    s = str(period or "")
    suf = {"0331": "Q1", "0630": "H1", "0930": "Q3", "1231": "FY"}.get(s[4:], "")
    return f"{s[:4]}{suf}" if suf else ""


def build_slots(data):
    """机器可读槽位契约（fillsheet.json，v0.1.0 N4）：render_report.py 的唯一数据源。
    值均为呈现完成态（R2/pct/±/箭头/语义色已格式化），render 只做插入与行生成；
    判断字段不出现在这里（模板残留 {{}} 即判断孔，check_html 占位符门禁兜底）。"""
    der = data.get("derived") or {}
    meta = data.get("meta") or {}
    stmts = data.get("statements") or {}
    notes = data.get("notes") or {}
    inc, cfs, bal = stmts.get("income") or {}, stmts.get("cashflow") or {}, stmts.get("balance") or {}
    ratios = der.get("ratios") or {}
    _v = lambda blk, f, k="cur": (blk.get(f) or {}).get(k)
    _hist = lambda node: (node or {}).get("hist") or []
    js = _js_slots(data)

    pl = _period_label(meta.get("period"))
    rt = meta.get("report_type") or ""
    slots = {
        "meta": {
            "company": meta.get("company"), "code": meta.get("code"),
            "market": meta.get("market"), "period_label": pl, "report_type": rt,
            "disclose_date": meta.get("disclose_date"), "analyst_date": meta.get("analyst_date"),
            "unit": meta.get("unit") or "亿元",
            "title": f"{meta.get('company')}（{meta.get('code')}）",
            "sub_lead": f"{pl} {rt}".strip(),
            "srcline_period": f"{str(meta.get('period') or '')[:4]} 年",
            "cycle_stage": meta.get("cycle_stage") or "",
        },
        "js": js,
    }

    # ── S1 KPI 四卡 ──
    roe_n = ratios.get("roe") or {}
    cts = der.get("cash_ts") or {}
    roe_d = None if roe_n.get("cur") is None or roe_n.get("prev") is None \
        else (roe_n["cur"] - roe_n["prev"]) * 100
    np_dt_roe = None
    if _v(inc, "np_dt") is not None and _v(bal, "equity_at"):
        np_dt_roe = _v(inc, "np_dt") / _v(bal, "equity_at") * 100
    _yoy_cls = lambda c, p: ("up" if c >= p else "dn") if (c is not None and p is not None) else ""
    slots["s1"] = {
        "kpi": [
            {"v": _F2(_v(inc, "revenue")),
             "r": f"同比 {_yoy(_v(inc, 'revenue'), _v(inc, 'revenue', 'prev'))}",
             "cls": _yoy_cls(_v(inc, "revenue"), _v(inc, "revenue", "prev")),
             "badge": "disc", "l": "营业收入（亿元）"},
            {"v": _F2(_v(inc, "np_at")),
             "r": f"同比 {_yoy(_v(inc, 'np_at'), _v(inc, 'np_at', 'prev'))}",
             "cls": _yoy_cls(_v(inc, "np_at"), _v(inc, "np_at", "prev")),
             "badge": "disc", "l": "归母净利润（亿元）"},
            {"v": _F2(_v(cfs, "ocf")),
             "r": f"净现比 {_F2((cts.get('ncr') or [None])[-1])}",
             "cls": "", "badge": "der", "l": "经营现金流净额（亿元）"},
            {"v": _PCT2(roe_n.get("cur")),
             "r": f"较上期 {'—' if roe_d is None else f'{roe_d:+.1f}pct'}",
             "cls": "" if roe_d is None else ("up" if roe_d > 0 else "dn"),
             "badge": "der",
             "l": f"ROE（净资产收益率，摊薄）· 扣非 {np_dt_roe:.2f}%" if np_dt_roe is not None
                  else "ROE（净资产收益率，摊薄）"},
        ],
    }

    # ── S1 四维表 12 行（固定行序；ROIC/内生为单期指标无 prev）──
    def _row(key, label, kind, badge, prev_missing="—"):
        node = ratios.get(key) or {}
        cur, prev = node.get("cur"), node.get("prev")
        d = None if (cur is None or prev is None) else cur - prev
        if kind == "pct":
            cur_s, prev_s = _PCT2(cur), _PCT2(prev)
            d_s = _arrow(d, scale=100, nd=2, suffix="pct") if d is not None else prev_missing
        elif kind == "day":
            cur_s, prev_s = _F2(cur), _F2(prev)
            d_s = _arrow(d, nd=2, suffix=" 天") if d is not None else prev_missing
        else:
            cur_s, prev_s = _F2(cur), _F2(prev)
            d_s = _arrow(d, nd=2) if d is not None else prev_missing
        return {"key": key, "label": label, "cur": cur_s or "—", "prev": prev_s or "—",
                "delta": d_s, "cls": _cls_of(key, d), "badge": badge}
    slots["s1"]["table4"] = [
        _row("gross_margin", "毛利率", "pct", "der"),
        _row("net_margin", "净利率", "pct", None),
        _row("roic", "投入资本回报率", "pct", "der", "—（单期指标）"),
        _row("sustainable_growth", "内生增长率", "pct", "der", "—（单期指标）"),
        _row("dio", "存货周转天数", "day", None),
        _row("dso", "应收周转天数", "day", None),
        _row("cash_to_sales", "收现比", "x", None),
        _row("ccc", "现金转换周期 CCC", "day", None),
        _row("debt_to_assets", "资产负债率", "pct", None),
        _row("dol", "经营杠杆 DOL", "x", "der"),
        _row("dfl", "财务杠杆 DFL", "x", "der"),
        _row("non_main_rev_share", "非主营业务收入占比", "pct", "der"),
    ]

    # ── S1 杜邦双卡 ──
    du = der.get("dupont") or {}
    _e1 = lambda x: None if x is None else _arrow(x, scale=100, nd=1, suffix="pct")
    _e1p = lambda x: None if x is None else f"{'+' if x >= 0 else '-'}{abs(x) * 100:.1f}pct"
    bal_hist = _hist(bal.get("equity_at"))
    eq_ye = bal_hist[-2] if len(bal_hist) >= 2 else None  # 上年末权益（drill prev 分母口径）
    slots["s1"]["dupont"] = {
        "cur": {"净利率": _PCT2((ratios.get("net_margin") or {}).get("cur")),
                "总资产周转率": _F2((ratios.get("asset_turnover") or {}).get("cur")),
                "权益乘数": _F2((ratios.get("equity_multiplier") or {}).get("cur"))},
        "prev": {"净利率": _PCT2((ratios.get("net_margin") or {}).get("prev")),
                 "总资产周转率": _F2((ratios.get("asset_turnover") or {}).get("prev")),
                 "权益乘数": _F2((ratios.get("equity_multiplier") or {}).get("prev"))},
        "effects": {"净利率": _e1(du.get("margin_effect")), "总资产周转率": _e1(du.get("turnover_effect")),
                    "杠杆": _e1(du.get("leverage_effect"))},
        "effects_cls": {"净利率": _cls_of("net_margin", du.get("margin_effect")),
                        "总资产周转率": _cls_of("asset_turnover", du.get("turnover_effect")),
                        "杠杆": "up" if (du.get("leverage_effect") or 0) > 0 else "dn"},
        "driver": du.get("driver"), "driver_second": du.get("driver_second"),
        "driver_fragile": bool(du.get("driver_fragile")),
        "effects_ratio": None if du.get("effects_ratio") is None else round(du.get("effects_ratio"), 2),
        "roe_cur": _PCT2(roe_n.get("cur")), "roe_prev": _PCT2(roe_n.get("prev")),
        "closure_gap_pct": None if du.get("closure_gap") is None else f"{du.get('closure_gap') * 100:+.2f}pct",
    }
    md_ = du.get("margin_drill") or {}
    if md_:
        slots["s1"]["dupont"]["margin_drill"] = (
            f"经营 {_e1p(md_.get('op_effect'))} · 税负 {_e1p(md_.get('tax_effect'))} · "
            f"利息 {_e1p(md_.get('interest_effect'))} · 少数股东 {_e1p(md_.get('minority_effect'))}")
    td_ = du.get("turnover_drill") or {}
    if td_:
        _SUBJ_FIELD = {"存货": "inventory", "预付款项": "prepayment", "应收": "ar",
                       "货币资金": "cash", "固定资产": "fixed_assets", "合同资产": "contract_assets",
                       "其他应收款": "other_ar", "商誉": "goodwill"}

        def _subj_change(name):
            f = _SUBJ_FIELD.get(name or "")
            node = bal.get(f) or {}
            c, p = node.get("cur"), node.get("prev")
            if c is None or p is None:
                return None
            d = c - p
            if p and abs(c / p - 1) > 1:  # 增幅超 ±100% 时读数用增幅（预付 +438% 形态）
                return f"{name} {(c / p - 1) * 100:+.0f}%"
            return f"{name} {d:+.2f} 亿"
        t1 = _subj_change(td_.get("top1_subject"))
        t2 = _subj_change(td_.get("top2_subject"))
        if t1 and t2:
            slots["s1"]["dupont"]["turnover_drill"] = (
                f"Δ总资产前二：{t1}（占 {abs((td_.get('top1_share') or 0)) * 100:.1f}%）/ "
                f"{t2}（占增量 {abs((td_.get('top2_share') or 0)) * 100:.1f}%）；"
                f"应收存货类 {(td_.get('wc_share') or 0) * 100:.1f}% · "
                f"产能类 {(td_.get('capex_share') or 0) * 100:.1f}%")
    ld_ = du.get("leverage_drill") or {}
    if ld_:
        ib_prev_r = None if not eq_ye or ld_.get("ib_prev") is None else ld_["ib_prev"] / eq_ye
        ni_prev_r = None if not eq_ye or ld_.get("ni_prev") is None else ld_["ni_prev"] / eq_ye
        slots["s1"]["dupont"]["leverage_drill"] = {
            "ib": f"{_F2(ib_prev_r) or '—'}→{_F2(ld_.get('ib_to_equity_cur')) or '—'}",
            "ni": f"{_F2(ni_prev_r) or '—'}→{_F2(ld_.get('ni_to_equity_cur')) or '—'}",
            "ni_share": f"{(ld_.get('ni_share') or 0) * 100:.1f}%",
            "dfl": None if ld_.get("dfl_delta") is None else f"{ld_['dfl_delta']:+.2f}",
            "quality_upgrade": bool(ld_.get("quality_upgrade")),
        }

    # ── S1 杜邦右卡（五年归因 A 表 + 分位表）──
    d5 = der.get("dupont5y") or {}
    if d5:
        _hist_end = lambda key: ((ratios.get(key) or {}).get("hist") or [None])
        _cum = lambda x: None if x is None else f"{x * 100:+.2f}pct"
        nm_h = _hist(ratios.get("net_margin"))
        at_h = _hist(ratios.get("asset_turnover"))
        em_h = _hist(ratios.get("equity_multiplier"))
        roe_h = _hist(roe_n)
        rd5 = None
        if d5.get("roe_start") is not None and d5.get("roe_end") is not None:
            rd5 = (d5["roe_end"] - d5["roe_start"]) * 100
        pg = d5.get("percentile") or {}
        slots["s1"]["dupont5y"] = {
            "p_start": d5.get("period_start"), "p_end": d5.get("period_end"),
            "rows": [
                {"label": "净利率", "start": _PCT2(nm_h[0] if nm_h else None),
                 "end": _PCT2(nm_h[-1] if nm_h else None), "cum": _cum(d5.get("margin_effect"))},
                {"label": "总资产周转率", "start": _F2(at_h[0] if at_h else None),
                 "end": _F2(at_h[-1] if at_h else None), "cum": _cum(d5.get("turnover_effect"))},
                {"label": "权益乘数", "start": _F2(em_h[0] if em_h else None),
                 "end": _F2(em_h[-1] if em_h else None), "cum": _cum(d5.get("leverage_effect"))},
            ],
            "roe": {"start": _PCT2(d5.get("roe_start")), "end": _PCT2(d5.get("roe_end")),
                    "delta": None if rd5 is None else f"{rd5:+.2f}pct",
                    "gap": _cum(d5.get("closure_gap"))},
            "pctile": {"净利率": PCTILE_LABEL.get(pg.get("net_margin")),
                       "总资产周转率": PCTILE_LABEL.get(pg.get("asset_turnover")),
                       "权益乘数": PCTILE_LABEL.get(pg.get("equity_multiplier"))},
        }
    # NCR 卡 takeaway 素材（嵌注释用）
    if cts.get("ncr"):
        slots["s1"]["ncr_hint"] = (f"净现比均值 {_F2(cts.get('ncr_mean5'))}（OCF 为负 "
                                   f"{cts.get('ncr_neg_years')} 年）· FCF 均值 "
                                   f"{_F2(cts.get('fcf_to_np_mean5'))}（FCF 为负 {cts.get('fcf_neg_years')} 年）")
    # hist<3 期整卡降级（模板注释约定）：ncr 缺块或非空点不足 3 → render 删 svg + figtitle 声明
    _ncr_pts = [x for x in (cts.get("ncr") or []) if x is not None]
    slots["s1"]["ncr_drop"] = len(_ncr_pts) < 3

    # ── S2 排雷扫描 ──
    sig = data.get("signals") or []
    cnt = {}
    for s_ in sig:
        cnt[s_.get("verdict")] = cnt.get(s_.get("verdict"), 0) + 1
    _sig_row = lambda s_: {"id": s_.get("id"), "title": _TXT(s_.get("title")), "data": _TXT(s_.get("data")),
                           "level": s_.get("level"), "concern": _TXT(s_.get("concern")),
                           "evidence": _TXT(s_.get("evidence"))}
    slots["s2"] = {
        "counts": {"total": len(sig), "hit": cnt.get("命中", 0), "watch": cnt.get("观察", 0),
                   "reverse": cnt.get("反向未触发", 0), "miss": cnt.get("未触发", 0)},
        "summary_line": (f"未触发汇总：已检 {len(sig)} 项——命中 {cnt.get('命中', 0)} · "
                         f"观察 {cnt.get('观察', 0)} · 反向 {cnt.get('反向未触发', 0)} 组 · "
                         f"未触发 {cnt.get('未触发', 0)}（反向=信号反向成立且含信息量；"
                         f"逐条读数落底稿，正文只承载有动作价值的条目）"),
        "hit_rows": [_sig_row(s_) for s_ in sig if s_.get("verdict") == "命中"],
        "watch_rows": [_sig_row(s_) for s_ in sig if s_.get("verdict") == "观察"],
    }
    _RECON_NAME = {"A1": "现金余额勾稽", "A2": "未分配利润滚动", "A3": "间接法现金流量调节表",
                   "A4": "收入-收现闭环", "A5": "折旧摊销勾稽", "A6": "Capex 勾稽",
                   "A7": "隐含利率检验", "A8": "投资收益合理性",
                   "B1": "应收 roll-forward", "B2": "存货 roll-forward", "B3": "在建工程 roll-forward",
                   "B4": "商誉 roll-forward", "C1": "CCC 现金转换周期", "C2": "DPO 双面性",
                   "D1": "母公司现金勾稽", "D2": "母公司未分配利润", "D3": "母公司其他应收款",
                   "D4": "母公司长期股权投资", "D5": "母公司 OCF 勾稽"}
    rec = data.get("recon") or {}
    abn = [(k, v) for k, v in rec.items()
           if isinstance(v, dict) and v.get("verdict") and "闭合" not in str(v.get("verdict"))]
    recon_rows = []
    for k, v in abn:
        lhs, rhs = v.get("lhs"), v.get("rhs")
        if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
            d_ = lhs - rhs
            dev = f"{d_:+.2f} 亿 / {abs(d_) / abs(rhs) * 100:.1f}%" if rhs else f"{d_:+.2f} 亿"
        else:
            dev = "—"
        pre = k.split("_")[0]
        recon_rows.append({"eq": f"{pre} {_RECON_NAME.get(pre, k)}", "verdict": v.get("verdict"),
                           "deviation": dev, "explain": _TXT(v.get("explanation") or "")})
    slots["s2"]["recon_rows"] = recon_rows
    slots["s2"]["recon_total"] = len(rec)
    slots["s2"]["recon_closed"] = len(rec) - len(abn)
    tk = der.get("threshold_check") or {}
    shell, refi, inc_ = tk.get("shell_line") or {}, tk.get("refinance_line") or {}, tk.get("incentive_line") or {}
    _line = lambda blk, target_txt: {
        "read": (f"ROE {_PCT2(blk.get('roe'))}" + (f" · 净利率 {_PCT2(blk.get('net_margin'))}"
                 if blk.get("net_margin") is not None else "")) if blk.get("roe") is not None else "—",
        "target": target_txt,
        "dist": (None if blk.get("roe") is None or blk.get("target") is None
                 else f"{(blk['roe'] - blk['target']) * 100:+.1f}pct"),
        "verdict": ("✅ 远离" if blk.get("hit") is False else ("🔴 贴线" if blk.get("hit") else "—"))}
    slots["s2"]["threshold"] = {
        "shell": _line(shell, "ROE 6.5%"), "refi": _line(refi, "ROE 10%"),
        "incentive": {"read": "—", "target": "—", "dist": "—",
                      "verdict": "✅ 无贴线场景" if inc_.get("hit") is None else
                                 ("✅ 远离" if inc_.get("hit") is False else "🔴 贴线")},
        "q4_na": rt != "年报",  # 半年报/季报：Q4 集中度行机械「—（不适用）」
    }

    # ── S3 净利桥（归并：投资/公允+其他收益+非经 → 非经常性损益一行）──
    _MERGE_NON = ("投资/公允", "投资/公允/资产处置", "其他收益（政府补助等）", "非经", "非经（营业外收支净）")
    _RELABEL = {"期间费用": "期间费用合计", "期间费用（销售/管理/研发/财务）": "期间费用合计",
                "减值": "减值损失", "减值（信用+资产）": "减值损失", "少数股东": "少数股东损益"}

    def _gp(k):
        a, b = _v(inc, "revenue", k), _v(inc, "cost", k)
        return round(a - b, 4) if a is not None and b is not None else None
    _abs_map = {
        "毛利": (_gp("cur"), _gp("prev")),
        "税金及附加": (_v(inc, "tax_surcharge"), _v(inc, "tax_surcharge", "prev")),
        # 期间费用/减值/非经：多科目合成口径，本期/上期列按成品惯例填「—」（fillsheet 纪律：
        # 「— 表示该环节无直接字段」），贡献额列照 np_bridge
        "期间费用": (None, None),
        "减值": (None, None),
        "所得税": (_v(inc, "income_tax"), _v(inc, "income_tax", "prev")),
        "少数股东": (_v(inc, "minority_np"), _v(inc, "minority_np", "prev")),
    }
    npb = der.get("np_bridge") or []
    np_rows, non_delta = [], 0.0
    has_non = False
    for x in npb:
        item = x.get("item")
        if item in _MERGE_NON:
            non_delta += x.get("delta") or 0
            has_non = True
            continue
        a, b = _abs_map.get(item, (None, None))
        d_ = x.get("delta")
        np_rows.append({"item": _RELABEL.get(item, item),
                        "cur": _F2(a) or "—", "prev": _F2(b) or "—",
                        "delta": None if d_ is None else f"{d_:+.2f}",
                        "cls": "" if d_ is None or abs(d_) < 0.05 else ("up" if d_ > 0 else "dn"),
                        "note": None})
    if has_non:
        np_rows.insert(len(np_rows) - 2 if len(np_rows) >= 2 else 0,
                       {"item": "非经常性损益", "cur": "—", "prev": "—",
                        "delta": f"{non_delta:+.2f}",
                        "cls": "" if abs(non_delta) < 0.05 else ("up" if non_delta > 0 else "dn"),
                        "note": None})
    # 期间费用行备注列机械：四项费用逐项 Δ（|Δ| 降序）
    _exp_items = [("研发", "rd_exp"), ("财务", "fin_exp"), ("销售", "sell_exp"), ("管理", "admin_exp")]
    exp_d = [(nm, (_v(inc, f) or 0) - (_v(inc, f, "prev") or 0))
             for nm, f in _exp_items if _v(inc, f) is not None and _v(inc, f, "prev") is not None]
    if exp_d:
        note_txt = " / ".join(f"{nm} {dv:+.2f}" for nm, dv in
                              sorted(exp_d, key=lambda t: -abs(t[1])))
        for r in np_rows:
            if r["item"] == "期间费用合计":
                r["note"] = note_txt
    slots["s3"] = {
        "np_rows": np_rows,
        "np_total": {"cur": _F2(_v(inc, "np_at")), "prev": _F2(_v(inc, "np_at", "prev")),
                     "delta": (None if _v(inc, "np_at") is None or _v(inc, "np_at", "prev") is None
                               else f"{_v(inc, 'np_at') - _v(inc, 'np_at', 'prev'):+.2f}")},
        "brends_seg": js.get("brends_seg") or "", "brends_ocf": js.get("brends_ocf") or "",
        # OCF 桥降级标记（补充资料未披露的合法 WARN 态）：空桥必删 svg，否则撞 empty-svg
        "ocf_drop": not any(isinstance(x.get("delta"), (int, float))
                            for x in (der.get("ocf_bridge") or [])),
    }
    wcd = der.get("wc_devour") or {}
    if wcd.get("amount") is not None:
        slots["s3"]["wc"] = {"amount": f"{wcd['amount']:.2f}",
                             "share": f"{wcd.get('share_of_np', 0) * 100:+.1f}%"}

    # ── S4 断言表（全机械行；分组行不生成，分析师可选后加）──
    _VD = {"通过": ("✅ 通过", "g"), "不成立": ("❌ 不成立", "r"), "无法验证": ("❓ 无法验证", "y")}
    ast = data.get("assertions") or []
    ast_rows = [{"id": a.get("id"), "text": _TXT(a.get("text")), "evidence": _TXT(a.get("evidence")),
                 "verdict_text": _VD.get(a.get("verdict"), ("—", ""))[0],
                 "badge_cls": _VD.get(a.get("verdict"), ("—", ""))[1],
                 "source": _TXT(a.get("source")), "missing": _TXT(a.get("missing"))}
                for a in ast]
    c_pass = sum(1 for a in ast if a.get("verdict") == "通过")
    c_fail = sum(1 for a in ast if a.get("verdict") == "不成立")
    c_unk = sum(1 for a in ast if a.get("verdict") == "无法验证")
    gaps = [a for a in ast_rows if a["missing"]]
    slots["s4"] = {
        "rows": ast_rows,
        "figtitle_prefix": f"{len(ast)} 条断言：{c_pass} 通过 / {c_fail} 不成立 / {c_unk} 无法验证",
        "counts_txt": f"共 {len(ast)} 条断言：✅ {c_pass} / ❌ {c_fail} / ❓ {c_unk}",
        "gap_declaration": ("数据缺口声明：" + "；".join(f"{g['id']} {g['text']}——{g['missing']}"
                                                      for g in gaps)) if gaps else "",
    }

    # ── S5 在建工程（空→降级行）/ 产能卡（空→整卡删）──
    cip = notes.get("cip_projects") or []
    slots["s5"] = {
        "cip_rows": [{"name": _TXT(p.get("name")), "budget": _TXTV(p.get("budget")),
                      "invested": _TXTV(p.get("invested_cur")), "progress": _TXTV(p.get("progress")),
                      "transferred": _TXTV(p.get("transferred")), "note": _TXT(p.get("note"))}
                     for p in cip],
        "cip_empty": not cip,
        "cap_drop": not (notes.get("capacity") or []),
    }

    # ── S6 股东结构 ──
    sh = notes.get("shareholders") or {}
    hn_c, hn_p = sh.get("holder_num_cur"), sh.get("holder_num_prev")
    top10 = []
    for t in sh.get("top10_changes") or []:
        if not isinstance(t, dict):  # 旧底稿字符串形态（万科轮前样本）：降级为名称行
            top10.append({"name": _TXT(t), "nature": "", "ratio": "", "pledge_raw": "",
                          "change_txt": "—", "change_cls": ""})
            continue
        chg = t.get("change")
        ratio_txt = t.get("ratio") or ""
        share_txt = None
        if isinstance(chg, (int, float)) and chg:
            share_txt = f"{t.get('change_type') or '变动'} {chg / 10000:+.2f} 万股"
            try:  # 占总股本% = change ÷ (持股数÷持股比例)，ratio 形如「28.59%」
                r_ = float(str(ratio_txt).rstrip("%")) / 100
                if r_ and t.get("shares"):
                    share_txt += f"（{chg / (t['shares'] / r_) * 100:+.2f}%）"
            except (ValueError, ZeroDivisionError):
                pass
        elif t.get("change_type"):
            share_txt = t.get("change_type")
        top10.append({"name": _TXT(t.get("name")), "nature": _TXT(t.get("nature")), "ratio": _TXT(ratio_txt),
                      "pledge_raw": _TXT(t.get("pledge_freeze")), "change_txt": share_txt or "—",
                      "change_cls": {"减持": "dn", "增持": "up"}.get(t.get("change_type"), "")})
    slots["s6"] = {
        "holders": {"cur_w": None if hn_c is None else round(hn_c / 10000, 2),
                    "prev_w": None if hn_p is None else round(hn_p / 10000, 2),
                    "has_ts": "num:[" in js["HOLDERS"] and "num:[]" not in js["HOLDERS"]},
        "top10": top10,
        "pledge_ratio": sh.get("pledge_ratio"),
    }

    # ── S7 peers 表 + 检验卡读数 + 期后表 ──
    prs = data.get("peers") or []
    _PCOLS = ("gross_margin", "rd_ratio", "debt_to_assets", "net_margin",
              "asset_turnover", "equity_multiplier", "roe")
    rd_ratio_cur = None
    if _v(inc, "rd_exp") is not None and _v(inc, "revenue"):
        rd_ratio_cur = _v(inc, "rd_exp") / _v(inc, "revenue")
    self_row = {"gross_margin": (ratios.get("gross_margin") or {}).get("cur"),
                "rd_ratio": rd_ratio_cur,
                "debt_to_assets": (ratios.get("debt_to_assets") or {}).get("cur"),
                "net_margin": (ratios.get("net_margin") or {}).get("cur"),
                "asset_turnover": (ratios.get("asset_turnover") or {}).get("cur"),
                "equity_multiplier": (ratios.get("equity_multiplier") or {}).get("cur"),
                "roe": (ratios.get("roe") or {}).get("cur")}
    med = {c: round(statistics.median([p[c] for p in prs if isinstance(p.get(c), (int, float))]), 4)
           for c in _PCOLS if any(isinstance(p.get(c), (int, float)) for p in prs)}
    _peers_fmt = lambda c, v: ("—" if v is None else
                               (_PCT2(v) if c in ("gross_margin", "rd_ratio", "debt_to_assets",
                                                  "net_margin", "roe") else _F2(v)))
    # 染色：vs 中位数，资产负债率中性不染（成品实证规则）
    _peer_cls = lambda c, v: ("" if c == "debt_to_assets" or v is None or med.get(c) is None
                              else ("up" if v > med[c] else ("dn" if v < med[c] else "")))
    diff_row = {}
    for c in _PCOLS:
        sv, mv = self_row.get(c), med.get(c)
        if sv is None or mv is None:
            diff_row[c] = {"txt": "—", "cls": ""}
            continue
        dd = sv - mv
        txt = f"{dd * 100:+.2f}pct" if c in ("gross_margin", "rd_ratio", "debt_to_assets",
                                             "net_margin", "roe") else f"{dd:+.2f}"
        diff_row[c] = {"txt": txt, "cls": _peer_cls(c, sv)}
    slots["s7"] = {
        "expect_actual": {"rev": _F2(_v(inc, "revenue")), "np": _F2(_v(inc, "np_at"))},
        "peers": {"self": {c: {"txt": _peers_fmt(c, self_row.get(c)), "cls": _peer_cls(c, self_row.get(c))}
                          for c in _PCOLS},
                  "rows": [{"name": p.get("name"),
                            **{c: {"txt": _peers_fmt(c, p.get(c)), "cls": ""} for c in _PCOLS}}
                           for p in prs],
                  "median": {c: _peers_fmt(c, med.get(c)) for c in _PCOLS},
                  "diff": diff_row},
    }
    rm = der.get("risk_models") or {}
    alt, ohl = rm.get("altman_z") or {}, rm.get("ohlson_o") or {}
    stc = (der.get("stress") or {}).get("scenarios") or []
    stress_txt = "/".join(_F2(sc.get("np_stressed")) or "—" for sc in stc)
    slots["s7"]["inspection"] = {
        "rev_np": f"{_yoy(_v(inc, 'revenue'), _v(inc, 'revenue', 'prev'))} vs "
                  f"{_yoy(_v(inc, 'np_at'), _v(inc, 'np_at', 'prev'))}",
        "rd": (f"{_F2(_v(inc, 'rd_exp'))} 亿（{_PCT2(rd_ratio_cur)} / {{{{资本化率}}}}）"
               if rd_ratio_cur is not None else "{{研发费率 / 资本化率}}"),
        "short_debt_cover": f"{(ratios.get('short_debt_cover') or {}).get('cur'):.2f} 倍"
                            if (ratios.get("short_debt_cover") or {}).get("cur") is not None else "—",
        "x6": (f"{(ratios.get('ocf_to_liab') or {}).get('cur'):.2f}（半年口径）"
               if (ratios.get("ocf_to_liab") or {}).get("cur") is not None else "—"),
        "risk_models": (f"Altman Z={alt.get('cur'):.2f}（{alt.get('zone')}区）· "
                        f"Ohlson P={ohl.get('prob'):.2f}（{ohl.get('level')}）") if alt and ohl else "—",
        "stress": f"收入-10/20/30% → 净利 {stress_txt} 亿" if stc else "—",
        "incr_eff": _F2((ratios.get("incr_expense_eff") or {}).get("cur")) or "—",
        "sales_eff": _F2((ratios.get("incr_sales_eff") or {}).get("cur")) or "—",
    }
    slots["s7"]["subsequent"] = [{"date": _TXT(e.get("date")), "event": _TXT(e.get("event")),
                                  "verifies": _TXT(e.get("verifies"))}
                                 for e in (notes.get("subsequent_events") or [])]

    # ── S8 watchlist 卡（indicator 即 figtitle；wb 拼接上限/下限/熔断句）──
    slots["s8"] = {"cards": [
        {"indicator": _TXT(w.get("indicator")), "current": _TXT(w.get("current")),
         "badge": w.get("badge"),
         "wb": (f"&gt; {_TXT(w.get('upper'))} {_TXT(w.get('upper_meaning'))} / &lt; {_TXT(w.get('lower'))} "
                f"{_TXT(w.get('lower_meaning'))}；{_TXT(w.get('tripwire'))}"),
         "srcline": _TXT(w.get("source"))}
        for w in (data.get("watchlist") or [])]}
    return slots

