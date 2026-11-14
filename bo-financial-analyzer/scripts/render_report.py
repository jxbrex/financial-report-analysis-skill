#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_report.py — fill→render（v0.1.0，N4）：模板 + 槽位 JSON → 报告 HTML。

用法：
    python scripts/render_report.py data.json                 # 槽位取同 stem .fillsheet.json
    python scripts/render_report.py data.json -o out.html     # 指定输出

机械槽位（数字/徽章/语义色/JS DATA 数组/可变表行生成）按「章节→表头→行标签→列位」
锚定填充；判断槽位（figtitle/takeaway/lede/评价列/结论列/判定徽章）残留 {{}} 孔——
分析师填孔后 check_html 占位符门禁清零方可交付（流程语义与手写时代一致）。

锚自检：每条锚必须唯一命中，否则打印断锚清单 exit 1（模板改版漂移时脚本显式报错，
不静默错填）。review 卡、S2 Q4 集中度行与 S3 Q4 读数已机械填充；Q4 标题和转固核对仍由分析师判断。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "report-template.html"

_BADGE_TXT = {"disc": "披露", "der": "推算", "est": "估算"}
_H = "{{}}"  # 判断孔（残留由 check_html 占位符门禁兜底）
# json 原文进 HTML 的插入点统一转义（等价 calc_slots._E 口径；文件名拼接不走此，见 main）
_E = lambda s: html.escape(str(s or ""), quote=False)


class R:
    """锚定替换器：所有替换必须唯一命中，断锚累积后统一报错。"""

    def __init__(self, html):
        self.h = html
        self.miss = []

    def sub1(self, old, new, tag):
        n = self.h.count(old)
        if n == 1:
            self.h = self.h.replace(old, new, 1)
        else:
            self.miss.append(f"{tag}: 锚命中 {n} 次「{old[:60]}」")

    def re1(self, pat, new, tag, flags=re.S):
        m = re.findall(pat, self.h, flags=flags)
        if len(m) == 1:
            self.h = re.sub(pat, lambda _: new, self.h, count=1, flags=flags)
        else:
            self.miss.append(f"{tag}: 正则命中 {len(m)} 次「{pat[:60]}」")

    def sect(self, sid):
        i = self.h.index(f'id="{sid}"')
        j = self.h.find(' <div class="sect">', i)
        if j == -1:
            j = self.h.find(' <!-- ══ 页脚', i)
        if j == -1:
            # 双右界均失：按空段返回（in_sect 拼接不变、不污染产物），断锚清单统一 exit 1 兜住
            self.miss.append(f"{sid}: 段落右界未找到（模板页脚/分节标记漂移）")
            return i, i
        return i, j

    def in_sect(self, sid, fn):
        i, j = self.sect(sid)
        self.h = self.h[:i] + fn(self.h[i:j]) + self.h[j:]


def _table_seg(seg, head_anchor, r, tag):
    i = seg.find(head_anchor)
    if i == -1:
        r.miss.append(f"{tag}: 表头锚「{head_anchor[:40]}」未命中")
        return None
    j = seg.find("</table>", i)
    return i, j + len("</table>")


def _row_replace(seg, row_anchor, fn, r, tag):
    """在 seg 内找首格以 row_anchor 开头的 <tr>（含 tr class 属性），fn(row) 返回新行。"""
    m = re.search(rf'<tr[^>]*><td[^>]*>\s*{re.escape(row_anchor)}.*?</tr>', seg, flags=re.S)
    if not m:
        r.miss.append(f"{tag}: 行锚「{row_anchor}」未命中")
        return seg
    return seg[:m.start()] + fn(m.group(0)) + seg[m.end():]


def _cells(row):
    return [(m.group(0), m.group(1), m.group(2))
            for m in re.finditer(r'<td([^>]*)>(.*?)</td>', row, flags=re.S)]


def _rebuild(cells, edits, row=""):
    """edits: {格序(0-based): 文本 | (文本, cls) | (文本, cls, "tdclass")}——
    默认染色用 span 包裹（四维表/peers 形态）；tdclass 时 cls 直接写进 td class
    （净利桥形态：成品 <td class="up">+0.73</td>，模板格自带 class 须整体重写）。
    row 传入时保留原 <tr> 开标签（模板行带 class/属性时不被静默剥掉）。"""
    out = []
    for i, (full, attrs, inner) in enumerate(cells):
        if i not in edits:
            out.append(full)
            continue
        e = edits[i]
        text, cls, mode = (e + ("span",))[:3] if isinstance(e, tuple) else (e, None, "span")
        if mode == "tdclass":
            out.append(f'<td class="{cls}">{text}</td>' if cls else f"<td>{text}</td>")
        elif cls:
            out.append(f'<td{attrs}><span class="{cls}">{text}</span></td>')
        else:
            out.append(f"<td{attrs}>{text}</td>")
    m_ = re.match(r"<tr[^>]*>", row or "")
    return (m_.group(0) if m_ else "<tr>") + "".join(out) + "</tr>"


# ════ 各章 filler ════

def fill_js(r, js):
    for key in ("TREND", "NCR_TS", "EFF_TS", "DUPONT_STACK", "SEG_BRIDGE", "SEG_ENDS",
                "OCF_BRIDGE", "OCF_END", "HOLDERS", "SANKEY"):
        # 行级替换不传 re.S：DOTALL 下 .* 会吞到文件末尾（赢合实测 TREND 替换团灭 JS 尾部）
        r.re1(rf"(?m)^const {key}=.*$", js[key], f"js.{key}", flags=0)


def fill_meta(r, m):
    r.sub1("<title>{{公司名}} {{报告期}}{{报告类型}}分析 — Bo-FinancialAnalyzer</title>",
           f"<title>{_E(m['company'])} {_E(m['sub_lead'])}分析 — Bo-FinancialAnalyzer</title>",
           "meta.title")
    r.sub1("BO-FINANCIALANALYZER · {{上市地}}",
           f"BO-FINANCIALANALYZER · {_E(m['market'])}", "meta.kicker")
    r.sub1("<h1>{{公司名}}（{{代码}}）</h1>", f"<h1>{_E(m['title'])}</h1>", "meta.h1")
    r.sub1("<b>{{报告期}}{{报告类型}}</b> 分析报告 · 报告发布于 {{披露日期}} · 分析生成于 {{生成日期}}",
           f"<b>{_E(m['sub_lead'])}</b> 分析报告 · 报告发布于 {_E(m['disclose_date'])} · "
           f"分析生成于 {_E(m['analyst_date'])}", "meta.sub")
    r.sub1("<span>{{公司名}}（{{代码}}）{{报告期}}{{报告类型}}分析 · 生成于 {{日期}}</span>",
           f"<span>{_E(m['title'])}{_E(m['sub_lead'])}分析 · 生成于 {_E(m['analyst_date'])}</span>",
           "meta.foot")
    # 以下两锚在模板各出现 2 处、语义同填（srcline 周期表述/比率表口径行）——
    # 显式计数入断锚：锚漂移或第 3 处新增时显式报错，不静默漏填/同填
    _pairs = [("公司{{报告期}}{{报告类型}}", f"公司 {m['srcline_period']}{m['report_type']}", "meta.srcline")]
    if m.get("report_type") and m["report_type"] != "年报":
        _pairs.append(("各期年报比率", f"各期{m['report_type']}比率", "meta.annual"))
    for old, new, tag in _pairs:
        n = r.h.count(old)
        if n != 2:
            r.miss.append(f"{tag}: 锚命中 {n} 次（预期 2 处同填）「{old[:40]}」")
        else:
            r.h = r.h.replace(old, new)


def drop_review(r, data):
    if data.get("review"):
        return
    r.re1(r" <!-- ══ 上期跟踪回顾.*?\n </div>\n\n(?= <!-- ══ 核心结论)", "", "drop.review")
    r.sub1(' <a href="#review" title="回溯 · 上期跟踪回顾">回顾</a>\n', "", "drop.toc_review")


def fill_review(r, review):
    rows = review.get("rows") or []
    if not rows:
        return
    r.sub1('<div class="v">{{m}}/{{n}}</div>',
           f'<div class="v">{review["met"]}/{review["total"]}</div>', "review.count")
    r.sub1('<div class="r">✅ 兑现 {{a}} · ❌ 未兑现 {{b}} · ⏳ 待观察 {{c}}</div>',
           f'<div class="r">{review["counts_txt"]}</div>', "review.counts")
    gen = "\n ".join(
        f'<tr><td>{item["tripwire"]}</td><td class="txt"><span class="badge {item["cls"]}">'
        f'{item["verdict"]}</span></td><td class="txt">{item["note"]}</td></tr>'
        for item in rows)
    r.re1(r'<tr><td>\{\{上期清单第 1 条.*?</tr>\n <tr><td>\{\{上期清单第 2 条.*?</tr>\n'
          r' <tr><td>\{\{上期清单第 3 条.*?</tr>', gen, "review.rows")


def fill_s1(r, s1, m):
    # KPI 四卡整卡重写
    cards = []
    for k in s1["kpi"]:
        cls = f' {k["cls"]}' if k["cls"] else ""
        cards.append(f'<div class="kpi"><div class="v">{k["v"]}</div>'
                     f'<div class="r{cls}">{k["r"]} <span class="badge {k["badge"]}">'
                     f'{_BADGE_TXT[k["badge"]]}</span></div>'
                     f'<div class="l">{k["l"]}</div></div>')
    r.re1(r'<div class="kpis">.*?\n </div>',
          "<div class=\"kpis\">\n " + "\n ".join(cards) + "\n </div>", "s1.kpis")

    def _s1(seg):
        # 四维表 12 行（格2/3 机械，格4 染色重写，评价列留孔）
        t = _table_seg(seg, "<tr><th>指标</th><th>本期</th><th>上期</th>", r, "s1.table4")
        if t:
            i, j = t
            tbody = seg[i:j]
            rows4 = [("毛利率 ", 0), ("净利率", 1), ("ROIC 投入资本回报率", 2), ("内生增长率", 3),
                     ("存货周转天数", 4), ("应收周转天数", 5), ("收现比", 6), ("现金转换周期 CCC", 7),
                     ("资产负债率", 8), ("经营杠杆 DOL", 9), ("财务杠杆 DFL", 10),
                     ("非主营业务收入占比", 11)]
            for anchor, idx in rows4:
                row = s1["table4"][idx]

                def _fn4(tr, row=row):
                    cells = _cells(tr)
                    edits = {}
                    if row.get("badge") and '<span class="badge ' in cells[0][2]:
                        edits[0] = re.sub(r'<span class="badge [^"]+">[^<]*</span>',
                                          f'<span class="badge {row["badge"]}">{_BADGE_TXT[row["badge"]]}</span>',
                                          cells[0][2], count=1)
                    if "{{" in tr:
                        edits[1] = row["cur"]
                        if "<td>{{}}</td>" in tr or re.search(r"<td>\{\{", tr):
                            edits[2] = row["prev"]
                        edits[3] = (row["delta"], row["cls"] or None)
                    return _rebuild(cells, edits, tr)
                tbody = _row_replace(tbody, anchor, _fn4, r, f"s1.t4.{anchor}")
            seg = seg[:i] + tbody + seg[j:]

        # 杜邦左卡
        dp = s1.get("dupont") or {}
        t = _table_seg(seg, "<tr><th>因子</th><th>本期</th><th>上期</th>", r, "s1.dupont")
        if t and dp:
            i, j = t
            tbody = seg[i:j]
            for label, ekey in (("净利率", "净利率"), ("总资产周转率", "总资产周转率"),
                                ("权益乘数", "杠杆")):
                def _fnd(tr, label=label, ekey=ekey):
                    cells = _cells(tr)
                    eff, ecls = dp["effects"].get(ekey) or _H, dp["effects_cls"].get(ekey) or ""
                    inner = cells[3][2]
                    inner = re.sub(r"\{\{[^}]*\}\}",
                                   f'<span class="{ecls}">{eff}</span> · {_H}' if ecls
                                   else f"{eff} · {_H}", inner, count=1)
                    first = cells[0][0]
                    if label == "净利率":  # 扣非双版对照槽：触发才填（二期接 dupont_dt），未触发删槽
                        first = re.sub(r"\{\{扣非双版[^}]*\}\}", "", first)
                    edits = {1: dp["cur"].get(label) or _H, 2: dp["prev"].get(label) or _H}
                    out = [first,
                           f"<td{cells[1][1]}>{edits[1]}</td>",
                           f"<td{cells[2][1]}>{edits[2]}</td>",
                           f"<td{cells[3][1]}>{inner}</td>"]
                    return "<tr>" + "".join(out) + "</tr>"
                tbody = _row_replace(tbody, label, _fnd, r, f"s1.dp.{label}")
            # 下钻子行（块缺失则整行槽残留，check_html 兜底）；替换显式计数入断锚，
            # 锚漂移时显式报错而非静默留孔
            def _dr1(old, new, tag):
                nonlocal tbody
                n = tbody.count(old)
                if n == 1:
                    tbody = tbody.replace(old, new, 1)
                else:
                    r.miss.append(f"{tag}: 锚命中 {n} 次「{old[:40]}」")
            if dp.get("margin_drill"):
                _dr1("└ 经营 {{±x.x}}pct · 税负 {{±x.x}}pct · 利息 {{±x.x}}pct · 少数股东 {{±x.x}}pct",
                     f"└ {dp['margin_drill']}", "s1.dp.margin_drill")
            if dp.get("turnover_drill"):
                _dr1("└ Δ总资产前二：{{科目}} {{±}} / {{科目}} {{±}}；应收存货类 {{x}}% · 产能类 {{y}}%",
                     f"└ {dp['turnover_drill']}", "s1.dp.turnover_drill")
            ld = dp.get("leverage_drill") or {}
            if ld:
                _dr1("有息/权益 {{x.xx→x.xx}} · 无息/权益 {{x.xx→x.xx}}",
                     f"有息/权益 {ld['ib']} · 无息/权益 {ld['ni']}", "s1.dp.ld_ratio")
                _dr1("无息占比 {{x}}% + ΔDFL {{±x.xx}}",
                     f"无息占比 {ld['ni_share']} + ΔDFL {ld['dfl']}", "s1.dp.ld_share")
            # ROE 合计行
            def _fnroe(tr):
                cells = _cells(tr)
                ratio = dp.get("effects_ratio")
                if ratio is None:  # 三效应全零的合法形态（calc_slots 原样传 None）
                    drv = "效应比不适用（三效应≈0）"
                elif dp.get("driver_fragile"):
                    drv = (f"双驱动（{dp.get('driver')}/{dp.get('driver_second')}）："
                           f"效应比 {ratio:.2f}&lt;1.5，禁止单一标签")
                else:
                    drv = (f"主驱动={dp.get('driver')}；效应比 {ratio:.2f}"
                           f"{'≥' if (ratio or 0) >= 1.5 else '&lt;'}1.5，"
                           f"{'单标签成立' if (ratio or 0) >= 1.5 else '双驱动待复核'}")
                return "<tr class=\"total\">" + "".join(
                    [cells[0][0], f"<td{cells[1][1]}>{dp.get('roe_cur') or _H}</td>",
                     f"<td{cells[2][1]}>{dp.get('roe_prev') or _H}</td>",
                     f"<td{cells[3][1]}>{drv}</td>"]) + "</tr>"
            tbody = _row_replace(tbody, "ROE（摊薄）", _fnroe, r, "s1.dp.roe")
            seg = seg[:i] + tbody + seg[j:]
        return seg
    r.in_sect("s1", _s1)

    # 杜邦右卡（五年归因 A 表 + 分位表）——表头 period 槽先填
    d5 = s1.get("dupont5y")
    if d5:
        r.sub1("<th>{{period_start}}</th>", f"<th>{d5['p_start']}</th>", "s1.d5.h1")
        r.sub1("<th>{{period_end}}</th>", f"<th>{d5['p_end']}</th>", "s1.d5.h2")

        def _d5(seg):
            t = _table_seg(seg, "<tr><th>因子</th><th>" + d5["p_start"], r, "s1.d5")
            if not t:
                return seg
            i, j = t
            tbody = seg[i:j]
            for row in d5["rows"]:
                def _fn5(tr, row=row):
                    cells = _cells(tr)
                    return "<tr>" + "".join([
                        cells[0][0], f"<td{cells[1][1]}>{row['start'] or _H}</td>",
                        f"<td{cells[2][1]}>{row['end'] or _H}</td>",
                        f'<td class="{row["cls"]}">{row["cum"] or _H}</td>'
                        if row.get("cls") else f"<td>{row['cum'] or _H}</td>",
                        cells[4][0]]) + "</tr>"
                tbody = _row_replace(tbody, row["label"], _fn5, r, f"s1.d5.{row['label']}")
            def _fnr5(tr):
                cells = _cells(tr)
                inner5 = re.sub(r"口径差 \{\{±x\.x\}\}pct", f"口径差 {d5['roe']['gap']}", cells[4][2])
                return ("<tr class=\"total\">" + "".join([
                    cells[0][0], f"<td{cells[1][1]}>{d5['roe']['start'] or _H}</td>",
                    f"<td{cells[2][1]}>{d5['roe']['end'] or _H}</td>",
                    f"<td{cells[3][1]}>{d5['roe']['delta'] or _H}</td>",
                    f"<td{cells[4][1]}>{inner5}</td>"]) + "</tr>")
            tbody = _row_replace(tbody, "ROE（摊薄）", _fnr5, r, "s1.d5.roe")
            return seg[:i] + tbody + seg[j:]
        r.in_sect("s1", _d5)

        def _pct(seg):
            t = _table_seg(seg, "<tr><th>因子</th><th>当前值</th><th>五年位置</th>", r, "s1.pctile")
            if not t:
                return seg
            i, j = t
            tbody = seg[i:j]
            cur_map = {r_["label"]: r_["end"] for r_ in d5["rows"]}
            for label in ("净利率", "总资产周转率", "权益乘数"):
                def _fnp(tr, label=label):
                    cells = _cells(tr)
                    badge = re.sub(r"\{\{[^}]*\}\}", d5["pctile"].get(label) or _H,
                                   cells[2][2], count=1)
                    return "<tr>" + "".join([
                        cells[0][0], f"<td{cells[1][1]}>{cur_map.get(label) or _H}</td>",
                        f"<td{cells[2][1]}>{badge}</td>", cells[3][0]]) + "</tr>"
                tbody = _row_replace(tbody, label, _fnp, r, f"s1.pctile.{label}")
            return seg[:i] + tbody + seg[j:]
        r.in_sect("s1", _pct)
    else:
        r.re1(r' <div class="card">\n <div class="figtitle">\{\{结论式：五年模式叙事.*?'
              r'\n </div>\n </div>\n <div class="fig">',
              ' <div class="card"><div class="figtitle">累计归因与因子分位降级：'
              '同口径平均余额序列不足三年</div><p class="lede">现有披露未形成足够的同口径历史序列，'
              '平均余额周转还缺相应期初；不虚构历史，不用两期点冒充累计趋势。'
              '本期杜邦归因与下期条件化跟踪仍保留。</p><div class="srcline">'
              '数据来源：公司各期报告 · 累计归因/分位因同口径序列不足而不适用'
              '</div></div>\n </div>\n <div class="fig">', "s1.d5_drop")
        r.re1(r' <div class="takeaway">修复路径：.*?</div>',
              ' <div class="takeaway">修复路径：累计分位证据不足，不做回到历史中枢的估算；'
              '只保留当期归因与下期条件化跟踪。</div>', "s1.d5_drop_repair")

    # 周期定位判词行
    stage = m.get("cycle_stage")
    if stage:
        tail = _H if "非周期" in stage else f"（{_H}）"
        r.sub1('<div class="wv">周期定位：{{上行/顶部/下行/底部（一句注解） / 非周期行业}} '
               '<span class="badge der">推算</span></div>',
               f'<div class="wv">周期定位：{stage}{tail} <span class="badge der">推算</span></div>',
               "s1.cycle_stage")

    # ncrline hist<3 期整卡降级（模板注释约定）：删 svg + figtitle 降级声明，
    # 否则空骨架必撞 empty-svg 门禁（长城实证的关键 SVG 非空检测）
    if s1.get("ncr_drop"):
        r.re1(r' <svg id="ncrline".*?</svg>\n', "", "s1.ncr_drop_svg")
        r.re1(r'<div class="figtitle">\{\{结论式：现金含量一句话.*?\}\}</div>',
              '<div class="figtitle">现金含量证据不足：净现比序列不足 3 期，'
              '本卡降级为声明（历史口径断裂或未披露）</div>', "s1.ncr_drop_title")


def fill_s2(r, s2):
    def _sig_tr(s_, cls, txt):
        return (f'<tr><td>{s_["title"]}：{s_["data"]} {_H}</td>'
                f'<td class="txt"><span class="badge {cls}">{txt}</span></td>'
                f'<td class="txt"><b>担心</b>：{_H}<br><b>本案</b>：{_H}</td>'
                f'<td class="txt">{_H}</td></tr>')
    rows = ([_sig_tr(s_, "r", "🔴 命中") for s_ in s2.get("hit_rows") or []]
            + [_sig_tr(s_, "y", "🟡 观察") for s_ in s2.get("watch_rows") or []])
    if rows:
        r.re1(r' <tr><td>\{\{命中信号.*?</tr>\n <tr><td>\{\{观察信号.*?</tr>',
              "\n ".join(rows), "s2.signal_rows")
    r.re1(r'<tr class="total"><td colspan="4" class="txt">未触发汇总：已检 .*?</td></tr>',
          f'<tr class="total"><td colspan="4" class="txt">{s2["summary_line"]}</td></tr>',
          "s2.summary")

    # 勾稽异常表
    rr = s2.get("recon_rows") or []
    def _recon_tr(x):
        vcls, vtxt = (("y", "⚠️ 可解释") if x["verdict"] == "可解释"
                      else ("r", "🔴 无法解释") if "无法" in str(x["verdict"])
                      else ("y", f"⚠️ {x['verdict']}"))
        return (f'<tr><td>{x["eq"]}</td><td class="txt"><span class="badge {vcls}">{vtxt}</span></td>'
                f'<td>{x["deviation"]}</td><td class="txt">{x["explain"]}</td>'
                f'<td class="txt">{_H}</td></tr>')
    if rr:
        r.re1(r' <tr><td>\{\{A4 收入-收现闭环\}\}.*?</tr>\n <tr><td>\{\{B1 应收 roll-forward\}\}.*?</tr>',
              "\n ".join(_recon_tr(x) for x in rr), "s2.recon_rows")
    r.sub1("共核对 {{N}} 条勾稽等式", f"共核对 {s2.get('recon_total', _H)} 条勾稽等式", "s2.recon_n")
    recon_summary = f"{s2.get('recon_closed', _H)} 条闭合"
    if s2.get("recon_explainable"):
        recon_summary += f" · {s2['recon_explainable']} 项可解释"
    if s2.get("recon_unexplained"):
        recon_summary += f" · {s2['recon_unexplained']} 项无法解释"
    if s2.get("recon_unexecuted"):
        names = "、".join(s2.get("recon_unexecuted_names") or [])
        recon_summary += f" · {s2['recon_unexecuted']} 项未执行（{names}）"
    r.sub1("{{全部闭合 / 其余 M 条闭合}}", recon_summary, "s2.recon_closed")

    # 四线考核表
    tk = s2.get("threshold") or {}
    def _line_row(anchor, blk):
        def _fn(tr):
            cells = _cells(tr)
            vcls = "g" if "远离" in blk["verdict"] or "无贴线" in blk["verdict"] else "y"
            return "<tr>" + "".join([cells[0][0], f"<td{cells[1][1]}>{blk['read']}</td>",
                                     f"<td{cells[2][1]}>{blk['target']}</td>",
                                     f"<td{cells[3][1]}>{blk['dist'] or '—'}</td>",
                                     f'<td{cells[4][1]}><span class="badge {vcls}">{blk["verdict"]}</span></td>'
                                     ]) + "</tr>"
        return _fn
    def _s2t(seg):
        t = _table_seg(seg, "<tr><th>检测线</th>", r, "s2.threshold")
        if not t:
            return seg
        i, j = t
        tbody = seg[i:j]
        if tk.get("shell"):
            tbody = _row_replace(tbody, "保壳线", _line_row("保壳线", tk["shell"]), r, "s2.tk.shell")
        if tk.get("refi"):
            tbody = _row_replace(tbody, "再融资线", _line_row("再融资线", tk["refi"]), r, "s2.tk.refi")
        if tk.get("incentive"):
            tbody = _row_replace(tbody, "股权激励考核线", _line_row("激励线", tk["incentive"]),
                                 r, "s2.tk.inc")
        if tk.get("q4"):
            tbody = _row_replace(tbody, "Q4 集中度", _line_row("Q4 集中度", tk["q4"]),
                                 r, "s2.tk.q4")
        elif tk.get("q4_na"):
            tbody = _row_replace(
                tbody, "Q4 集中度",
                lambda tr: (f'<tr><td>Q4 集中度</td><td>{tk.get("q4_na_label") or "—（不适用）"}</td><td>≤40%</td>'
                            f'<td>—</td><td class="txt">—</td></tr>'),
                r, "s2.tk.q4")
        return seg[:i] + tbody + seg[j:]
    r.in_sect("s2", _s2t)


def fill_s3(r, s3):
    # 桑基卡（v0.1.4）：降级=删 svg（empty-svg 门禁）+删 takeaway+标题换声明+srcline 换降级注；
    # 正常态填机械 srcline（口径随 period_type）
    if s3.get("sankey_drop"):
        r.re1(r' <svg id="sankey".*?</svg>\n', "", "s3.sankey_drop_svg")
        r.re1(r' <div class="takeaway">\{\{读法：桑基.*?</div>\n', "", "s3.sankey_drop_takeaway")
        r.re1(r'<div class="figtitle">\{\{结论式：资金流向.*?\}\}</div>',
              '<div class="figtitle">资金流向桑基图不适用：当期收入/利润/经营现金流存在非正项'
              '（或单季差额原料缺失），本卡降级为声明——资金链条解读见本表净利桥与 OCF 桥卡</div>',
              "s3.sankey_drop_title")
        r.sub1(' <div class="srcline">口径：{{SANKEY 口径}} · 单位：亿元人民币 · 数据来源：定期报告合并利润表、合并现金流量表</div>',
               ' <div class="srcline">降级声明：形态不适用或原料缺失 · 资金链条证据见本表净利桥与 OCF 桥卡</div>',
               "s3.sankey_drop_src")
    elif s3.get("sankey_src"):
        r.sub1(' <div class="srcline">口径：{{SANKEY 口径}} · 单位：亿元人民币 · 数据来源：定期报告合并利润表、合并现金流量表</div>',
               f' <div class="srcline">{s3["sankey_src"]}</div>', "s3.sankey_src")
    if s3.get("ocf_drop"):
        # OCF 桥降级（补充资料未披露的合法 WARN 态）：空桥必须删 svg（empty-svg 门禁）
        # + 删端点行（无数据可填）+ figtitle 换降级声明——对齐 ncr_drop 模式
        r.re1(r' <svg id="ocfbridge".*?</svg>\n', "", "s3.ocf_drop_svg")
        r.re1(r' <div class="brends">净利润 \{\{X\}\} 亿.*?</div>\n', "", "s3.ocf_drop_brends")
        r.re1(r'<div class="figtitle">\{\{结论式：经营现金流净额（OCF）.*?\}\}</div>',
              '<div class="figtitle">OCF 调节桥未披露：现金流量表补充资料缺失，'
              '本卡降级为声明（间接法调节明细不可得）</div>', "s3.ocf_drop_title")
    if s3.get("seg_drop"):
        # 分部上期金额未披露时 SEG_BRIDGE 合法为空：删空图换声明，保留总收入端点行
        r.re1(r' <svg id="segbridge".*?</svg>\n', "", "s3.seg_drop_svg")
        r.re1(r'<div class="figtitle">\{\{结论式：Δ收入归因.*?\}\}</div>',
              '<div class="figtitle">分部收入变动桥未绘制：分部增减缺少可比金额，'
              '本卡仅保留总收入变动</div>', "s3.seg_drop_title")
        r.re1(r' <div class="srcline">数据来源：\{\{报告 MD&A 产销量表 / 分部收入附注\}\}.*?</div>\n',
              ' <div class="srcline">数据来源：定期报告合并利润表 · 分部增减缺少可比金额，'
              '不绘制收入桥</div>\n', "s3.seg_drop_src")
    if s3.get("brends_seg"):
        r.re1(r'<div class="brends">基期收入 .*?</div>',
              f'<div class="brends">{s3["brends_seg"]}</div>', "s3.brends_seg")
    if s3.get("brends_ocf"):
        r.re1(r'<div class="brends">净利润 .*?</div>',
              f'<div class="brends">{s3["brends_ocf"]}</div>', "s3.brends_ocf")
    wc = s3.get("wc")
    if wc:
        r.sub1("营运资本吞噬额 {{X}} 亿（占净利润 {{Y}}%，负值=净释放）",
               f"营运资本吞噬额 {wc['amount']} 亿（占净利润 {wc['share']}，负值=净释放）", "s3.wc")

    rows = {x["item"]: x for x in s3.get("np_rows") or []}
    total = s3.get("np_total") or {}
    def _s3(seg):
        t = _table_seg(seg, "<tr><th>环节</th>", r, "s3.npb")
        if not t:
            return seg
        i, j = t
        tbody = seg[i:j]
        for item in ("毛利", "税金及附加", "期间费用合计", "减值损失", "非经常性损益", "所得税",
                     "少数股东损益"):
            row = rows.get(item)
            if not row:
                continue
            def _fn3(tr, row=row):
                cells = _cells(tr)
                edits = {1: row["cur"], 2: row["prev"],
                         3: (row["delta"] or _H, row["cls"] or None, "tdclass")}
                if row.get("note"):
                    edits[4] = row["note"]
                return _rebuild(cells, edits, tr)
            tbody = _row_replace(tbody, item, _fn3, r, f"s3.np.{item}")
        if total:
            def _fnt(tr):
                cells = _cells(tr)
                return ("<tr class=\"total\">" + "".join([
                    cells[0][0], f"<td{cells[1][1]}>{total.get('cur') or _H}</td>",
                    f"<td{cells[2][1]}>{total.get('prev') or _H}</td>",
                    f"<td{cells[3][1]}>{total.get('delta') or _H}</td>",
                    cells[4][0]]) + "</tr>")
            tbody = _row_replace(tbody, "归母净利润", _fnt, r, "s3.np.total")
        return seg[:i] + tbody + seg[j:]
    r.in_sect("s3", _s3)

    q4_rows = s3.get("q4_rows") or []
    if q4_rows:
        def _s3q4(seg):
            t = _table_seg(seg, "<tr><th>检验项</th>", r, "s3.q4")
            if not t:
                return seg
            i, j = t
            tbody = seg[i:j]
            for row in q4_rows:
                def _fnq4(tr, row=row):
                    cells = _cells(tr)
                    return _rebuild(cells, {1: row["read"],
                                            3: f'<span class="badge {row["cls"]}">{row["verdict"]}</span>'}, tr)
                tbody = _row_replace(tbody, row["item"], _fnq4, r, f"s3.q4.{row['item']}")
            return seg[:i] + tbody + seg[j:]
        r.in_sect("s3", _s3q4)


def fill_s4(r, s4):
    big_rows = s4.get("big_moves") or []
    if big_rows:
        gen = "\n ".join(f'<tr><td>{x["subject"]}</td><td>{x["change"]}</td>'
                          f'<td class="txt">{x["explanation"]}</td></tr>' for x in big_rows)
        r.re1(r'<tr><td>\{\{科目\}\}</td><td>\{\{%\}\}</td>.*?</tr>',
              gen, "s4.big_moves")
    if s4.get("big_src"):
        r.re1(r'<div class="srcline">数字大动而文字不解释.*?</div>',
              f'<div class="srcline">数据来源：{s4["big_src"]} · 数字大动而文字不解释，本身就是信号</div>',
              "s4.big_src")
    rows = s4.get("rows") or []
    if rows:
        gen = "\n ".join(
            f'<tr><td>{a["text"]}</td><td class="txt">{a["evidence"]}</td>'
            f'<td class="txt"><span class="badge {a["badge_cls"]}">{a["verdict_text"]}</span></td>'
            f'<td class="txt">{a["source"]}</td></tr>' for a in rows)
        r.re1(r' <tr class="group"><td colspan="4">\{\{科目组名.*?</tr>\n <tr><td>\{\{如：.*?</tr>',
              gen, "s4.assertion_rows")
    r.re1(r'<div class="figtitle">\{\{结论式：断言验证.*?\}\}</div>',
          f'<div class="figtitle">{s4["figtitle_prefix"]}——{_H}</div>', "s4.figtitle")
    r.re1(r'<div class="takeaway">汇总：共 .*?</div>',
          f'<div class="takeaway">汇总：{s4["counts_txt"]}；未解释的大幅变动 {_H} 项；'
          f'指引兑现率 {_H}——计数与 figtitle 同源（text-mining.md 第七节呈现规范）</div>',
          "s4.counts")
    if s4.get("gap_declaration"):
        r.re1(r'<div class="srcline">数据缺口声明：.*?</div>',
              f'<div class="srcline">{s4["gap_declaration"]}</div>', "s4.gap")
    else:
        r.re1(r' <div class="srcline">数据缺口声明：.*?</div>\n', "", "s4.gap_drop")


def fill_s5(r, s5):
    if s5.get("cip_empty"):
        balance = s5.get("cip_balance")
        if balance:
            label = f"在建工程（期末余额{balance:.2f}亿，无项目附注）"
            verdict = '<span class="badge y">⚠️ 观察</span>'
        elif balance == 0:
            label = "在建工程（期末余额为零，无项目附注）"
            verdict = '<span class="badge g">✅ 无挂账</span>'
        else:
            label = "在建工程（期末余额未披露，无项目附注）"
            verdict = '<span class="badge y">⚠️ 观察</span>'
        r.re1(r'<tr><td>\{\{项目名\}\}.*?</tr>',
              f'<tr><td>{label}</td><td>—</td><td>—</td><td>—</td>'
              f'<td>—</td><td>—</td><td class="txt">{verdict}</td></tr>',
              "s5.cip_empty")
    elif s5.get("cip_rows"):
        gen = "\n ".join(
            f'<tr><td>{p["name"]}</td><td>{p.get("budget") or "—"}</td>'
            f'<td>{p.get("invested") or "—"}</td><td>{p.get("closing") or "—"}</td>'
            f'<td>{p.get("progress") or "—"}</td><td>{p.get("transferred") or "—"}</td>'
            f'<td class="txt">{_H}</td></tr>'
            for p in s5["cip_rows"])
        r.re1(r'<tr><td>\{\{项目名\}\}.*?</tr>', gen, "s5.cip_rows")
    if s5.get("cap_drop"):
        r.re1(r' <div class="card">\n <div class="figtitle">\{\{结论式：产能利用一句话.*?\n </div>\n',
              "", "s5.cap_drop")


def fill_s6(r, s6):
    rows = []
    for t in s6.get("top10") or []:
        nm = f'{t["name"]}（{t["nature"]}）' if t.get("nature") else t["name"]
        chg = (f'<span class="{t["change_cls"]}">{t["change_txt"]}</span>'
               if t["change_cls"] else t["change_txt"])
        rows.append(f'<tr><td>{nm}</td><td>{t["ratio"] or "—"}</td><td>{_H}</td>'
                    f'<td class="txt">{chg}</td></tr>')
    if rows:
        r.re1(r'<tr><td>\{\{\}\}</td><td>\{\{%\}\}</td><td>\{\{%或「零质押」\}\}</td>.*?</tr>',
              "\n ".join(rows), "s6.top10")
    mgmt = s6.get("mgmt")
    if mgmt:
        change = (f'<span class="{mgmt["cls"]}">{mgmt["text"]}</span>' if mgmt["cls"]
                  else mgmt["text"])
        r.re1(r'<tr><td>高管增减持（合计）</td>.*?</tr>',
              f'<tr><td>高管增减持（合计）</td><td>—</td><td>—</td><td class="txt">{change}</td></tr>',
              "s6.mgmt")
        if mgmt.get("src"):
            r.re1(r'<div class="srcline">数据来源：Tushare top10_holders.*?</div>',
                  f'<div class="srcline">数据来源：{mgmt["src"]}；Tushare stk_holdertrade 可交叉核对 · '
                  '质押率&gt;70% 徽章化并进 <a href="#s2">风险清单</a></div>', "s6.mgmt_src")
    hd = s6.get("holders") or {}
    if not hd.get("has_ts"):
        r.re1(r' <div class="fig">\n <div class="figtitle">\{\{结论式：户数走向一句话.*?\n </div>\n',
              f' <div class="card">\n <div class="figtitle">股东户数</div>\n'
              f' <div class="wv">{hd.get("cur_w") or _H} 万户（上期 {hd.get("prev_w") or _H} 万户）'
              f' <span class="badge disc">披露</span></div>\n'
              f' <div class="wb">{_H}</div>\n'
              f' <div class="srcline">数据来源：公司定期报告股东户数节 · 时序不足 3 期降级两期文字行</div>\n'
              f' </div>\n', "s6.holders_drop")


def fill_s7(r, s7, m):
    # 预期对照表：actual/预测中位数/偏离均走槽位；旧槽缺行时保留实际列兼容路径
    def _s7e(seg):
        t = _table_seg(seg, "<tr><th>指标</th><th>实际</th><th>一致预期</th>", r, "s7.expect")
        if not t:
            return seg
        i, j = t
        tbody = seg[i:j]
        pl = m.get("period_label") or ""
        exp_rows = {row["key"]: row for row in s7.get("expect_rows") or []}
        for anchor, key in (("营业收入（亿元）", "rev"), ("归母净利（亿元）", "np")):
            row = exp_rows.get(key)
            if row:
                actual = f"{row['actual']}（{pl}）" if row["actual"] != "—" else "—"
                edits = {1: actual, 2: row["forecast"],
                         3: (row["delta"], row["cls"] or None, "tdclass")}
                tbody = _row_replace(tbody, anchor, lambda tr, edits=edits: _rebuild(_cells(tr), edits, tr),
                                     r, f"s7.exp.{key}")
                continue
            v = s7.get("expect_actual", {}).get(key)
            if v:
                tbody = _row_replace(
                    tbody, anchor,
                    lambda tr, v=v: _rebuild(_cells(tr), {1: f"{v}（{pl}）"}, tr), r, f"s7.exp.{key}")
        return seg[:i] + tbody + seg[j:]
    r.in_sect("s7", _s7e)
    if s7.get("expect_src"):
        r.re1(r'<div class="srcline">数据来源：Tushare report_rc.*?</div>',
              f'<div class="srcline">数据来源：{s7["expect_src"]}</div>', "s7.expect_src")

    # peers 表：本公司行 + 同业行 + 对比行整表生成
    pr = s7.get("peers") or {}
    if pr.get("rows") is not None and pr.get("self"):
        cols = ("gross_margin", "rd_ratio", "debt_to_assets", "net_margin",
                "asset_turnover", "equity_multiplier", "roe")
        def _pcell(c):
            return (f'<td><span class="{c["cls"]}">{c["txt"]}</span></td>' if c.get("cls")
                    else f'<td>{c["txt"]}</td>')
        lines = ["<tr><td><b>" + (_E(m.get("company")) or _H) + "</b></td>"
                 + "".join(_pcell(pr["self"][c]) for c in cols) + "</tr>"]
        for p in pr["rows"]:
            lines.append(f'<tr><td>{_E(p["name"])}</td>'
                         + "".join(_pcell(p[c]) for c in cols) + "</tr>")
        diff = pr.get("diff") or {}
        def _dcell(c):
            d = diff.get(c) or {}
            cls = d.get("cls")
            return f'<td class="{cls}">{d.get("txt", "—")}</td>' if cls else \
                f'<td>{d.get("txt", "—")}</td>'
        lines.append('<tr class="total"><td>本公司 vs 中位数</td>'
                     + "".join(_dcell(c) for c in cols) + "</tr>")
        r.re1(r'<tr><td><b>\{\{本公司\}\}</b></td>.*?</tr>\n <tr><td>\{\{同业A\}\}.*?</tr>\n'
              r' <tr><td>\{\{同业B\}\}.*?</tr>\n <tr class="total"><td>本公司 vs 中位数</td>.*?</tr>',
              "\n ".join(lines), "s7.peers")

    # 检验卡读数列（判定/结论列留孔）
    insp = s7.get("inspection") or {}
    def _s7i(seg):
        t = _table_seg(seg, "<tr><th>检验项</th><th>读数</th>", r, "s7.insp")
        if not t:
            return seg
        i, j = t
        tbody = seg[i:j]
        for anchor, key in (("收入增速 vs 净利增速", "rev_np"), ("研发费用（费率", "rd"),
                            ("短债覆盖倍数", "short_debt_cover"), ("现金流偿债口径", "x6"),
                            ("破产风险双模型", "risk_models"), ("流动性压力情景", "stress"),
                            ("增量费用效率", "incr_eff"), ("销售费用获客效率", "sales_eff")):
            if insp.get(key):
                tbody = _row_replace(tbody, anchor,
                                     lambda tr, key=key: _rebuild(_cells(tr), {1: insp[key]}, tr),
                                     r, f"s7.insp.{key}")
        return seg[:i] + tbody + seg[j:]
    r.in_sect("s7", _s7i)

    # 期后表（判定徽章留孔）
    subs = s7.get("subsequent") or []
    if subs:
        gen = "\n ".join(
            f'<tr><td>{e["date"]}</td><td class="txt">{e["event"]}</td>'
            f'<td class="txt"><span class="badge {{{{g|y}}}}">{{{{✅|⚠️}}}}</span></td>'
            f'<td class="txt">{e["verifies"]}</td></tr>' for e in subs)
        r.re1(r'<tr><td>\{\{YYYY-MM-DD\}\}.*?</tr>', gen, "s7.subsequent")


def fill_s8(r, s8):
    cards = []
    for c in s8.get("cards") or []:
        badge = c.get("badge") or "disc"
        badge = badge if badge in ("disc", "der", "est") else "disc"  # 进 class 属性，白名单兜底
        # 四个文本槽均已由 calc_slots._TXT 转义，wb 还含合法实体；此处再 _E 会双重转义
        cards.append(f'<div class="card">\n <div class="figtitle">{c["indicator"]}</div>\n'
                     f' <div class="wv">{c["current"]} <span class="badge {badge}">'
                     f'{_BADGE_TXT.get(badge, "披露")}</span></div>\n'
                     f' <div class="wb">{c["wb"]}</div>\n'
                     f' <div class="srcline">数据来源：{c["srcline"]}</div>\n </div>')
    if not cards:
        return
    inner = "\n ".join(cards[:4])
    outer = ("\n ".join(cards[4:]))
    def _s8(seg):
        # grid2 右界=最后一个 ` </div>`（其后是 sect 闭合行）——贪婪到底，防卡尾提前闭合
        m_ = re.search(r'<div class="grid2">.*\n </div>(?=\n </div>\s*$)', seg, flags=re.S)
        if not m_:
            r.miss.append("s8.grid2 未命中")
            return seg
        new = '<div class="grid2">\n ' + inner + "\n </div>"
        if outer:
            new += "\n" + outer
        return seg[:m_.start()] + new + seg[m_.end():]
    r.in_sect("s8", _s8)


def fill_ipo(r, ipo, report_type):
    if report_type != "招股书":
        r.re1(r" <!-- ══ 招股书专章.*?\n </div>\n\n(?= <!-- ══ S1 财务总览)", "", "drop.ipo")
        r.sub1(" {{IPO_NAV}}\n", "", "drop.ipo_nav")
        return
    r.sub1(" {{IPO_NAV}}", ' <a href="#ipo" title="IPO 发行、募投与期后核验">发行</a>', "ipo.nav")
    for key, field in (("IPO_ISSUE_TITLE", "issue_title"), ("IPO_PLAN_TITLE", "plan_title"),
                       ("IPO_INTERIM_TITLE", "interim_title"), ("IPO_EQUITY_TITLE", "equity_title"),
                       ("IPO_INTERIM_NOTE", "interim_note"), ("IPO_POST_NOTE", "post_note")):
        r.sub1("{{" + key + "}}", _E(ipo.get(field) or "未披露"), "ipo." + field)

    def _gap(n, text):
        return f'<tr><td colspan="{n}" class="txt">{_E(text)}</td></tr>'
    issue_rows = [
        f'<tr><td>{_E(x.get("item"))}</td><td>{_E(x.get("value"))} '
        f'<span class="badge disc">披露</span></td><td class="txt">{_E(x.get("note"))}</td></tr>'
        for x in ipo.get("issue_rows") or []
    ]
    plan_rows = [
        f'<tr><td>{_E(x.get("name"))}</td><td>{_E(x.get("total"))} '
        f'<span class="badge disc">披露</span></td><td>{_E(x.get("raised"))}</td>'
        f'<td class="txt">{_E(x.get("period"))}</td><td class="txt">{_E(x.get("capacity"))}；'
        f'{_E(x.get("benefit"))}</td></tr>'
        for x in ipo.get("plan_rows") or []
    ]
    interim_rows = [
        f'<tr><td>{_E(x.get("item"))}</td><td>{_E(x.get("cur"))} '
        f'<span class="badge disc">审阅</span></td><td>{_E(x.get("prev"))}</td>'
        f'<td>{_E(x.get("change"))} <span class="badge der">推算</span></td>'
        f'<td class="txt">{_E(x.get("scope"))}</td></tr>'
        for x in ipo.get("interim_rows") or []
    ]
    equity_rows = [
        f'<tr><td>{_E(x.get("holder"))}</td><td>{_E(x.get("pre"))} '
        f'<span class="badge disc">披露</span></td><td>{_E(x.get("post"))}</td></tr>'
        for x in ipo.get("equity_rows") or []
    ]
    post_rows = [
        f'<tr><td>{_E(x.get("item"))}</td><td>{_E(x.get("cur"))}</td><td>{_E(x.get("prev"))}</td>'
        f'<td>{_E(x.get("change"))}</td><td class="txt"><span class="badge disc">{_E(x.get("scope"))}</span></td></tr>'
        for x in ipo.get("post_rows") or []
    ]
    for key, rows, n, gap in (
        ("IPO_ISSUE_ROWS", issue_rows, 3, "发行方案未结构化披露"),
        ("IPO_PLAN_ROWS", plan_rows, 5, "募投项目未结构化披露"),
        ("IPO_INTERIM_ROWS", interim_rows, 5, "期后审阅数据未结构化披露"),
        ("IPO_EQUITY_ROWS", equity_rows, 3, "发行前后股权未结构化披露"),
        ("IPO_POST_ROWS", post_rows, 5, "无上市后实际数据，不作兑现核验"),
    ):
        r.sub1("{{" + key + "}}", "\n".join(rows) if rows else _gap(n, gap), "ipo." + key)


def drop_ipo_inapplicable(r):
    r.re1(r' <div class="sect">\n <div class="secthead" id="s6">.*?\n </div>\n\n(?= <!-- ══ S7)',
          ' <div class="sect">\n <div class="secthead" id="s6"><span class="no">06</span>'
          '<span class="t">股东结构</span><span class="line"></span><span class="tag">发行前后股权 · 招股书适用</span></div>\n'
          ' <div class="card"><div class="figtitle">股东户数与二级市场增减持：上市前不适用</div>'
          '<p class="lede">发行前后股权、控股股东与实控人控制比例见 <a href="#ipo">招股书专章</a>；'
          '不以招股书静态股东名册冒充定期报告的户数或交易趋势。</p>'
          '<div class="srcline">数据来源：招股说明书股本结构章节 · 股东户数/高管交易模块裁剪</div></div>\n </div>\n\n',
          "drop.ipo_s6")
    def _s7(seg):
        out = re.sub(r' <div class="card">\n <div class="figtitle">\{\{结论式：vs 一致预期.*?'
                     r'\n </div>\n(?= <!-- ◆ peers)',
                     ' <div class="card"><div class="figtitle">机构一致预期：上市前不适用</div>'
                     '<p class="lede">招股书无上市前券商一致预期；若已有上市后实际值，预测兑现核验见 '
                     '<a href="#ipo">招股书专章</a>，不与年度主表混算。</p>'
                     '<div class="srcline">数据来源：招股说明书及上市后公告 · 机构预期模块裁剪</div></div>\n',
                     seg, count=1, flags=re.S)
        if out == seg:
            r.miss.append("drop.ipo_expect: 一致预期卡锚未命中")
        return out
    r.in_sect("s7", _s7)


def drop_q4(r, report_type):
    if report_type == "年报":
        return  # 年报保留 Q4 卡，读数由 fill_s3 机械填充
    r.re1(r' <!-- ◆ Q4 卡（年报专属）：.*?\n <div class="card">\n <div class="figtitle">\{\{结论式：Q4 五项检验.*?\n </div>\n',
          "", "drop.q4")


def strip_comments(html):
    """剥交付物注释：head 区 /* */ 全剥（连尾换行）；行首 <!-- --> 整块连行删，
    单行 ══ 分区注释保留（剥 ◆/（P编号）后缀）；行内残余非分区注释剥文本；
    剥后连续空行压一行；script 区不动。"""
    head, sep, tail = html.partition("<script>")
    head = re.sub(r"[ ]*/\*.*?\*/\n?", "", head, flags=re.S)
    def _block(m_):
        inner = m_.group(1)
        if "══" in inner and "\n" not in inner:
            name = inner.split("══")[1].split("◆")[0].split("（")[0].strip()
            return f" <!-- ══ {name} ══ -->\n"
        return ""
    head = re.sub(r"(?m)^[ ]*<!--(.*?)-->\n?", _block, head, flags=re.S)
    head = re.sub(r"<!--(?![^>]*══)(.*?)-->", "", head, flags=re.S)
    head = re.sub(r"\n{3,}", "\n\n", head)
    return head + sep + tail


def main():
    ap = argparse.ArgumentParser(description="模板 + 槽位 JSON → 报告 HTML（判断槽残留 {{}} 孔）")
    ap.add_argument("json_path", type=Path, help="data.json 路径")
    ap.add_argument("--slots", type=Path, default=None, help="fillsheet.json（缺省同 stem）")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="输出路径（缺省 reports/{公司}-{代码}-{类型}-{期}-{日}.html）")
    args = ap.parse_args()

    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    data = json.loads(args.json_path.read_text(encoding="utf-8"))
    slots_path = args.slots or args.json_path.with_suffix("").with_name(
        args.json_path.stem + ".fillsheet.json")
    if not slots_path.exists():
        sys.exit(f"🔴 槽位 JSON 不存在：{slots_path}——先跑 calc.py --fill")
    slots = json.loads(slots_path.read_text(encoding="utf-8"))
    try:  # 新鲜度提醒：底稿比槽位新 → 可能改了 data.json 忘跑 --fill（WARN 不阻断）
        if args.json_path.stat().st_mtime > slots_path.stat().st_mtime + 1:
            print(f"🟡 提醒：底稿 {args.json_path.name} 比槽位 JSON 新——若刚改过底稿，"
                  f"请先重跑 calc.py --fill 再 render", file=sys.stderr)
    except OSError:
        pass
    if not TEMPLATE.exists():
        sys.exit(f"🔴 模板不存在：{TEMPLATE}")

    m = slots["meta"]
    r = R(TEMPLATE.read_text(encoding="utf-8"))
    drop_review(r, data)
    fill_review(r, slots.get("review") or {})
    drop_q4(r, m.get("report_type") or "")
    fill_js(r, slots["js"])
    fill_meta(r, m)
    fill_s1(r, slots.get("s1") or {}, m)
    fill_s2(r, slots.get("s2") or {})
    fill_s3(r, slots.get("s3") or {})
    fill_s4(r, slots.get("s4") or {})
    fill_s5(r, slots.get("s5") or {})
    fill_s6(r, slots.get("s6") or {})
    fill_s7(r, slots.get("s7") or {}, m)
    fill_s8(r, slots.get("s8") or {})
    fill_ipo(r, slots.get("ipo") or {}, m.get("report_type") or "")
    if m.get("report_type") == "招股书":
        drop_ipo_inapplicable(r)

    if r.miss:
        print("🔴 断锚清单（模板结构与锚配置不符，未产出）：")
        for x in r.miss:
            print(f"  · {x}")
        return 1

    html = strip_comments(r.h)
    holes = html.count("{{")
    out = args.out
    if out is None:
        code = (m.get("code") or "").split(".")[0]
        day = (m.get("analyst_date") or "").replace("-", "")
        name = f"{m.get('company')}-{code}-{m.get('report_type')}-{m.get('period_label')}-{day}.html"
        out = HERE.parent.parent / "reports" / name
    out.write_text(html, encoding="utf-8", newline="\n")  # 报告 HTML 行尾 LF（成品惯例）
    print(f"✅ 渲染完成：{out.name}（待填判断孔 {holes} 处——grep '{{' 定位；"
          f"机械面已填，填完孔跑 gate.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
