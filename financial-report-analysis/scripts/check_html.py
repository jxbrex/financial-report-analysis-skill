#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_html.py — financial-report-analysis 的报告机检门禁（HTML 层）

calc.py 只校验数据层（data.json）；报告 HTML 层此前没有任何机器校验入口。
本脚本补这个缺口：在交付前扫一遍最终 HTML，挡住「占位符没填完」「违反模板
硬规则」「必备章节缺失」这类硬伤，并把可疑之处列成待人工确认清单。

用法：
    python scripts/check_html.py reports/xxx.html [--verbose] [--warn-only] [--strict]

退出码：
    0 = 通过
    1 = 有 FAIL
    默认仅 FAIL 影响退出码（与 calc.py 一致）；--strict 让 WARN 也判失败；
    --warn-only 转纯提示模式：任何发现（含 FAIL）都不影响退出码，仅打印清单。

十一类检查（★ = 启发式，有误报/漏报，输出「待人工确认」而非断言错误）：
  1. placeholder  [FAIL] 未替换的 {{占位}}。HTML 注释内的不算——模板的
                  「◆ SLOT」注释里常写示例占位符，那是说明文字不是漏填；
                  <style>/<script> 内的也不算（CSS 里 `…1fr}}` 是合法语法，
                  不排除会把成片 CSS 误报成漏填）。
  2. bare-number  [WARN] ★ 关键数字没有挂证据等级徽章（.badge.disc/der/est）。
  3. srcline      [WARN] 每张 <table class="data"> 之后缺 .srcline 数据来源标注。
  4. hardrule     [FAIL] 外部资源（<link href="http… / <script src="http… /
                  @import / @font-face）、渐变、暗色背景、投影。样式类判据只扫
                  <style> 块与 inline style，避免误伤正文里出现的同名词。
  5. required     [FAIL] 页脚免责声明「不构成投资建议」、下期跟踪清单。
  6. sectnum      [WARN] 章节编号（.secthead .no）连续性——跳号/重号/倒退。
  7. anchor       [WARN] 悬空页内锚点（href="#x" 找不到 id="x"）；以及章节
                  secthead 完全没有 id（模板约定 s0~s8，缺了锚点体系就失效）。
  8~10. s2-shape  [WARN] 排雷章瘦身形态（secthead id="s2" 起至下一 secthead 止；
                  排雷章瘦身定案见修订计划 v0.2.0，三条均为 WARN）：
    8. 反向可见行：「badge rev」出现 >0——反向未触发应并入未触发汇总行，
       不应保留可见行；
    9. 未触发逐条行：「badge g」出现 >1——未触发不应逐条展开（汇总 total 行
       可能含 g，留 1 容忍；宁可少报不误报）；
    10. 观察行 >6：观察徽章「🟡」出现 >6——观察两行形态（担心→本案，v0.0.7）、
       上限 6 条，超出并入汇总（只数 🟡 开头徽章，勾稽表 ⚠️ 不计入）。
  11. figtitle-style [WARN] ★ 结论式标题（v0.0.7 读法层）：figtitle 括号内含方法
                  说明关键词（必做/滚动/降级/检测/方法/口径说明/规则见）→ 疑似
                  描述式标题，应改写为结论式、方法注记挪 srcline。

启发式检查的边界（诚实声明，改判据前先读这段）：
  · bare-number 的判据是：在 <td> / KPI 卡 .v / .figtitle 里出现「3 位以上数字
    或带 %/亿/万/倍 单位的数字」，且该单元格与其所在行都没有 disc/der/est 徽章。
    它必然有误差：
      - 正文段落（<p>、<li>）里的数字不纳入检查——无法可靠区分「关键数字主张」
        与「叙述性描述」，纳入会让误报淹没信号；
      - class 含 .txt 的单元格被排除。模板把「判定 / 解释 / 阈值 / 出处」列统一
        标 .txt，这些列的数字是过程性或限定性内容（如阈值「>40%」），不是需要
        证据徽章的关键数字主张。实测中这一条救掉最多误报；
      - 4 位年份（2025 年报 / 2025FY / 2024 末）豁免，否则数据表的期次标签会被
        成片误报；
      - 判定粒度是「行」：同一行任一单元格挂了徽章即算整行合格，行内其他裸数字
        可能被漏掉；
      - 表格里天然就是数字，未必每个都需要徽章——所以输出是清单，不是结论。
  · srcline：判据是「本表结束后、下一张 <table> 或下一章 secthead 之前，是否出现
    .srcline」。同一个卡片里多张表共用一个来源标注时会漏报。
  · sectnum / anchor：纯结构匹配，不看语义；编号写汉字或罗马数字的章节会被跳过。
  · hardrule 的暗色判据只看 background:#0xx/#1xx/#2xx 这类写法，rgb() 形式的深色
    与 var() 变量不纳入；反过来 #2 打头的中色（如 #2b5a8f）可能误报。
  · 页内锚点只检查 #id 形式，不检查 JS getElementById 的 id。
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Windows 控制台默认 GBK，emoji 与中文会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

FAIL, WARN, OK = "FAIL", "WARN", "OK"
ICON = {FAIL: "🔴", WARN: "🟡", OK: "✅"}

# 单次运行最多打印多少条明细（--verbose 全打）
DETAIL_CAP = 20

# 数字型内容：3 位以上数字，或带 %/亿/万/倍 单位的数字
NUM_RE = re.compile(r"\d{3,}|\d+(?:\.\d+)?\s*(?:%|亿|万|倍)")
# 期次标签豁免：2025 年报 / 2025FY / 2024 末 / 2024H1 —— 是坐标不是主张
YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*(?:年|末|FY|H[12]|Q[1-4]|年报|半年报|季报)[-—/]?")
# 证据等级徽章
BADGE_RE = re.compile(r'class="[^"]*\bbadge\b[^"]*\b(?:disc|der|est)\b')


class Report:
    def __init__(self):
        self.rows = []  # (level, code, msg, details:list[str])

    def add(self, level, code, msg, details=None):
        self.rows.append((level, code, msg, details or []))

    def counts(self):
        c = {FAIL: 0, WARN: 0, OK: 0}
        for lv, _, _, _ in self.rows:
            c[lv] += 1
        return c


# ─────────────────────────── 文本处理助手 ───────────────────────────

def mask_ranges(text, ranges):
    """把指定区间内的字符换成空格（保留换行），长度不变 → 行号仍可复用。"""
    if not ranges:
        return text
    chars = list(text)
    for a, b in ranges:
        for i in range(a, min(b, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def tag_ranges(text, tag):
    """<tag …>…</tag> 的区间；有开无闭则兜到文件尾。"""
    out = []
    for m in re.finditer(rf"<{tag}\b[^>]*>", text, re.I):
        end = re.search(rf"</{tag}\s*>", text[m.end():], re.I)
        out.append((m.start(), m.end() + end.end() if end else len(text)))
    return out


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def snippet(s, n=70):
    s = " ".join(s.split())
    return s[:n] + "…" if len(s) > n else s


def has_number(plain):
    """文本里是否有「非期次标签」的数字型内容。"""
    for m in NUM_RE.finditer(plain):
        if YEAR_RE.match(plain, m.start()):
            continue
        return True
    return False


class Sections:
    """章节索引：按位置定位某处属于哪一章，用于给告警标注所在章节。"""

    def __init__(self, text):
        self.heads = []
        for m in re.finditer(r'<div class="secthead"[^>]*>(.*?)</div>', text, re.S):
            no = re.search(r'<span class="no">(.*?)</span>', m.group(1), re.S)
            t = re.search(r'<span class="t">(.*?)</span>', m.group(1), re.S)
            self.heads.append((m.start(),
                               no.group(1).strip() if no else "",
                               t.group(1).strip() if t else ""))

    def label(self, pos):
        cur = None
        for p, no, t in self.heads:
            if p <= pos:
                cur = (no, t)
            else:
                break
        if not cur:
            return "报告头"
        return f"{cur[0]} {cur[1]}".strip() or "报告头"

    def numbers(self):
        return [int(no) for _, no, _ in self.heads if no.isdigit()]


# ─────────────────────────── 1. 占位符 ───────────────────────────

def check_placeholders(raw, visible, rep, verbose):
    """raw=原文（只用于取行号）；visible=注释/样式/脚本均已屏蔽的等长文本。"""
    placements = re.finditer(r"\{\{", visible)
    hits, spans = [], []
    unclosed = 0
    for m in placements:
        end = visible.find("}}", m.end())
        if end != -1 and end - m.end() <= 200:
            spans.append((m.start(), end + 2))
            hits.append((m.start(), snippet(visible[m.start():end + 2])))
        else:
            unclosed += 1
            hits.append((m.start(), snippet(visible[m.start():m.start() + 40]) + "（未见配对 }}）"))

    # 正文里残留的孤立 }}
    for m in re.finditer(r"\}\}", visible):
        if not any(a <= m.start() < b for a, b in spans):
            hits.append((m.start(), snippet(visible[max(0, m.start() - 30):m.start() + 2]) + "（孤立 }}）"))

    if not hits:
        rep.add(OK, "placeholder", "未发现 {{占位}} 残留（注释与 <style>/<script> 内的说明性示例已按约定排除）")
        return
    details = [f"第 {line_of(raw, p)} 行：{s}" for p, s in hits]
    if not verbose and len(details) > DETAIL_CAP:
        rest = len(details) - DETAIL_CAP
        details = details[:DETAIL_CAP] + [f"…另有 {rest} 处，用 --verbose 查看全部"]
    rep.add(FAIL, "placeholder", f"未替换占位符 {len(hits)} 处（注释与 <style>/<script> 外）"
                                 + (f"，其中 {unclosed} 处未见配对 }}" if unclosed else ""), details)


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


# ─────────────────────────── 3. 数据来源标注 ───────────────────────────

def check_srcline(text, rep, verbose, secs):
    tables = [(m.start(), m.end()) for m in re.finditer(r'<table class="data"', text)]
    missing = []
    for start, end in tables:
        stop = len(text)
        for cand in (text.find('<table class="data"', end),
                     text.find('class="secthead"', end)):
            if cand != -1:
                stop = min(stop, cand)
        if re.search(r'class="srcline"', text[end:stop]):
            continue
        missing.append(start)
    if not tables:
        rep.add(WARN, "srcline", "全文未找到 <table class=\"data\">——报告结构可能不符合模板")
        return
    if not missing:
        rep.add(OK, "srcline", f"{len(tables)} 张数据表均带 .srcline 数据来源标注")
        return
    details = [f"第 {line_of(text, p)} 行：{secs.label(p)} 的数据表缺 .srcline"
               for p in missing]
    if not verbose and len(details) > DETAIL_CAP:
        details = details[:DETAIL_CAP] + [f"…另有 {len(details) - DETAIL_CAP} 张表，用 --verbose 查看全部"]
    rep.add(WARN, "srcline", f"{len(tables)} 张数据表中 {len(missing)} 张缺数据来源标注", details)


# ─────────────────────────── 4. 模板硬规则 ───────────────────────────

def check_hardrules(raw, css_ranges, rep):
    """css_ranges = <style> 区间 + inline style 属性区间；样式类判据只在这些区间里找，
    避免误伤正文里出现的「gradient」「box-shadow」等普通词。"""
    def in_css(pos):
        return any(a <= pos < b for a, b in css_ranges)

    viol = []  # (行号, 说明)

    for pat, why in ((r'<link\b[^>]*href\s*=\s*["\']https?://', "外部样式表"),
                     (r'<script\b[^>]*src\s*=\s*["\']https?://', "外部脚本"),
                     (r'<img\b[^>]*src\s*=\s*["\']https?://', "外链图片")):
        for m in re.finditer(pat, raw, re.I):
            viol.append((line_of(raw, m.start()), f"{why}：{snippet(m.group(0), 60)}"))

    for pat, why in ((r"@import\b", "@import 引入外部样式"),
                     (r"@font-face\b", "@font-face 引入外部字体"),
                     (r"gradient\s*\(", "渐变（gradient）"),
                     (r"box-shadow\s*:", "投影（box-shadow）"),
                     (r"text-shadow\s*:", "投影（text-shadow）"),
                     # 暗色背景：只认 background:#0xx/#1xx/#2xx（十六进制）
                     (r"background(?:-color)?\s*:\s*#[0-2](?:[0-9a-fA-F]{2}|[0-9a-fA-F]{5})\b",
                      "疑似暗色背景")):
        for m in re.finditer(pat, raw, re.I):
            if not in_css(m.start()):
                continue
            ctx = snippet(raw[max(0, m.start() - 35):m.start() + 35], 70)
            viol.append((line_of(raw, m.start()), f"{why}：…{ctx}…"))

    if not viol:
        rep.add(OK, "hardrule", "无外部资源 / 渐变 / 暗色背景 / 投影（样式判据只扫 <style> 与 inline style）")
        return
    viol.sort()
    details = [f"第 {ln} 行 {s}" for ln, s in viol]
    if len(details) > DETAIL_CAP:
        details = details[:DETAIL_CAP] + [f"…另有 {len(details) - DETAIL_CAP} 处"]
    rep.add(FAIL, "hardrule", f"违反模板硬规则 {len(viol)} 处", details)


# ─────────────────────────── 5. 必备要素 ───────────────────────────

REQUIRED = [
    ("免责声明", ("不构成投资建议",), "页脚缺免责声明关键词「不构成投资建议」"),
    ("下期跟踪清单", ("下期跟踪清单", "先行指标"), "缺「下期跟踪清单」章节（先行指标仪表盘）"),
]


def check_required(visible, rep):
    missing = []
    for name, kws, msg in REQUIRED:
        if not any(k in visible for k in kws):
            missing.append((name, msg))
    if not missing:
        rep.add(OK, "required", "免责声明 / 下期跟踪清单 两项齐备")
        return
    for name, msg in missing:
        rep.add(FAIL, "required", msg)


# ─────────────────────────── 6/7. 结构完整性 ───────────────────────────

def check_structure(text, rep, secs):
    nums = secs.numbers()
    if not nums:
        rep.add(WARN, "sectnum", "未解析到任何数字章节编号（.secthead .no），无法校验连续性")
    else:
        problems = []
        for i, n in enumerate(nums):
            if i == 0:
                if n != 0:
                    problems.append(f"首章编号是 {n:02d}，模板约定从 00 起")
                continue
            if n != nums[i - 1] + 1:
                problems.append(f"第 {i + 1} 章编号 {n:02d}，上一章 {nums[i - 1]:02d}（应为 {nums[i - 1] + 1:02d}）")
        if problems:
            rep.add(WARN, "sectnum", f"章节编号不连续：{len(problems)} 处", problems)
        else:
            rep.add(OK, "sectnum", f"章节编号连续：{nums[0]:02d}~{nums[-1]:02d}（共 {len(nums)} 章）")

    ids = set(re.findall(r'id="([^"]+)"', text))
    hrefs = [m.group(1) for m in re.finditer(r'href="#([^"]+)"', text)]
    dangling = sorted({h for h in hrefs if h not in ids})

    if not hrefs and not secs.heads:
        rep.add(WARN, "anchor", "全文无页内锚点，也无章节头，锚点体系无法校验")
        return
    if dangling:
        details = [f'href="#{h}" 找不到对应 id' for h in dangling]
        rep.add(WARN, "anchor", f"悬空页内锚点 {len(dangling)} 个（{len(hrefs)} 个锚点引用）", details)
    else:
        rep.add(OK, "anchor", f"页内锚点全部有效（{len(hrefs)} 个引用 / {len(ids)} 个 id）")

    # 章节头缺 id：模板约定每个 .secthead 带固定 id（s0~s8 / review）
    head_html = re.findall(r'<div class="secthead"[^>]*>', text)
    with_id = sum(1 for h in head_html if re.search(r'\bid="', h))
    if head_html and with_id == 0:
        rep.add(WARN, "anchor", f"{len(head_html)} 个章节头都没有 id——模板约定 s0~s8，跨章下钻链接会失效")


# ─────────────────────────── 8~10. 排雷章瘦身形态（s2） ───────────────────────────

def check_s2_shape(text, rep):
    """排雷章（secthead id="s2" 起至下一 secthead 止）的瘦身形态检查，三条 WARN。
    排雷章瘦身定案见修订计划 v0.2.0：正文只保留 🔴命中逐条与 🟡观察（≤6 行），
    反向未触发与未触发一律并入表末汇总行。"""
    m = re.search(r'<div class="secthead"[^>]*\bid="s2"', text)
    if not m:
        rep.add(WARN, "s2-shape", "未找到排雷扫描章节（secthead id=\"s2\"），无法校验瘦身形态")
        return
    nxt = re.search(r'class="secthead"', text[m.end():])
    seg = text[m.start(): m.end() + nxt.start() if nxt else len(text)]

    def badges(kw):
        return re.findall(rf'class="[^"]*\bbadge\b[^"]*\b{kw}\b', seg)

    # 反向未触发：并入未触发汇总行，正文不应保留可见行
    rev = badges("rev")
    if rev:
        rep.add(WARN, "s2-shape",
                f"排雷章出现 {len(rev)} 行「反向未触发」可见行——应并入未触发汇总行，不应保留可见行")
    # 未触发逐条行：汇总 total 行可能含 g，留 1 容忍；宁可少报不误报
    g = badges("g")
    if len(g) > 1:
        rep.add(WARN, "s2-shape",
                f"排雷章出现 {len(g)} 个绿色徽章行——未触发不应逐条展开（仅容忍汇总行 1 处），逐条读数见 data.json signals 块")
    # 观察行上限：观察两行形态（担心→本案，v0.0.7），最多 6 条，超出并入汇总。
    # 只数「🟡」开头的观察徽章——勾稽表的「⚠️ 可解释偏差」同为 badge y 但语义不同，不计入
    y = re.findall(r'class="[^"]*\bbadge\b[^"]*\by\b[^"]*"[^>]*>\s*🟡', seg)
    if len(y) > 6:
        rep.add(WARN, "s2-shape",
                f"排雷章观察条目 {len(y)} 行，超过 6 行上限——应压缩或并入汇总")
    if not (rev or len(g) > 1 or len(y) > 6):
        rep.add(OK, "s2-shape", "排雷章符合瘦身形态：无反向可见行、未触发未逐条展开、观察 ≤6 行")


# ─────────────────────────── 11. s8 阈值化与回看归因 ───────────────────────────

# 数字阈值形态：>46 / <43 / ≥2 / -20% / 1.5 倍
THRESH_RE = re.compile(r'[><≥≤]\s*[-+]?\d|[-+]?\d+(?:\.\d+)?\s*[%倍]')
ATTRIB_RE = re.compile(r'假设错|时点错|口径错')


def _section_seg(text, anchor):
    """截取某 secthead 章至下一 secthead 的片段；找不到返回 None。"""
    m = re.search(rf'<div class="secthead"[^>]*\bid="{anchor}"', text)
    if not m:
        return None
    nxt = re.search(r'class="secthead"', text[m.end():])
    return text[m.start(): m.end() + nxt.start() if nxt else len(text)]


def check_s8_shape(text, rep):
    """下期跟踪清单（s8）阈值化形态（v0.0.6 T5）：观察方向列（第 3 列）应含数字阈值
    （>x% / <y% / ≥z 倍）；纯 if-then 句式允许但提示，推动阈值带落地。"""
    seg = _section_seg(text, "s8")
    if seg is None:
        rep.add(WARN, "s8-shape", "未找到下期跟踪清单章节（secthead id=\"s8\"），无法校验阈值化形态")
        return
    bad = []
    for r in re.findall(r'<tr>(.*?)</tr>', seg, re.S):
        if '<th' in r:
            continue
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)
        if len(tds) < 3:
            continue
        cell = re.sub(r'<[^>]+>', '', tds[2])
        # HTML 实体反转义（&gt; 40 亿 → > 40 亿），否则规范的转义写法反被误报；
        # 无法数字化阈值的 if-then 句式（若…则…）按 T5 设计豁免
        cell = cell.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        if not THRESH_RE.search(cell) and not re.search(r'若.{2,30}则', cell):
            name = re.sub(r'<[^>]+>', '', tds[0]).strip()[:20]
            bad.append(f"「{name}」观察方向列未见数字阈值（>x / <y 形态）；无法数字化时应有 if-then 句式")
    if bad:
        rep.add(WARN, "s8-shape", f"下期跟踪清单 {len(bad)} 行未见数字阈值带（T5）", bad[:5])
    else:
        rep.add(OK, "s8-shape", "下期跟踪清单观察方向列均含数字阈值带（T5）")


def check_review_shape(text, rep):
    """上期跟踪回顾章（review）归因必填校验（v0.0.6 T6）：❌ 未兑现行的复盘列必须含
    误差归因（假设错/时点错/口径错）；无回看章（无旧报告）属正常。"""
    seg = _section_seg(text, "review")
    if seg is None:
        rep.add(OK, "review-shape", "无回看章（无旧报告时正常），跳过归因校验")
        return
    bad = []
    for r in re.findall(r'<tr>(.*?)</tr>', seg, re.S):
        if '<th' in r:
            continue
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)
        if len(tds) < 3:
            continue
        verdict_cell = re.sub(r'<[^>]+>', '', tds[1])
        if '❌' not in verdict_cell and '未兑现' not in verdict_cell:
            continue
        cell = re.sub(r'<[^>]+>', '', tds[2])
        if not ATTRIB_RE.search(cell):
            name = re.sub(r'<[^>]+>', '', tds[0]).strip()[:20]
            bad.append(f"「{name}」❌ 行复盘列缺误差归因（假设错/时点错/口径错）")
    if bad:
        rep.add(WARN, "review-shape", f"回看章 {len(bad)} 行 ❌ 未填误差归因（T6 冻结纪律）", bad[:5])
    else:
        rep.add(OK, "review-shape", "回看章 ❌ 行均带误差归因（T6）")


# ─────────────────────────── 11·五. figtitle 结论式（v0.0.7 读法层） ───────────────────────────

# figtitle 括号内的方法说明关键词：这类注记（年报必做/同类型滚动/降级为分部桥……）
# 应挪 srcline，标题写判断。只扫（全角括号）段——标题正文里的同类词（如「Q4 五项检验总判」）不误伤
FIGTITLE_METHOD_RE = re.compile(r'（[^）]*(?:必做|滚动|降级|检测|方法|口径说明|规则见)[^）]*）')


def check_figtitle_style(text, rep, secs):
    """figtitle 结论式（v0.0.7 读法层硬规则）：括号内含方法说明关键词 → 疑似描述式标题。
    启发式 WARN：清单导航类标题（异常下钻地图）天然无结论，命中后人工确认即可。"""
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


# ─────────────────────────── 12. 数字回验（T8，--json 时执行） ───────────────────────────

# 正文数字（含千分位）；src 行号；数字阈值语境（>x / <y / ≥z）
PLAIN_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
SRC_LINE_RE = re.compile(r"L(\d+)")
NUM_KEY_LIST = ("cur", "prev", "lhs", "rhs",
                "rev_cur", "rev_prev", "cost_cur", "cost_prev",
                "vol_cur", "vol_prev", "price_cur", "price_prev",
                "volume", "price", "mix", "delta")


def _iter_metric_leaves(node, path, out):
    """收集数值叶子：Metric 结构（含 cur）、by_segment 行（含 rev_cur）、recon 条目（含 lhs）、
    rev_factors（含 volume）、桥条目（含 delta）。"""
    if isinstance(node, dict):
        if "cur" in node or "rev_cur" in node or "lhs" in node or "volume" in node or "delta" in node:
            out.append((".".join(path), node))
            return
        for k, v in node.items():
            _iter_metric_leaves(v, path + [k], out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _iter_metric_leaves(v, path + [str(i)], out)


def _num_of(node, k):
    v = node.get(k)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
        return float(v)  # 保留符号：笔误检测符号敏感（负增速不会撞正比率）
    return None


def build_authority(data):
    """权威值集：json 全部数值叶子。返回 (plain_entries, pct_entries, uniq_plain, uniq_pct)：
    plain = 各字段原值（金额/天数/倍数，供无 % 语境数字比较）；
    pct = 仅 derived.ratios 的 ×100 变体（供带 % 语境数字比较）。
    「独特性」= 与【其他叶子】的值 2% 内无碰撞（同一叶子 cur/prev 互撞不算）；
    笔误检测只在独特值上做：撞脸的值无法归因，报了也是噪音。"""
    leaves = []
    _iter_metric_leaves(data, [], leaves)
    plain, pct = [], []
    for path, node in leaves:
        for k in NUM_KEY_LIST:
            v = _num_of(node, k)
            if v is None:
                continue
            plain.append((v, f"{path}.{k}", path))
            if path.startswith("derived.ratios"):
                pct.append((v * 100, f"{path}.{k}×100", path))

    def uniq_of(entries):
        out = []
        for i, (v, p, leaf) in enumerate(entries):
            if not any(j != i and leaf != leaf2 and v * w > 0 and abs(v - w) / max(abs(w), 1e-9) <= 0.02
                       for j, (w, _, leaf2) in enumerate(entries)):
                out.append((v, p))
        return out

    return plain, pct, uniq_of(plain), uniq_of(pct)


def check_numbers_vs_json(body, raw, data, rep):
    """①级：HTML 数字 ↔ data.json。
    先把 HTML 标签等长屏蔽（viewBox/属性数字不是正文主张，替换保行号）；
    % 语境分离：带 % 后缀的数字只与 derived.ratios ×100 变体比，不带 % 只与字段原值比
    （增速/同业百分数不会撞金额，票据金额不会撞 ROE×100）。
    与权威值「按显示精度相等且同号」→ 匹配 OK；未匹配但落在某【独特】值 0.15% 窗口内
    → FAIL 疑似笔误（报告行号 + 最接近的 json 字段）；其余无关数字跳过。
    阈值语境（&lt;x / &gt;y）、期次年份、序号小整数、外币（美元/欧元/港元）豁免。"""
    plain, pct, uniq_plain, uniq_pct = build_authority(data)
    tag_spans = [(m.start(), m.end()) for m in re.finditer(r'<[^>]+>', body)]
    text = mask_ranges(body, tag_spans)
    matched = 0
    suspects = []
    for m in PLAIN_NUM_RE.finditer(text):
        # 阈值语境豁免：数字前是 &lt;/&gt;/&le;/&ge;/≥/≤ 的是触发线，不是数值主张
        # （正文裸 < 必然转义为 &lt;；标签闭合 > 不算——否则 <td> 内数字全被误豁免）
        head = text[max(0, m.start() - 8):m.start()].rstrip()
        if head.endswith(("&lt;", "&gt;", "&le;", "&ge;", "≥", "≤")):
            continue
        txt = m.group(0).replace(",", "")
        # 外币语境豁免：后随 美元/欧元/港元 等币种的数字不是人民币科目（json 全部为人民币亿元）
        tail = text[m.end():m.end() + 12]
        if re.match(r'\s*(?:万|亿|百亿|千万)?\s*(?:美元|欧元|港元|港币|日元|HKD|USD|EUR)', tail):
            continue
        try:
            d = float(txt)
        except ValueError:
            continue
        if abs(d) < 0.01:
            continue
        if d == int(d) and (1900 <= d <= 2100 or abs(d) < 10):
            continue  # 期次年份 / 序号小整数
        is_pct = text[m.end():].lstrip()[:1] in ("%", "％")
        match_pool = pct if is_pct else plain
        dec = len(txt.partition(".")[2])
        tol = max(0.5 * (10 ** -dec), 1e-9)
        # 显示精度内相等且同号：|v − d| ≤ 半个显示精度（双向舍入都算匹配，宽容防误报）
        if any(v * d > 0 and abs(v - d) <= tol for v, _, _ in match_pool):
            matched += 1
            continue
        pool = uniq_pct if is_pct else uniq_plain
        same_sign = [vp for vp in pool if vp[0] * d > 0]
        if not same_sign:
            continue
        bv, bp = min(same_sign, key=lambda vp: abs(vp[0] - d) / max(abs(vp[0]), 1e-9))
        dev = abs(bv - d) / max(abs(bv), 1e-9)
        if dev <= 0.0015:  # 笔误的特征是小偏差（抄错相邻位/小数点，典型 ≤0.12%）；
            # 窗口外的「近似」多为语义不同的数字（实测：同业数字撞脸集中在 0.19%~0.5%）
            suspects.append(f"L{line_of(raw, m.start())} 数字 {txt} 与 data.json {bp}={bv:g} "
                            f"相近但不等（差 {dev:.2%}）——疑似笔误，请核对")
    if suspects:
        rep.add(FAIL, "num-vs-json",
                f"①级 HTML↔data.json：{len(suspects)} 处数字与独特值相近但不等（疑似笔误；已匹配 {matched} 处）",
                suspects[:DETAIL_CAP])
    else:
        rep.add(OK, "num-vs-json",
                f"①级 HTML↔data.json：{matched} 处数字匹配，未见疑似笔误"
                f"（原值 {len(plain)} · %变体 {len(pct)} · 独特值 {len(uniq_plain)}+{len(uniq_pct)}）")


def _resolve_md(md_rel, json_path):
    """meta.source_md（相对仓库根）的路径解析：依次试 原样 / cwd / json 上级各层；
    兼容 v0.2.0 目录治理前旧路径（reports/xxx.md → reports/archive/原始报告/xxx.md）。"""
    if not md_rel:
        return None
    variants = [md_rel]
    if md_rel.startswith("reports/") and "archive" not in md_rel:
        variants.append(md_rel.replace("reports/", "reports/archive/原始报告/", 1))
    cands = []
    for rel in variants:
        cands += [Path(rel), Path.cwd() / rel]
        base = json_path.parent
        for _ in range(4):
            cands.append(base / rel)
            base = base.parent
    for c in cands:
        if c.is_file():
            return c
    return None


def _value_in_text(v, text):
    """v 的三档单位换算（×1e8 元 / ×1e4 万 / ×1 亿）在文本数字中是否有 5% 内容差命中（同号比较）。"""
    for m in PLAIN_NUM_RE.finditer(text):
        try:
            d = float(m.group(0))
        except ValueError:
            continue
        for cand in (v, v * 1e4, v * 1e8):
            if cand and d * cand > 0 and abs(d - cand) / abs(cand) <= 0.05:
                return True
    return False


def check_json_vs_md(data, json_path, rep):
    """②级：data.json ↔ 原文 md（5% 容差 + 单位换算 + 行号窗 ±2）。
    src 无 L 行号 → 跳过计数；md 缺失 → 声明并整体跳过（HANDOFF T8 定案）。"""
    md_rel = (data.get("meta") or {}).get("source_md")
    md_path = _resolve_md(md_rel, json_path)
    if md_path is None:
        rep.add(OK, "json-md", f"声明：原文 md 未找到（{md_rel}），②级 data.json↔原文 未执行")
        return
    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    leaves = []
    for section in ("statements", "parent_statements", "notes"):
        _iter_metric_leaves(data.get(section) or {}, [section], leaves)
    checked = exact = shifted = no_src = 0
    misses = []
    for path, node in leaves:
        src = node.get("src") or ""
        lns = [int(x) for x in SRC_LINE_RE.findall(src)]
        if not lns:
            no_src += 1
            continue
        for key in ("cur", "prev"):
            v = _num_of(node, key)
            if v is None:
                continue
            checked += 1
            hit_off = None
            for ln in lns:
                for off in (0, -1, 1, -2, 2):
                    i = ln - 1 + off
                    if 0 <= i < len(lines) and _value_in_text(v, lines[i].replace(",", "")):
                        hit_off = off
                        break
                if hit_off is not None:
                    break
            if hit_off is None:
                misses.append(f"{path}.{key}={v:g}：src 行 {lns}（±2）内未找到——行号偏移或表格错位")
            elif hit_off != 0:
                shifted += 1
            else:
                exact += 1
    if misses:
        rep.add(WARN, "json-md",
                f"②级 data.json↔md：{len(misses)} 处 src 行内未找到值"
                f"（checked {checked} · 精确命中 {exact} · 偏移命中 {shifted} · 无行号跳过 {no_src}）",
                misses[:DETAIL_CAP])
    else:
        rep.add(OK, "json-md",
                f"②级 data.json↔md：{checked} 处全部命中"
                f"（精确 {exact} · 偏移 {shifted} · 无行号跳过 {no_src}）")


# ─────────────────────────── 主流程 ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description="financial-report-analysis 报告 HTML 机检")
    ap.add_argument("html_path", help="报告 HTML 路径")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="data.json 路径：启用 T8 数字回验（①级 HTML↔json 笔误检测 + ②级 json↔原文 md 核对）")
    ap.add_argument("--verbose", action="store_true", help="打印全部明细，不截断")
    ap.add_argument("--warn-only", action="store_true", help="纯提示模式：任何发现都不影响退出码")
    ap.add_argument("--strict", action="store_true", help="WARN 也判失败")
    args = ap.parse_args()

    path = Path(args.html_path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        print(f"🔴 文件不存在：{args.html_path}")
        return 1
    except UnicodeDecodeError as e:
        print(f"🔴 文件不是 UTF-8，无法校验：{e}")
        return 1

    comment_ranges = [(m.start(), m.end()) for m in re.finditer(r"<!--.*?-->", raw, re.S)]
    style_ranges = tag_ranges(raw, "style")
    script_ranges = tag_ranges(raw, "script")

    # 正文视图：注释 / <style> / <script> 全部屏蔽（长度不变，行号可复用）。
    # CSS 里 `{grid-template-columns:1fr}}` 这类合法 }} 也因此不会误报成漏填占位符。
    body = mask_ranges(raw, comment_ranges + style_ranges + script_ranges)

    # 样式判据的作用域：<style> 块 + inline style 属性
    css_ranges = style_ranges + [(m.start(1), m.end(1))
                                 for m in re.finditer(r'style="([^"]*)"', raw)]

    secs = Sections(body)
    rep = Report()

    data = None
    if args.json_path:
        try:
            data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"🔴 --json 读取失败：{e}")
            return 1

    check_placeholders(raw, body, rep, args.verbose)
    check_bare_numbers(body, rep, args.verbose, secs)
    check_srcline(body, rep, args.verbose, secs)
    check_hardrules(raw, css_ranges, rep)
    check_required(body, rep)
    check_structure(body, rep, secs)
    check_s2_shape(body, rep)
    check_s8_shape(body, rep)
    check_review_shape(body, rep)
    check_figtitle_style(body, rep, secs)
    if data is not None:
        check_numbers_vs_json(body, raw, data, rep)
        check_json_vs_md(data, Path(args.json_path).resolve(), rep)

    print(f"\n=== check_html.py 报告机检 · {path.name} ===\n")
    order = {FAIL: 0, WARN: 1, OK: 2}
    for lv, code, msg, details in sorted(rep.rows, key=lambda r: (order[r[0]], r[1])):
        print(f"{ICON[lv]} [{lv:<4}] {code:<14} {msg}")
        for d in details:
            print(f"      · {d}")

    c = rep.counts()
    print(f"\n--- 汇总：FAIL {c[FAIL]} · WARN {c[WARN]} · OK {c[OK]} ---")

    if args.warn_only:
        print("✅ 通过（--warn-only 提示模式：上述发现仅供人工复核，不影响退出码）")
        return 0
    failed = c[FAIL] + (c[WARN] if args.strict else 0)
    if failed:
        print("❌ 未通过：先修 FAIL 项再交付；WARN 项逐条人工确认。")
        return 1
    print("✅ 通过。" + ("（--strict 模式：WARN 亦已清零）" if args.strict else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
