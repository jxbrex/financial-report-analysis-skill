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

模块布局（v0.0.19 起）：
    check_html.py       本入口：结构/硬规则族 + 主流程
    check_html_text.py  呈现文本族（文风/标签/格式类检查，含 v0.0.19 三条新规则）
    check_html_common.py 共享助手；check_html_t8.py T8 数字回验整族

本模块直接实现的检查（★ = 启发式，有误报/漏报，输出「待人工确认」而非断言错误）：
  1. placeholder  [FAIL] 未替换的 {{占位}}。HTML 注释内的不算——模板的
                  「◆ SLOT」注释里常写示例占位符，那是说明文字不是漏填；
                  <style>/<script> 内的也不算（CSS 里 `…1fr}}` 是合法语法，
                  不排除会把成片 CSS 误报成漏填）。
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
  11. s8-shape    [WARN] 下期跟踪清单阈值化（数字阈值带槽 / 旧表兜底第 3 列）。
  11·二. review-shape [WARN] 回看章 ❌ 行复盘列必填误差归因（假设错/时点错/口径错）。
  14. dupont-stack [FAIL]（仅 --json）ΔROE 堆叠条数据槽 ↔ derived.dupont 三效应
                  与 closure_gap 一致性——口径差段不许视觉隐瞒。

呈现文本族（check_html_text.py，本入口调用）：
  2. bare-number  [WARN] ★ 关键数字没有挂证据等级徽章（.badge.disc/der/est）。
  11·五. figtitle-style [WARN] ★ 结论式标题：括号内含方法说明关键词 → 疑似描述式。
  12. slot-length [WARN] s1 四维表「评价」列注脚 ≤15 字（>20 告警）。
  13. s1-v15-shape [WARN] ★ 杜邦双卡形态：下钻子行 ≤3；因子分位表带白描读数
                  （v0.0.19 起 X/5 从高到低；旧措辞与「上限区/下限区/常态区」均禁）
                  且禁用「显著」；现金时序表/周期证据表存在（降级或非周期须有声明）。
  11·六. abbrev / ocf-bridge-shape / figtitle-attribution / inspection-verdict
                  [WARN] v0.0.12 读法层兜底四件 + v0.0.15 s5 判定列扩展。
  15. internal-ref [FAIL] 可见文本禁现内部过程引用（v0.0.18）：底稿文件名
                  （data.json/fillsheet）、方法库路径（references/）、脚本名
                  （calc.py/check_html）、字段路径（derived.）、技能版本号（v0.0.x）、
                  取数工具函数名（mx_xxx）——这些都不是「数据来源」，来源只写对外口径
                  （定期报告/公告/Tushare/东方财富）。HTML 注释/style/script 已屏蔽不算。
  16. srcline-dup [FAIL] srcline 拼接纪律（v0.0.18）：禁嵌套、相邻组 ≤2 条
                  （来源条+图例条为合法双条）、禁文本重复。
  17. percentile-map [FAIL]（仅 --json）因子分位白描读数 ↔ derived.dupont5y.percentile
                  映射一致性（v0.0.19 起 X/5：0→5/5 / .25→4/5 / .5→3/5 / .75→2/5 / 1→1/5）。
                  旧版式存量报告仍贴旧标签会 FAIL——纪律 7 不追溯，属预期。
  18. recon-label [WARN] v0.0.19 勾稽三态短式（闭合/可解释/无法解释），旧长标签提示。
  19. decimal-places [WARN] ★ v0.0.19 可见数字 ≤2 位小数（pct 效应值 1 位），
                  srcline 屏蔽；版本号/日期形态不匹配。
  20. assertion-count [FAIL] v0.0.19 断言验证矩阵算术自洽：figtitle 三态计数
                  a+b+c=N、与表内 ✅/❌/❓ 徽章数一致；--json 再比对底稿 assertions。

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
import ast
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


from check_html_common import (FAIL, WARN, OK, Report, DETAIL_CAP,
                               mask_ranges, tag_ranges, line_of, snippet,
                               Sections, _section_seg)
from check_html_t8 import check_numbers_vs_json, check_json_vs_md, check_undisclosed_claims
# 呈现文本族（v0.0.19 拆出）；PCTILE_LABEL 在此再导出——回归契约锁从本模块 import
from check_html_text import (  # noqa: F401
    PCTILE_LABEL,
    check_bare_numbers, check_figtitle_style, check_slot_length, check_abbrev,
    check_ocf_bridge_shape, check_figtitle_attribution, check_inspection_verdict,
    check_internal_ref, check_srcline_dup, check_s1_v15_shape, check_percentile_map,
    check_recon_label, check_decimal_places, check_assertion_counts)


ICON = {FAIL: "🔴", WARN: "🟡", OK: "✅"}
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
        rep.add(WARN, "anchor", f"{len(head_html)} 个章节头都没有 id——模板约定 s0~s8，跨章追查链接会失效")


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
                f"排雷章出现 {len(g)} 个绿色徽章行——未触发不应逐条展开（仅容忍汇总行 1 处），逐条读数落底稿不进报告")
    # 观察行上限：观察两行形态（担心→本案，v0.0.7），最多 6 条，超出并入汇总。
    # 只数「🟡」开头的观察徽章——勾稽表的「⚠️ 可解释」同为 badge y 但语义不同，不计入
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



def check_s8_shape(text, rep):
    """下期跟踪清单（s8）阈值化形态（v0.0.6 T5；v0.0.9 L5 卡组化）：
    卡组形态判 .wb 阈值带槽（>x% / <y% / ≥z 倍）；存量旧表形态兜底判第 3 列。
    纯 if-then 句式允许但提示，推动阈值带落地。"""
    seg = _section_seg(text, "s8")
    if seg is None:
        rep.add(WARN, "s8-shape", "未找到下期跟踪清单章节（secthead id=\"s8\"），无法校验阈值化形态")
        return

    def plain(cell):
        cell = re.sub(r'<[^>]+>', '', cell)
        # HTML 实体反转义（&gt; 40 亿 → > 40 亿），否则规范的转义写法反被误报
        return cell.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    def judge(cells, label):
        bad = []
        for i, cell in enumerate(cells):
            p = plain(cell)
            if not THRESH_RE.search(p) and not re.search(r'若.{2,30}则', p):
                bad.append(f"{label}第 {i + 1} 项未见数字阈值（>x / <y 形态）；无法数字化时应有 if-then 句式")
        return bad

    wbs = re.findall(r'<div class="wb"[^>]*>(.*?)</div>', seg, re.S)
    if wbs:
        bad = judge(wbs, "阈值带槽")
        wvs = re.findall(r'<div class="wv"[^>]*>(.*?)</div>', seg, re.S)
        nobadge = [i + 1 for i, w in enumerate(wvs) if 'class="badge' not in w]
        if nobadge:
            bad.append(f"读数槽第 {nobadge} 个未挂证据等级徽章")
    else:
        # 存量旧表形态（v0.0.9 前产出）兜底：观察方向列 = 第 3 列
        bad = []
        for r in re.findall(r'<tr>(.*?)</tr>', seg, re.S):
            if '<th' in r:
                continue
            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)
            if len(tds) < 3:
                continue
            name = plain(tds[0]).strip()[:20]
            for b in judge([tds[2]], ""):
                bad.append(f"「{name}」{b}")
    if bad:
        rep.add(WARN, "s8-shape", f"下期跟踪清单 {len(bad)} 处未见数字阈值带（T5）", bad[:5])
    else:
        rep.add(OK, "s8-shape", "下期跟踪清单阈值带均含数字阈值（T5）")


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


# ─────────────────── v0.0.15：ΔROE 堆叠条数据槽比对（FAIL，仅 --json） ───────────────────

def check_dupont_stack(raw, data, rep):
    """DUPONT_STACK 数据槽 ↔ derived.dupont 一致性（v0.0.15，仅 --json 模式）：
    三效应×100（pct，呈现一位小数）与 json 比对；gap≠0 时槽内必须保留（视觉不许隐瞒加和缺口）。
    槽语法解析失败只 WARN 不 FAIL——语法问题不该掩盖数据问题，且 WARN 已足够显眼。"""
    m = re.search(r'DUPONT_STACK\s*=\s*\{\s*steps\s*:\s*(\[.*?\])\s*,\s*gap\s*:\s*([-0-9.eE]+)\s*\}',
                  raw, re.S)
    if not m:
        rep.add(OK, "dupont-stack", "无 DUPONT_STACK 数据槽（杜邦降级缺省时正常）")
        return
    du = (data.get("derived") or {}).get("dupont") or {}
    if all(du.get(k) is None for k in ("margin_effect", "turnover_effect", "leverage_effect")):
        rep.add(OK, "dupont-stack", "derived.dupont 未填（口径断裂），堆叠条槽跳过比对")
        return
    try:
        steps = ast.literal_eval(m.group(1))
        gap = float(m.group(2))
    except (ValueError, SyntaxError):
        rep.add(WARN, "dupont-stack", "DUPONT_STACK 槽解析失败——检查 JS 数组字面量语法")
        return
    bad = []
    expect = [du.get("margin_effect"), du.get("turnover_effect"), du.get("leverage_effect")]
    names = ["净利率", "周转率", "杠杆"]
    if len(steps) != 3:
        bad.append(f"steps 应为 3 段效应（净利率/周转率/杠杆），实际 {len(steps)} 段")
    else:
        for i, (nm, v) in enumerate(steps):
            e = expect[i]
            if e is None:
                continue
            if abs(v - e * 100) > 0.15:
                bad.append(f"堆叠条「{nm}」{v}pct ≠ derived.dupont 效应 {e * 100:.1f}pct"
                           f"（×100 转 pct，容差 0.15）")
            if nm != names[i]:
                bad.append(f"堆叠条第 {i + 1} 段名「{nm}」应为「{names[i]}」（定序约定）")
    g_e = du.get("closure_gap")
    if g_e is not None and abs(gap - g_e * 100) > 0.15:
        bad.append(f"堆叠条 gap={gap}pct ≠ closure_gap {g_e * 100:.1f}pct——口径差不许视觉隐瞒")
    if bad:
        rep.add(FAIL, "dupont-stack", "ΔROE 堆叠条数据槽与 derived.dupont 不符：" + "；".join(bad[:4]))
    else:
        rep.add(OK, "dupont-stack", "ΔROE 堆叠条数据槽与 derived.dupont 一致（含口径差段）")


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
    check_slot_length(body, rep)
    check_abbrev(body, rep, secs)
    check_ocf_bridge_shape(raw, rep)
    check_figtitle_attribution(body, rep, secs)
    check_inspection_verdict(body, rep)
    check_s1_v15_shape(body, rep)
    check_internal_ref(body, rep, secs)
    check_srcline_dup(body, rep)
    check_recon_label(body, rep)
    check_decimal_places(body, rep)
    check_assertion_counts(body, data, rep)
    if data is not None:
        check_dupont_stack(raw, data, rep)
        check_percentile_map(body, data, rep)
        check_numbers_vs_json(body, raw, data, rep, args.verbose)
        check_json_vs_md(data, Path(args.json_path).resolve(), rep, args.verbose)
        check_undisclosed_claims(body, data, Path(args.json_path).resolve(), rep)

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
