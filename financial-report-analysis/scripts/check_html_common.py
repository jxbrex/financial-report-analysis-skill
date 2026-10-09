# -*- coding: utf-8 -*-
"""check_html_common.py — check_html.py 的共享层：级别常量、Report、正则常量、
文本处理助手、章节索引。被 check_html.py 与 check_html_t8.py 引用。
"""

import re


FAIL, WARN, OK = "FAIL", "WARN", "OK"


# 单次运行最多打印多少条明细（--verbose 全打）
DETAIL_CAP = 20


# 数字型内容：3 位以上数字，或带 %/亿/万/倍 单位的数字
NUM_RE = re.compile(r"\d{3,}|\d+(?:\.\d+)?\s*(?:%|亿|万|倍)")
# 期次标签豁免：2025 年报 / 2025FY / 2024 末 / 2024H1 / 2026-08-28 —— 是坐标不是主张
YEAR_RE = re.compile(r"(?:(?:19|20)\d{2}\s*(?:年|末|FY|H[12]|Q[1-4]|年报|半年报|季报)[-—/]?"
                     r"|(?:19|20)\d{2}-\d{2}-\d{2})")
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


def visible_text(body):
    """body（已屏蔽注释/style/script）再去掉标签 → 纯可见文本视图。
    标签区间等长屏蔽、换行不动 → line_of 的行号仍与 raw 一致。
    t8 的 num-vs-json 与 assert-trunc 共用此一处定义（v0.0.22 前各写一遍同型代码）。"""
    return mask_ranges(body, [(m.start(), m.end()) for m in re.finditer(r"<[^>]+>", body)])


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


def _section_seg(text, anchor):
    """截取某 secthead 章至下一 secthead 的片段；找不到返回 None。"""
    m = re.search(rf'<div class="secthead"[^>]*\bid="{anchor}"', text)
    if not m:
        return None
    nxt = re.search(r'class="secthead"', text[m.end():])
    return text[m.start(): m.end() + nxt.start() if nxt else len(text)]

