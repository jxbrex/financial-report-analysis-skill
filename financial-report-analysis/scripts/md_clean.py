#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md_clean.py — 财报 markitdown 产物的一次性确定性清洗（Phase 0，v0.0.13）

病理（云铝 2026H1 实测）：PDF 表格被拆成「标签碎行 + 数值行 + 分隔行」三~五物理行
（物理/逻辑 = 1.39×），叠加页眉页脚噪声共约占 21% 行数——读任何一个数都要人肉拼行，
Read 切片切在表中间即垃圾。本脚本把逻辑行拼回、噪声删除，并生成章节索引 sidecar。

用法：
    python scripts/md_clean.py <原始md路径> [--out-dir DIR]
产出（与原始 md 同目录，--out-dir 可改）：
    {stem}.clean.md    唯一工作副本（data.json 的 source_md 应指向它；T8② 行号对其回核）
    {stem}.index.json  章节索引：sections[{name,line}] + blocks{关键块名:line}（clean md 行号）
stdout 打印清洗统计与「未合并清单」（供人工/子代理知悉）；**不变量违反 exit 1**：
    原始 md 非页眉行的数字 token 多重集 ⊆ clean md 数字 token 多重集（防清洗丢数）

原始 md 保留作溯源快照，不修改；既有报告的 json 仍指原始 md（快照不回改）。
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Windows 控制台默认 GBK，emoji 与中文会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError): pass

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
SEP_RE = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$")  # | --- | 分隔行（必须含 dash；空单元格值行不算）
PAGE_NO_RE = re.compile(r"^\s*\d{1,4}\s*$")           # 纯页码行
FURN_RE = re.compile(r"(公告编号|证券代码|证券简称|上海证券交易所|深圳证券交易所|北京证券交易所)")
# 夹心碎行候选：无数字、短、不以句读结尾（「其中：」类散文排除）、不以注/其中开头
FRAG_RULE_LEN = 40
FRAG_BAD_END = re.compile(r"[。；：，]$")
FRAG_BAD_START = re.compile(r"^(其中|注\d?|说明|第[一二三四五六七八九十]+[章节]|[一二三四五六七八九十]+、)")
SECTION_RE = re.compile(r"^(第[一二三四五六七八九十]+[章节]|[一二三四五六七八九十]+、)\s*\S{2,30}$")
BLOCK_KEYS = ("合并资产负债表", "合并利润表", "合并现金流量表", "母公司资产负债表",
              "管理层讨论与分析", "审计报告", "关键审计事项", "关联方", "承诺及或有事项",
              "资产负债表日后事项", "分部信息", "员工情况", "利润分配")


def is_pipe(line):
    return line.strip().startswith("|")


def is_frag(line):
    s = line.strip()
    if not s or is_pipe(s) or SEP_RE.match(line):
        return False
    if len(s) >= FRAG_RULE_LEN or NUM_RE.search(s):
        return False
    if FRAG_BAD_END.search(s) or FRAG_BAD_START.match(s):
        return False
    return True


def classify_furniture(lines):
    """页眉页脚：纯页码 / 机构与公告字样 / 逐页重复的报告标题行。
    重复规则**只认报告标题形态**（……年度/半年度/季度报告结尾）——泛化的「短行重复≥3」
    会误删正文散文（如独立成行的公司名），不变量只护数字不护文字，宁可少删。"""
    counts = Counter(l.strip() for l in lines if 0 < len(l.strip()) <= 40)
    title_rep = re.compile(r"(年度|半年度|季度)报告$")
    furn = set()
    for i, l in enumerate(lines):
        s = l.strip()
        if not s:
            continue
        if PAGE_NO_RE.match(l):
            # 纯数字行 = 页码 仅当「跳空行后的」紧邻内容行也是噪声（页码/公告字样/报告
            # 标题/章节头/文件边界）——markitdown 段落间几乎总隔空行，紧邻空行分不出
            # 页码与文中数字行；文中独立年份（如散文间的「2024」）跳空后两侧是正文，不删
            def _ctx(step):
                j = i + step
                while 0 <= j < len(lines) and not lines[j].strip():
                    j += step
                return lines[j].strip() if 0 <= j < len(lines) else ""
            prev_s, nxt_s = _ctx(-1), _ctx(1)
            near_noise = (not prev_s or not nxt_s
                          or PAGE_NO_RE.match(prev_s) or PAGE_NO_RE.match(nxt_s)
                          or FURN_RE.search(prev_s) or FURN_RE.search(nxt_s)
                          or title_rep.search(prev_s) or title_rep.search(nxt_s)
                          or SECTION_RE.match(prev_s) or SECTION_RE.match(nxt_s))
            if near_noise:
                furn.add(i)
        elif FURN_RE.search(s):
            furn.add(i)
        elif title_rep.search(s) and counts[s] >= 3:
            furn.add(i)
    return furn


def clean(lines):
    furn = classify_furniture(lines)
    out = []          # [行文本, 原始行号, 是否被合法改写]
    deleted = {"sep": 0, "furn": 0, "merged": 0}
    unmerged = []
    pending_pre = None
    in_table = False
    seen_sep = False
    consumed = set()

    for i, line in enumerate(lines):
        if i in consumed:
            continue
        if i in furn:
            deleted["furn"] += 1
            in_table = False
            continue
        if not line.strip():
            in_table = False
            out.append([line, i, False])
            continue
        if SEP_RE.match(line):
            if in_table and seen_sep:
                deleted["sep"] += 1
                continue
            in_table, seen_sep = True, True
            out.append([line, i, False])
            continue
        if is_pipe(line):
            in_table, seen_sep = True, (seen_sep if in_table else False)
            pre, pre_i = pending_pre if pending_pre else (None, None)
            pending_pre = None
            post = None
            parts = line.split("|", 2)
            first = parts[1] if len(parts) >= 3 else ""
            # 只有「标签未随行到达」的行才需要向后找 post 碎行：
            # ① pre 以断字结尾（现/（/引号）② 首格为空（标签全在后方）。
            # 首格自带完整标签的行（如「| 投资活动现金流入小计 |…|」）不找 post——
            # 否则会把下一逻辑行的 pre 碎行错抢成本行标签（云铝首测实证）。
            # len(parts)<3 的畸形管道行（如孤立「|」）不可改写——不消费 post，
            # 碎行走正常 frag 流程保文本，防静默丢行
            needs = (pre is not None and re.search(r"[现（(“\"]$", pre)) or (pre is None and not first.strip())
            if needs and len(parts) >= 3:
                j = i + 1
                while j < len(lines) and SEP_RE.match(lines[j]):
                    j += 1
                if (j < len(lines) and is_frag(lines[j]) and lines[j].strip()
                        and len(lines[j].strip()) <= 8):
                    post = j
                    consumed.add(j)
            merged = False
            if pre or post is not None:
                label = ((pre or "") + (lines[post].strip() if post is not None else "")).strip()
                if label and len(parts) >= 3:
                    rest = parts[2]
                    line = (f"| {label} |{rest}" if not first.strip()
                            else f"| {label} {first.strip()} |{rest}")
                    merged = True
                    deleted["merged"] += bool(pre) + (post is not None)
            if pre is not None and not merged:
                # pre 未能并入本行（非断字待续/畸形管道行不可改写）——落独立行保文本 +
                # 未合并清单，与「pending_pre 被顶替落行」同型（v0.1.1 静默丢行修复）
                out.append([pre, pre_i, False])
                unmerged.append((pre_i + 1, pre))
            out.append([line, i, merged])
            continue
        if is_frag(line):
            prev_raw = lines[i - 1] if i else ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            adjacent = (is_pipe(prev_raw) or SEP_RE.match(prev_raw)
                        or is_pipe(nxt) or SEP_RE.match(nxt))
            if not adjacent:
                out.append([line, i, False])   # 散文，不是表格碎行
                continue
            if is_pipe(nxt):
                if pending_pre is not None:
                    # 旧 pre 未消费就被顶替——落独立行保文本（进未合并清单供知悉），不静默丢
                    out.append([pending_pre[0], pending_pre[1], False])
                    unmerged.append((pending_pre[1] + 1, pending_pre[0]))
                pending_pre = (line.strip(), i)
                continue
            if out and is_pipe(out[-1][0]):
                # 上一逻辑行的 post 碎行（lookahead 未消费到的形态）：并上行并标记改写
                last = out[-1]
                last[0] = (last[0].rstrip() + f" {line.strip()} |" if last[0].rstrip().endswith("|")
                           else last[0] + f" | {line.strip()} |")
                last[2] = True
                deleted["merged"] += 1
                continue
            unmerged.append((i + 1, line.strip()))
            out.append([line, i, False])
            continue
        in_table = False
        out.append([line, i, False])

    if pending_pre:
        out.append([pending_pre[0], pending_pre[1], False])
        unmerged.append((pending_pre[1] + 1, pending_pre[0]))
    # 空行压缩：>2 连空 → 1
    final, blank = [], 0
    for text, raw_i, _mod in out:
        if not text.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        final.append(text)
    modified = {raw_i for _t, raw_i, mod in out if mod}
    return final, deleted, unmerged, furn, modified


def build_index(lines):
    sections, blocks = [], {}
    for i, l in enumerate(lines):
        s = l.strip()
        if SECTION_RE.match(s) and len(s) <= 40:
            sections.append({"name": s, "line": i + 1})
        for k in BLOCK_KEYS:
            if k not in blocks and s.startswith(k) and len(s) <= 60:
                blocks[k] = i + 1
    return {"sections": sections, "blocks": blocks}


def main():
    ap = argparse.ArgumentParser(description="财报 md 一次性确定性清洗 + 章节索引")
    ap.add_argument("md_path")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    src = Path(args.md_path)
    raw_text = src.read_text(encoding="utf-8")
    lines = raw_text.splitlines()
    final, deleted, unmerged, furn, modified = clean(lines)

    # 不变量：原始非页眉行数字 token 多重集 ⊆ clean 数字 token 多重集
    raw_nums = Counter()
    for i, l in enumerate(lines):
        if i in furn:
            continue
        raw_nums.update(NUM_RE.findall(l))
    clean_nums = Counter()
    for l in final:
        clean_nums.update(NUM_RE.findall(l))
    missing = raw_nums - clean_nums
    if missing:
        print(f"🔴 不变量违反：{sum(missing.values())} 个数字 token 在清洗中丢失，"
              f"样例 {list(missing.elements())[:8]}——禁止产出 clean md")
        return 1
    # 不变量二：文字不丢——非页眉、非分隔、非合法改写、≥8 字的中文行必须作为子串存在于 clean 全文。
    # 未改写行必逐字存在于 final → 先行集合 O(1) 快判；仅被拼接的碎行（子串形态存在）
    # 走 blob 慢判——避免候选行 × 全文的 O(n²) 扫描（v0.1.1，17MB 级 md 85s→亚秒）
    clean_blob = "\n".join(final)
    final_set = set(l.strip() for l in final)
    lost = []
    for i, l in enumerate(lines):
        s = l.strip()
        if i in furn or i in modified or SEP_RE.match(l) or len(s) < 8 or not re.search(r"[一-鿿]", s):
            continue
        if s in final_set or s in clean_blob:
            continue
        lost.append((i + 1, s))
    if lost:
        print(f"🔴 不变量违反：{len(lost)} 行中文文本在清洗中丢失，"
              f"样例 {[s[:30] for _, s in lost[:5]]}——禁止产出 clean md")
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_path = out_dir / f"{src.stem}.clean.md"
    index_path = out_dir / f"{src.stem}.index.json"
    idx = build_index(final)
    clean_path.write_text("\n".join(final) + "\n", encoding="utf-8")
    index_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1),
                          encoding="utf-8")

    print(f"✅ {src.name}：{len(lines)} → {len(final)} 行（−{1 - len(final) / len(lines):.0%}）")
    print(f"   删重复分隔行 {deleted['sep']} · 页眉页脚 {deleted['furn']} · 拼回碎行 {deleted['merged']}")
    print(f"   索引：{len(idx['sections'])} 节 / {len(idx['blocks'])} 关键块")
    print(f"   产物：{clean_path.name} + {index_path.name}（source_md 应指向 clean 副本）")
    if unmerged:
        print(f"   ⚠️ 未合并清单 {len(unmerged)} 条（人工/子代理知悉，不影响不变量）：")
        for ln, s in unmerged[:10]:
            print(f"      L{ln} {s[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
