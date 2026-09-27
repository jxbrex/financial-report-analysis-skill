# -*- coding: utf-8 -*-
"""check_html_t8.py — T8 数字回验（check_html.py --json 时启用的两级校验）：
①级 HTML↔data.json 笔误检测（独特值 0.5% 窗口 FAIL）；②级 data.json↔原文 md 行号回核。
"""

import json
import re
from pathlib import Path

from check_html_common import FAIL, WARN, OK, DETAIL_CAP, line_of, mask_ranges


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


def check_numbers_vs_json(body, raw, data, rep, verbose=False):
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
        details = suspects
        if not verbose and len(details) > DETAIL_CAP:
            details = details[:DETAIL_CAP] + [f"…另有 {len(suspects) - DETAIL_CAP} 处，用 --verbose 查看全部"]
        rep.add(FAIL, "num-vs-json",
                f"①级 HTML↔data.json：{len(suspects)} 处数字与独特值相近但不等（疑似笔误；已匹配 {matched} 处）",
                details)
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
    """v 的四档单位换算（×1e8 元 / ×1e5 千元 / ×1e4 万 / ×1 亿）在文本数字中是否有 5% 内容差命中。
    千元档覆盖报表主体以千元列示的公司（如比亚迪：财务报表及附注单位为千元）；
    比较取绝对值——A 股报表以括号表示负数（如「(3,247,033 )」），符号由 src 语境与①级负责。"""
    for m in PLAIN_NUM_RE.finditer(text):
        try:
            d = abs(float(m.group(0)))
        except ValueError:
            continue
        for cand in (abs(v), abs(v) * 1e4, abs(v) * 1e5, abs(v) * 1e8):
            if cand and abs(d - cand) / abs(cand) <= 0.05:
                return True
    return False


def check_json_vs_md(data, json_path, rep, verbose=False):
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
        details = misses
        if not verbose and len(details) > DETAIL_CAP:
            details = details[:DETAIL_CAP] + [f"…另有 {len(misses) - DETAIL_CAP} 处，用 --verbose 查看全部"]
        rep.add(WARN, "json-md",
                f"②级 data.json↔md：{len(misses)} 处 src 行内未找到值"
                f"（checked {checked} · 精确命中 {exact} · 偏移命中 {shifted} · 无行号跳过 {no_src}）",
                details)
    else:
        rep.add(OK, "json-md",
                f"②级 data.json↔md：{checked} 处全部命中"
                f"（精确 {exact} · 偏移 {shifted} · 无行号跳过 {no_src}）")


