#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_html_text.py — 报告机检的「呈现文本族」检查（v0.0.19 从 check_html.py 拆出）

口径划分：本模块管「文字怎么呈现」——裸数字启发式、figtitle 文风、槽位长度、
缩写展开、桥图项数、归因标题复述、判定列、内部引用禁词、srcline 拼接、杜邦双卡
形态、分位白描映射、勾稽三态措辞、可见数字精度、断言计数自洽、数据缺口声明落点。
结构/硬规则类（占位符、外部资源、必备要素、锚点、章节形态、s2/s8/review、
dupont-stack 数据槽比对、T8 数字回验）留在 check_html.py / check_html_t8.py。

入口仍是 check_html.py；本模块不单独运行。
"""


import ast
import re

from check_html_common import (FAIL, WARN, OK, DETAIL_CAP, BADGE_RE,
                               line_of, snippet, has_number, _section_seg)


# ─────────────────────────── 2. 裸数字（启发式） ───────────────────────────

def _row_of(text, pos, end):
    a = text.rfind("<tr", 0, pos)
    b = text.find("</tr>", end)
    if a == -1 or b == -1:
        return text[pos:end]
    return text[a:b + 5]


def check_bare_numbers(text, rep, verbose, secs):
    hits = []  # (pos, kind, snippet)

    # a) <td>：key 数字表；.txt 列按模板约定是判定/解释/阈值/出处，排除
    for m in re.finditer(r"<td\b([^>]*)>(.*?)</td>", text, re.S):
        attrs, inner = m.group(1), m.group(2)
        cls = re.search(r'class="([^"]*)"', attrs)
        if cls and "txt" in cls.group(1).split():
            continue
        plain = re.sub(r"<[^>]+>", " ", inner)
        if not has_number(plain):
            continue
        if BADGE_RE.search(inner) or BADGE_RE.search(_row_of(text, m.start(), m.end())):
            continue
        hits.append((m.start(), "td", snippet(plain)))

    # b) KPI 卡：.v 是主读数，同卡内有徽章即算合格
    for m in re.finditer(r'<div class="kpi">(.*?)</div>\s*</div>', text, re.S):
        block = m.group(0)
        v = re.search(r'<div class="v">(.*?)</div>', block, re.S)
        if not v:
            continue
        plain = re.sub(r"<[^>]+>", " ", v.group(1))
        if not has_number(plain):
            continue
        if BADGE_RE.search(block):
            continue
        hits.append((m.start(), "kpi", snippet(plain)))

    # c) 图题：数字出现在图题里时，看标题下方一段内有没有徽章
    for m in re.finditer(r'<div class="figtitle"[^>]*>(.*?)</div>', text, re.S):
        plain = re.sub(r"<[^>]+>", " ", m.group(1))
        if not has_number(plain):
            continue
        nxt = text.find('class="figtitle"', m.end())
        window = text[m.start(): nxt if nxt != -1 else m.end() + 1200]
        if BADGE_RE.search(window):
            continue
        hits.append((m.start(), "figtitle", snippet(plain)))

    if not hits:
        rep.add(OK, "bare-number", "启发式：未发现无证据等级徽章的关键数字（不排除正文段落漏检）")
        return

    by_sect = {}
    for p, kind, snip in hits:
        by_sect.setdefault(secs.label(p), []).append((p, kind, snip))
    dist = " · ".join(f"{k} {len(v)}" for k, v in
                      sorted(by_sect.items(), key=lambda kv: -len(kv[1])))

    details = [f"第 {line_of(text, p)} 行 [{kind}] {secs.label(p)}：{snip}" for p, kind, snip in hits]
    if not verbose and len(details) > DETAIL_CAP:
        details = details[:DETAIL_CAP] + [f"…另有 {len(hits) - DETAIL_CAP} 处，用 --verbose 查看全部"]
    rep.add(WARN, "bare-number",
            f"启发式：检测到 {len(hits)} 处关键数字无置信度徽章（待人工确认）——分布：{dist}",
            details)


# ─────────────────────────── 11·五. figtitle 结论式（v0.0.7 读法层） ───────────────────────────

# figtitle 括号内的方法说明关键词：这类注记（年报必做/同类型滚动/降级为分部桥……）
# 应挪 srcline，标题写判断。只扫（全角括号）段——标题正文里的同类词（如「Q4 五项检验总判」）不误伤
FIGTITLE_METHOD_RE = re.compile(r'（[^）]*(?:必做|滚动|降级|检测|方法|口径说明|规则见)[^）]*）')


def check_figtitle_style(text, rep, secs):
    """figtitle 结论式（v0.0.7 读法层硬规则）：括号内含方法说明关键词 → 疑似描述式标题。
    启发式 WARN：清单导航类标题（异常线索追查）天然无结论，命中后人工确认即可。"""
    hits = []
    for m in re.finditer(r'<div class="figtitle"[^>]*>(.*?)</div>', text, re.S):
        plain = re.sub(r"<[^>]+>", "", m.group(1))
        if FIGTITLE_METHOD_RE.search(plain):
            hits.append((m.start(), snippet(plain)))
    if not hits:
        rep.add(OK, "figtitle-style", "figtitle 均为结论式（括号内未见方法说明注记）")
        return
    details = [f"第 {line_of(text, p)} 行 [{secs.label(p)}]：{s}" for p, s in hits]
    rep.add(WARN, "figtitle-style",
            f"{len(hits)} 处 figtitle 括号内疑似方法说明——结论式标题应写判断，方法注记挪 srcline",
            details[:DETAIL_CAP])


def check_slot_length(text, rep):
    """槽位长度契约（v0.0.9 L3，WARN 级宁宽勿严）：s1 四维比率表「评价」列
    （第一张 table.data 每行最后一个 td.txt）契约 ≤15 字注脚，>20 字 → WARN（15+5 容忍）。
    杜邦表在 s1 内排第二张、末列是归因长文本，不在检查范围——只测第一张表。"""
    seg = _section_seg(text, "s1")
    if seg is None:
        rep.add(WARN, "slot-length", "未找到财务总览章节（secthead id=\"s1\"），无法校验槽位长度契约")
        return
    m = re.search(r'<table class="data"[^>]*>(.*?)</table>', seg, re.S)
    if not m:
        rep.add(WARN, "slot-length", "s1 章未找到数据表，无法校验评价列契约")
        return
    bad = []
    for r in re.findall(r'<tr>(.*?)</tr>', m.group(1), re.S):
        if '<th' in r:
            continue
        td_txts = re.findall(r'<td[^>]*class="[^"]*txt[^"]*"[^>]*>(.*?)</td>', r, re.S)
        if not td_txts:
            continue
        cell = re.sub(r'<[^>]+>', '', td_txts[-1]).strip()
        cell = cell.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        if len(cell) > 20:
            bad.append(f"评价列注脚 {len(cell)} 字（契约 ≤15）：「{cell[:24]}…」")
    if bad:
        rep.add(WARN, "slot-length",
                f"s1 四维表 {len(bad)} 行评价列超契约长度（注脚应 ≤15 字，长解释挪 takeaway/srcline）",
                bad[:6])
    else:
        rep.add(OK, "slot-length", "s1 四维表评价列均在契约长度内（≤15 字注脚）")


# ─────────────────── 11·六. v0.0.12 读法层机检兜底（均 WARN 启发式） ───────────────────

# 缩写白名单：报告面向非专业读者，这些缩写首现必须有中文展开
# （SKILL.md Phase 8 读法层 v0.0.10 定规则；v0.0.12 补机检——中免 2026H1 漏 DFS/IR 的教训）
ABBREV_LIST = ["OCF", "EBITDA", "EBIT", "ROIC", "ROE", "DOL", "DFL",
               "DSO", "DIO", "DPO", "CCC", "KAM", "MD&A", "DFS", "IR", "PE", "PB"]


def check_abbrev(text, rep, secs):
    """缩写首现展开：白名单缩写的**首次出现**处必须带展开形态（±40 字窗口内判定）——
    ① 缩写（中文…） ② （缩写…中文…）且缩写在括号段开头 ③ 标签形态「三字以上中文名 + 缩写」。
    首现判定贴合 v0.0.10 纪律原文（首现展开），比「全文任一处展开」严格：
    中免 2026H1 的 DFS/IR 裸用能被抓住（「公司 IR 口径」仅两字邻接不算展开）。
    启发式 WARN：命中是「待人工确认」清单。"""
    masked = re.sub(r'<span class="badge[^"]*">.*?</span>',
                    lambda m: " " * (m.end() - m.start()), text, flags=re.S)
    # 标签等长替换（不删除）——保住长度与位置，行号/章节定位不漂移
    plain = re.sub(r"<[^>]+>", lambda m: " " * (m.end() - m.start()), masked)
    # {{}} 占位符等长屏蔽——占位符内的缩写（如 {{ROE}}）会被实数替换，不算真实出现
    plain = re.sub(r"\{\{.*?\}\}", lambda m: " " * (m.end() - m.start()), plain, flags=re.S)
    missing = []
    for ab in ABBREV_LIST:
        word = re.compile(rf"(?<![A-Za-z0-9&]){re.escape(ab)}(?![A-Za-z0-9])")
        m = word.search(plain)
        if not m:
            continue
        win = plain[max(0, m.start() - 40):m.end() + 40]
        expanded = (
            re.search(rf"(?<![A-Za-z0-9&]){re.escape(ab)}（[^）]*[一-鿿]", win)
            or re.search(rf"[一-鿿][一-鿿·]{{2,}}（\s*{re.escape(ab)}(?![A-Za-z0-9])", win)
            or re.search(rf"[一-鿿][一-鿿·]{{2,}} ?{re.escape(ab)}(?![A-Za-z0-9(（])", win)
        )
        if not expanded:
            missing.append(f"{ab}（第 {line_of(plain, m.start())} 行 [{secs.label(m.start())}]："
                           f"…{snippet(plain[max(0, m.start() - 12):m.end() + 12], 30)}…）")
    if missing:
        rep.add(WARN, "abbrev",
                f"{len(missing)} 个缩写首现未带中文展开（纪律：首现须「中文全称+缩写」）："
                f"{'、'.join(missing)}")
    else:
        rep.add(OK, "abbrev", "白名单缩写首现均带中文展开形态")


def check_ocf_bridge_shape(raw, rep):
    """OCF 调节桥项数纪律（v0.0.12）：调节柱 ≤8 根（不含净利润端点；约定 ≤6 + 容忍），
    「其他」桶 |Δ| 不得超 Σ|Δ|×30%（超则须拆出桶内最大项）。中免 2026H1 铺 11 项的教训。"""
    m = re.search(r'OCF_BRIDGE\s*=\s*(\[.*?\]);', raw, re.S)
    if not m:
        rep.add(OK, "ocf-bridge-shape", "无 OCF_BRIDGE 数据槽（章节缺省时正常）")
        return
    try:
        rows = ast.literal_eval(m.group(1))
    except (ValueError, SyntaxError):
        rep.add(WARN, "ocf-bridge-shape", "OCF_BRIDGE 数组解析失败——检查 JS 数组字面量语法")
        return
    items = rows[1:]
    bad = []
    if len(items) > 8:
        bad.append(f"调节柱 {len(items)} 根 > 8（约定 ≤6：|Δ|≥调节净额10% 或 ≥3亿 才单列，其余并入「其他」）")
    total = sum(abs(v) for _, v in items if isinstance(v, (int, float)))
    other = sum(abs(v) for name, v in items
                if isinstance(v, (int, float)) and "其他" in str(name))
    if total and other / total > 0.30:
        bad.append(f"「其他」桶占 Σ|Δ| 的 {other / total:.0%} > 30%——桶过大藏信息，拆出桶内最大项单列")
    if bad:
        rep.add(WARN, "ocf-bridge-shape", "OCF 桥项数纪律：" + "；".join(bad))
    else:
        rep.add(OK, "ocf-bridge-shape", f"OCF 桥调节柱 {len(items)} 根、其他桶占比合规")


# 归因类 figtitle 的判定词与前瞻词（v0.0.12：治「figtitle 复述表格数字」——
# 归因只是中间步骤，标题必须落到「能不能信 + 盯什么」）
FIGTITLE_ATTR_RE = re.compile(r"归因|桥|杜邦|ROE")
FIGTITLE_FWD_RE = re.compile(r"盯|验证|下期|关注|证伪|兑现|前瞻|看点")
FIGTITLE_PCT_RE = re.compile(r"[-+−]?\d+(?:\.\d+)?\s*(?:pct|%)")


def check_figtitle_attribution(text, rep, secs):
    """归因类 figtitle（含 归因/桥/杜邦/ROE）两条启发式：
    ① 缺前瞻词（盯/验证/下期/关注/证伪/兑现）→ 疑似只报归因没落裁决；
    ② 与紧随其后的表格共享 ≥2 个相同 pct 数字 → 疑似复述表格（数字只许在表格里）。"""
    hits = []
    for m in re.finditer(r'<div class="figtitle"[^>]*>(.*?)</div>', text, re.S):
        plain = re.sub(r"<[^>]+>", "", m.group(1))
        if not FIGTITLE_ATTR_RE.search(plain):
            continue
        reasons = []
        if not FIGTITLE_FWD_RE.search(plain):
            reasons.append("缺前瞻词（盯/验证/下期/关注/证伪/兑现）")
        nums = list(dict.fromkeys(n.replace(" ", "").replace("−", "-")
                                  for n in FIGTITLE_PCT_RE.findall(plain)))
        if len(nums) >= 2:
            tm = re.search(r"<table[^>]*>(.*?)</table>", text[m.end():], re.S)
            if tm:
                tplain = re.sub(r"<[^>]+>", "", tm.group(1)).replace(" ", "").replace("−", "-")
                # 边界感知等值比较：「1.2%」不许命中表格里的「11.2%」——子串匹配会把
                # 表内读数误判成「共享数字」（复述罪名叠错）
                shared = [n for n in nums
                          if re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", tplain)]
                if len(shared) >= 2:
                    reasons.append(f"与紧随表格共享 {len(shared)} 个数字（{'、'.join(shared[:4])}），疑似复述")
        if reasons:
            hits.append((m.start(), f"{snippet(plain)} —— {'；'.join(reasons)}"))
    if not hits:
        rep.add(OK, "figtitle-attribution", "归因类 figtitle 均有前瞻落点且未见表格复述")
        return
    details = [f"第 {line_of(text, p)} 行 [{secs.label(p)}]：{s}" for p, s in hits]
    rep.add(WARN, "figtitle-attribution",
            f"{len(hits)} 处归因类 figtitle 疑似只有归因没有裁决（四段式：方向→归因→含义→盯什么）",
            details[:DETAIL_CAP])


def check_inspection_verdict(text, rep):
    """检验类卡片判定列（v0.0.12）：s7 内 figtitle 含「检验/期后」的表，数据行须带
    ✅/⚠️/❌ 判定徽标或「—（披露项）」——扫颜色即知结果，治「全文字缺重点」。
    v0.0.15 扩展 s5（在建工程/产能表，补判定列纪律漏网点）。"""
    bad = []
    seg = _section_seg(text, "s7")
    if seg is None:
        rep.add(WARN, "inspection-verdict", "未找到外部校验章（secthead id=\"s7\"），无法校验判定列")
    else:
        for m in re.finditer(r'<div class="figtitle"[^>]*>(.*?)</div>', seg, re.S):
            plain = re.sub(r"<[^>]+>", "", m.group(1))
            if not re.search(r"检验|期后", plain):
                continue
            tm = re.search(r"<table[^>]*>(.*?)</table>", seg[m.end():], re.S)
            if not tm:
                continue
            rows = [r for r in re.findall(r"<tr>(.*?)</tr>", tm.group(1), re.S) if "<th" not in r]
            for r in rows:
                cell = re.sub(r"<[^>]+>", "", r)
                if not re.search(r"✅|⚠️|❌|—（披露项）|—\(披露项\)", cell):
                    first = re.search(r"<td[^>]*>(.*?)</td>", r, re.S)
                    name = re.sub(r"<[^>]+>", "", first.group(1)).strip()[:16] if first else "?"
                    bad.append(f"「{plain[:14]}…」表行「{name}」无判定徽标")
    seg5 = _section_seg(text, "s5")
    if seg5 is not None:
        for tm in re.finditer(r'<table class="data"[^>]*>(.*?)</table>', seg5, re.S):
            head = re.search(r'<tr>(.*?)</tr>', tm.group(1), re.S)
            if not head or not re.search(r"判定", head.group(1)):
                continue
            rows = [r for r in re.findall(r"<tr>(.*?)</tr>", tm.group(1), re.S) if "<th" not in r]
            for r in rows:
                cell = re.sub(r"<[^>]+>", "", r)
                if not re.search(r"✅|⚠️|❌", cell):
                    first = re.search(r"<td[^>]*>(.*?)</td>", r, re.S)
                    name = re.sub(r"<[^>]+>", "", first.group(1)).strip()[:16] if first else "?"
                    bad.append(f"s5 表行「{name}」无判定徽标（在建/产能表判定列纪律 v0.0.15）")
    if bad:
        rep.add(WARN, "inspection-verdict",
                f"{len(bad)} 行检验/期后/在建表缺判定列（✅ 通过 / ⚠️ 注意 / ❌ 异常 / — 披露项）",
                bad[:DETAIL_CAP])
    else:
        rep.add(OK, "inspection-verdict", "检验/期后/在建类表格数据行均带判定徽标")


# ─────────────────── v0.0.18：内部过程引用禁词（FAIL）───────────────────

# 报告面向报告读者：底稿文件名 / 方法库路径 / 脚本名 / 字段路径 / 技能版本号 / 取数工具
# 函数名都是制作过程产物，不是「数据来源」——可见文本一律禁现（注释/style/script 已屏蔽）。
# 万华轮教训：模板 srcline 曾把「见 data.json signals 块」「references/articulation.md」
# 「derived.threshold_check（calc.py 复算）」「v0.0.15 设定待校准」直接写给读者。
INTERNAL_REF_RE = re.compile(
    r"data\.json|references/|derived\.|calc\.py|check_html|fillsheet|v0\.\d+\.\d+|mx_[a-z_]+")


def check_internal_ref(body, rep, secs):
    hits = [(m.start(), m.group(0)) for m in INTERNAL_REF_RE.finditer(body)]
    if not hits:
        rep.add(OK, "internal-ref", "可见文本未出现内部过程引用（底稿/方法库/脚本/字段路径/版本号/工具函数名）")
        return
    by_sect = {}
    for p, w in hits:
        by_sect.setdefault(secs.label(p), []).append(w)
    dist = " · ".join(f"{k} {len(v)}" for k, v in sorted(by_sect.items(), key=lambda kv: -len(kv[1])))
    details = [f"第 {line_of(body, p)} 行 [{secs.label(p)}]「{w}」：…{snippet(body[max(0, p - 20):p + 30], 50)}…"
               for p, w in hits[:DETAIL_CAP]]
    rep.add(FAIL, "internal-ref",
            f"可见文本出现内部过程引用 {len(hits)} 处（分布：{dist}）——数据来源只写对外口径"
            f"（定期报告/公告/Tushare/东方财富），过程产物不进报告",
            details)


def check_srcline_dup(body, rep):
    """srcline 拼接纪律（v0.0.18，FAIL）：① 禁嵌套（srcline div 内又开一条）；
    ② 相邻 srcline 组 ≤2 条（来源条+图例条为合法双条形态）；③ 全文禁相同文本重复。
    万华轮 713 行嵌套重复、563 行相邻拼接的教训。"""
    bad = []
    for m in re.finditer(r'<div class="srcline"[^>]*>((?:(?!</div>).){0,800}?)<div class="srcline"',
                         body, re.S):
        bad.append(f"第 {line_of(body, m.start())} 行：srcline 内嵌套另一条 srcline（拼接缺陷）")
    spans = [(m.start(), m.end())
             for m in re.finditer(r'<div class="srcline"[^>]*>.*?</div>', body, re.S)]
    chain = 1
    for i in range(1, len(spans)):
        if re.fullmatch(r"\s*", body[spans[i - 1][1]:spans[i][0]]):
            chain += 1
            if chain > 2:
                bad.append(f"第 {line_of(body, spans[i][0])} 行：相邻 srcline 超过 2 条"
                           f"（每卡至多 1 条来源 + 1 条图例）")
        else:
            chain = 1
    seen = {}
    for p, e in spans:
        t = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", body[p:e]))
        if len(t) >= 12 and t in seen:
            bad.append(f"第 {line_of(body, p)} 行与第 {line_of(body, seen[t])} 行：srcline 文本完全重复")
        seen.setdefault(t, p)
    if bad:
        rep.add(FAIL, "srcline-dup", f"srcline 拼接纪律违规 {len(bad)} 处（禁嵌套/相邻>2/文本重复）",
                bad[:DETAIL_CAP])
    else:
        rep.add(OK, "srcline-dup", "srcline 无嵌套、相邻组 ≤2 条、无重复文本")


# ─────────────────── v0.0.15：S1 杜邦双卡与证据表形态（WARN 启发式） ───────────────────

def _table_containing(seg, kw):
    """段内首个正文含关键词 kw 的 <table> 块（模板匹配用）。
    假设：kw 在该段内只出现于目标表（当前 s1 内「五年位置」「净现比」唯一）——
    未来版式让关键词出现在别的表时会错配，届时改结构锚点。"""
    m = re.search(rf'<table[^>]*>(?:(?!</table>).)*{re.escape(kw)}(.*?)</table>', seg, re.S)
    return m


# 分位白描读数形态（v0.0.19 起 X/5：五年从高到低第 X；旧措辞「5 期中第 2 高」族退役）
PCTILE_TEXT_RE = re.compile(r"(?<![\d/])[1-5]/5(?![\d/])")
PCTILE_OLD_RE = re.compile(r"5 期最低|5 期中第 2 低|5 期中居中|5 期中第 2 高|5 期最高")


def check_s1_v15_shape(text, rep):
    """S1 杜邦双卡形态：① 杜邦下钻子行 ≤3（每因子 ≤1 行密度纪律）；
    ② 因子分位表（表头含「五年位置」）数据行必须带白描读数（v0.0.19 起 X/5 从高到低；
       hist<3 合法降级的「分位不可用/分位需/分位降级」声明行豁免，v0.1.2 蜜雪实证），
       旧措辞「5 期中第 2 高」族与「上限区/下限区/常态区」档位标签均禁贴，
       且表内禁用「显著」统计措辞（n=5 位置读数非统计分位）；
    ③ 现金时序证据（v0.0.20 起 svg#ncrline 双折线图，旧版式为净现比表格）与周期定位判词
       （v0.0.21 起为趋势图卡 .wv 大字声明行；v0.0.20 形态挂 srcline、更旧为阶段判定行——
       三形态均认「周期定位：」字样）存在——降级须有声明；
       非周期股填「非周期行业」声明。
    注意：对 v0.0.19 前的存量旧版式报告重跑本检查必出 ②③ WARN——纪律 7 不重出旧报告，
    该 WARN 属预期，勿追溯修旧报告。"""
    seg = _section_seg(text, "s1")
    if seg is None:
        rep.add(WARN, "s1-v15-shape", "未找到财务总览章（secthead id=\"s1\"），无法校验杜邦双卡形态")
        return
    bad = []
    drills = re.findall(r'<tr class="drillrow">', seg)
    if len(drills) > 3:
        bad.append(f"杜邦下钻子行 {len(drills)} 行 >3——每因子 ≤1 行（判断只在 figtitle/takeaway）")
    tm = _table_containing(seg, "五年位置")
    if tm:
        rows = [r for r in re.findall(r"<tr>(.*?)</tr>", tm.group(1), re.S) if "<th" not in r]
        # 分位降级声明行豁免（v0.1.2，蜜雪实证）：hist<3 期合法降级时行内写「分位不可用/
        # 分位需 ≥3 期/分位卡降级」即合规形态，不是缺白描
        _deg = re.compile(r"分位不可用|分位需|分位卡?降级")
        live = [r for r in rows if not _deg.search(re.sub(r"<[^>]+>", "", r))]
        nob = sum(1 for r in live if not PCTILE_TEXT_RE.search(r))
        if nob:
            bad.append(f"因子分位表 {nob}/{len(live)} 行缺白描读数"
                       f"（X/5：五年从高到低第 X，v0.0.19；降级声明行已豁免）")
        if PCTILE_OLD_RE.search(tm.group(0)):
            bad.append("因子分位表仍用旧白描措辞「5 期中第 2 高」族——v0.0.19 起改 X/5 读数")
        if re.search(r"上限区|下限区|常态区", tm.group(0)):
            bad.append("因子分位表仍贴「上限区/下限区/常态区」档位标签——v0.0.18 起改白描读数")
        if re.search(r"显著", tm.group(0)):
            bad.append("因子分位表内出现「显著」——n=5 位置读数禁用统计措辞")
    has_cash_ev = "ncrline" in seg or _table_containing(seg, "净现比")
    if not has_cash_ev and "现金含量证据不足" not in seg:
        bad.append("s1 未见现金时序折线图（svg#ncrline）或现金时序表，也无「现金含量证据不足」降级声明")
    if "周期定位：" not in seg and "阶段判定" not in seg and "非周期" not in seg:
        bad.append("s1 未见周期定位判词声明行（「周期定位：」，v0.0.21 起 .wv 大字置顶趋势图卡）"
                   "或阶段判定行，也无「非周期」声明")
    if bad:
        rep.add(WARN, "s1-v15-shape", f"s1 杜邦双卡/证据表形态 {len(bad)} 处待确认", bad[:6])
    else:
        rep.add(OK, "s1-v15-shape",
                "s1 杜邦双卡形态合规（下钻子行 ≤3、分位白描读数、现金/周期证据在位）")


# v0.0.19 分位白描映射：(rank−1)/(n−1)，n=5 离散步长 0.25 → X/5（五年从高到低第 X）。
# 与 calc_models.py PCTILE_LABEL 双写互指（跨家族 import 会造成 calc↔check_html 耦合，
# 故保持双写 + 回归一致性断言锁契约，改动必须同步）
PCTILE_LABEL = {0.0: "5/5", 0.25: "4/5", 0.5: "3/5", 0.75: "2/5", 1.0: "1/5"}


def check_percentile_map(body, data, rep):
    """因子分位白描读数 ↔ derived.dupont5y.percentile 一致性（v0.0.18 起 FAIL，仅 --json；
    v0.0.19 起读数改 X/5 从高到低）：s1「五年位置」表三因子行必须出现映射读数
    （0→5/5 / .25→4/5 / .5→3/5 / .75→2/5 / 1→1/5），且不得再贴「上限区/下限区/常态区」
    档位标签或旧措辞「5 期中第 2 高」族。
    旧版式存量报告仍贴旧标签会 FAIL——纪律 7 不追溯，属预期（运维速查）。"""
    pct = ((data.get("derived") or {}).get("dupont5y") or {}).get("percentile") or {}
    if all(v is None for v in pct.values()):
        rep.add(OK, "percentile-map", "derived.dupont5y.percentile 未填（hist 不足降级时正常），跳过白描校验")
        return
    seg = _section_seg(body, "s1")
    if seg is None:
        return  # 缺章由 s1-v15-shape 报告
    tm = _table_containing(seg, "五年位置")
    if not tm:
        rep.add(FAIL, "percentile-map", "json 有分位数据但 s1 未见「五年位置」表")
        return
    tbl = tm.group(0)
    bad = []
    for fname, key in (("净利率", "net_margin"), ("总资产周转率", "asset_turnover"),
                       ("权益乘数", "equity_multiplier")):
        v = pct.get(key)
        if v is None:
            continue
        row = re.search(rf"<tr>(?:(?!</tr>).)*{fname}.*?</tr>", tbl, re.S)
        if not row:
            bad.append(f"分位表缺「{fname}」行")
            continue
        label = PCTILE_LABEL.get(round(v, 2))
        if label is None:
            continue  # 非 n=5 步长值（hist≠5 期）不校验映射，由人工核对
        if label not in row.group(0):
            bad.append(f"「{fname}」分位 {v:g} 应标「{label}」，行内未见（白描映射 X/5，v0.0.19）")
        if re.search(r"上限区|下限区|常态区", row.group(0)):
            bad.append(f"「{fname}」行仍贴档位标签（上限区/下限区/常态区）——v0.0.18 起改白描读数")
    if bad:
        rep.add(FAIL, "percentile-map", "因子分位白描读数与 derived.dupont5y.percentile 不符："
                                        + "；".join(bad[:5]))
    else:
        rep.add(OK, "percentile-map", "因子分位白描读数与 derived.dupont5y.percentile 映射一致")


# ─────────────────── v0.0.19：三条新规则（美的轮反馈驱动） ───────────────────

def check_recon_label(body, rep):
    """勾稽三态措辞（v0.0.19，WARN）：报告徽章用短式「闭合 / 可解释 / 无法解释」——
    旧长标签「可解释偏差 / 无法解释偏差」属 v0.0.18 前写法，提示改写。
    存量旧报告命中属预期（纪律 7 不追溯）。"""
    hits = [m.start() for m in re.finditer(r"无法解释偏差|可解释偏差", body)]
    if not hits:
        rep.add(OK, "recon-label", "勾稽三态徽章为短式（闭合 / 可解释 / 无法解释）")
        return
    details = [f"第 {line_of(body, p)} 行：…{snippet(body[max(0, p - 15):p + 12], 30)}…"
               for p in hits[:DETAIL_CAP]]
    rep.add(WARN, "recon-label",
            f"勾稽三态旧长标签「…偏差」{len(hits)} 处——v0.0.19 起徽章用短式「可解释 / 无法解释」",
            details)


# 可见数字精度：≥3 位小数才命中；版本号（0.0.18）/日期（2026.09.30）形态不会匹配
DECIMAL_RE = re.compile(r"\d+\.\d{3,}")


def check_decimal_places(body, rep):
    """可见数字精度纪律（v0.0.19，WARN 启发式）：可见文本出现 ≥3 位小数——呈现层最多
    两位小数（pct 效应值一位），原始精度留底稿不进报告。srcline 已屏蔽不算。
    美的 2026H1 教训：五年趋势图收入柱顶 1826.61009 五位小数直接上桌。
    存量旧报告命中属预期（纪律 7 不追溯）。"""
    masked = re.sub(r'<div class="srcline"[^>]*>.*?</div>',
                    lambda m: " " * (m.end() - m.start()), body, flags=re.S)
    hits = [(m.start(), m.group(0)) for m in DECIMAL_RE.finditer(masked)]
    if not hits:
        rep.add(OK, "decimal-places", "可见数字均在两位小数以内（srcline 已屏蔽）")
        return
    details = [f"第 {line_of(body, p)} 行「{w}」：…{snippet(body[max(0, p - 15):p + 25], 40)}…"
               for p, w in hits[:DETAIL_CAP]]
    rep.add(WARN, "decimal-places",
            f"可见文本 {len(hits)} 处数字超两位小数——呈现层 ≤2 位（pct 效应值 1 位），原始精度留底稿",
            details)


def check_assertion_counts(body, data, rep):
    """断言验证矩阵算术自洽（v0.0.19，FAIL）：s4 figtitle「N 条断言：a 通过 / b 不成立 /
    c 无法验证」必须 a+b+c=N，且与紧随表格内三态徽章（✅/❌/❓）个数一致；
    --json 时再与底稿 assertions 块三态计数比对。
    美的 2026H1 教训：figtitle「10 条：8 通过 / 1 不成立 / 2 无法验证」——8+1+2=11≠10
    且表内实际 7 通过，纯笔误当时无任何门禁拦截。
    表内计数按 ✅/❌/❓ 表情个数——模板约定这三个表情只出现在三态徽章里。"""
    seg = _section_seg(body, "s4")
    if seg is None:
        rep.add(OK, "assertion-count", "无 s4 章（报告类型裁剪时正常），断言计数校验跳过")
        return
    ft = None
    for m in re.finditer(r'<div class="figtitle"[^>]*>(.*?)</div>', seg, re.S):
        plain = re.sub(r"<[^>]+>", "", m.group(1))
        if "{{" in plain:
            continue  # 模板未填充槽位
        if "断言" in plain and re.search(r"通过|不成立|无法验证", plain):
            ft = (m, plain)
            break
    if ft is None:
        rep.add(WARN, "assertion-count",
                "s4 未找到带三态计数的断言 figtitle（应为「N 条断言：a 通过 / b 不成立 / c 无法验证」形态）")
        return
    m, plain = ft
    # 总条数取三态计数关键词之前最后一个「N 条」——figtitle 前置「复盘 3 条上期断言」
    # 类短语时首个「N 条」不是本期总数（对抗评审探针实证的误报面）
    anchor = re.search(r"通过|不成立|无法验证", plain)
    totals = re.findall(r"(\d+)\s*条", plain[:anchor.start()] if anchor else plain)
    total = totals[-1] if totals else None
    got = [re.search(rf"(\d+)\s*{kw}", plain) for kw in ("通过", "不成立", "无法验证")]
    if any(g is None for g in got):
        rep.add(WARN, "assertion-count",
                f"断言 figtitle 三态计数不完整（「{snippet(plain)}」）——写全 a 通过 / b 不成立 / c 无法验证")
        return
    a_n, b_n, c_n = (int(g.group(1)) for g in got)
    bad = []
    if total:
        n = int(total)
        if a_n + b_n + c_n != n:
            bad.append(f"figtitle「{n} 条」但三态计数 {a_n}+{b_n}+{c_n}={a_n + b_n + c_n}——算术不自洽")
    tm = re.search(r"<table[^>]*>(.*?)</table>", seg[m.end():], re.S)
    if tm:
        tbl = tm.group(1)
        ga, gb, gc = tbl.count("✅"), tbl.count("❌"), tbl.count("❓")
        if (ga, gb, gc) != (a_n, b_n, c_n):
            bad.append(f"figtitle 计数 {a_n}/{b_n}/{c_n} 与表内徽章 ✅{ga}/❌{gb}/❓{gc} 不一致")
    if data is not None:
        arr = data.get("assertions") or []
        if arr:
            ja = sum(1 for x in arr if isinstance(x, dict) and x.get("verdict") == "通过")
            jb = sum(1 for x in arr if isinstance(x, dict) and x.get("verdict") == "不成立")
            jc = sum(1 for x in arr if isinstance(x, dict) and x.get("verdict") == "无法验证")
            if (ja, jb, jc) != (a_n, b_n, c_n):
                bad.append(f"figtitle 计数 {a_n}/{b_n}/{c_n} 与底稿断言 {ja}/{jb}/{jc} 不一致")
    if bad:
        rep.add(FAIL, "assertion-count", "断言验证矩阵计数不自洽：" + "；".join(bad[:3]))
    else:
        rep.add(OK, "assertion-count",
                f"断言验证矩阵计数自洽（{a_n} 通过 / {b_n} 不成立 / {c_n} 无法验证）")


def check_gap_declaration(body, rep):
    """数据缺口声明集中落点（v0.0.21，FAIL）：s4 章出现 ❓（无法验证）徽章时，
    章内必须存在「数据缺口声明」行（模板表下 srcline 槽位），❓ 断言逐条写明缺什么数据。
    text-mining.md 第七节早要求「❓ 条目必须同时出现在数据缺口声明」，但模板无集中落点、
    无机检——美的/卫星 2026H1 两份报告均缺（规范与执行脱节实证，卫星复核轮遗留项）。
    无 s4 章（报告类型裁剪）或 ❓=0 时跳过。❓ 计数按表情个数——模板约定 ✅/❌/❓
    只出现在三态徽章里（与 assertion-count 同一约定）。"""
    seg = _section_seg(body, "s4")
    if seg is None:
        rep.add(OK, "gap-declaration", "无 s4 章（报告类型裁剪时正常），数据缺口声明校验跳过")
        return
    tm = list(re.finditer(r"<table[^>]*>(.*?)</table>", seg, re.S))
    # ❓ 只数表格内徽章（s4 可能有多张表——宣称方向/断言矩阵/变动未解释，声明行与
    # takeaway 的 ❓ 字样不计入）
    n_q = sum(m.group(1).count("❓") for m in tm)
    if n_q == 0:
        rep.add(OK, "gap-declaration", "s4 无 ❓ 断言，数据缺口声明行可省")
        return
    if "数据缺口" not in seg:
        rep.add(FAIL, "gap-declaration",
                f"s4 有 {n_q} 处 ❓ 断言但未见「数据缺口声明」行——❓ 须逐条写明缺什么数据"
                "（text-mining.md 第七节呈现规范 2）")
        return
    # 逐条覆盖：每个含 ❓ 的表行首格文本前 10 字必须出现在声明行文本里——
    # 「声明行存在但只写了一半」不算落实（规范与执行脱节以一半形式重现的口子）
    decl = re.sub(r"<[^>]+>", "", "".join(
        re.findall(r'<div class="srcline"[^>]*>(.*?)</div>', seg, re.S)))
    missing_rows = []
    for m in tm:
        for r in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S):
            if "❓" not in r:
                continue
            first = re.search(r"<td[^>]*>(.*?)</td>", r, re.S)
            key = re.sub(r"<[^>]+>", "", first.group(1)).strip()[:10] if first else ""
            if key and key not in decl:
                missing_rows.append(key)
    if missing_rows:
        rep.add(FAIL, "gap-declaration",
                f"数据缺口声明行在位但未逐条覆盖 {len(missing_rows)} 条 ❓ 断言"
                f"（{'、'.join(missing_rows[:5])}）——❓ 须逐条写明缺什么数据"
                "（text-mining.md 第七节呈现规范 2）")
    else:
        rep.add(OK, "gap-declaration", f"s4 ❓ 断言 {n_q} 处，数据缺口声明行在位且逐条覆盖")
