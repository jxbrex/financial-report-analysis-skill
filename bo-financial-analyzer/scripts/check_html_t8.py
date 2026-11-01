# -*- coding: utf-8 -*-
"""check_html_t8.py — T8 数字回验（check_html.py --json 时启用的两级校验）：
①级 HTML↔data.json 笔误检测（独特值 0.15% 窗口 FAIL）；②级 data.json↔原文 md 行号回核；
①级同侧：断言 text/evidence 填充截断检测（assert-trunc，v0.0.22）与未披露声明反向检索。
"""

import html
import re
from pathlib import Path

from check_html_common import FAIL, WARN, OK, DETAIL_CAP, line_of, visible_text


# ─────────────────────────── 12. 数字回验（T8，--json 时执行） ───────────────────────────

# 正文数字（含千分位；全角减号 − 是归因列负值常态——v0.1.5 补口，此前 − 数字整串失明）；
# src 行号；数字阈值语境（>x / <y / ≥z）
PLAIN_NUM_RE = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?")
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
    """权威值集：json 全部数值叶子。返回 (plain_entries, pct_entries, uniq_plain, uniq_pct, hist_pool)：
    plain = 各字段原值（金额/天数/倍数，供无 % 语境数字比较）；
    pct = 仅 derived.ratios 的 ×100 变体（供带 % 语境数字比较）。
    「独特性」= 与【其他叶子】的值 2% 内无碰撞（同一叶子 cur/prev 互撞不算）；
    笔误检测只在独特值上做：撞脸的值无法归因，报了也是噪音。
    hist_pool = 所有数组（hist/hist_ye/cycle_evidence/cash_ts 等）的数值元素（含
    derived.ratios 的 ×100 变体）——「五期序列」类呈现的 HTML 数字常与 cur/prev
    独特值同域相邻（美的 2026H1 实证：毛利率序列 25.24 撞 cur 25.26、应收周转天数
    序列 64.4 撞 prev 64.4671），它们是序列中间值的精度舍入，先按 hist_pool 豁免
    再进独特值相近检查，消除该类系统性误报。"""
    leaves = []
    _iter_metric_leaves(data, [], leaves)
    plain, pct, hist_pool = [], [], []
    for path, node in leaves:
        for k in NUM_KEY_LIST:
            v = _num_of(node, k)
            if v is None:
                continue
            plain.append((v, f"{path}.{k}", path))
            if path.startswith("derived.ratios"):
                pct.append((v * 100, f"{path}.{k}×100", path))
        for k in ("hist", "hist_ye"):
            arr = node.get(k)
            if isinstance(arr, list):
                for i, v in enumerate(arr):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        hist_pool.append((float(v), f"{path}.{k}[{i}]"))
                        if path.startswith("derived.ratios"):
                            hist_pool.append((float(v) * 100, f"{path}.{k}[{i}]×100"))

    def walk_arrays(node, path):
        """收集其余数组型数值（cycle_evidence/cash_ts/dupont5y 等）进 hist_pool。"""
        if isinstance(node, dict):
            for k, v in node.items():
                walk_arrays(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    hist_pool.append((float(v), ".".join(path + [str(i)])))
                else:
                    walk_arrays(v, path + [str(i)])

    walk_arrays(data, [])

    def uniq_of(entries):
        out = []
        for i, (v, p, leaf) in enumerate(entries):
            if not any(j != i and leaf != leaf2 and v * w > 0 and abs(v - w) / max(abs(w), 1e-9) <= 0.02
                       for j, (w, _, leaf2) in enumerate(entries)):
                out.append((v, p))
        return out

    return plain, pct, uniq_of(plain), uniq_of(pct), hist_pool


def check_numbers_vs_json(body, raw, data, rep, verbose=False):
    """①级：HTML 数字 ↔ data.json。
    先把 HTML 标签等长屏蔽（viewBox/属性数字不是正文主张，替换保行号）；
    % 语境分离：带 % 后缀的数字只与 derived.ratios ×100 变体比，不带 % 只与字段原值比
    （增速/同业百分数不会撞金额，票据金额不会撞 ROE×100）。
    与权威值「按显示精度相等且同号」→ 匹配 OK；未匹配但落在某【独特】值 0.15% 窗口内
    → FAIL 疑似笔误（报告行号 + 最接近的 json 字段）；其余无关数字跳过。
    阈值语境（&lt;x / &gt;y）、期次年份、序号小整数、外币（美元/欧元/港元）豁免。"""
    plain, pct, uniq_plain, uniq_pct, hist_pool = build_authority(data)
    text = visible_text(body)
    matched = 0
    suspects = []
    for m in PLAIN_NUM_RE.finditer(text):
        # 阈值语境豁免：数字前是 &lt;/&gt;/&le;/&ge;/≥/≤/＞/＜ 的是触发线，不是数值主张
        # （正文裸 < 必然转义为 &lt;；标签闭合 > 不算——否则 <td> 内数字全被误豁免）
        head = text[max(0, m.start() - 8):m.start()].rstrip()
        if head.endswith(("&lt;", "&gt;", "&le;", "&ge;", "≥", "≤", "＞", "＜")):
            continue
        txt = m.group(0).replace(",", "").replace("−", "-")  # 全角减号归一，float 不认 −
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
        # % 语境含「pct」词边界：归因列单位纪律一律 ±x.xpct（report-template.html:339），
        # 此前只认 %/％，pct 数字落进原值池与金额互撞失明
        is_pct = bool(re.match(r"(?:%|％|pct\b)", text[m.end():].lstrip()))
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
        # 序列呈现豁免：数字与 json 某数组元素（含 ×100 变体）按【显示精度】相等 =
        # 序列中间值的舍入呈现（周期表/信号行的五期读数），非笔误——不进独特值相近检查。
        # 豁免必须用显示精度 tol 而非近似窗：hist 末位=cur，0.15% 近似窗会把
        # cur/prev 的笔误一并赦免（回归改错样例 1688.9 vs revenue 1688.381 实证）
        if any(v * d > 0 and abs(v - d) <= tol for v, _ in hist_pool):
            matched += 1
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
    """v 的单位换算（×1e8 元 / ×1e2 百万 / ×1e5 千元 / ×1e4 万 / ×1 亿）在文本数字中是否有 5% 内容差命中。
    千元档覆盖报表主体以千元列示的公司（如比亚迪：财务报表及附注单位为千元）；
    百万档覆盖以百万元列报的港股/美股年报（v0.1.3，阿里巴巴 2026FY 实证：US GAAP 年报
    百万元列报，②级 207/233 miss 的根因；1 亿元=100 百万元，故 ×1e2）；
    比较取绝对值——A 股报表以括号表示负数（如「(3,247,033 )」），符号由 src 语境与①级负责。"""
    for m in PLAIN_NUM_RE.finditer(text):
        try:
            # 财报千位符数字（131,530）去逗号再解析——原 float() 直接拒逗号致②级对
            # 千位符整体失明（v0.1.3 阿里年报实证；A 股 md 同样带千位符）；
            # 全角减号同步归一（与①级 PLAIN_NUM_RE 同口径，v0.1.5）——float("−123")
            # 抛 ValueError 被下方 except 吞掉反而失明
            d = abs(float(m.group(0).replace(",", "").replace("−", "-")))
        except ValueError:
            continue
        for cand in (abs(v), abs(v) * 1e2, abs(v) * 1e4, abs(v) * 1e5, abs(v) * 1e8):
            if cand and abs(d - cand) / abs(cand) <= 0.05:
                return True
    return False


def check_json_vs_md(data, json_path, rep, verbose=False):
    """②级：data.json ↔ 原文 md（5% 容差 + 单位换算 + 行号窗 ±2）。
    回核面：三表 statements/parent_statements/notes + recon 勾稽块的数值键
    （cur/prev + 分部 rev_cur/rev_prev/cost_cur/cost_prev + 勾稽 lhs/rhs——
    与①级权威池同域；rev_factors/桥 delta 的 src 形态不一，不在面内）。
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
    _iter_metric_leaves(data.get("recon") or {}, ["recon"], leaves)
    checked = exact = shifted = no_src = 0
    misses = []
    for path, node in leaves:
        src = node.get("src") or ""
        lns = [int(x) for x in SRC_LINE_RE.findall(src)]
        if not lns:
            no_src += 1
            continue
        for key in ("cur", "prev", "rev_cur", "rev_prev", "cost_cur", "cost_prev", "lhs", "rhs"):
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


# ─────────────────────────── 13. 未披露声明反向检索（v0.0.20） ───────────────────────────

UNDISCLOSED_KW = [
    # (关键词, 声明模式)——白名单克制：首轮只「补充资料」（卫星化学 2026H1 失守模式固化）
    ("补充资料", re.compile(r"(?:无|未披露|缺乏|缺少|缺)[^，。；、]{0,15}补充资料")),
]


def check_undisclosed_claims(visible, data, json_path, rep):
    """未披露声明反向检索（v0.0.20，卫星化学 2026H1 实证固化）：
    报告声明「无/未披露/缺 X」时回原文 md 检索 X——md 命中即 FAIL（声明与原文矛盾）。
    防「提取漏项 + 错误常识合理化」失守模式：找不到就当未披露写进报告（如
    「A 股半年报不强制披露补充资料」），三道门禁无一拦截；首轮白名单只「补充资料」。"""
    md_rel = (data.get("meta") or {}).get("source_md")
    md_path = _resolve_md(md_rel, json_path)
    if md_path is None:
        rep.add(OK, "undisclosed", f"原文 md 未找到（{md_rel}），未披露声明反向检索未执行")
        return
    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    # 标签换成「，」（正则排除集内的字符）——等长屏蔽只留 9 个空格，仍会被
    # `[^，。；、]{0,15}` 跨过，把相邻单元格（如「无」+「补充资料口径待核」）拼成
    # 假「声明」；本检查不引行号，长度变化无副作用
    text = re.sub(r"<[^>]+>", "，", visible)
    bad = []
    for kw, pat in UNDISCLOSED_KW:
        claims = pat.findall(text)
        if claims and kw in md_text:
            bad.append(f"报告 {len(claims)} 处声明「{claims[0]}…」，但原文 md 含「{kw}」"
                       f"（{md_text.count(kw)} 次）——「未披露」声明与原文矛盾："
                       "回 Phase 1 补提取并改写报告，禁止凭常识降级")
    if bad:
        for b in bad:
            rep.add(FAIL, "undisclosed", b)
    else:
        rep.add(OK, "undisclosed", "未见与原文矛盾的「未披露」声明")


# ─────────── 断言填充截断检测（assert-trunc，T8①级同侧，v0.0.22） ───────────
# 本段不占规则序号：check_html.py 头部清单的序号是全局唯一口径（12/13/14 已被呈现
# 文本族与 dupont-stack 占用），T8 族在头部清单以「T8 回验族」一行整体登记。
# 上方「12.」「13.」是历史编号、与呈现文本族重号，本轮不动——改号会牵连文档指代。

# 截断判定下限：以 json 值前 ANCHOR_LEN 字为定位锚点，公共前缀达此长度才算「真前缀」
# （更短的公共前缀区分不了「截断」与「正常改写」）。
# debt: 天花板=HTML 侧呈现不足 ANCHOR_LEN 字时锚点找不到即漏检；调短锚点会抬高误报，
#       真实报告出现「截到 10 字以内」的形态时再降。
ANCHOR_LEN = 15


def check_assert_truncation(body, data, rep, verbose=False):
    """①级 HTML↔data.json 同侧：s4 断言表 text/evidence 填充截断检测（v0.0.22，
    长城 2026H1 事故固化：s4 断言表 63 个单元格文本以「…」结尾，底稿 assertions 里
    是完整句子，属填充方手工截断；T8 只比数字不比文本，全漏）。
    判定：以 json 值前 ANCHOR_LEN 字为定位锚点，在可见文本中逐处算与 json 值的最长
    公共前缀——达全长即完整呈现；真前缀紧接截断记号（全角「…」或 ASCII「...」）即
    「真前缀 + 省略号」填充截断形态，FAIL（明细带 HTML 行号）。截断点在前 30 字之后
    的（长城实证主流形态，如 evidence 第 58 字截断）同样命中。
    不判：json 值本身以「…」结尾的（底稿就写省略号）；「真前缀 + 等」是合法中文
    缩略形态，不纳入判据。
    另出 WARN：底稿 text/evidence 缺失、空串或不足 ANCHOR_LEN 字的断言——这类字段
    无锚点可判，且呈现层往往自撰文本（长城 A10：底稿 evidence 为空串、报告自撰 54 字
    并以「…」收尾，是全表 63 个省略号单元格里唯一逃过 FAIL 的一个），须回填底稿才有依据。"""
    items = data.get("assertions")
    if not isinstance(items, list) or not items:
        rep.add(OK, "assert-trunc", "底稿无 assertions 数组，填充截断检测跳过")
        return
    # 可见文本视图：标签等长屏蔽（保行号），实体还原后供前缀比较
    text = html.unescape(visible_text(body))
    hits = []
    gaps = []
    checked = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        aid = it.get("id") or "?"
        short = []
        for field in ("text", "evidence"):
            v = it.get(field)
            if not isinstance(v, str) or len(v) < ANCHOR_LEN:
                short.append(field)  # 底稿缺口：无锚点可判，转 WARN 清单
                continue
            if v.endswith("…"):
                continue
            checked += 1
            anchor = v[:ANCHOR_LEN]
            pos = text.find(anchor)
            full = False
            cut = cut_at = None
            while pos != -1:
                n = 0
                while n < len(v) and pos + n < len(text) and text[pos + n] == v[n]:
                    n += 1
                if n == len(v):
                    full = True
                    break
                # 截断记号：全角「…」或 ASCII「...」（切片越界得空串，无需边界判断）
                if text[pos + n:pos + n + 1] == "…" or text[pos + n:pos + n + 3] == "...":
                    cut, cut_at = n, pos  # 截断点即公共前缀长
                pos = text.find(anchor, pos + 1)
            if cut is not None and not full:
                hits.append(f"L{line_of(text, cut_at)} 断言 {aid} 的 {field} 被截断于第 {cut} 字"
                            f"（底稿全长 {len(v)} 字）：「{v[max(0, cut - 20):cut]}…」"
                            "——报告文本必须整句呈现，不许手工加省略号")
        if short:
            gaps.append((aid, short))
    if hits:
        details = hits
        if not verbose and len(details) > DETAIL_CAP:
            details = details[:DETAIL_CAP] + [f"…另有 {len(hits) - DETAIL_CAP} 处，用 --verbose 查看全部"]
        rep.add(FAIL, "assert-trunc",
                f"①级 HTML↔data.json：{len(hits)} 处断言文本被填充截断（checked {checked} 个字段）"
                "——底稿是完整句子，呈现层不许手工截断", details)
    elif checked:
        rep.add(OK, "assert-trunc",
                f"①级 HTML↔data.json：{checked} 个断言 text/evidence 字段未见填充截断形态")
    else:
        rep.add(OK, "assert-trunc",
                f"底稿无合格断言字段（text/evidence 缺失或不足 {ANCHOR_LEN} 字），填充截断检测跳过")
    if gaps:
        ids = "、".join(a for a, _ in gaps[:10])
        more = f"…（其余 {len(gaps) - 10} 条见明细）" if len(gaps) > 10 else ""
        rep.add(WARN, "assert-trunc",
                f"底稿 text/evidence 为空或不足 {ANCHOR_LEN} 字（{len(gaps)} 条：{ids}{more}）——回填底稿后再判呈现；"
                "呈现层文本须有底稿依据（长城 A10 自撰截断实证）",
                [f"断言 {a}：{'/'.join(f)} 缺失或不足 {ANCHOR_LEN} 字" for a, f in gaps])


