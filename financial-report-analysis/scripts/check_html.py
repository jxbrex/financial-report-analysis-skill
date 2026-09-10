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

七类检查（★ = 启发式，有误报/漏报，输出「待人工确认」而非断言错误）：
  1. placeholder  [FAIL] 未替换的 {{占位}}。HTML 注释内的不算——模板的
                  「◆ SLOT」注释里常写示例占位符，那是说明文字不是漏填；
                  <style>/<script> 内的也不算（CSS 里 `…1fr}}` 是合法语法，
                  不排除会把成片 CSS 误报成漏填）。
  2. bare-number  [WARN] ★ 关键数字没有挂证据等级徽章（.badge.disc/der/est）。
  3. srcline      [WARN] 每张 <table class="data"> 之后缺 .srcline 数据来源标注。
  4. hardrule     [FAIL] 外部资源（<link href="http… / <script src="http… /
                  @import / @font-face）、渐变、暗色背景、投影。样式类判据只扫
                  <style> 块与 inline style，避免误伤正文里出现的同名词。
  5. required     [FAIL] 页脚免责声明「不构成投资建议」、最强反方章节、下期跟踪清单。
  6. sectnum      [WARN] 章节编号（.secthead .no）连续性——跳号/重号/倒退。
  7. anchor       [WARN] 悬空页内锚点（href="#x" 找不到 id="x"）；以及章节
                  secthead 完全没有 id（模板约定 s0~s9，缺了锚点体系就失效）。

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
    ("最强反方", ("最强反方", "多头", "空头"), "缺「最强反方」章节（多头/空头对立论点）"),
    ("下期跟踪清单", ("下期跟踪清单", "先行指标"), "缺「下期跟踪清单」章节（先行指标仪表盘）"),
]


def check_required(visible, rep):
    missing = []
    for name, kws, msg in REQUIRED:
        if not any(k in visible for k in kws):
            missing.append((name, msg))
    if not missing:
        rep.add(OK, "required", "免责声明 / 最强反方 / 下期跟踪清单 三项齐备")
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

    # 章节头缺 id：模板约定每个 .secthead 带固定 id（s0~s9 / review）
    head_html = re.findall(r'<div class="secthead"[^>]*>', text)
    with_id = sum(1 for h in head_html if re.search(r'\bid="', h))
    if head_html and with_id == 0:
        rep.add(WARN, "anchor", f"{len(head_html)} 个章节头都没有 id——模板约定 s0~s9，跨章下钻链接会失效")


# ─────────────────────────── 主流程 ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description="financial-report-analysis 报告 HTML 机检")
    ap.add_argument("html_path", help="报告 HTML 路径")
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

    check_placeholders(raw, body, rep, args.verbose)
    check_bare_numbers(body, rep, args.verbose, secs)
    check_srcline(body, rep, args.verbose, secs)
    check_hardrules(raw, css_ranges, rep)
    check_required(body, rep)
    check_structure(body, rep, secs)

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
