#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_regression.py — bo-financial-analyzer 的金标准回归测试

【它在测什么】
四个冻结样本（fixture）经 Phase 7.5 门禁 scripts/calc.py 后，必须同时满足门禁结论
与样本语义，用来抓「改坏门禁」这一类回归：
  · tests/moutai_2025.json     贵州茅台 2025 年报 —— 干净样本，抓**误报**（假阳性）
  · tests/kangdexin_2018.json  康得新 2018 年报   —— 造假样本，抓**漏报**（假阴性）
  · tests/vanke_2026h1.json    万科A 2026 半年报  —— 连亏地产样本（v0.0.17 固化）：
                               扣非双版/双驱动护栏的真实触发锚点 + fill 块级 note 保留
  · tests/wanhua_2026h1.json   万华化学 2026 半年报 —— 周期股样本（v0.0.18 固化，N3 落地）：
                               周期证据链 + 双驱动护栏第二真实样本 + ROIC/内生增长率首验锚点

断言清单
  [共同] calc.py exit code == 0（FAIL 清零），汇总 FAIL == 0
  [茅台] WARN == 0；recon 中 verdict 为「无法解释/可解释」的条目 == 0；
         v0.0.12 四项新检查（dupont/risk-models/stress/cash-ts）输出行存在
  [康得新] signals >= 11 条；其中 level=='r' 的红色信号 >= 6 条；
           recon 命中（verdict != 闭合）>= 3 条；Altman 复算被执行
  [万科] WARN == 2（interest_arrears + recon-coverage 两条合法 WARN）；
         dupont_dt.triggered（扣非双版）与 dupont.driver_fragile（双驱动）真实命中；
         Altman 危险区 + Ohlson 中；risk_models 块级 note 存活
门禁改钝（干净样本冒出 WARN、造假样本不再报警）都会让本脚本 exit 1。

【怎么跑】
    python tests/run_regression.py              # 简洁清单
    python tests/run_regression.py --verbose    # 附带 calc.py 的完整原始输出
    退出码：0 = 全部通过；1 = 有断言失败（清单里 ❌ 的行即原因）

【改动纪律】
只要动了 scripts/calc.py 或 references/extraction-schema.md，提交前必须跑本脚本，
且必须双例全绿；改错比率、删 src、破坏桥闭合等反例应能把它打红。

【实现约定】
  · 门禁结论走 subprocess 调 calc.py，只断言 exit code；
  · calc.py 打印的 `--- 汇总：FAIL x · WARN y · OK z · SKIP w ---` 是它唯一的机器可读
    摘要行，只解析这一行，不对彩色明细行做正则（脆）；
  · 业务断言全部直接读 fixture JSON，不经过 calc.py 的输出。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows 控制台默认 GBK，中文/emoji 会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError): pass

HERE = Path(__file__).resolve().parent          # …/bo-financial-analyzer/tests
SKILL = HERE.parent                             # …/bo-financial-analyzer
CALC = SKILL / "scripts" / "calc.py"

MOUTAI = HERE / "moutai_2025.json"
KANGDEXIN = HERE / "kangdexin_2018.json"
VANKE = HERE / "vanke_2026h1.json"
WANHUA = HERE / "wanhua_2026h1.json"
YINGHE = HERE / "yinghe_2026h1.json"

# calc.py 的汇总行（唯一机器可读摘要）
SUMMARY_RE = re.compile(
    r"---\s*汇总：FAIL\s*(\d+)\s*·\s*WARN\s*(\d+)\s*·\s*OK\s*(\d+)\s*·\s*SKIP\s*(\d+)\s*---"
)


class Case:
    """一个 fixture 的断言收集器：逐条记录通过/失败，最后统一汇报。"""

    def __init__(self, title, fixture):
        self.title = title
        self.fixture = fixture
        self.results = []       # (ok, desc)

    def expect(self, ok, desc):
        self.results.append((bool(ok), desc))
        return bool(ok)

    @property
    def failed(self):
        return [d for ok, d in self.results if not ok]


def run_calc(fixture, *extra):
    """在技能根目录下用当前解释器跑 calc.py（可带额外参数），返回 CompletedProcess。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    python = sys.executable
    return subprocess.run(
        [python, str(CALC), str(fixture), *extra],
        cwd=str(SKILL),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def parse_summary(stdout):
    """只取汇总行；取不到返回 None（视为门禁输出格式被改坏）。"""
    m = SUMMARY_RE.search(stdout or "")
    if not m:
        return None
    return dict(zip(("FAIL", "WARN", "OK", "SKIP"), (int(x) for x in m.groups())))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _prologue(case, proc, data, warn=None):
    """四例公共序言：exit 0 + 汇总行可解析 + FAIL==0 + schema 1.6（可选 WARN 数锚，
    warn=(期望值, 合法性说明)）。汇总行不可解析返回 None（调用方直接 return）。"""
    case.expect(proc.returncode == 0, f"calc.py exit 0（实际 {proc.returncode}）")
    summary = parse_summary(proc.stdout)
    if not case.expect(summary is not None, "汇总行可解析（calc.py 输出格式未变）"):
        return None
    case.expect(summary["FAIL"] == 0, f"FAIL == 0（实际 {summary['FAIL']}）")
    if warn is not None:
        case.expect(summary["WARN"] == warn[0],
                    f"WARN == {warn[0]}（{warn[1]}，实际 {summary['WARN']}）")
    case.expect((data.get("meta") or {}).get("schema_version") == "1.6",
                f"schema_version == 1.6（实际 {((data.get('meta') or {}).get('schema_version'))}）")
    return summary


def recon_hits(data):
    """verdict != 闭合 的 recon 条目（即门禁认定的勾稽异常）。"""
    return [(k, v.get("verdict")) for k, v in (data.get("recon") or {}).items()
            if isinstance(v, dict) and v.get("verdict") and v.get("verdict") != "闭合"]


def check_moutai(case, proc, data):
    """干净样本：抓误报。"""
    if _prologue(case, proc, data, (0, "干净样本零误报")) is None:
        return

    loose = [(k, v) for k, v in recon_hits(data) if v in ("无法解释", "可解释")]
    case.expect(not loose,
                f"recon 未闭合条目 == 0（实际 {len(loose)}）" +
                (f"：{', '.join(f'{k}={v}' for k, v in loose)}" if loose else ""))

    # 新检查项（T2 趋势比率逐期复算）必须真的被执行到，防止将来静默失效。
    # 断言对象是 calc.py 输出中 ratio-hist 行的存在（检查被执行），不是 OK/SKIP 计数
    case.expect("ratio-hist" in (proc.stdout or ""),
                "新检查生效：calc.py 输出含 ratio-hist 行（比率历史复算被执行）")
    # v0.0.12：杜邦连环替代/破产双模型/压力情景/现金时序四项检查必须被执行
    for code in ("dupont", "risk-models", "stress", "cash-ts"):
        case.expect(code in (proc.stdout or ""),
                    f"新检查生效：calc.py 输出含 {code} 行（v0.0.12 检查被执行）")
    # v0.0.15（schema 1.3）：杜邦下钻五检查必须被执行（dupont-dt/dupont5y/cycle-evidence/
    # threshold-check/peers；SKIP 也算执行——断言行的存在，不断言 OK/SKIP）
    for code in ("dupont-dt", "dupont5y", "cycle-evidence", "threshold-check", "peers"):
        case.expect(code in (proc.stdout or ""),
                    f"新检查生效：calc.py 输出含 {code} 行（v0.0.15 检查被执行）")

    # v0.0.15：五年累计归因闭合 + 分位边界 + 杠杆拆解（茅台特征值）
    d5 = (data.get("derived") or {}).get("dupont5y") or {}
    e = [d5.get(k) for k in ("margin_effect", "turnover_effect", "leverage_effect")]
    if all(isinstance(x, (int, float)) for x in e):
        prod_delta = d5.get("roe_product_cur", 0) - d5.get("roe_product_prev", 0)
        case.expect(abs(sum(e) - prod_delta) <= 0.005,
                    f"dupont5y 闭合：三效应加和 {sum(e):+.4f} ≈ Δ三因子积 {prod_delta:+.4f}")
        pg = d5.get("percentile") or {}
        pvals = [pg.get(k) for k in ("net_margin", "asset_turnover", "equity_multiplier")]
        case.expect(all(isinstance(p, (int, float)) and 0 <= p <= 1 for p in pvals),
                    f"因子分位 ∈[0,1]（实际 {pvals}）")
        case.expect(pg.get("net_margin") == 0.0,
                    f"茅台净利率处五年最低分位=0（实际 {pg.get('net_margin')}）——位置读数特征值")
    else:
        case.expect(False, f"dupont5y 三效应已填（实际 {e}）")
    ld = ((data.get("derived") or {}).get("dupont") or {}).get("leverage_drill") or {}
    case.expect(isinstance(ld.get("ni_share"), (int, float)) and ld["ni_share"] > 0.9,
                f"茅台无息占款占总杠杆 >90%（实际 {ld.get('ni_share')}）——话语权型杠杆特征值")

    # v0.0.17（schema 1.4）：ROIC 与内生增长率落库——茅台特征值锚定
    rr = ((data.get("derived") or {}).get("ratios")) or {}
    roic = (rr.get("roic") or {}).get("cur")
    case.expect(isinstance(roic, (int, float)) and roic > 0.3,
                f"茅台 ROIC >30%（实际 {roic}）——去杠杆口径下仍是高回报（N1 落地）")
    sgr = (rr.get("sustainable_growth") or {}).get("cur")
    case.expect(isinstance(sgr, (int, float)) and 0 < sgr < 0.15,
                f"茅台内生增长率 ∈(0,15%)（实际 {sgr}，留存率×ROE）——N2 落地")


def check_kangdexin(case, proc, data):
    """造假样本：抓漏报。"""
    if _prologue(case, proc, data) is None:
        return

    sigs = data.get("signals") or []
    case.expect(len(sigs) >= 11, f"signals 条数 >= 11（实际 {len(sigs)}）")
    reds = [s for s in sigs if isinstance(s, dict) and s.get("level") == "r"]
    case.expect(len(reds) >= 6, f"红色信号（level=='r'）>= 6（实际 {len(reds)}）")

    hits = recon_hits(data)
    case.expect(len(hits) >= 3,
                f"recon 命中（verdict != 闭合）>= 3（实际 {len(hits)}）" +
                (f"：{', '.join(f'{k}={v}' for k, v in hits)}" if hits else ""))

    # 新增检查项（P1-12/P1-15/P1-17 + recon 覆盖率）必须真的被执行到，防止将来静默失效。
    # 断言对象是 calc.py 输出中 recon-coverage 行的存在（检查被执行），不是 WARN 数量——
    # recon 覆盖率升级为硬门禁（--min-recon）后 WARN 计数会变化，断言不应随之假红
    case.expect("recon-coverage" in (proc.stdout or ""),
                "新检查生效：calc.py 输出含 recon-coverage 行（覆盖率检查被执行）")
    # v0.0.6 T9：D 组母公司单体勾稽（manual 型结构校验）必须真的被执行到
    case.expect("D1_parent_cash" in (proc.stdout or ""),
                "新检查生效：calc.py 输出含 D1_parent_cash 行（D 组母公司勾稽被执行）")
    # v0.0.12：造假样本的破产双模型必须真的算出来——锚定 OK 行（降级为 SKIP 即红，
    # 旧断言「输出含 Altman 字样」在 SKIP 文案带字时会假绿，v0.1.1 加固）
    case.expect(any("[OK" in l and "risk-models" in l and "Altman" in l
                    for l in (proc.stdout or "").splitlines()),
                "新检查生效：康得新 Altman 复算为 OK 行（非 SKIP 降级，v0.1.1 锚加固）")
    asserts = data.get("assertions") or []
    case.expect(len(asserts) >= 1, f"断言表已落库（assertions >= 1，实际 {len(asserts)}）")
    bad = [a for a in asserts if isinstance(a, dict) and a.get("verdict") == "不成立"]
    case.expect(len(bad) >= 1,
                f"判「不成立」的断言 >= 1 条（实际 {len(bad)}——空列表会让反证断言恒真，v0.1.1 补锚）")
    case.expect(all(a.get("evidence") for a in bad),
                f"判「不成立」的断言均带反证（{len(bad)} 条）")
    # v0.0.15（schema 1.3）：口径断裂样本的五年归因必须合法降级（整块缺失/null + SKIP 行）
    d5 = (data.get("derived") or {}).get("dupont5y") or {}
    case.expect(all(d5.get(k) is None for k in
                    ("margin_effect", "turnover_effect", "leverage_effect")),
                "康得新 dupont5y 三效应全 null（2019 追溯重述口径断裂，合法降级）")
    case.expect("dupont5y" in (proc.stdout or ""),
                "新检查生效：calc.py 输出含 dupont5y 行（降级路径被执行）")


def check_vanke(case, proc, data):
    """万科 2026H1 半年报（连亏地产）：扣非双版/双驱动护栏的真实触发样本（v0.0.17 固化）。"""
    # 已知合法 WARN 恰好 2 条：interest_arrears（单期付息错期）+ recon-coverage（B2/B3 附注未披露）
    if _prologue(case, proc, data, (2, "interest_arrears + recon-coverage 合法两条")) is None:
        return
    dd = data.get("derived") or {}
    case.expect((dd.get("dupont_dt") or {}).get("triggered") is True,
                "扣非双版真实触发（净利率口径差 1.59pct>1pct 路径；非经仅 7.4%）")
    dp = dd.get("dupont") or {}
    case.expect(dp.get("driver_fragile") is True and (dp.get("effects_ratio") or 9) < 1.5,
                f"双驱动护栏真实命中（effects_ratio={dp.get('effects_ratio')}）")
    rm = dd.get("risk_models") or {}
    case.expect((rm.get("altman_z") or {}).get("zone") == "危险"
                and (rm.get("ohlson_o") or {}).get("level") == "中",
                "破产双模型：Altman zone=危险 + Ohlson level=中（连亏地产特征值）")
    p5 = (dd.get("dupont5y") or {}).get("percentile") or {}
    case.expect(p5.get("equity_multiplier") == 1.0 and p5.get("net_margin") == 0.0,
                f"五年分位：杠杆满分位 1.0 + 净利率 0 分位（实际 {p5}）")
    for code in ("cycle-evidence", "threshold-check", "peers", "cash-ts"):
        case.expect(code in (proc.stdout or ""),
                    f"检查被执行：calc.py 输出含 {code} 行")
    # 块级 note 是判断字段（万科轮手写地产适用性声明）：fill 不得吞掉——v0.0.17 修掉的真缺陷
    case.expect(bool((rm.get("note") or "").strip()),
                "risk_models 块级 note（适用性声明）在 fill 后存活")
    # v0.0.17（schema 1.4）：连亏期 ROIC 为负、内生增长率按规则置 null（np_at≤0）
    rv = ((data.get("derived") or {}).get("ratios")) or {}
    case.expect(isinstance((rv.get("roic") or {}).get("cur"), (int, float))
                and rv["roic"]["cur"] < 0,
                f"万科 ROIC 为负（实际 {(rv.get('roic') or {}).get('cur')}）——连亏期去杠杆口径")
    case.expect((rv.get("sustainable_growth") or {}).get("cur") is None,
                "万科内生增长率 null（亏损期不计算，规则正确置空）")


def check_wanhua(case, proc, data):
    """万华化学 2026H1（v0.0.18 固化，N3 落地）：首份周期股报告底稿——
    周期证据链可复算 + 双驱动护栏第二真实样本 + ROIC/内生增长率首验锚点 +
    白描分位映射锚点（0.5/0.25/0.5 → 居中/第 2 低/居中）。"""
    if _prologue(case, proc, data,
                 (2, "interest_arrears 单期 + recon-coverage 16/17 合法两条")) is None:
        return
    meta = data.get("meta") or {}
    case.expect(meta.get("cycle_stage") == "上行" and meta.get("industry_profile") == "资源周期",
                f"周期股锚点：cycle_stage=上行 + industry_profile=资源周期"
                f"（实际 {meta.get('cycle_stage')}/{meta.get('industry_profile')}）")
    dd = data.get("derived") or {}
    dp = dd.get("dupont") or {}
    case.expect(dp.get("driver_fragile") is True and (dp.get("effects_ratio") or 9) < 1.5,
                f"双驱动护栏真实命中第二样本（effects_ratio={dp.get('effects_ratio')}）")
    case.expect((dd.get("dupont_dt") or {}).get("triggered") is False,
                "扣非双版未触发（非经 3.84%<20% 且口径差 <1pct，单版归因合法）")
    rv = dd.get("ratios") or {}
    roic = (rv.get("roic") or {}).get("cur")
    sgr = (rv.get("sustainable_growth") or {}).get("cur")
    case.expect(isinstance(roic, (int, float)) and abs(roic - 0.0543) < 5e-4,
                f"ROIC 复算锚点 0.0543（实际 {roic}）——v0.0.17 新槽位首验样本")
    case.expect(isinstance(sgr, (int, float)) and abs(sgr - 0.0541) < 5e-4,
                f"内生增长率复算锚点 0.0541（实际 {sgr}）")
    p5 = (dd.get("dupont5y") or {}).get("percentile") or {}
    case.expect(p5.get("net_margin") == 0.5 and p5.get("asset_turnover") == 0.25
                and p5.get("equity_multiplier") == 0.5,
                f"白描分位映射锚点：0.5/0.25/0.5 → 3/5 / 4/5 / 3/5（实际 {p5}）")
    cv = dd.get("cycle_evidence") or {}
    rg = cv.get("rev_growth") or []
    case.expect(len(rg) == 5 and rg[-1] is not None and abs(rg[-1] - 0.3126) < 5e-4,
                f"周期证据链：收入增速五期在库、末值 +31.26%（实际 {rg[-1] if rg else None}）")
    recon = data.get("recon") or {}
    case.expect(len(recon) == 16 and all((v or {}).get("verdict") for v in recon.values()),
                f"recon 覆盖 16/17（B2 附注未披露合法缺省，实际 {len(recon)} 条）")
    il = ((dd.get("threshold_check") or {}).get("incentive_line"))
    case.expect(isinstance(il, dict) and all(il.get(k) is None for k in
                ("actual", "target", "ratio", "share_payment", "hit")),
                "激励线「无计划」形态统一：全 null 对象（对齐 schema 与万科实践，v0.0.18 修）")
    # v1.5：segment_quadrant 首验锚点——delta 口径四行 + 象限归属 + 石化错位度 2（资源错配信号）
    sq = dd.get("segment_quadrant") or {}
    rows = sq.get("rows") or []
    case.expect(sq.get("y_mode") == "delta" and len(rows) == 4,
                f"segment_quadrant 落库：delta 口径 4 行（实际 {len(rows)} 行，y_mode={sq.get('y_mode')}）")
    case.expect([r.get("quadrant") for r in rows]
                == ["现金牛/潜力", "以量换价", "以量换价", "现金牛/潜力"],
                f"四象限归属锚点（实际 {[r.get('quadrant') for r in rows]}）")
    case.expect(len(rows) > 1 and rows[1].get("rank_gap") == 2,
                f"石化系列错位度 rank_gap=2（资源错配信号锚点，实际 {rows[1].get('rank_gap') if len(rows) > 1 else None}）")
    case.expect("segment-quadrant" in (proc.stdout or ""),
                "新检查生效：calc.py 输出含 segment-quadrant 行（v1.5 检查被执行）")
    for code in ("cycle-evidence", "dupont5y", "cash-ts"):
        case.expect(code in (proc.stdout or ""),
                    f"检查被执行：calc.py 输出含 {code} 行")


def report_case(case, proc, verbose):
    print(f"\n【{case.title}】{case.fixture.relative_to(SKILL)}")
    for ok, desc in case.results:
        print(f"  {'✅' if ok else '❌'} {desc}")
    if verbose:
        print("  ── calc.py 原始输出 ──")
        for line in (proc.stdout or "").rstrip().splitlines():
            print(f"  │ {line}")
        if proc.stderr and proc.stderr.strip():
            print("  ── stderr ──")
            for line in proc.stderr.rstrip().splitlines():
                print(f"  │ {line}")


def main():
    ap = argparse.ArgumentParser(description="bo-financial-analyzer 金标准回归测试")
    ap.add_argument("--verbose", action="store_true", help="附带 calc.py 的完整原始输出")
    args = ap.parse_args()

    # scripts 目录入 import 路径必须最先做（后续各构造块的 calc_*/check_html/render_report
    # import 全靠它；原先埋在中段，前置块提前 return 会跳过后续 import 的隐式顺序坑）
    sys.path.insert(0, str(SKILL / "scripts"))

    print("=== bo-financial-analyzer 金标准回归 · calc.py 四例 ===")
    print(f"技能根：{SKILL}")
    print(f"门禁：  {CALC}")

    missing = [p for p in (CALC, MOUTAI, KANGDEXIN, VANKE, WANHUA) if not p.exists()]
    if missing:
        for p in missing:
            print(f"❌ 缺少文件：{p}")
        print("\n--- 汇总：通过 0 · 失败 1 ---")
        return 1

    total = passed = 0

    def _block(title, checks, fail_msg):
        """打印一个断言块（【title】+ 逐条 ✅/❌）并计入总数；全绿返回 True，否则打印
        失败提示返回 False（调用方 return 1）。收编各版本构造块与 --fill/--min-recon/
        md_clean/公式直测块共 11 份同型「print + for + if not all」样板。"""
        nonlocal total, passed
        print(f"\n【{title}】")
        for ok, desc in checks:
            print(f"  {'✅' if ok else '❌'} {desc}")
            total += 1
            passed += bool(ok)
        if all(ok for ok, _ in checks):
            return True
        print(f"❌ 回归未通过：{fail_msg}")
        return False

    def _check_html(html, json_path=MOUTAI):
        """跑 check_html.py（默认配茅台底稿走 --json/T8 路径；json_path=None 则不带 --json）。"""
        cmd = [sys.executable, str(SKILL / "scripts" / "check_html.py"), str(html)]
        if json_path:
            cmd += ["--json", str(json_path)]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    cases = []
    for title, fixture, checker in (
        ("贵州茅台 2025 年报 · 干净样本（抓误报）", MOUTAI, check_moutai),
        ("康得新 2018 年报 · 造假样本（抓漏报）", KANGDEXIN, check_kangdexin),
        ("万科A 2026 半年报 · 连亏地产样本（扣非双版/双驱动真实触发）", VANKE, check_vanke),
        ("万华化学 2026 半年报 · 周期股样本（双驱动第二样本/ROIC·SGR 首验锚点）", WANHUA, check_wanhua),
    ):
        proc = run_calc(fixture)
        case = Case(title, fixture)
        try:
            data = load_json(fixture)
        except (OSError, json.JSONDecodeError) as e:
            case.expect(False, f"fixture 可解析为 JSON（{e}）")
            report_case(case, proc, args.verbose)
            cases.append(case)
            continue
        checker(case, proc, data)
        report_case(case, proc, args.verbose)
        cases.append(case)

    for case in cases:
        for ok, _ in case.results:
            total += 1
            passed += ok

    # 报告机检冒烟（P2 遗留项）：确认 check_html.py 可运行且各版本新检查存活——
    # 只断言输出中检查行的存在（防静默失效），不校验内容
    smoke = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "check_html.py"),
         str(SKILL / "assets" / "report-template.html")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    _so = smoke.stdout or ""
    smoke_checks = [
        (smoke.returncode in (0, 1) and "汇总" in _so,
         f"check_html.py 跑模板可运行（exit {smoke.returncode}）"),
        ("s8-shape" in _so, "s8-shape 检查存活（v0.0.6 下期跟踪清单阈值化）"),
        ("figtitle-style" in _so, "figtitle-style 检查存活（v0.0.7 结论式标题）"),
        (all(c in _so for c in ("abbrev", "ocf-bridge-shape", "figtitle-attribution",
                                "inspection-verdict")),
         "v0.0.12 四检查存活（缩写/桥项数/归因标题/判定列）"),
        ("s1-v15-shape" in _so, "s1-v15-shape 存活（v0.0.15；dupont-stack 走 T8 路径断言）"),
        (all(c in _so for c in ("internal-ref", "srcline-dup")), "v0.0.18 两检查存活"),
        (all(c in _so for c in ("recon-label", "decimal-places", "assertion-count")),
         "v0.0.19 三检查存活"),
        ("gap-declaration" in _so, "gap-declaration 存活（v0.0.21）"),
    ]
    if not _block("报告机检冒烟（check_html.py 跑模板）", smoke_checks,
                  "check_html.py 无法正常运行或新检查缺失。"):
        return 1

    def _run_html_str(s, json_path=MOUTAI):
        """HTML 片段写临时件跑机检（默认配茅台底稿；json_path=None 则不走 --json）——
        各版本构造反例共用。"""
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(s)
            tmp = f.name
        try:
            return _check_html(tmp, json_path)
        finally:
            os.unlink(tmp)

    # ── T8 数字回验三断言（v0.0.6）──
    # ①级：故意改错一个数字必须 FAIL 且指出位置；②级：src 行号回原文核对必须被执行
    # 改错版不落文件：运行时由正确版改数生成（两版唯一有效差异 1688.4 → 1688.9）
    t8_ok = _check_html(HERE / "t8_demo.html")
    _t8_txt = (HERE / "t8_demo.html").read_text(encoding="utf-8")
    if ">1688.4<" not in _t8_txt:
        raise RuntimeError("t8_demo.html 锚点数字形态变了？（着陆断言防 replace 落空；"
                           "裸 assert 在 python -O 下会被剥掉，v0.1.1 改 raise）")
    t8_bad = _run_html_str(_t8_txt.replace(">1688.4<", ">1688.9<"))
    t8_checks = [
        (t8_ok.returncode == 0,
         f"T8：正确样例 exit 0（实际 {t8_ok.returncode}）"),
        (t8_bad.returncode == 1 and "相近但不等" in (t8_bad.stdout or ""),
         f"T8①级：改错样例必 FAIL 且报疑似笔误（实际 exit {t8_bad.returncode}）"),
        ("json-md" in (t8_ok.stdout or ""),
         "T8②级：data.json↔原文 md 核对被执行（输出含 json-md 行）"),
        ("dupont-stack" in (t8_ok.stdout or ""),
         "v0.0.15：dupont-stack 堆叠条数据槽校验被执行（--json 路径）"),
    ]
    if not _block("T8 数字回验（check_html --json）", t8_checks,
                  "T8 数字回验断言失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.0.18 新规则构造用例（禁词 / 嵌套 srcline / 分位映射错配，各一反例）──
    _SECT = ('<div class="sect"><div class="secthead" id="s1"><span class="no">01</span>'
             '<span class="t">财务总览</span><span class="line"></span></div>')
    bad_ref = _run_html_str(
        _SECT + '<div class="card"><table class="data"><tr><th>指标</th></tr>'
        '<tr><td>净利率 <span class="badge der">推算</span></td></tr></table>'
        '<div class="srcline">逐条读数与出处见 data.json signals 块</div></div></div>')
    bad_nest = _run_html_str(
        _SECT + '<div class="card"><table class="data"><tr><th>指标</th></tr>'
        '<tr><td>净利率 <span class="badge der">推算</span></td></tr></table>'
        '<div class="srcline">来源：公司年报<div class="srcline">来源：公司年报</div></div></div>')
    bad_pct = _run_html_str(
        _SECT + '<div class="card"><table class="data">'
        '<tr><th>因子</th><th>当前值</th><th>五年位置</th></tr>'
        '<tr><td>净利率 <span class="badge der">推算</span></td><td>48.8%</td>'
        '<td><span class="badge disc">1/5</span></td></tr>'
        '<tr><td>总资产周转率</td><td>0.56</td><td><span class="badge disc">1/5</span></td></tr>'
        '<tr><td>权益乘数</td><td>1.20</td><td><span class="badge disc">2/5</span></td></tr>'
        '</table><div class="srcline">分位表演示</div></div></div>')
    v18_checks = [
        (bad_ref.returncode == 1 and "internal-ref" in (bad_ref.stdout or ""),
         "v0.0.18 构造用例：可见文本「见 data.json」必 FAIL（internal-ref）"),
        (bad_nest.returncode == 1 and "srcline-dup" in (bad_nest.stdout or ""),
         "v0.0.18 构造用例：嵌套 srcline 必 FAIL（srcline-dup）"),
        (bad_pct.returncode == 1 and "percentile-map" in (bad_pct.stdout or "")
         and "5/5" in (bad_pct.stdout or ""),
         "v0.0.18 构造用例：分位白描错配必 FAIL（percentile-map，茅台净利率 0 分位应标 5/5）"),
    ]
    if not _block("v0.0.18 新规则构造用例", v18_checks,
                  "v0.0.18 新规则构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.0.19 新规则构造用例（断言计数错配 FAIL / 旧长标签 WARN / 三位小数 WARN）──
    _SECT4 = ('<div class="sect"><div class="secthead" id="s4"><span class="no">04</span>'
              '<span class="t">管理层在说什么</span><span class="line"></span></div>')
    bad_ac = _run_html_str(
        _SECT4 + '<div class="card">'
        '<div class="figtitle">10 条重点断言：8 通过 / 1 不成立 / 2 无法验证</div>'
        '<table class="data"><tr><th>断言</th><th>三态</th></tr>'
        + '<tr><td>断言甲</td><td><span class="badge g">✅ 通过</span></td></tr>' * 7
        + '<tr><td>断言乙</td><td><span class="badge r">❌ 不成立</span></td></tr>'
        + '<tr><td>断言丙</td><td><span class="badge y">❓ 无法验证</span></td></tr>' * 2
        + '</table><div class="srcline">断言表演示</div></div></div>')
    warn_rl = _run_html_str(
        _SECT + '<div class="card"><table class="data"><tr><th>等式</th><th>三态</th></tr>'
        '<tr><td>A4 收入-收现</td><td><span class="badge y">⚠️ 可解释偏差</span></td></tr>'
        '</table><div class="srcline">勾稽表演示</div></div></div>')
    warn_dec = _run_html_str(
        _SECT + '<div class="card"><table class="data"><tr><th>科目</th><th>金额</th></tr>'
        '<tr><td>营业收入 <span class="badge disc">披露</span></td><td>1826.61009</td></tr>'
        '</table><div class="srcline">小数位演示</div></div></div>')
    v19_checks = [
        (bad_ac.returncode == 1 and "assertion-count" in (bad_ac.stdout or ""),
         "v0.0.19 构造用例：断言 figtitle「10 条=8+1+2」且表内仅 7✅ 必 FAIL（assertion-count）"),
        ("recon-label" in (warn_rl.stdout or ""),
         "v0.0.19 构造用例：旧长标签「可解释偏差」必出 WARN（recon-label）"),
        ("decimal-places" in (warn_dec.stdout or "")
         and "1826.61009" in (warn_dec.stdout or ""),
         "v0.0.19 构造用例：可见文本五位小数必出 WARN（decimal-places）"),
    ]
    if not _block("v0.0.19 新规则构造用例", v19_checks,
                  "v0.0.19 新规则构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.0.20 新规则构造用例（undisclosed 未披露声明反向检索：卫星化学失守模式固化）──
    def _run_html_json_md(html_s, md_s):
        """临时 HTML + 临时 md + 茅台 json（meta.source_md 改指临时 md）——
        undisclosed 依赖 --json 的 source_md 解析；茅台原文 md 不在库（回归自包含），
        故用临时 md 控制「补充资料」字样有无。"""
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html_s)
            tmp_html = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(md_s)
            tmp_md = f.name
        data = load_json(MOUTAI)
        data.setdefault("meta", {})["source_md"] = tmp_md
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            tmp_json = f.name
        try:
            return _check_html(tmp_html, tmp_json)
        finally:
            os.unlink(tmp_html)
            os.unlink(tmp_md)
            os.unlink(tmp_json)

    from calc_models import write_fillsheet

    def _fillsheet_slot(data, marker, terminator):
        """独立跑一次 write_fillsheet（临时 md），返回 marker 与 terminator 之间的槽体；
        marker 不存在返回 None。每次调用都重跑、不复用前块文本（防跨块隐式依赖静默
        断裂，v0.0.21 纪律）。"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            tmp = f.name
        try:
            write_fillsheet(data, tmp)
            seg = open(tmp, encoding="utf-8").read().split(marker, 1)
            return seg[1].split(terminator, 1)[0] if len(seg) == 2 else None
        finally:
            os.unlink(tmp)

    _DECL = ('<div class="card"><table class="data"><tr><th>指标</th></tr>'
             '<tr><td>净现比 <span class="badge der">推算</span></td></tr></table>'
             '<div class="srcline">半年报无现金流量表补充资料（A 股半年报不强制披露），调节项不可机检</div></div>')
    bad_und = _run_html_json_md(
        _SECT + _DECL, "| 项目 | 金额 |\n| 现金流量表补充资料 | 1.0 |\n")
    ok_und = _run_html_json_md(
        _SECT + _DECL, "| 项目 | 金额 |\n| 净利润 | 1.0 |\n")
    # M2 回归锚：cash_ts 均值缺省时 fillsheet 不得泄漏 Python repr
    # （`mean:None` 进 JS 字面量 = ReferenceError，整页图表全灭；ncrLine 的 mean!=null
    # 守卫要求生产者产出合法的 null）
    _data = load_json(MOUTAI)
    _data["derived"]["cash_ts"]["ncr_mean5"] = None
    _ncr_slot = _fillsheet_slot(_data, "const NCR_TS={", "};") or ""
    mean_null_ok = "mean:None" not in _ncr_slot and "mean:null" in _ncr_slot
    v20_checks = [
        (bad_und.returncode == 1 and "undisclosed" in (bad_und.stdout or ""),
         "v0.0.20 构造用例：声明「无补充资料」但 md 检出补充资料必 FAIL（undisclosed）"),
        ("undisclosed" in (ok_und.stdout or "") and "未见与原文矛盾" in (ok_und.stdout or ""),
         "v0.0.20 构造用例：md 真缺补充资料时 undisclosed 判 OK（不误报合法缺数声明）"),
        (mean_null_ok,
         "v0.0.20 构造用例：cash_ts 均值缺省时 fillsheet 产出 mean:null（JS 合法），不泄漏 Python repr（M2 锚）"),
    ]
    if not _block("v0.0.20 新规则构造用例", v20_checks,
                  "v0.0.20 新规则构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.0.21 新规则构造用例（gap-declaration：❓ 断言须进数据缺口声明行）──
    _S4_CARD = ('<div class="card">'
                '<div class="figtitle">2 条重点断言：1 通过 / 0 不成立 / 1 无法验证</div>'
                '<table class="data"><tr><th>断言</th><th>三态</th></tr>'
                '<tr><td>断言甲</td><td><span class="badge g">✅ 通过</span></td></tr>'
                '<tr><td>断言乙</td><td><span class="badge y">❓ 无法验证</span></td></tr>'
                '</table><div class="srcline">断言表演示</div>')
    bad_gap = _run_html_str(_SECT4 + _S4_CARD + '</div>')
    ok_gap = _run_html_str(
        _SECT4 + _S4_CARD +
        '<div class="srcline">数据缺口声明：断言乙——缺分部收入口径（分部附注可补）</div></div>')
    # SEG_ENDS 槽锚（v0.0.21）：fillsheet 必须产出合法 JS 数组字面量
    # （json.dumps 包裹，None→null——mean:None 整页图表全灭教训的同型防线）
    _seg_slot = _fillsheet_slot(load_json(MOUTAI),
                                "const SEG_ENDS=[", "];")
    seg_ends_ok = _seg_slot is not None and "None" not in _seg_slot
    v21_checks = [
        (bad_gap.returncode == 1 and "未见「数据缺口声明」行" in (bad_gap.stdout or ""),
         "v0.0.21 构造用例：❓ 断言无数据缺口声明行必 FAIL（gap-declaration）"),
        ("gap-declaration" in (ok_gap.stdout or "") and "声明行在位" in (ok_gap.stdout or ""),
         "v0.0.21 构造用例：❓ 断言带数据缺口声明行判 OK（不误报）"),
        (seg_ends_ok,
         "v0.0.21 构造用例：fillsheet 产出 const SEG_ENDS=[…] 合法 JS（无 Python None 泄漏）"),
    ]
    if not _block("v0.0.21 新规则构造用例", v21_checks,
                  "v0.0.21 新规则构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.0.22 新规则构造用例（长城 2026H1 填充事故复盘：JS 团灭 + 断言截断）──
    # js-dup-decl 内联复刻长城事故形态：OCF_END 顶层重复声明（整段 script SyntaxError）；
    # TREND 单份 + 两函数内局部 const W 为块级作用域合法重名，不得误报
    _dup = _run_html_str(
        _SECT + '<div class="card"><table class="data">'
        '<tr><th>指标</th><th>本期</th></tr>'
        '<tr><td>经营现金流净额（亿元） <span class="badge disc">披露</span></td><td>104.4</td></tr>'
        '</table><div class="srcline">数据来源：构造样本（js-dup-decl 验收用例）</div></div></div>'
        '<script>\nconst TREND=[1,2,3];\nconst OCF_END=104.36;\nconst OCF_END=0;\n'
        'function drawTrend(){\n const W=600,H=200;\n return W+H;\n}\n'
        'function drawBridge(){\n const W=500;\n return W;\n}\n</script>',
        json_path=None)
    # assert-trunc 内联复刻长城填充截断事故：A1 text 真前缀 24 字 +「…」截断（底稿完整句）
    # 必 FAIL；A1 evidence 与 A2 text/evidence 完整呈现，不得误报
    _trunc_json = {"meta": {"company": "构造样本", "code": "000000", "period": "2026H1",
                            "report_type": "半年报", "unit": "亿元"},
                   "assertions": [
                       {"id": "A1",
                        "text": "公司披露的海外收入创历史新高与分部附注增速及海关出口数据方向一致，宣称有多源交叉证据支撑。",
                        "evidence": "分部附注海外收入同比增长四成以上，海关同期出口数据同向增长，两个来源口径一致。",
                        "verdict": "通过"},
                       {"id": "A2",
                        "text": "管理层宣称的毛利率提升主要来自原材料成本下降与高端产品结构改善。",
                        "evidence": "成本附注显示主要原材料采购价格回落，分部毛利率表显示高端产品线收入占比上升。",
                        "verdict": "不成立"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(_SECT4 + '<div class="card">'
                '<div class="figtitle">2 条断言：1 通过 / 1 不成立 / 0 无法验证</div>'
                '<table class="data"><tr><th class="txt">断言</th><th class="txt">验证证据</th>'
                '<th class="txt">判定</th><th class="txt">出处</th></tr>'
                '<tr><td>A1 公司披露的海外收入创历史新高与分部附注增速及海关…</td>'
                '<td class="txt">分部附注海外收入同比增长四成以上，海关同期出口数据同向增长，两个来源口径一致。</td>'
                '<td class="txt"><span class="badge g">✅ 通过</span></td><td class="txt">分部附注</td></tr>'
                '<tr><td>A2 管理层宣称的毛利率提升主要来自原材料成本下降与高端产品结构改善。</td>'
                '<td class="txt">成本附注显示主要原材料采购价格回落，分部毛利率表显示高端产品线收入占比上升。</td>'
                '<td class="txt"><span class="badge r">❌ 不成立</span></td><td class="txt">成本附注</td></tr>'
                '</table><div class="srcline">数据来源：构造样本（assert-trunc 验收用例）</div></div></div>')
        _th = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(_trunc_json, f, ensure_ascii=False)
        _tj = f.name
    try:
        _trunc = _check_html(_th, _tj)
    finally:
        os.unlink(_th)
        os.unlink(_tj)
    # 不命中对照：顶层单份 const + 函数内局部 const W/H（块级作用域合法重名）不得误报
    _nodup = _run_html_str(
        _SECT + '<div class="card"><table class="data"><tr><th>指标</th></tr>'
        '<tr><td>净利率</td></tr></table><div class="srcline">对照</div></div></div>'
        '<script>\nconst TREND={a:1};\nfunction f(){\n const W=1;const H=2;\n return W+H;\n}\n</script>')
    # EFF_TS/TREND 新槽锚：fillsheet 必须产出两槽且为合法 JS（无 Python None 泄漏）
    _eff_slot = _fillsheet_slot(load_json(MOUTAI),
                                "const EFF_TS={", "};") or ""
    eff_ok = all(k in _eff_slot for k in ("dio:", "dso:", "ccc:")) and "None" not in _eff_slot
    _tr_slot = _fillsheet_slot(load_json(MOUTAI),
                               "const TREND={", "};") or ""
    trend_ok = all(k in _tr_slot for k in ("ocf:", "rd:")) and "None" not in _tr_slot
    v22_checks = [
        # 断言钉「[FAIL] 规则名」整段而非只查 code：OK 行同样含 code，仅查 code 不具鉴别力
        (_dup.returncode == 1 and "[FAIL] js-dup-decl" in (_dup.stdout or "")
         and "OCF_END" in (_dup.stdout or ""),
         "v0.0.22 构造用例：const 顶层重复声明必 FAIL（js-dup-decl，长城 JS 团灭复盘）"),
        ("无重名" in (_nodup.stdout or ""),
         "v0.0.22 构造用例：顶层单份 const + 函数内局部 const 不误报（js-dup-decl 判据=行首顶层）"),
        # 计数锚带全角冒号前缀：裸「1 处」会被「11 处」子串命中
        (_trunc.returncode == 1 and "[FAIL] assert-trunc" in (_trunc.stdout or "")
         and "A1 的 text" in (_trunc.stdout or "")
         and "：1 处断言文本被填充截断" in (_trunc.stdout or ""),
         "v0.0.22 构造用例：断言 text 截断必 FAIL（assert-trunc；同 json 完整断言不误报）"),
        (eff_ok and trend_ok,
         "v0.0.22 构造用例：fillsheet 产出 EFF_TS/TREND（含 ocf/rd）槽合法 JS（无 None 泄漏）"),
    ]
    if not _block("v0.0.22 新规则构造用例", v22_checks,
                  "v0.0.22 新规则构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.0.23 新规则构造用例（海康回填轮：四宫格混入非 svg 撑破 2×2）──
    _GRID4_OK = ('<div class="grid2"><svg id="revchart"></svg><svg id="npchart"></svg>'
                 '<svg id="effline"></svg><svg id="capexbars"></svg></div>')
    bad_grid4 = _run_html_str(
        _SECT + '<div class="grid2"><svg id="revchart"></svg>'
        '<div class="takeaway">读法行混进来了</div><svg id="capexbars"></svg></div></div>')
    ok_grid4 = _run_html_str(_SECT + _GRID4_OK + '</div>')
    v23_checks = [
        (bad_grid4.returncode == 1 and "[FAIL] s1-grid4" in (bad_grid4.stdout or ""),
         "v0.0.23 构造用例：四宫格 grid2 混入 takeaway/表格必 FAIL（s1-grid4，海康回填实证）"),
        ("㗊型在位" in (ok_grid4.stdout or ""),
         "v0.0.23 构造用例：四宫格纯 svg 四件判 OK（不误报；降级删 svg 同构合法）"),
    ]
    if not _block("v0.0.23 新规则构造用例", v23_checks,
                  "v0.0.23 新规则构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── 分位白描映射双写契约锁（v0.0.18）：check_html_text.py 与 calc_models.py 各持一份
    # PCTILE_LABEL（跨家族 import 会造成耦合，故双写；check_html.py 再导出本锁的 import 锚点），
    # 本断言防单边漂移（sys.path 已在 fill 冒烟前插入）
    from check_html import PCTILE_LABEL as _PL_CHECK
    from calc_models import PCTILE_LABEL as _PL_FILL
    if not _block("分位白描映射契约锁",
                  [(_PL_CHECK == _PL_FILL,
                    "check_html.PCTILE_LABEL == calc_models.PCTILE_LABEL")],
                  "白描映射双写漂移，同步两处后再提交。"):
        return 1

    # ── 渲染测量条件冒烟（v0.0.9 L2）──
    # Chrome/Edge 可用时对 t8_demo.html 跑 check_render 期望 exit 0；
    # 不可用打印 SKIP 不计入断言（渲染门禁本体是可选门禁，环境无关时不假红）
    render_smoke = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "check_render.py"),
         str(HERE / "t8_demo.html")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    render_out = render_smoke.stdout or ""
    if "渲染门禁跳过" in render_out:
        print("\n【渲染测量冒烟】check_render.py：SKIP（本机无 Chrome/Edge，可选门禁不阻塞）")
    elif not _block("渲染测量冒烟",
                    [(render_smoke.returncode == 0 and "渲染测量 0 问题" in render_out,
                      f"check_render.py 跑 t8_demo.html：exit {render_smoke.returncode}")],
                    "渲染测量冒烟未绿，看上方 check_render 输出。"):
        return 1

    # ── effline 标签堆栈避让构造用例（v0.0.23）──
    # 海康 2026H1 真实缠绕数据（DIO/DSO/CCC 挤 224~389 天、同期三标签同 x）：
    # v0.0.22 两档固定槽实证 5 处重叠、viewBox 拉高无效。从模板实时抽取 <script> 并换入
    # 缠绕 EFF_TS 构造最小页面（只含 effline svg，其余图表调用因元素缺席自动 no-op），
    # check_render 期望 0 问题；无浏览器时随渲染门禁一并 SKIP 不计断言
    if "渲染门禁跳过" in render_out:
        print("\n【effline 标签避让构造用例】SKIP（本机无 Chrome/Edge，随渲染门禁一并跳过）")
    else:
        _tpl = (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
        _js = re.search(r"<script>(.*?)</script>", _tpl, re.S).group(1)
        _eff = ("const EFF_TS={labels:['2022H1','2023H1','2024H1','2025H1','2026H1'],"
                "dio:[332.98,342.02,308.27,304.46,389.21],"
                "dso:[270.82,298.9,321.51,317.49,224.49],"
                "ccc:[321.51,356.38,337.93,321.31,285.93]};")
        _js = re.sub(r"const EFF_TS=\{.*?\};", _eff, _js, count=1)
        if "332.98" not in _js:
            raise RuntimeError("模板 EFF_TS 槽替换失败——槽形态变了？（裸 assert 在 -O 下失效，v0.1.1 改 raise）")
        _page = ("<!doctype html><html lang=\"zh-Hans\"><head><meta charset=\"utf-8\"><style>"
                 ":root{--bg:#fff;--ink:rgb(58,42,28);--muted:rgba(58,42,28,.6);"
                 "--faint:rgba(58,42,28,.32);--grid:rgba(58,42,28,.16);--card:#fff;"
                 "--data:rgb(171,94,38);--data2:rgb(203,158,108);--faintdata:rgb(233,213,187);"
                 "--der:rgb(122,84,52);--good:#0F7B4F;--warn:#B8860B;--bad:#C0392B}"
                 "body{padding:40px 20px}.sheet{width:100%;max-width:1040px;margin:0 auto}"
                 "svg{width:100%;height:auto;display:block}</style></head><body>"
                 "<div class=\"sheet\"><svg id=\"effline\" viewBox=\"0 0 460 250\" "
                 "preserveAspectRatio=\"xMidYMid meet\"></svg></div>"
                 f"<script>{_js}</script></body></html>")
        _tmp = HERE / "_effline_avoid_demo.html"
        _tmp.write_text(_page, encoding="utf-8")
        try:
            _r = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_render.py"),
                                 str(_tmp)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
            _eff_ok = _r.returncode == 0 and "渲染测量 0 问题" in (_r.stdout or "")
            if not _eff_ok:
                print(_r.stdout)
        finally:
            _tmp.unlink(missing_ok=True)
        if not _block("effline 标签避让构造用例（v0.0.23，海康缠绕数据）",
                      [(_eff_ok, "check_render 0 问题——同期标签无互撞、零轴不误画")],
                      "effline 避让失效，看上方 check_render 输出。"):
            return 1

    # ── svgclip 文本出界构造用例 + deltaBars 长标签端到端（v0.0.25）──
    # 赢合 2026H1 实证：segbridge 类目标签「锂电池专用生产设备」（9 全角字）在固定
    # L=86 下左端探出 SVG 视口被裁，而旧判据对 svg 内元素免测——三道门禁全绿漏检、
    # 靠用户目检发现。两个子用例：①静态页 svg 内 text x=-30 必命中 svgclip 且 exit 1
    # （检测器阳性）；②模板 JS + 赢合真实长标签 SEG_BRIDGE 走 deltaBars——自适应 L
    # 生效则 0 问题（修复回归锁）。无浏览器时随渲染门禁一并 SKIP 不计断言
    if "渲染门禁跳过" in render_out:
        print("\n【svgclip 出界 + deltaBars 长标签构造用例】SKIP（本机无 Chrome/Edge，随渲染门禁一并跳过）")
    else:
        _tmp = HERE / "_svgclip_demo.html"
        _tmp.write_text(
            "<!doctype html><html lang=\"zh-Hans\"><head><meta charset=\"utf-8\"></head>"
            "<body><div class=\"sheet\"><svg id=\"demo\" viewBox=\"0 0 200 100\">"
            "<text x=\"-30\" y=\"50\" font-size=\"10\">出界文字</text>"
            "</svg></div></body></html>", encoding="utf-8")
        try:
            _r = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_render.py"),
                                 str(_tmp)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
            _clip_ok = _r.returncode == 1 and "svgclip" in (_r.stdout or "")
            if not _clip_ok:
                print(_r.stdout)
        finally:
            _tmp.unlink(missing_ok=True)
        _tpl = (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
        _js = re.search(r"<script>(.*?)</script>", _tpl, re.S).group(1)
        _js = re.sub(r"const SEG_BRIDGE=\[.*?\];",
                     "const SEG_BRIDGE=[['锂电池专用生产设备',22.26],"
                     "['其他业务（含电子烟）',-4.0]];", _js, count=1)
        _js = re.sub(r"const SEG_ENDS=\[.*?\];", "const SEG_ENDS=[42.64,60.9];",
                     _js, count=1)
        if "锂电池专用生产设备" not in _js:
            raise RuntimeError("模板 SEG_BRIDGE 槽替换失败——槽形态变了？（裸 assert 在 -O 下失效，v0.1.1 改 raise）")
        _page = ("<!doctype html><html lang=\"zh-Hans\"><head><meta charset=\"utf-8\"><style>"
                 ":root{--bg:#fff;--ink:rgb(58,42,28);--muted:rgba(58,42,28,.6);"
                 "--faint:rgba(58,42,28,.32);--grid:rgba(58,42,28,.16);--card:#fff;"
                 "--data:rgb(171,94,38);--data2:rgb(203,158,108);--faintdata:rgb(233,213,187);"
                 "--der:rgb(122,84,52);--good:#0F7B4F;--warn:#B8860B;--bad:#C0392B}"
                 "body{padding:40px 20px}.sheet{width:100%;max-width:1040px;margin:0 auto}"
                 "svg{width:100%;height:auto;display:block}</style></head><body>"
                 "<div class=\"sheet\"><svg id=\"segbridge\" viewBox=\"0 0 960 200\" "
                 "preserveAspectRatio=\"xMidYMid meet\"></svg></div>"
                 f"<script>{_js}</script></body></html>")
        _tmp2 = HERE / "_segbridge_long_label_demo.html"
        _tmp2.write_text(_page, encoding="utf-8")
        try:
            _r2 = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_render.py"),
                                  str(_tmp2)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            _seg_ok = _r2.returncode == 0 and "渲染测量 0 问题" in (_r2.stdout or "")
            if not _seg_ok:
                print(_r2.stdout)
        finally:
            _tmp2.unlink(missing_ok=True)
        if not _block("svgclip 出界检测 + deltaBars 长标签端到端（v0.0.25，赢合实证）",
                      [(_clip_ok, "静态出界 text 必命中 svgclip 且 exit 1"),
                       (_seg_ok, "赢合长标签 SEG_BRIDGE 自适应 L 后渲染 0 问题")],
                      "看上方 check_render 输出。"):
            return 1

    # ── check_render 探测器阳性（v0.1.1 审计补口：五类探测器此前只有 svgclip 有阳性，
    # empty-svg/overlap 置空变异回归全绿——长城事故补口规则恰恰没有「破坏必红」锁）──
    if "渲染门禁跳过" in render_out:
        print("\n【check_render 探测器阳性】SKIP（本机无 Chrome/Edge，随渲染门禁一并跳过）")
    else:
        _tmpe = HERE / "_empty_svg_demo.html"
        _tmpe.write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head><body>'
            '<div class="sheet"><svg id="ncrline" viewBox="0 0 460 250"></svg></div></body></html>',
            encoding="utf-8")
        try:
            _re = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_render.py"),
                                  str(_tmpe)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            _esvg_ok = _re.returncode == 1 and "empty-svg" in (_re.stdout or "")
            if not _esvg_ok:
                print(_re.stdout)
        finally:
            _tmpe.unlink(missing_ok=True)
        _tmpo = HERE / "_overlap_demo.html"
        _tmpo.write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head><body>'
            '<div class="sheet"><svg id="demo" viewBox="0 0 200 100">'
            '<text x="50" y="50" font-size="10">重叠标签甲甲乙乙</text>'
            '<text x="52" y="51" font-size="10">重叠标签丙丙丁丁</text>'
            '</svg></div></body></html>',
            encoding="utf-8")
        try:
            _ro2 = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_render.py"),
                                   str(_tmpo)], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            _ovl_ok = _ro2.returncode == 1 and "overlap" in (_ro2.stdout or "")
            if not _ovl_ok:
                print(_ro2.stdout)
        finally:
            _tmpo.unlink(missing_ok=True)
        if not _block("check_render 探测器阳性（v0.1.1 审计补口）",
                      [(_esvg_ok, "空 svg 必命中 empty-svg 且 exit 1（长城团灭补口规则锁）"),
                       (_ovl_ok, "同位两 text 必命中 overlap 且 exit 1")],
                      "check_render 探测器阳性失效，看上方输出。"):
            return 1

    # ── render_report 重放金标准 + fillsheet 逐字锁（v0.1.0，N4 fill→render）──
    # 赢合 fixture 全链：临时副本 --fill（write_fillsheet 必须与金标准逐字一致——
    # 重构回归锁）→ render_report（锚自检 exit 0）→ 产物关键槽文本命中 +
    # check_html FAIL 仅 placeholder 一类（机械数字天生过 T8① 笔误检测）。
    # 赢合 fixture 直接跑 --fill 会重写 fixture（json.dump 整文件），一律用临时副本
    _work = HERE / "_render_replay"
    _work.mkdir(exist_ok=True)
    try:
        _cp = _work / "yinghe.json"
        shutil.copy(HERE / "yinghe_2026h1.json", _cp)
        _r = subprocess.run([sys.executable, str(SKILL / "scripts" / "calc.py"),
                             str(_cp), "--fill"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        _mdp = _work / "yinghe.fillsheet.md"
        _md = _mdp.read_text(encoding="utf-8") if _mdp.exists() else ""
        _gold = (HERE / "yinghe_2026h1.fillsheet.golden.md").read_text(encoding="utf-8")
        _out = _work / "yinghe.html"
        _rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                              str(_cp), "-o", str(_out)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        _html = _out.read_text(encoding="utf-8") if _out.exists() else ""
        _holes = _html.count("{{")
        _cko = ""
        if _out.exists():
            _ck = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_html.py"),
                                  str(_out), "--json", str(_cp)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            _cko = _ck.stdout or ""
        _fails = [l for l in _cko.splitlines() if l.startswith("🔴")]
        if not _block("render_report 重放金标准（v0.1.0 N4，赢合全链）",
                      [(_r.returncode == 0, f"calc --fill exit {_r.returncode}"),
                       (_md == _gold, "fillsheet.md 与金标准逐字一致（write_fillsheet 重构锁）"),
                       (_rr.returncode == 0
                        and "分析 — Bo-FinancialAnalyzer</title>" in _html
                        and "BO-FINANCIALANALYZER · " in _html
                        and "— financial-report-analysis</title>" not in _html
                        and "FINANCIAL REPORT ANALYSIS" not in _html,
                        f"render 锚自检 exit {_rr.returncode}（{(_rr.stdout or '')[:200]}）；"
                        "成品品牌 Bo-FinancialAnalyzer/BO-FINANCIALANALYZER 且旧品牌清零"),
                       ('const SEG_BRIDGE=[["锂电池专用生产设备", 22.26]' in _html,
                        "SEG_BRIDGE 分部轴机械生成（by_segment Δ）"),
                       ("64.58 倍" in _html
                        and "10 条断言：8 通过 / 0 不成立 / 2 无法验证" in _html,
                        "检验卡读数/断言计数前缀命中"),
                       (100 < _holes < 400, f"判断孔数 {_holes} 在 100~400 区间"),
                       (_fails and all("placeholder" in l for l in _fails),
                        f"check_html FAIL 仅 placeholder 一类（实际 {[l[4:28] for l in _fails]}）"),
                       (not any("num-vs-json" in l or "internal-ref" in l for l in _fails),
                        "T8①/internal-ref 零命中（FAIL 行内无此二类）")],
                      "render 重放失败，看上方明细。"):
            return 1
        # 渲染子断言（随渲染门禁 SKIP 降级）
        if "渲染门禁跳过" in render_out:
            print("\n【render 重放渲染测量】SKIP（本机无 Chrome/Edge，随渲染门禁一并跳过）")
        elif _out.exists():
            _r3 = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_render.py"),
                                  str(_out)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            _r3_ok = _r3.returncode == 0 and "渲染测量 0 问题" in (_r3.stdout or "")
            if not _r3_ok:
                print(_r3.stdout)
            if not _block("render 重放渲染测量（v0.1.0）",
                          [(_r3_ok, "check_render 0 问题——JS 槽/行生成结构健康")],
                          "render 产物渲染异常，看上方 check_render 输出。"):
                return 1
        # ncrline hist<3 降级构造用例（v0.1.0 热核审计补口，无真实样本）：ocf hist 砍到
        # 2 期（末位保持=cur 免得撞 hist 校验）+ 删 derived.cash_ts 旧块（否则 fill 重算
        # 失败时旧块残留、ncr_drop 不触发）→ render 须删 ncrline svg + figtitle 降级声明
        _d2 = json.loads((HERE / "yinghe_2026h1.json").read_text(encoding="utf-8"))
        _ocf = _d2["statements"]["cashflow"]["ocf"]
        _ocf["hist"] = [_ocf["hist"][-2], _ocf["cur"]]
        _d2["derived"].pop("cash_ts", None)
        _cp2 = _work / "yinghe_ncr2.json"
        _cp2.write_text(json.dumps(_d2, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, str(SKILL / "scripts" / "calc.py"),
                        str(_cp2), "--fill"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        _out2 = _work / "yinghe_ncr2.html"
        _rr2 = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                               str(_cp2), "-o", str(_out2)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        _h2 = _out2.read_text(encoding="utf-8") if _out2.exists() else ""
        if not _block("ncrline hist<3 降级构造用例（v0.1.0）",
                      [(_rr2.returncode == 0, f"降级路径 render exit {_rr2.returncode}"),
                       ('id="ncrline"' not in _h2, "ncrline svg 已删"),
                       ('<div class="figtitle">现金含量证据不足' in _h2,
                        "figtitle 降级声明在（注意 srcline 原文含该词，须带 figtitle 前缀判定）")],
                      "ncrline 降级路径失效。"):
            return 1
        # 茅台（年报·净调整<0 分流形态）槽链覆盖（v0.1.4）：与赢合 gap>0 双源汇入
        # 双形态对照——fill+render 管道产出桑基卡且机检 sankey-slot 判 OK
        _cpm = _work / "moutai.json"
        shutil.copy(MOUTAI, _cpm)
        subprocess.run([sys.executable, str(CALC), str(_cpm), "--fill"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        _outm = _work / "moutai.html"
        subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                        str(_cpm), "-o", str(_outm)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        _htm = _outm.read_text(encoding="utf-8") if _outm.exists() else ""
        _ckm = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_html.py"),
                               str(_outm), "--json", str(_cpm)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace") if _outm.exists() else None
        if not _block("render 重放·茅台（gap<0 分流形态，v0.1.4）",
                      [('const SANKEY={"pt": "本期"' in _htm, "茅台 SANKEY 槽填充（本期口径）"),
                       ('"gap": -237.88' in _htm, "净调整负值进槽（分流形态数据）"),
                       (_ckm is not None and "[OK  ] sankey-slot" in (_ckm.stdout or ""),
                        "check_html sankey-slot 判 OK")],
                      "茅台 render 重放失败，看上方明细。"):
            return 1
        # 桑基整卡降级构造用例（v0.1.4）：净利改负 → compute_sankey 返回 None →
        # 槽 null → render 删 svg + figtitle 换声明（对齐 ncr_drop 形态）
        _d3 = json.loads((HERE / "yinghe_2026h1.json").read_text(encoding="utf-8"))
        _d3["statements"]["income"]["np_total"]["cur"] = -3.68
        _d3["statements"]["income"]["np_at"]["cur"] = -3.51
        _cp3 = _work / "yinghe_sankey_drop.json"
        _cp3.write_text(json.dumps(_d3, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, str(CALC), str(_cp3), "--fill"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        _out3 = _work / "yinghe_sankey_drop.html"
        _rr3 = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                               str(_cp3), "-o", str(_out3)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        _h3 = _out3.read_text(encoding="utf-8") if _out3.exists() else ""
        if not _block("sankey 降级构造用例（v0.1.4）",
                      [(_rr3.returncode == 0, f"降级路径 render exit {_rr3.returncode}"),
                       ('id="sankey"' not in _h3, "sankey svg 已删（empty-svg 门禁兼容）"),
                       ('<div class="figtitle">资金流向桑基图不适用' in _h3,
                        "figtitle 降级声明在"),
                       ('const SANKEY=null;' in _h3, "SANKEY 槽为 null（JS 守卫 no-op）")],
                      "sankey 降级路径失效。"):
            return 1
    finally:
        shutil.rmtree(_work, ignore_errors=True)

    # ── --fill 幂等金标准（v0.0.13；v0.0.17 起字符串叶含 note/src 纳入精确比对）──
    # 数值容差 5e-4；字符串叶（driver/zone/note/src 等）必须逐字不变——万科轮实证：
    # fill 吞掉 risk_models 块级 note，旧比对跳过 note/src 所以这一类缺陷不可见
    def _leaves(node, pre=""):
        out = {}
        if isinstance(node, dict):
            for k, v in node.items():
                out.update(_leaves(v, pre + k + "."))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                out.update(_leaves(v, pre + str(i) + "."))
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            out[pre[:-1]] = node
        elif isinstance(node, (str, bool)):
            out[pre[:-1]] = node   # bool 叶纳入（triggered/driver_fragile 等是 fill 输出），
        return out                 # 否则 fill 翻转布尔幂等照绿（v0.1.1 盲区修复）

    fill_checks = []
    with tempfile.TemporaryDirectory() as td2:
        for fx in ("moutai_2025.json", "kangdexin_2018.json", "vanke_2026h1.json",
                   "wanhua_2026h1.json"):
            src = HERE / fx
            dst = Path(td2) / fx
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SKILL / "scripts" / "calc.py"),
                                str(dst), "--fill"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            a = _leaves(json.loads(src.read_text(encoding="utf-8"))["derived"])
            b = _leaves(json.loads(dst.read_text(encoding="utf-8"))["derived"])
            # 键集必须先完全相等（缺失/新增键直接列出）——(x or 0) 会把「键缺失 vs
            # 值≈0」压进容差内假绿；bool/str 叶精确比对，数值叶容差 5e-4（v0.1.1 加固）
            bad = sorted(set(a) ^ set(b))
            for k in sorted(set(a) & set(b)):
                x, y = a.get(k), b.get(k)
                if isinstance(x, (str, bool)) or isinstance(y, (str, bool)):
                    if x != y:
                        bad.append(k)
                elif abs((x or 0) - (y or 0)) > 5e-4:
                    bad.append(k)
            fill_checks.append((r.returncode == 0 and not bad,
                                f"--fill 幂等 {fx[:4]}…：exit 0 且 derived 不变（差异键 {bad[:3]}）"))
            # fillsheet JS 槽形态冒烟（v0.0.19）：`('…',)` 元组 repr 是 f-string 把 JS 逗号
            # 误写进插值大括号的特征（美的轮 TREND 槽 np:('…',) 笔误实证，幂等比对照不出来）
            fs_text = (Path(td2) / (dst.stem + ".fillsheet.md")).read_text(encoding="utf-8")
            leak = re.search(r"\('[^']*',\)", fs_text)
            fill_checks.append((leak is None,
                                f"--fill JS 槽形态 {fx[:4]}…：fillsheet 无元组 repr 泄漏"
                                + (f"（命中 {leak.group(0)[:30]}…）" if leak else "")))
    gate_help = subprocess.run([sys.executable, str(SKILL / "scripts" / "gate.py"), "--help"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    fill_checks.append((gate_help.returncode == 0, "gate.py 单入口可运行（--help exit 0）"))
    # v0.0.17：ts_fetch 冒烟——零测试短板补齐（只验可运行与用法文本，不触网）
    ts_help = subprocess.run([sys.executable, str(SKILL / "scripts" / "ts_fetch.py"), "--help"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
    fill_checks.append((ts_help.returncode == 0 and "api_name" in (ts_help.stdout or ""),
                        "ts_fetch.py 取数通道可运行（--help exit 0 且含 api_name）"))
    if not _block("--fill 幂等金标准（v0.0.13）+ 单入口冒烟", fill_checks,
                  "--fill 幂等或 gate.py / ts_fetch.py 断言失败。"):
        return 1

    # ── --min-recon 硬门禁（v0.0.17，任务 5）：康得新 14/17——阈值 15 必 FAIL、14 通过 ──
    mr15 = run_calc(KANGDEXIN, "--min-recon", "15")
    mr14 = run_calc(KANGDEXIN, "--min-recon", "14")
    mr_checks = [
        (mr15.returncode == 1 and "未达 --min-recon 15" in (mr15.stdout or ""),
         f"--min-recon 15：康得新 14/17 未达标 exit 1（实际 exit {mr15.returncode}）"),
        (mr14.returncode == 0,
         f"--min-recon 14：康得新 14/17 达标 exit 0（实际 exit {mr14.returncode}）"),
        (parse_summary(mr15.stdout or "") is not None
         and parse_summary(mr15.stdout)["FAIL"] >= 1,
         "--min-recon 15：FAIL 计入汇总行（recon-coverage 升 FAIL）"),
    ]
    if not _block("--min-recon 硬门禁（v0.0.17）", mr_checks,
                  "--min-recon 硬门禁断言失败。"):
        return 1

    # ── md_clean 金标准（v0.0.17 自包含化）：合成样本 tests/md_clean_synth.md ──
    # 覆盖全部四类历史病理：pre/post 碎行拼回、重复分隔行去重、页眉页脚删除、
    # 空单元格行保留、pending_pre 顶替不丢文本、编号小标题不并行。
    # 不再依赖被 .gitignore 排除的真实报告 md（新机器 clone 后回归必红的 🔴 项已修）；
    # 本机存量真实 md 改为「存在才跑」的加成校验，打印 INFO、不计断言（断言数跨环境确定）。
    synth = HERE / "md_clean_synth.md"
    md_checks = []
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                            str(synth), "--out-dir", td],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout or ""
        clean_path = Path(td) / (synth.stem + ".clean.md")
        text = clean_path.read_text(encoding="utf-8") if clean_path.exists() else ""
        idx_path = Path(td) / (synth.stem + ".index.json")
        idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
        n_sep = sum(1 for l in text.splitlines()
                    if re.match(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$", l))
        md_checks = [
            (r.returncode == 0 and "不变量违反" not in out,
             "md_clean 合成样本：exit 0 且双不变量通过"),
            ("| 销售商品、提供劳务收到的现 金 | 2,345.67" in text,
             "pre 碎行拼回（断字结尾的标签并入下一表行）"),
            ("| 管理费用 | 88.88" in text,
             "post 碎行拼回（首格为空的行向后取标签）"),
            ("已计提未支付的利息费用" in text,
             "pending_pre 被顶替时落独立行保文本（不静默丢）"),
            ("公告编号" not in text and "测试股份有限公司 2026 年半年度报告" not in text,
             "页眉页脚删除（公告字样/纯页码/重复报告标题行）"),
            (n_sep == 3, f"重复分隔行去重（3 张表各留首条，实际 {n_sep}）"),
            ("| | |" in text, "空单元格行保留（不被当分隔行误删）"),
            ("一、 主要会计数据" in text, "编号小标题不并入表行（散文豁免）"),
            (len(idx.get("sections") or []) >= 5 and len(idx.get("blocks") or {}) >= 2,
             f"索引产出：sections={len(idx.get('sections') or [])} ≥5 / "
             f"blocks={len(idx.get('blocks') or {})} ≥2"),
        ]
        # v0.1.1 审计补口两构造：孤立「|」管道行不得吞 pre 碎行（修复前碎行被 consumed
        # 后静默丢、统计还虚报拼回数）；文中独立数字行不得当页码误删（修复前散文间的
        # 「2024」被删且页码类删除不计入数字不变量，双不变量结构性失明）
        for name, md_text, must_in in (
            ("_audit_frag",
             "第三节 管理层讨论与分析\n报告期内公司营业收入 1,234.56 亿元。\n"
             "| 项目 | 本期 |\n| --- | --- |\n| 货币资金 | 530.80 |\n"
             "经营活动现金流量净额\n|\n| 1,234.56 |\n\n报告期内公司继续经营中，无重大变化。\n",
             "经营活动现金流量净额"),
            ("_audit_year",
             "第一节 重要提示\n本公司 2023 年完成重组，各项工作有序推进。\n\n2024\n\n"
             "公司实现营业收入 1,234.56 亿元，同比增长，经营情况稳定向好发展。\n",
             "2024"),
        ):
            _f2 = Path(td) / f"{name}.md"
            _f2.write_text(md_text, encoding="utf-8")
            _rr2 = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                                   str(_f2), "--out-dir", td],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            _c2p = Path(td) / f"{name}.clean.md"
            _c2 = _c2p.read_text(encoding="utf-8") if _c2p.exists() else ""
            md_checks.append((_rr2.returncode == 0 and must_in in _c2,
                              f"v0.1.1 构造：{name[7:]} 形态 exit 0 且「{must_in}」保留不丢"))
        # 加成校验：本机若存有真实报告 md（不入库），跑一遍双不变量作参考
        for md_name in ("贵州茅台2025年年度报告.md", "康得新2018年年度报告.md"):
            md_src = SKILL.parent / "reports" / "archive" / "原始报告" / md_name
            if not md_src.exists():
                continue
            rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                                 str(md_src), "--out-dir", td],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(f"  ℹ️ 加成（不计断言）：md_clean {md_name[:4]}… "
                  f"exit {rr.returncode}（本机存量真实 md）")
    if not _block("md_clean 金标准（v0.0.17 合成样本，自包含）", md_checks,
                  "md_clean 金标准断言失败。"):
        return 1

    # ── v0.0.15 构造用例（公式层直测，不动 fixture 文件）──
    # 扣非双版触发 / 双驱动护栏 / 话语权型杠杆升档——两条规则无真实 fixture 覆盖
    # （茅台非经 0.03% 不触发、杠杆非主驱动），用 deepcopy 构造临界场景验证
    import copy
    import calc_dupont

    constructed = []
    base = load_json(MOUTAI)

    d1 = copy.deepcopy(base)
    d1["statements"]["income"]["np_dt"]["cur"] = \
        d1["statements"]["income"]["np_at"]["cur"] * 0.7   # 非经占比 30% → 触发双版
    r1 = calc_dupont.compute_dupont_dt(d1)
    closed1 = (r1.get("margin_effect") is not None
               and abs(r1["margin_effect"] + r1["turnover_effect"] + r1["leverage_effect"]
                       - (r1["roe_product_cur"] - r1["roe_product_prev"])) <= 0.005)
    constructed.append((r1.get("triggered") is True and closed1,
                        "构造·扣非双版：非经 30% → triggered=True 且三效应恒等闭合"))

    d2 = copy.deepcopy(base)
    d2["derived"]["ratios"]["net_margin"]["prev"] = 0.5085  # |净利率效应|≈|周转率效应|
    r2 = calc_dupont.compute_dupont(d2)
    ratio2 = (r2 or {}).get("effects_ratio")
    constructed.append((bool(r2) and r2.get("driver_fragile") is True
                        and ratio2 is not None and ratio2 < 1.5,
                        f"构造·双驱动护栏：effects_ratio={ratio2:.2f} <1.5 → driver_fragile=True"
                        if ratio2 else "构造·双驱动护栏：compute_dupont 返回 None（不应发生）"))

    d3 = copy.deepcopy(base)
    d3["derived"]["ratios"]["equity_multiplier"]["prev"] = 1.42  # 杠杆效应放大为主驱动
    r3 = calc_dupont.compute_dupont(d3)
    ld3 = (r3 or {}).get("leverage_drill") or {}
    constructed.append((bool(r3) and r3.get("driver") == "杠杆"
                        and ld3.get("quality_upgrade") is True,
                        f"构造·话语权型杠杆升档：杠杆主驱动+无息占比 {ld3.get('ni_share')} "
                        f"+ΔDFL {ld3.get('dfl_delta')} → quality_upgrade=True"))
    if not _block("v0.0.15 构造用例（扣非双版/双驱动/升档）", constructed,
                  "v0.0.15 构造用例断言失败。"):
        return 1

    # ── v1.5 构造用例（segment-quadrant：填错 quadrant 必 FAIL；选填缺省合法由
    # 茅台/康得新/万科三例天然覆盖——它们无此键且 calc exit 0）──
    import calc as _calc
    from calc_common import Report as _Rep, FAIL as _FAIL
    d4 = copy.deepcopy(load_json(WANHUA))
    d4["derived"]["segment_quadrant"]["rows"][1]["quadrant"] = "明星"   # 石化复算=以量换价
    rep4 = _Rep()
    _calc.check_segment_quadrant(d4, rep4)
    # 声明 delta 但 cost_prev 缺 null：期望按数据形态算（y_mode FAIL），不得崩溃
    d5 = copy.deepcopy(load_json(WANHUA))
    d5["statements"]["income"]["by_segment"][0]["cost_prev"] = None
    rep5 = _Rep()
    _calc.check_segment_quadrant(d5, rep5)
    if not _block("v1.5 构造用例（segment-quadrant）",
                  [(any(lv == _FAIL and "quadrant" in msg for lv, _, msg in rep4.rows),
                    "v1.5 构造用例：四象限填错 quadrant 必 FAIL（segment-quadrant）"),
                   (any(lv == _FAIL and "y_mode" in msg for lv, _, msg in rep5.rows),
                    "v1.5 构造用例：声明 delta 但 cost_prev 缺 null → y_mode FAIL 且不 crash")],
                  "v1.5 构造用例断言失败。"):
        return 1

    # ── calc FAIL 判据阳性（v0.1.1 全库审计补口）──
    # 变异实证：四例都是合法样本只断言 exit 0，门禁 FAIL 判据被改钝/误删时回归照样全绿
    # （M4 check_signals 清空、M5 ratio-hist FAIL→WARN 均无感）。每个破坏样本锁一片
    # FAIL 分支（exit 1 + 关键码），v0.1.1 修复的新判据同锁。
    def _run_calc_json(obj, name):
        """破坏样本写临时 json 跑 calc.py（calc FAIL 判据阳性用例共用；不动 fixture 原文件）。"""
        with tempfile.NamedTemporaryFile("w", suffix="_" + name, delete=False,
                                         encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            tmp = f.name
        try:
            return run_calc(Path(tmp))
        finally:
            os.unlink(tmp)

    d_src = copy.deepcopy(base)
    del d_src["statements"]["balance"]["cash"]["src"]          # ① 出处链命门
    r_src = _run_calc_json(d_src, "del_src.json")
    d_hole = copy.deepcopy(base)
    d_hole["statements"]["balance"]["hole_test"] = {"cur": 1.0}  # ② 孤儿 cur 叶子（曾静默吞）
    r_hole = _run_calc_json(d_hole, "hole.json")
    d_ratio = copy.deepcopy(base)
    d_ratio["derived"]["ratios"]["roe"]["cur"] += 0.05         # ③ 比率 derived 改错
    r_ratio = _run_calc_json(d_ratio, "bad_ratio.json")
    d_str = copy.deepcopy(base)
    d_str["derived"]["ratios"]["roe"]["cur"] = "5.2%"          # ④ 字符串 cur（曾 traceback）
    r_str = _run_calc_json(d_str, "str_cur.json")
    d_hye = copy.deepcopy(load_json(WANHUA))
    d_hye["statements"]["balance"]["ar"]["prev"] = None        # ⑤ hist_ye 脱钩（曾静默）
    r_hye = _run_calc_json(d_hye, "hye.json")
    d_st = copy.deepcopy(load_json(WANHUA))
    d_st["derived"]["stress"]["scenarios"] = d_st["derived"]["stress"]["scenarios"][:1]  # ⑥ 截断
    r_st = _run_calc_json(d_st, "stress.json")
    d_avg = copy.deepcopy(load_json(VANKE))
    d_avg["statements"]["balance"]["payable"]["prev"] = None   # ⑦ avg 不再期末冒充平均
    r_avg = _run_calc_json(d_avg, "avg.json")
    d_sk = copy.deepcopy(load_json(YINGHE))
    d_sk["derived"]["sankey"]["np_at"] += 1                    # ⑨ 桑基科目改错（v0.1.4）
    r_sk = _run_calc_json(d_sk, "sankey.json")
    # ⑧ effects_ratio=null 合法形态（直测）：三效应全零时 check_dupont 不得逼分析师造数
    d_er = copy.deepcopy(base)
    for _nm in ("net_margin", "asset_turnover", "equity_multiplier"):
        d_er["derived"]["ratios"][_nm]["cur"] = d_er["derived"]["ratios"][_nm]["prev"]
    c_er = calc_dupont.compute_dupont(d_er)
    d_er["derived"]["dupont"].update({
        "margin_effect": c_er["margin_effect"], "turnover_effect": c_er["turnover_effect"],
        "leverage_effect": c_er["leverage_effect"],
        "roe_product_cur": c_er["roe_product_cur"], "roe_product_prev": c_er["roe_product_prev"],
        "closure_gap": c_er["closure_gap"], "effects_ratio": None, "driver": None,
        "driver_fragile": None, "driver_second": None, "margin_drill": None})
    if isinstance(d_er["derived"]["dupont"].get("leverage_drill"), dict):
        d_er["derived"]["dupont"]["leverage_drill"]["quality_upgrade"] = None
    rep_er = _Rep()
    _calc.check_dupont(d_er, rep_er)
    fails_er = [m for lv, _, m in rep_er.rows if lv == _FAIL]
    calc_pos_checks = [
        (r_src.returncode == 1 and "src" in (r_src.stdout or ""),
         "阳性①：删 src 必 exit 1（structure/src 出处链判据）"),
        (r_hole.returncode == 1 and "hole_test" in (r_hole.stdout or ""),
         "阳性②：孤儿 {cur:x} 叶子必 exit 1（walk_leaves 不再静默吞，v0.1.1）"),
        (r_ratio.returncode == 1 and "复算不符" in (r_ratio.stdout or ""),
         "阳性③：比率 derived 改错必 exit 1（ratio 判据）"),
        (r_str.returncode == 1 and "Traceback" not in (r_str.stderr or "")
         and "类型非法" in (r_str.stdout or ""),
         "阳性④：ratios.cur 字符串必出可读 type FAIL 不崩堆栈（v0.1.1）"),
        (r_hye.returncode == 1 and "脱钩" in (r_hye.stdout or ""),
         "阳性⑤：hist_ye 非空 + prev 缺失必 exit 1（hist 脱钩判据，v0.1.1）"),
        (r_st.returncode == 1 and "scenarios 条数" in (r_st.stdout or ""),
         "阳性⑥：stress 截断必 exit 1（不再 zip 假通过，v0.1.1）"),
        (r_avg.returncode == 1 and "不足以复算" in (r_avg.stdout or "")
         and "dpo 复算不符" not in (r_avg.stdout or ""),
         "阳性⑦：payable.prev 缺失 → dpo/ccc 报「不足以复算」WARN、ni_prev/hist_ye 脱钩 "
         "FAIL 如实指出修复点——avg 不再产出退化值逼分析师改错 derived（v0.1.1）"),
        (c_er["effects_ratio"] is None and not fails_er,
         "阳性⑧：三效应全零 + effects_ratio=null 合法形态 check_dupont 零 FAIL"
         "（不再逼分析师造数，v0.1.1）"),
        (r_sk.returncode == 1 and "sankey" in (r_sk.stdout or ""),
         "阳性⑨：桑基科目值改错必 exit 1（sankey 复算比对，v0.1.4）"),
    ]
    if not _block("calc FAIL 判据阳性（v0.1.1 审计补口）", calc_pos_checks,
                  "calc FAIL 判据阳性失效——门禁对坏数据失语，逐条核对上方 ❌。"):
        return 1

    # ── check_html FAIL 判据阳性（v0.1.1 全库审计补口）──
    # 变异实证：hardrule/required/dupont-stack 三条 FAIL→WARN 回归全绿（冒烟只查存在性）。
    # 本块给这三条补上「破坏必红」，并把 v0.1.1 判据修复一并锁死。
    hr_bad = _run_html_str(_SECT + '<style>.x{background:linear-gradient(#fff,#000)}</style></div>')
    hr_note = _run_html_str(_SECT + '<style>/* 纪律：禁用渐变 gradient() */</style></div>')
    hr_cdn = _run_html_str(_SECT + '<script src="//cdn.example.com/a.js"></script></div>')
    req_bad = _run_html_str(_SECT + '<div class="card"><p>正文</p></div></div>')
    ir_new = _run_html_str(_SECT + '<div class="card"><p>流程版本 v0.1.0 设定</p></div></div>')
    ds_bad = _run_html_str(
        _SECT + '<div class="card"><p>杜邦</p></div></div>'
        '<script>const DUPONT_STACK={"steps": [["净利率", 9.9], ["周转率", 9.9], ["杠杆", 9.9]],'
        ' "gap": 9.9};</script>')
    _dum = (load_json(MOUTAI).get("derived") or {}).get("dupont") or {}
    _p1x = lambda x: None if x is None else round(x * 100, 1)
    ds_ok = _run_html_str(
        _SECT + '<div class="card"><p>杜邦</p></div></div>'
        f'<script>const DUPONT_STACK={{"steps": [["净利率", {_p1x(_dum.get("margin_effect"))}],'
        f' ["周转率", {_p1x(_dum.get("turnover_effect"))}], ["杠杆", {_p1x(_dum.get("leverage_effect"))}]],'
        f' "gap": {_p1x(_dum.get("closure_gap"))}}};</script>')
    _GAP_ROWS = ('<table class="data"><tr><th>断言</th><th>三态</th></tr>'
                 '<tr><td>应收账款增速高于收入增速</td>'
                 '<td><span class="badge y">❓ 无法验证</span></td></tr>'
                 '<tr><td>毛利率提升源于产品结构升级</td>'
                 '<td><span class="badge y">❓ 无法验证</span></td></tr></table>')
    gap_half = _run_html_str(
        _SECT4 + '<div class="card">'
        '<div class="figtitle">2 条断言：0 通过 / 0 不成立 / 2 无法验证</div>' + _GAP_ROWS +
        '<div class="srcline">数据缺口声明：应收账款增速高于收入增速——缺分部口径</div></div></div>')
    gap_full = _run_html_str(
        _SECT4 + '<div class="card">'
        '<div class="figtitle">2 条断言：0 通过 / 0 不成立 / 2 无法验证</div>' + _GAP_ROWS +
        '<div class="srcline">数据缺口声明：应收账款增速高于收入增速——缺分部口径；'
        '毛利率提升源于产品结构升级——缺销量结构</div></div></div>')
    und_cross = _run_html_json_md(
        _SECT + '<div class="card"><table class="data"><tr><td>无</td><td>补充资料口径待核</td></tr>'
        '</table><div class="srcline">对照</div></div></div>',
        "| 现金流量表补充资料 | 1.0 |\n")
    # T8① 全角阈值符号豁免（v0.1.1）：挑一个「窗内偏移后不在 hist_pool 显示精度内」的
    # 独特 % 值——全角＞/半角&gt; 同样不 FAIL（豁免行为一致），裸写无符号必 FAIL（判据没松）
    from check_html_t8 import build_authority as _ba
    _uniq_pct, _hist_pool = _ba(load_json(MOUTAI))[3:5]
    _v0 = None
    for _cand, _cpath in _uniq_pct:
        _dv = round(_cand * 0.999, 2)
        if abs(_dv - _cand) / max(abs(_cand), 1e-9) <= 0.0015 \
                and not any(abs(h - _dv) <= 0.005 for h, _ in _hist_pool):
            _v0 = _dv
            break
    t8_fw = t8_hw = t8_bare = None
    if _v0 is not None:
        t8_fw = _run_html_str(_SECT + f'<div class="card"><p>利用率＞{_v0:.2f}%</p></div></div>')
        t8_hw = _run_html_str(_SECT + f'<div class="card"><p>利用率&gt;{_v0:.2f}%</p></div></div>')
        t8_bare = _run_html_str(_SECT + f'<div class="card"><p>利用率 {_v0:.2f}%</p></div></div>')
    # SANKEY 数据槽正反构造（v0.1.4）：正确判 OK / 改值必 FAIL
    from calc_slots import build_sankey_slot as _bsk
    _ysk = _bsk(load_json(YINGHE))
    sk_ok = _run_html_str(_SECT + '<div class="card"><p>桑基</p></div></div>'
                          '<script>const SANKEY=' + json.dumps(_ysk, ensure_ascii=False)
                          + ';</script>', YINGHE)
    _skbd = json.loads(json.dumps(_ysk))
    _skbd["rev"] = round(_skbd["rev"] + 1, 2)
    sk_bad = _run_html_str(_SECT + '<div class="card"><p>桑基</p></div></div>'
                           '<script>const SANKEY=' + json.dumps(_skbd, ensure_ascii=False)
                           + ';</script>', YINGHE)
    html_pos_checks = [
        (hr_bad.returncode == 1 and "[FAIL] hardrule" in (hr_bad.stdout or ""),
         "阳性①：真渐变 background:linear-gradient 必 FAIL（hardrule）"),
        ("✅" in "".join(l for l in (hr_note.stdout or "").splitlines() if "hardrule" in l),
         "阳性②：style 注释里的「禁用渐变 gradient()」纪律文字不误报（v0.1.1）"),
        (hr_cdn.returncode == 1 and "[FAIL] hardrule" in (hr_cdn.stdout or ""),
         "阳性③：协议相对外链 //cdn 必 FAIL（hardrule 逃逸口封堵，v0.1.1）"),
        (req_bad.returncode == 1 and "[FAIL] required" in (req_bad.stdout or ""),
         "阳性④：缺页脚免责/跟踪清单必 FAIL（required）"),
        (ir_new.returncode == 1 and "[FAIL] internal-ref" in (ir_new.stdout or ""),
         "阳性⑤：现行版本号 v0.1.0 可见文本必 FAIL（internal-ref 不再只认 v0.0.x，v0.1.1）"),
        (ds_bad.returncode == 1 and "[FAIL] dupont-stack" in (ds_bad.stdout or ""),
         "阳性⑥：堆叠条错数据必 FAIL（dupont-stack——存在性断言测不出的形态）"),
        ("dupont-stack" in (ds_ok.stdout or "") and "一致" in (ds_ok.stdout or "")
         and "[FAIL] dupont-stack" not in (ds_ok.stdout or ""),
         "阳性⑦：fill 新 json 形态正确值判 OK（dupont-stack 双形态兼容，v0.1.1）"),
        (gap_half.returncode == 1 and "未逐条覆盖" in (gap_half.stdout or ""),
         "阳性⑧：❓ 两条只声明一条必 FAIL（gap-declaration 逐条判据，v0.1.1）"),
        ("[FAIL] gap-declaration" not in (gap_full.stdout or "")
         and "逐条覆盖" in (gap_full.stdout or ""),
         "阳性⑨：❓ 逐条声明判 OK（gap-declaration 不误报；构造片段无页脚，"
         "required FAIL 与本规则无关不查 exit）"),
        ("未见与原文矛盾" in (und_cross.stdout or ""),
         "阳性⑩：相邻单元格「无」+「补充资料」不拼假声明（undisclosed 跨格误报修复，v0.1.1）"),
        (t8_fw is not None and "[FAIL] num-vs-json" not in (t8_fw.stdout or "")
         and "[FAIL] num-vs-json" not in (t8_hw.stdout or "")
         and "[FAIL] num-vs-json" in (t8_bare.stdout or ""),
         f"阳性⑪：T8① 全角＞/半角&gt; 阈值语境同豁免、裸写窗内值必 FAIL"
         f"（全角符号补豁免且判据未松，v0.1.1；取值 {_v0}）"),
        ("[OK  ] sankey-slot" in (sk_ok.stdout or "") and "一致" in (sk_ok.stdout or ""),
         "阳性⑫：SANKEY 槽正确值判 OK（sankey-slot，v0.1.4）"),
        ("[FAIL] sankey-slot" in (sk_bad.stdout or ""),
         "阳性⑬：SANKEY 槽改值必 FAIL（sankey-slot，v0.1.4）"),
    ]
    if not _block("check_html FAIL 判据阳性（v0.1.1 审计补口）", html_pos_checks,
                  "check_html FAIL 判据阳性失效，逐条核对上方 ❌。"):
        return 1

    # ── render 断锚与降级路径阳性（v0.1.1 全库审计补口）──
    # 断锚 exit 1 此前无阳性（变异实证：断锚 return 1→0 回归全绿）；六条降级路径此前
    # 只有 ncr_drop 有构造用例——模板缩进/结构调整会让降级静默失效而无人知。
    import render_report
    with tempfile.TemporaryDirectory() as _tdr:
        _wr = Path(_tdr)
        _cpr = _wr / "yinghe.json"
        shutil.copy(HERE / "yinghe_2026h1.json", _cpr)
        subprocess.run([sys.executable, str(CALC), str(_cpr), "--fill"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        # ① 断锚必 exit 1 + 打印断锚清单（锚复制成双份；import 级换 TEMPLATE 指向，
        #    不改仓库模板文件，finally 还原）
        _tplr = _wr / "tpl_dup.html"
        _tplr.write_text(
            (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
            .replace("<h1>{{公司名}}（{{代码}}）</h1>",
                     "<h1>{{公司名}}（{{代码}}）</h1>\n<h1>{{公司名}}（{{代码}}）</h1>"),
            encoding="utf-8")
        import io as _io
        from contextlib import redirect_stdout as _rso
        _old_tpl = render_report.TEMPLATE
        _old_argv = sys.argv
        _buf = _io.StringIO()
        try:
            render_report.TEMPLATE = _tplr
            sys.argv = ["render_report.py", str(_cpr), "-o", str(_wr / "dup.html")]
            with _rso(_buf):
                _rc_anchor = render_report.main()
        finally:
            render_report.TEMPLATE = _old_tpl
            sys.argv = _old_argv
        anchor_fail = _rc_anchor == 1 and "断锚" in _buf.getvalue()

        def _replay(mutate, name):
            """yinghe 副本改一处 → --fill → render（降级路径构造用例共用）。"""
            d = json.loads((HERE / "yinghe_2026h1.json").read_text(encoding="utf-8"))
            mutate(d)
            cp = _wr / f"{name}.json"
            cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(CALC), str(cp), "--fill"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = _wr / f"{name}.html"
            rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                 str(cp), "-o", str(out)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
            return rr, (out.read_text(encoding="utf-8") if out.exists() else "")

        rr_h, h_holders = _replay(
            lambda d: d["notes"]["shareholders"].pop("holder_ts", None), "yh_holders")
        rr_c, h_cip = _replay(lambda d: d["notes"].pop("cip_projects", None), "yh_cip")

        def _no_missing(d):
            for a in d.get("assertions") or []:
                a.pop("missing", None)
        rr_g, h_gap = _replay(_no_missing, "yh_gap")

        def _seg_off(d):
            d["statements"]["income"]["by_segment"][0]["rev_cur"] += 5.0
        rr_s, h_seg = _replay(_seg_off, "yh_seg")
        rr_o, h_ocf = _replay(lambda d: d["derived"].pop("ocf_bridge", None), "yh_ocf")
    render_pos_checks = [
        (anchor_fail, "断锚阳性：锚复制成双份必 exit 1 且打印断锚清单（v0.1.1）"),
        (rr_h.returncode == 0 and 'id="holders"' not in h_holders
         and "时序不足 3 期降级" in h_holders,
         "降级①：删 holder_ts → 户数图卡降级两期文字行（holders_drop）"),
        (rr_c.returncode == 0 and "在建工程（期末余额为零" in h_cip,
         "降级②：删 cip_projects → 在建降级行（cip_empty）"),
        (rr_g.returncode == 0 and "数据缺口声明" not in h_gap,
         "降级③：断言全无 missing → 数据缺口声明行整行删（gap_drop）"),
        (rr_s.returncode == 0 and '"其他"' in h_seg,
         "降级④：分部合计≠Δ收入 → SEG_BRIDGE 补「其他」桶闭合（SEG 轴）"),
        (rr_o.returncode == 0 and 'id="ocfbridge"' not in h_ocf
         and "OCF 调节桥未披露" in h_ocf,
         "降级⑤：删 ocf_bridge → 桥卡降级声明（ocf_drop，v0.1.1 新增）"),
    ]
    if not _block("render 断锚与降级路径阳性（v0.1.1 审计补口）", render_pos_checks,
                  "render 断锚/降级路径失效，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.2 港股首跑反馈构造用例（蜜雪 2026H1 实证五修）──
    # ① OCF 桥起点标签参数化：端点行/端点柱标签取底稿 ocf_bridge 首行科目名（剥括号注），
    #    港股间接法起点「税前利润」不再靠手工改呈现层；A 股首行即「净利润」产出逐字不变。
    v12_checks = []
    with tempfile.TemporaryDirectory() as _td12:
        _d12 = json.loads((HERE / "yinghe_2026h1.json").read_text(encoding="utf-8"))
        _d12["derived"]["ocf_bridge"][0]["item"] = "税前利润（港股间接法起点）"
        _cp12 = Path(_td12) / "hk_ocf.json"
        _cp12.write_text(json.dumps(_d12, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, str(CALC), str(_cp12), "--fill"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        _fs12 = _cp12.with_suffix(".fillsheet.md")
        _fs12_txt = _fs12.read_text(encoding="utf-8") if _fs12.exists() else ""
        v12_checks.append(
            ("端点行：税前利润 3.68" in _fs12_txt and "端点行：净利润" not in _fs12_txt,
             "v0.1.2①：OCF 桥端点行起点标签取底稿首行科目名（剥括号注）"))
    _tpl12 = (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
    v12_checks.append(
        ("期初·'+(((OCF_BRIDGE[0]||[])[0])||'净利润'" in _tpl12,
         "v0.1.2①：模板端点柱标签运行时自 OCF_BRIDGE[0] 派生（空桥兜「净利润」）"))

    # ② --min-recon auto 校准表：港股半年报 8（蜜雪实测结构性上限），A 股三档不变；
    #    康得新 recon 14/17——港股 auto 达标不升 FAIL、A 股年报 auto（15）必 FAIL、
    #    港股 auto 删到 7 条必 FAIL 钉住阈值方向。
    def _auto_run(market, rtype, drop=0):
        _d = json.loads((HERE / "kangdexin_2018.json").read_text(encoding="utf-8"))
        _d["meta"]["market"] = market
        _d["meta"]["report_type"] = rtype
        for _k in list((_d.get("recon") or {}).keys())[:drop]:
            _d["recon"].pop(_k, None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as _f:
            json.dump(_d, _f, ensure_ascii=False)
            _p = _f.name
        try:
            return run_calc(_p, "--min-recon", "auto")
        finally:
            os.unlink(_p)
    _r_hk = _auto_run("港股", "半年报")
    _r_a = _auto_run("A股", "年报")
    _r_hk7 = _auto_run("港股", "半年报", drop=7)
    v12_checks += [
        ("覆盖下限 8" in (_r_hk.stdout or "") and "未达 --min-recon" not in (_r_hk.stdout or ""),
         "v0.1.2②：港股半年报 auto → 下限 8，康得新 14/17 达标不升 FAIL"),
        ("未达 --min-recon 15" in (_r_a.stdout or ""),
         "v0.1.2②：A 股年报 auto → 下限 15，康得新 14/17 必 FAIL（A 股口径未漂移）"),
        ("未达 --min-recon 8" in (_r_hk7.stdout or ""),
         "v0.1.2②：港股半年报 auto 删至 7/17 必 FAIL（阈值方向钉死）"),
    ]

    # ③ s1-v15-shape 分位降级行豁免：hist<3 合法降级声明行（分位需/分位卡降级）不计缺白描；
    #    无豁免词又无 X/5 的数据行仍必报。
    _S1H = ('<div class="sect"><div class="secthead" id="s1"><span class="no">01</span>'
            '<span class="t">财务总览</span><span class="line"></span></div>')
    _pct_deg = _run_html_str(
        _S1H + '<div class="card"><table class="data">'
        '<tr><th>因子</th><th>当前值</th><th>五年位置</th></tr>'
        '<tr><td>三因子</td><td colspan="2">分位需 ≥3 期可比序列，分位卡降级（序列仅两期）</td></tr>'
        '</table><svg id="ncrline"></svg><div>周期定位：非周期行业声明</div></div></div>',
        json_path=None)
    _pct_live = _run_html_str(
        _S1H + '<div class="card"><table class="data">'
        '<tr><th>因子</th><th>当前值</th><th>五年位置</th></tr>'
        '<tr><td>净利率</td><td>15.0%</td><td>区间中部</td></tr>'
        '</table><svg id="ncrline"></svg><div>周期定位：非周期行业声明</div></div></div>',
        json_path=None)
    v12_checks += [
        ("[OK  ] s1-v15-shape" in (_pct_deg.stdout or ""),
         "v0.1.2③：分位表降级声明行豁免（蜜雪 hist<3 形态不再误报）"),
        ("缺白描读数" in (_pct_live.stdout or ""),
         "v0.1.2③：无豁免词且缺 X/5 的数据行仍必报（判据未松）"),
    ]

    # ④ s2-shape 剔除四线贴线考核卡判定徽章：该卡固定 3 枚 badge g（✅ 远离/无贴线场景）
    #    不是信号行（赢合/海康/蜜雪三份现行版式全误报）；卡外绿徽仍按原规则计数。
    _S2H = ('<div class="sect"><div class="secthead" id="s2"><span class="no">02</span>'
            '<span class="t">排雷扫描</span><span class="line"></span></div>')
    _4LINE = ('<div class="card"><table class="data">'
              '<tr><th>检测线</th><th>读数</th><th>目标</th><th>距离</th><th class="txt">判定</th></tr>'
              '<tr><td>保壳线</td><td>ROE 8.6%</td><td>ROE 6.5%</td><td>+2.1pct</td>'
              '<td class="txt"><span class="badge g">✅ 远离</span></td></tr>'
              '<tr><td>再融资线</td><td>ROE 8.6%</td><td>ROE 10%</td><td>-1.4pct</td>'
              '<td class="txt"><span class="badge g">✅ 远离</span></td></tr>'
              '<tr><td>激励线</td><td>无</td><td>—</td><td>—</td>'
              '<td class="txt"><span class="badge g">✅ 无贴线场景</span></td></tr>'
              '</table></div>')
    _s2_ok = _run_html_str(_S2H + _4LINE + "</div>", json_path=None)
    _s2_bad = _run_html_str(
        _S2H + _4LINE + '<div class="card"><span class="badge g">✅ 未触发</span>'
        '<span class="badge g">✅ 未触发</span></div></div>', json_path=None)
    v12_checks += [
        ("[OK  ] s2-shape" in (_s2_ok.stdout or ""),
         "v0.1.2④：四线卡 ✅ 判定徽章不计入绿徽（三份现行版式误报消除）"),
        ("绿色徽章" in (_s2_bad.stdout or ""),
         "v0.1.2④：四线卡外的逐条绿徽仍必报（判据未松）"),
    ]

    # ⑤ md_clean 港式章节名索引：无编号章节头精确整行匹配 + 去重取首现；港式主表入 blocks。
    with tempfile.TemporaryDirectory() as _tdm:
        _hkm = Path(_tdm) / "hk_sample.md"
        _hkm.write_text(
            "公司資料\n\n蜜雪集團股份有限公司 中期報告正文文字行，含數字 1,234.56 保留。\n\n"
            "管理層討論與分析\n\n本期收入 148.75 億元，同比增長，經營情況穩定向好發展。\n\n"
            "管理層討論與分析\n\n| 項目 | 本期 |\n| --- | --- |\n| 收入 | 14,875,393 |\n\n"
            "中期簡明綜合損益表\n\n| 期內利潤 | 2,975,707 |\n\n其他資料\n\n其他資料\n\n釋義\n",
            encoding="utf-8")
        _rm = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                              str(_hkm), "--out-dir", _tdm],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        _idxm_p = Path(_tdm) / "hk_sample.index.json"
        _idxm = json.loads(_idxm_p.read_text(encoding="utf-8")) if _idxm_p.exists() else {}
        _sec_names = [s.get("name") for s in (_idxm.get("sections") or [])]
        v12_checks += [
            (_rm.returncode == 0 and "不变量违反" not in (_rm.stdout or ""),
             "v0.1.2⑤：港式合成样本 exit 0 且双不变量通过"),
            ("管理層討論與分析" in _sec_names and _sec_names.count("管理層討論與分析") == 1
             and "公司資料" in _sec_names,
             f"v0.1.2⑤：港式章节头识别且页眉重复去重（sections={_sec_names}）"),
            ("中期簡明綜合損益表" in (_idxm.get("blocks") or {}),
             "v0.1.2⑤：港式主表入 blocks（中期簡明前綴）"),
        ]
    if not _block("v0.1.2 港股首跑反馈构造用例（蜜雪实证五修）", v12_checks,
                  "v0.1.2 构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.3 阿里港股年报首验反馈构造用例（非日历年财年三连锁/分位 X/N/T8② 百万档/
    #    auto 港股年报/labels 最长序列）——阿里 2026FY（3-31 财年止、US GAAP、百万元列报）实证 ──
    v13_checks = []
    from calc_common import hist_periods as _hp13
    from calc_slots import _pctile_label as _pl13, _period_label as _plb13
    from calc_models import build_slots as _bs13
    from check_html_t8 import _value_in_text as _vit13
    # ① 非日历年财年三连锁：hist_periods 年报不再卡 12-31（FY 标签）；A 股零漂移；
    #    半年报非 0630 仍卡死；_period_label 年报一律 FY（修阿里误标 2026Q1 致文件名错）。
    v13_checks += [
        (_hp13({"period": "20260331", "report_type": "年报"}, 5)
         == ["FY2022", "FY2023", "FY2024", "FY2025", "FY2026"],
         "v0.1.3①：hist_periods 年报非日历年财年（3-31 止）产 FY 标签"),
        (_hp13({"period": "20251231", "report_type": "年报"}, 2) == ["2024", "2025"],
         "v0.1.3①：A 股 12-31 年报标签零漂移"),
        (_hp13({"period": "20260331", "report_type": "半年报"}, 2) is None,
         "v0.1.3①：半年报非 0630 仍卡死返回 None（口径不放宽）"),
        (_plb13("20260331", "年报") == "2026FY" and _plb13("20251231", "年报") == "2025FY"
         and _plb13("20260630", "半年报") == "2026H1",
         "v0.1.3①：_period_label 年报一律 FY（修误标 2026Q1），半年报不变"),
    ]
    # ② 分位白描 X/N：n<5 窗口按公式（阿里四年窗口 0.6667→2/4）；n=5/未知走契约锁映射。
    v13_checks += [
        (_pl13(0.6667, 4) == "2/4" and _pl13(1.0, 4) == "1/4" and _pl13(0.0, 4) == "4/4",
         "v0.1.3②：分位 n=4 窗口 X/N 白描（阿里四年窗口实证形态）"),
        (_pl13(0.5, 5) == "3/5" and _pl13(0.5, None) == "3/5",
         "v0.1.3②：n=5 与未知窗口仍走 PCTILE_LABEL 契约锁映射"),
    ]
    # ③ T8② 百万档：阿里 US GAAP 年报百万元列报（1315.30 亿 ↔ 原文 131,530 百万）；
    #    无关大数不误命中。
    v13_checks += [
        (_vit13(1315.30, "| 現金及現金等價物 | 2(p) | 145,487 | 131,530 | 19,068 |"),
         "v0.1.3③：T8② 百万档命中（1315.30 亿 ↔ 原文 131,530 百万）"),
        (not _vit13(1315.30, "| 無關數字 | 999,999 | 888,888 | 777 |"),
         "v0.1.3③：百万档不误命中无关大数"),
    ]
    # ④ --min-recon auto 港股年报=12（阿里实测上限；复用 v0.1.2② 的康得新 14/17 助手）。
    _r_hkar = _auto_run("港股", "年报")
    v13_checks.append(
        ("覆盖下限 12" in (_r_hkar.stdout or "") and "未达 --min-recon" not in (_r_hkar.stdout or ""),
         "v0.1.3④：港股年报 auto → 下限 12（阿里实测），康得新 14/17 达标不升 FAIL"))
    # ⑤ labels 取最长序列（阿里实证：cash_ts 4 期截断 rev 5 期的隐患）：rev 5 期 +
    #    ncr 4 期形态下 TREND labels 5 期 FY、ocf 4 期前置 null 右对齐。
    _min13 = {"meta": {"period": "20260331", "report_type": "年报"},
              "statements": {"income": {"revenue": {"cur": 5, "hist": [1, 2, 3, 4, 5]},
                                        "np_at": {"cur": 5, "hist": [1, 2, 3, 4, 5]}},
                             "cashflow": {"ocf": {"cur": 4, "hist": [2, 3, 4, 4]}},
                             "balance": {}},
              "derived": {"ratios": {"roe": {"cur": 0.5, "hist": [0.1, 0.2, 0.3, 0.4, 0.5]}},
                          "cash_ts": {"ncr": [1.0, 1.0, 1.0, 1.0], "fcf_to_np": [0.5] * 4,
                                      "periods": ["FY2023", "FY2024", "FY2025", "FY2026"]}}}
    _t13 = _bs13(_min13)["js"]["TREND"]
    v13_checks.append(
        ('labels:["FY2022", "FY2023", "FY2024", "FY2025", "FY2026"]' in _t13
         and "ocf:[null, 2, 3, 4, 4]" in _t13,
         "v0.1.3⑤：labels 取最长序列（5 期 FY）+ 短序列前置 null 右对齐，不截断首期"))
    if not _block("v0.1.3 阿里港股年报首验反馈构造用例", v13_checks,
                  "v0.1.3 构造用例失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.5 ponytail-audit 修复轮构造断言（批次 D：19 条修复的「破坏必红」集中锁）──
    # 前序批次修复的回归锁：每条至少一正或一反，断言钉 calc.py/check_*/render 输出文案
    # （v0.1.1 纪律：钉整段/规则行文案，不查 returncode  alone——片段无页脚，required FAIL
    # 是背景噪音，exit 非 0 不构成证据）。所有文案均经「现场验证」逐字锁定。
    import calc_risk
    import calc_evidence
    import calc_sankey
    from calc_common import hist_periods as _hp15
    from calc_risk import compute_cash_ts as _cct15, check_cash_ts as _chk_ct15
    from calc_evidence import compute_cycle_evidence as _cce15, \
        compute_segment_quadrant as _csq15
    from calc_sankey import SANKEY_KEYS as _SK15, route_items as _ri15
    from calc_slots import write_fillsheet as _wfs15, _jd as _jd15, \
        build_slots as _bs15

    # ① sum_bridge 非 dict：净利桥混入字符串 → SKIP「未填或不完整」，闭合 OK 消失
    d15 = copy.deepcopy(base)
    d15["derived"]["np_bridge"] = ["字符串混入"]
    r15 = _run_calc_json(d15, "v15_npbridge.json")
    # ② cur=null 脱钩：hist 非空 + cur 缺失 → FAIL 口径脱钩（calc.py 结构检查）
    d15_h = copy.deepcopy(base)
    d15_h["statements"]["income"]["sell_exp"] = {"cur": None, "hist": [1.0, 2.0, 2.5], "src": ""}
    r15_h = _run_calc_json(d15_h, "v15_curnull.json")
    # ③ recon 矛盾双行：可解释 + 空 explanation → FAIL 且该 key 不再出 OK 行
    d15_r = copy.deepcopy(base)
    d15_r["recon"] = {"A1_cash": {"lhs": 100.0, "rhs": 90.0, "verdict": "可解释",
                                  "explanation": "", "src": "L100 测试"}}
    r15_r = _run_calc_json(d15_r, "v15_recon.json")
    # ④ ratio-hist 具名 WARN：payable/contract_liab 置空（删节点会撞 leverage_drill 复算 FAIL）
    d15_c = copy.deepcopy(base)
    for _f in ("payable", "contract_liab"):
        if _f in d15_c["statements"]["balance"]:
            d15_c["statements"]["balance"][_f] = {"cur": None, "prev": None, "src": ""}
    _ld15 = d15_c["derived"]["dupont"].get("leverage_drill")
    if isinstance(_ld15, dict):
        _ld15["quality_upgrade"] = None
    r15_c = _run_calc_json(d15_c, "v15_ratiohist.json")
    _r15l = (r15.stdout or "").splitlines()
    v15_calc = [
        (r15.returncode == 0 and "未填或不完整" in (r15.stdout or "")
         and not any("[OK" in l and "净利桥" in l for l in _r15l),
         "①np_bridge 混入字符串：SKIP「净利桥未填或不完整」且闭合 OK 消失（sum_bridge 非 dict 不崩）"),
        # ② cur=null 脱钩：hist 非空 + cur 缺失 → FAIL 口径脱钩（calc.py 结构检查）
        (r15_h.returncode == 1
         and "cur 缺失但 hist 已填——有历史无数本期，口径脱钩" in (r15_h.stdout or ""),
         "②cur=null+hist 已填：FAIL「cur 缺失但 hist 已填——有历史无数本期，口径脱钩」"),
        # ③ recon 矛盾双行：可解释 + 空 explanation → FAIL 且该 key 不再出 OK 行
        (r15_r.returncode == 1
         and "verdict=「可解释」但 explanation 为空" in (r15_r.stdout or "")
         and not any("[OK" in l and "A1_cash" in l
                     for l in (r15_r.stdout or "").splitlines()),
         "③recon 可解释+explanation 空：FAIL「verdict=「可解释」但 explanation 为空」且 A1_cash 无 OK 行"),
        # ④ ratio-hist 具名 WARN：payable/contract_liab 置空 → ccc 序列整体缺失具名 WARN
        (r15_c.returncode == 0
         and "ccc 科目序列整体缺失，已填 hist 无法复算——未经校验" in (r15_c.stdout or ""),
         "④payable/contract_liab 置空：WARN「ccc 科目序列整体缺失，已填 hist 无法复算——未经校验」"),
    ]
    if not _block("v0.1.5 构造断言（calc 门禁修复锁）", v15_calc,
                  "v0.1.5 calc 修复锁失败，逐条核对上方 ❌。"):
        return 1

    # ⑤ cash_ts 跨期错配：缺口位按原始索引配对，ncr[2] 是 None（不是 14/12 跨缺口错配值）
    _ct5 = _cct15({"statements": {
        "cashflow": {"ocf": {"cur": 15, "hist": [10, 12, None, 14, 15]},
                     "capex": {"cur": 1, "hist": [1, 1, 1, 1, 1]}},
        "income": {"np_at": {"cur": 15, "hist": [10, 11, 12, None, 15]}}},
        "meta": {"period": "20251231", "report_type": "年报"}})
    _d5s = {"statements": {
        "cashflow": {"ocf": {"cur": 15, "hist": [10, 12, None, 14, 15]},
                     "capex": {"cur": 1, "hist": [1, 1, 1, 1, 1]}},
        "income": {"np_at": {"cur": 15, "hist": [10, 11, 12, None, 15]}}},
        "meta": {"period": "20251231", "report_type": "年报"}}
    _ct5b = _cct15(_d5s)
    _bad_ncr = list(_ct5b["ncr"])
    _bad_ncr[0] = "1.0x"          # 数字位置塞字符串：cmp_series 记 bad（不崩不跳）
    _d5s["derived"] = {"cash_ts": dict(_ct5b)}
    _d5s["derived"]["cash_ts"]["ncr"] = _bad_ncr
    _rep_ct = _Rep()
    _chk_ct15(_d5s, _rep_ct)
    # ⑥ cycle_evidence：缺口期增速 None（不跨缺口算 0.10）；GM 线独立成块；三线均 <2 期 → None
    _cv6a = _cce15({"statements": {"income": {"revenue": {"cur": 121, "hist": [100, None, 110, 121]}},
                                   "cashflow": {}},
                    "derived": {"ratios": {}}, "meta": {"period": "20251231", "report_type": "年报"}})
    _cv6b = _cce15({"statements": {"income": {}, "cashflow": {}},
                    "derived": {"ratios": {"gross_margin": {"cur": 0.4, "hist": [0.5, 0.4]}}},
                    "meta": {}})
    _cv6c = _cce15({"statements": {"income": {}, "cashflow": {}},
                    "derived": {"ratios": {"gross_margin": {"cur": 0.4, "hist": [0.4]}}},
                    "meta": {}})
    # ⑦ segment 聚合缺成本：任一分部 cost_cur 缺 → y0=None 且行级 p（毛利份额）整 None
    _sq7 = _csq15({"statements": {"income": {"by_segment": [
        {"name": "甲", "rev_cur": 10, "rev_prev": 8},
        {"name": "乙", "rev_cur": 12, "rev_prev": 9}]}}})
    # ⑧ dupont_dt 裸数字：ratios.nonrecurring_share=0.25（非对象节点）不崩且触发双版
    d15_8 = copy.deepcopy(base)
    d15_8["derived"]["ratios"]["nonrecurring_share"] = 0.25
    _r8 = calc_dupont.compute_dupont_dt(d15_8)
    # ⑨ turnover_drill skip_none：balance 仅 inventory 两期齐全 → top2_share=None 合法，
    #    check_dupont 不得产出「无法复算」FAIL（cmp_fields skip_none 修复锁）
    d15_9 = copy.deepcopy(base)
    _bal9 = d15_9["statements"]["balance"]
    for _f9 in list(_bal9.keys()):
        if _f9 not in ("inventory", "total_assets"):
            del _bal9[_f9]
    _c9 = calc_dupont.compute_dupont(d15_9)
    _td9 = (_c9 or {}).get("turnover_drill") or {}
    if _td9:
        d15_9["derived"]["dupont"].update(
            {k: _c9[k] for k in ("margin_effect", "turnover_effect", "leverage_effect",
                                 "roe_product_cur", "roe_product_prev", "closure_gap",
                                 "driver", "driver_fragile", "effects_ratio", "driver_second",
                                 "margin_drill", "turnover_drill", "leverage_drill")})
    _rep9 = _Rep()
    if _td9:
        _calc.check_dupont(d15_9, _rep9)
    _fails9 = [m for lv, _, m in _rep9.rows if lv == _FAIL]
    v15_fn = [
        (_ct5 is not None and _ct5["ncr"][2] is None and _ct5["ncr"][3] is None
         and abs(_ct5["ncr"][1] - 12 / 11) < 1e-9,
         "⑤cash_ts 跨期错配：缺口位 ncr[2]/ncr[3] 是 None（不是 14/12 跨缺口错配值）"),
        (any("cash_ts.ncr[0] 不符" in m
             for lv, _, m in _rep_ct.rows if lv == _FAIL),
         "⑤cash_ts 字符串形态：数字位置塞字符串记 bad「cash_ts.ncr[0] 不符」（cmp_series 不崩）"),
        (_cv6a is not None and _cv6a["rev_growth"][2] is None
         and abs(_cv6a["rev_growth"][3] - 0.10) < 1e-9,
         "⑥cycle_evidence 缺口期：rev_growth[2] 是 None（不跨缺口算 0.10），[3]=0.10"),
        (_cv6b is not None and _cv6b["gross_margin"] == [0.5, 0.4],
         "⑥cycle_evidence GM 独立成块：rev/capex 无 hist 时 gross_margin 线仍产出"),
        (_cv6c is None,
         "⑥cycle_evidence 三线均 <2 期：compute 返回 None"),
        (_sq7 is not None and _sq7["y0"] is None
         and all(r.get("p") is None for r in _sq7["rows"]),
         "⑦segment 聚合缺成本：y0=None 且行级 p（毛利份额）整 None（不按 0 凑）"),
        (_r8.get("triggered") is True and "margin_effect" in _r8,
         "⑧dupont_dt 裸数字：nonrecurring_share=0.25（非对象节点）不崩且触发扣非双版"),
        (_td9.get("top2_share") is None,
         "⑨turnover_drill 构造落地：仅 inventory 两期齐全 → top2_share=None（skip_none 判据载体）"),
        (not _fails9,
         f"⑨turnover_drill skip_none：top2_share=None 不产生「无法复算」FAIL（实际 {_fails9[:2]}）"),
    ]
    if not _block("v0.1.5 构造断言（公式层直测锁）", v15_fn,
                  "v0.1.5 公式层直测锁失败，逐条核对上方 ❌。"):
        return 1

    # ⑩ 桑基单季差额（赢合副本改三季报 + cum_prev 输入字段）：正例 OK+WARN / 改坏必 FAIL；
    #    route_items 符号路由直测（other_lump<0 → 减项「其他损益净损失」；impair<0 → 加项「减值净转回」）
    def _sankey_diff(corrupt):
        d = json.loads((HERE / "yinghe_2026h1.json").read_text(encoding="utf-8"))
        d["meta"]["period"] = "20260930"
        d["meta"]["report_type"] = "三季报"     # 「季报」子串 + 0930 → diff 口径；年化因子 4/3 在库
        _m = {"period": "20260930", "report_type": "三季报"}
        for _blk in ("cash_ts", "cycle_evidence"):
            _n = (d["derived"].get(_blk) or {})
            if _n.get("periods"):
                _n["periods"] = _hp15(_m, len(_n["periods"]))
        _d5n = (d["derived"].get("dupont5y") or {})
        if _d5n.get("period_start"):
            _labs = _hp15(_m, 5)
            _d5n["period_start"], _d5n["period_end"] = _labs[0], _labs[-1]
        _sk = d["derived"]["sankey"]
        _cum = {k: _sk[k] for k in _SK15}
        _pv = {k: round(_cum[k] * 0.6, 4) for k in _SK15}
        _diff = {k: round(_cum[k] - _pv[k], 4) for k in _SK15}
        if corrupt:      # 先算好 diff 再改坏 cum_prev——构造卡口必失败的样本
            _pv = dict(_pv)
            _pv["rev"] = round(_pv["rev"] + 5, 4)
        d["derived"]["sankey"] = {"period_type": "单季差额", **_diff,
                                  "cum": _cum, "cum_prev": _pv,
                                  "src": _sk.get("src") or "L1 测试",
                                  "note": _sk.get("note")}
        _alt, _ = calc_risk.compute_altman(d)   # 三季报年化因子不同，Altman 存储值同步重算
        if _alt is not None:
            d["derived"]["risk_models"]["altman_z"] = _alt
        return d

    _sk_ok = _run_calc_json(_sankey_diff(False), "v15_sk_ok.json")
    _sk_bad = _run_calc_json(_sankey_diff(True), "v15_sk_bad.json")
    _minus10, _plus10 = _ri15({"tax_sur": 1, "sell": 1, "admin": 1, "rd": 1,
                               "fin": -2, "impair": -3, "other_lump": -5})
    v15_sankey = [
        (_sk_ok.returncode == 0
         and "桑基图 20 科目复算自洽（单季差额）" in (_sk_ok.stdout or "")
         and "cum_prev 为纯输入字段，门禁仅验自洽——人工核对上一累计期出处" in (_sk_ok.stdout or ""),
         "⑩单季差额正例：OK「桑基图 20 科目复算自洽（单季差额）」+ WARN「cum_prev 纯输入字段仅验自洽」"),
        (_sk_bad.returncode == 1 and "单季差额卡口" in (_sk_bad.stdout or ""),
         "⑩cum_prev 改坏：FAIL「单季差额卡口：rev 值 … ≠ cum−cum_prev」"),
        (any(m.get("label") == "其他损益净损失" for m in _minus10),
         "⑩route_items：other_lump<0 → 减项侧出现「其他损益净损失」"),
        (any(p.get("label") == "减值净转回" for p in _plus10),
         "⑩route_items：impair<0 → 加项侧出现「减值净转回」"),
    ]
    if not _block("v0.1.5 构造断言（桑基单季差额 + 符号路由）", v15_sankey,
                  "v0.1.5 桑基锁失败，逐条核对上方 ❌。"):
        return 1

    # ⑪ fillsheet 桥 delta 守卫：np_bridge 环节 delta=None → 不抛异常且贡献额列为「—」
    d15_11 = copy.deepcopy(base)
    d15_11["derived"]["np_bridge"] = [{"item": "毛利", "delta": None},
                                      {"item": "所得税", "delta": 1.5}]
    _fs_path = HERE / "_v15_fillsheet_tmp.md"
    try:
        _wfs15(d15_11, str(_fs_path))
        _fs_lines = _fs_path.read_text(encoding="utf-8").splitlines()
    finally:
        _fs_path.unlink(missing_ok=True)
    _jd_up = _jd15("</SCRIPT>")
    _jd_lo = _jd15("</script>")
    v15_slot = [
        (any(l.startswith("| 毛利 ") and l.rstrip().endswith("| — |") for l in _fs_lines),
         "⑪fillsheet 桥 delta 守卫：delta=None 不抛异常且该行贡献额列为「—」"),
        ("<\\/SCRIPT>" in _jd_up and "<\\/script>" in _jd_lo,
         "⑫_jd 大小写不敏感：</SCRIPT> 与 </script> 均转 <\\/（防提前闭合 script 团灭 JS）"),
    ]
    if not _block("v0.1.5 构造断言（fillsheet/_jd 守卫）", v15_slot,
                  "v0.1.5 fillsheet/_jd 锁失败，逐条核对上方 ❌。"):
        return 1

    # ⑬ render 转义与守卫（茅台临时副本端到端，产物全落临时目录不污染 reports/）+
    # ⑭ sect() 右界断锚（摘页脚锚 + watchlist 非空触发 fill_s8→sect("s8") 双右界均失）
    with tempfile.TemporaryDirectory() as _td15:
        _wr15 = Path(_td15)

        def _fill_copy(mutate, name):
            """茅台副本改一处 → --fill（render 端到端用例共用）。"""
            cp = _wr15 / f"{name}.json"
            d = copy.deepcopy(base)
            mutate(d)
            cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(CALC), str(cp), "--fill"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
            return cp

        # ① meta.company 注入 <A>（fill 前改：槽位 json 携带原文，render 插入点统一 _E 转义）
        cp_a = _fill_copy(lambda d: d["meta"].update(company="测试<A>公司"), "v15_esc")
        out_a = _wr15 / "v15_esc.html"
        rr_a = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                               str(cp_a), "-o", str(out_a)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        h_a = out_a.read_text(encoding="utf-8") if out_a.exists() else ""

        # ② dupont 三效应+effects_ratio 置 None（合法形态：fill 后改 derived 再重建槽位 json——
        #    --fill 会重算 derived，孔位形态只能 fill 后注入）
        cp_b = _fill_copy(lambda d: None, "v15_eff")
        d_b = json.loads(cp_b.read_text(encoding="utf-8"))
        for _k in ("margin_effect", "turnover_effect", "leverage_effect", "effects_ratio"):
            d_b["derived"]["dupont"][_k] = None
        cp_b.write_text(json.dumps(d_b, ensure_ascii=False), encoding="utf-8")
        (_wr15 / "v15_eff.fillsheet.json").write_text(
            json.dumps(_bs15(d_b), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        out_b = _wr15 / "v15_eff.html"
        rr_b = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                               str(cp_b), "-o", str(out_b)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        h_b = out_b.read_text(encoding="utf-8") if out_b.exists() else ""

        # ③ watchlist badge 非法值 → fill_s8 class 白名单兜底 disc（不进 class 属性）
        cp_c = _fill_copy(lambda d: d.update(watchlist=[{
            "indicator": "测试跟踪卡", "current": "1.0", "badge": "bogus",
            "upper": "2", "upper_meaning": "偏高", "lower": "0", "lower_meaning": "偏低",
            "tripwire": "熔断句", "source": "测试来源"}]), "v15_badge")
        out_c = _wr15 / "v15_badge.html"
        rr_c = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                               str(cp_c), "-o", str(out_c)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        h_c = out_c.read_text(encoding="utf-8") if out_c.exists() else ""

        # ⑭ 断锚：模板副本摘除页脚锚（「 <!-- ══ 页脚」是 s8 的右界）+ watchlist 非空
        #    （fill_s8 空卡直接 return、碰不到 sect("s8")——右界断锚必须借 watchlist 触发）
        cp_d = _fill_copy(lambda d: d.update(watchlist=[{
            "indicator": "断锚触发卡", "current": "1.0", "badge": "disc",
            "upper": "2", "upper_meaning": "偏高", "lower": "0", "lower_meaning": "偏低",
            "tripwire": "熔断句", "source": "测试来源"}]), "v15_anchor")
        tpl_d = _wr15 / "v15_tpl.html"
        tpl_d.write_text(
            (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
            .replace(" <!-- ══ 页脚 ◆ SLOT ══ -->", " <!-- ◆ 摘除页脚锚 ══ -->", 1),
            encoding="utf-8")
        import io
        from contextlib import redirect_stdout
        _old_tpl, _old_argv = render_report.TEMPLATE, sys.argv
        _buf = io.StringIO()
        try:
            render_report.TEMPLATE = tpl_d
            sys.argv = ["render_report.py", str(cp_d), "-o", str(_wr15 / "v15_anchor.html")]
            with redirect_stdout(_buf):
                _rc_anchor = render_report.main()
        finally:
            render_report.TEMPLATE, sys.argv = _old_tpl, _old_argv
        _anchor_out = _buf.getvalue()

    v15_render = [
        (rr_a.returncode == 0 and "<h1>测试&lt;A&gt;公司（600519.SH）</h1>" in h_a
         and "<title>测试&lt;A&gt;公司" in h_a and "<A>" not in h_a,
         "⑬①公司名注入 <A>：h1/title 含 &lt;A&gt; 转义、产物无裸 <A>"),
        (rr_b.returncode == 0 and "效应比不适用（三效应≈0）" in h_b,
         "⑬②三效应+effects_ratio=None 合法形态：render exit 0 且合计行「效应比不适用（三效应≈0）」"),
        (rr_c.returncode == 0 and "bogus" not in h_c
         and '<span class="badge disc">披露</span>' in h_c,
         "⑬③badge 非法值：class 白名单兜底 disc，产物无 badge bogus"),
        (_rc_anchor == 1 and "断锚清单" in _anchor_out and "段落右界未找到" in _anchor_out,
         "⑭sect() 右界断锚：摘页脚锚必 exit 1 且断锚清单含「段落右界未找到」"),
    ]
    if not _block("v0.1.5 构造断言（render 转义/守卫/断锚）", v15_render,
                  "v0.1.5 render 锁失败，逐条核对上方 ❌。"):
        return 1

    # ⑮ T8① 双盲区：全角减号（U+2212）负值整串失明修复锁 + pct 词边界后缀走 ×100 池
    #    （挑权威池真实独特负值，偏差 ~0.07%——超显示精度 0.005 落在 0.15% 笔误窗内；
    #    桑基 gap 是扁平 dict 不进权威池，故不能作锚——现场验证结论）
    _plain15, _pct15, _up15, _upct15, _hpool15 = _ba(load_json(MOUTAI))
    _v15t = None
    for _cand15, _cpath15 in _up15:
        if _cand15 >= -50:
            continue
        _dv15 = round(_cand15 * 1.0007, 2)
        if abs(_dv15 - _cand15) <= 0.005 or abs(_dv15 - _cand15) / abs(_cand15) > 0.0015:
            continue
        if any(w * _dv15 > 0 and abs(w - _dv15) <= 0.005 for w, _, _ in _plain15):
            continue
        if any(w * _dv15 > 0 and abs(w - _dv15) <= 0.005 for w, _ in _hpool15):
            continue
        _v15t = _dv15
        break
    t8_fw = None
    if _v15t is not None:
        t8_fw = _run_html_str(
            _SECT + f'<div class="card"><p>净调整 \u2212{abs(_v15t):.2f} 亿元</p></div></div>')
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as _jf15:
        json.dump({"meta": {"company": "构造样本", "code": "000000", "period": "20251231",
                            "report_type": "年报", "unit": "亿元"},
                   "derived": {"ratios": {"net_cash_ratio": {"cur": 0.3365, "prev": 0.30,
                                                             "note": "构造"}}}},
                  _jf15, ensure_ascii=False)
        _jpct = _jf15.name
    try:
        t8_pct = _run_html_str(
            _SECT + '<div class="card"><p>净现比 33.65pct 水平</p></div></div>', _jpct)
        t8_pct_bad = _run_html_str(
            _SECT + '<div class="card"><p>净现比 33.66pct 水平</p></div></div>', _jpct)
    finally:
        os.unlink(_jpct)
    # ⑯ gate 红测：占位符残留走单入口必 exit 1 且汇总点名 check_html；正例容忍两种合法形态
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as _hf15:
        _hf15.write(_SECT + '<div class="card"><p>{{未填孔}}</p></div></div>')
        _hgate = _hf15.name
    try:
        g_bad = subprocess.run([sys.executable, str(SKILL / "scripts" / "gate.py"),
                                _hgate, str(MOUTAI)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        os.unlink(_hgate)
    g_ok = subprocess.run([sys.executable, str(SKILL / "scripts" / "gate.py"),
                           str(HERE / "t8_demo.html"), str(MOUTAI)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    v15_t8 = [
        (t8_fw is not None and "[FAIL] num-vs-json" in (t8_fw.stdout or "")
         and "相近但不等" in (t8_fw.stdout or ""),
         f"⑮①全角减号 U+2212：负值笔误必 FAIL「相近但不等」（取值 {_v15t}；修复前 − 数字整串失明）"),
        ("[FAIL] num-vs-json" not in (t8_pct.stdout or "")
         and "1 处数字匹配" in (t8_pct.stdout or ""),
         "⑮②pct 精确匹配：33.65pct 与 json ×100 池精确相等计入匹配、不产生 FAIL"),
        ("[FAIL] num-vs-json" in (t8_pct_bad.stdout or "")
         and "相近但不等" in (t8_pct_bad.stdout or ""),
         "⑮②pct 偏差 0.03%：33.66pct 对独特值 33.65 必 FAIL「相近但不等」（pct 词边界判据未松）"),
        (g_bad.returncode == 1 and "check_html 未通过（FAIL 未清零）" in (g_bad.stdout or ""),
         "⑯gate 红测：占位符残留必 exit 1 且 gate 汇总点名「check_html 未通过（FAIL 未清零）」"),
        (g_ok.returncode == 0
         and ("三道门禁全绿" in (g_ok.stdout or "")
              or "渲染门禁跳过" in (g_ok.stdout or "")),
         "⑯gate 正例：t8_demo+茅台 exit 0（有浏览器=三道全绿/无浏览器=渲染跳过，两种合法形态）"),
    ]
    if not _block("v0.1.5 构造断言（T8 双盲区 + gate 红测）", v15_t8,
                  "v0.1.5 T8/gate 锁失败，逐条核对上方 ❌。"):
        return 1

    # ⑲ check_html 两缺口：①steps 字符串元素必 FAIL「形态异常」不崩 traceback；
    #    ②json 有杜邦三效应/桑基数据但 HTML 无槽 → 双 WARN（卡被静默删除抓瞎补口）
    ds_bad = _run_html_str(
        _SECT + '<div class="card"><p>杜邦</p></div></div>'
        '<script>const DUPONT_STACK={"steps": ["净利率", "周转率", "杠杆"], "gap": null};</script>')
    ds_missing = _run_html_str(_SECT + '<div class="card"><p>无槽正文</p></div></div>')
    # ⑳ T8② 真空修复（发现 17）：md 缺失必锁「未执行」声明；md 在库且含已知数字必出「精确命中」
    d15_md = copy.deepcopy(base)
    d15_md.setdefault("meta", {})["source_md"] = "reports/__v15_不存在__.md"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as _jf20:
        json.dump(d15_md, _jf20, ensure_ascii=False)
        _jmd = _jf20.name
    try:
        t8_md_missing = _check_html(HERE / "t8_demo.html", _jmd)
    finally:
        os.unlink(_jmd)

    def _src_leaves15(node, path, out):
        if isinstance(node, dict):
            if "cur" in node:
                ms = [int(x) for x in re.findall(r"L(\d+)", node.get("src") or "")]
                if ms:
                    out.append((min(ms), path, node.get("cur")))
                return
            for k, v in node.items():
                _src_leaves15(v, f"{path}.{k}", out)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _src_leaves15(v, f"{path}[{i}]", out)

    _leaves15 = []
    for _sec15 in ("statements", "parent_statements", "notes"):
        _src_leaves15(base.get(_sec15) or {}, _sec15, _leaves15)
    _ln15, _lp15, _lcur15 = min(_leaves15)
    _md_pos = "\n" * (_ln15 - 1) + f"| {_lp15} | {_lcur15} |\n"
    t8_md_hit = _run_html_json_md(
        _SECT + '<div class="card"><p>对照</p></div></div>', _md_pos)
    # ㉒ percentile-map 4 期窗口（_win_n HTML 红测）：hist 截 4 期 + 分位置 1.0 → 应标「1/4」；
    #    贴「1/5」契约锁标签必 FAIL（v0.0.18 块是 n=5 窗口反例，本用例锁 n≠5 窗口正/反）
    d15_p4 = copy.deepcopy(base)
    for _k in ("net_margin", "asset_turnover", "equity_multiplier"):
        _h15 = d15_p4["derived"]["ratios"][_k]["hist"]
        d15_p4["derived"]["ratios"][_k]["hist"] = _h15[-4:]
    for _k in ("net_margin", "asset_turnover", "equity_multiplier"):
        d15_p4["derived"]["dupont5y"]["percentile"][_k] = 1.0
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as _jf22:
        json.dump(d15_p4, _jf22, ensure_ascii=False)
        _jp4 = _jf22.name
    _PCT_TBL = ('<div class="card"><table class="data">'
                '<tr><th>因子</th><th>当前值</th><th>五年位置</th></tr>'
                '<tr><td>净利率 <span class="badge der">推算</span></td><td>48.8%</td>'
                '<td><span class="badge disc">LBL</span></td></tr>'
                '<tr><td>总资产周转率</td><td>0.56</td><td><span class="badge disc">LBL</span></td></tr>'
                '<tr><td>权益乘数</td><td>1.20</td><td><span class="badge disc">LBL</span></td></tr>'
                '</table><div class="srcline">分位表演示</div></div>')
    try:
        p4_ok = _run_html_str(_SECT + _PCT_TBL.replace("LBL", "1/4") + '</div>', _jp4)
        p4_bad = _run_html_str(_SECT + _PCT_TBL.replace("LBL", "1/5") + '</div>', _jp4)
    finally:
        os.unlink(_jp4)
    v15_html = [
        (ds_bad.returncode != 0 and "形态异常" in (ds_bad.stdout or "")
         and "Traceback" not in (ds_bad.stdout or ""),
         "⑲①DUPONT_STACK steps 字符串元素：exit 非 0 由 FAIL「形态异常」贡献、不崩 traceback"),
        ("json 有杜邦三效应数据但 HTML 无 DUPONT_STACK 槽" in (ds_missing.stdout or ""),
         "⑲②json 有杜邦三效应但无槽：WARN「json 有杜邦三效应数据但 HTML 无 DUPONT_STACK 槽」"),
        ("json 有 derived.sankey 但 HTML 无 SANKEY 槽且无 svg#sankey" in (ds_missing.stdout or ""),
         "⑲②json 有 derived.sankey 但无槽无图：WARN「json 有 derived.sankey 但 HTML 无 SANKEY 槽且无 svg#sankey」"),
        ("未执行" in (t8_md_missing.stdout or ""),
         "⑳T8② md 缺失形态：输出锁「未执行」声明（旧断言可被 json-md 任意 OK 行真空通过）"),
        ("精确命中" in (t8_md_hit.stdout or "") and "未执行" not in (t8_md_hit.stdout or ""),
         f"⑳T8② md 在库正例：L{_ln15} 植入原文值必出「精确命中」执行态（{_lp15}={_lcur15}）"),
        ("[OK  ] percentile-map" in (p4_ok.stdout or ""),
         "㉒percentile-map n=4 窗口：三因子贴「1/4」白描判 OK（_win_n 窗口感知正例）"),
        (p4_bad.returncode != 0 and "[FAIL] percentile-map" in (p4_bad.stdout or "")
         and "应标「1/4」" in (p4_bad.stdout or ""),
         "㉒percentile-map n=4 窗口红测：贴「1/5」契约锁标签必 FAIL「应标「1/4」」"),
    ]
    if not _block("v0.1.5 构造断言（check_html 两缺口 + T8② 真空 + 分位窗口）", v15_html,
                  "v0.1.5 check_html 锁失败，逐条核对上方 ❌。"):
        return 1

    # ㉑ check_render 三探测器阳性（发现 17 测试真空）：spill/clipped/pageclip 各构造必报
    if "渲染门禁跳过" in render_out:
        print("\n【v0.1.5 check_render 三探测器阳性】SKIP（本机无 Chrome/Edge，随渲染门禁一并跳过）")
    else:
        _probes = {
            "_v15_spill_demo.html":
                ('<!doctype html><html><head><meta charset="utf-8"></head><body>'
                 '<div class="sheet" style="max-width:1040px;margin:0 auto">'
                 '<div style="white-space:nowrap;width:3000px">超宽不换行块</div>'
                 '</div></body></html>', "spill"),
            "_v15_clipped_demo.html":
                ('<!doctype html><html><head><meta charset="utf-8"></head><body>'
                 '<div class="sheet" style="max-width:1040px;margin:0 auto">'
                 '<div style="overflow-x:hidden;width:200px">'
                 '<div style="width:900px">被裁切的内容块</div></div>'
                 '</div></body></html>', "clipped"),
            "_v15_pageclip_demo.html":
                ('<!doctype html><html><head><meta charset="utf-8"></head><body>'
                 '<div class="sheet" style="max-width:1040px;margin:0 auto"><p>正文</p></div>'
                 '<div style="width:3600px">页面级超宽元素</div>'
                 '</body></html>', "pageclip"),
        }
        _probe_checks = []
        for _name15, (_page15, _crit15) in _probes.items():
            _p15 = HERE / _name15
            _p15.write_text(_page15, encoding="utf-8")
            try:
                _rp15 = subprocess.run(
                    [sys.executable, str(SKILL / "scripts" / "check_render.py"), str(_p15)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            finally:
                _p15.unlink(missing_ok=True)
            _probe_checks.append(
                (_rp15.returncode == 1 and f"·{_crit15}]" in (_rp15.stdout or ""),
                 f"㉑{_crit15} 探测器阳性：构造页必 exit 1 且报 [{_crit15}]（发现 17 真空修复）"))
        if not _block("v0.1.5 check_render 三探测器阳性", _probe_checks,
                      "v0.1.5 check_render 探测器阳性失效，逐条核对上方 ❌。"):
            return 1

    # ⑱ md_clean 两形态（发现 1 测试真空）：独立表题行「单位：元」不被拼进表头、
    #    孤分隔行 | --- | 不被拼进碎行、pre 碎行拼回（断字带空格形态，与 synth1 金标准同惯例）
    with tempfile.TemporaryDirectory() as _tdm:
        rm15 = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                               str(HERE / "md_clean_synth2.md"), "--out-dir", _tdm],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        _txt15 = (Path(_tdm) / "md_clean_synth2.clean.md").read_text(encoding="utf-8")
        _lines15 = _txt15.splitlines()
        _bare_sep = sum(1 for l in _lines15 if l.strip() == "| --- |")
    # ⑰ ts_fetch 静态断言（需 tushare token，网络路径不可回归）：--out 分支写全量 rows 非 shown
    _ts_src = (SKILL / "scripts" / "ts_fetch.py").read_text(encoding="utf-8")
    _ts_out_branch = re.search(r"if args\.out:(.*?)\n    sys\.stdout\.write", _ts_src, re.S)
    v15_misc = [
        (rm15.returncode == 0 and "不变量违反" not in (rm15.stdout or ""),
         "⑱md_clean synth2：exit 0 且双不变量通过"),
        (any(l.strip() == "单位：元" for l in _lines15) and "| 单位：元 |" not in _txt15,
         "⑱独立表题行「单位：元」 standalone（不被拼进表头第一格，无 | 单位：元 | 污染）"),
        (_bare_sep >= 1 and "| --- 已计提" not in _txt15 and "已计提未支付的利息" in _txt15,
         "⑱孤分隔行 | --- | 未被拼进碎行（碎行 standalone 保文本，无 | --- 已计提 污染）"),
        ("| 销售商品、提供劳务收到的现 金 | 2,345.67 | 2,100.11 |" in _txt15,
         "⑱pre 碎行拼回：销售商品…现 金 合并行仍在（normal 形态回归对照）"),
        (_ts_out_branch is not None and "for r in rows" in _ts_out_branch.group(1)
         and "shown" not in _ts_out_branch.group(1)
         and "shown = rows if limit == 0 else rows[:limit]" in _ts_src,
         "⑰ts_fetch --out 分支静态锁：落盘写全量 rows（非截断 shown）——需 token 不可自动化，静态断言"),
    ]
    if not _block("v0.1.5 构造断言（md_clean 两形态 + ts_fetch 静态）", v15_misc,
                  "v0.1.5 md_clean/ts_fetch 锁失败，逐条核对上方 ❌。"):
        return 1

    # ══ 更名命名契约（RED）：本技能定名 Bo-FinancialAnalyzer（目录 bo-financial-analyzer）══
    # 断言目标命名；旧命名下本块 5 条应全 ❌，更名落地后由 257 条全绿锁死。
    _skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    _tmpl_html = (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
    _render_src = (SKILL / "scripts" / "render_report.py").read_text(encoding="utf-8")
    _fm = re.search(r"\A---\n(.*?)\n---\n", _skill_md, re.S)
    _fm_name_m = re.search(r"^name:\s*(\S+)", _fm.group(1), re.M) if _fm else None
    # 标题/页眉（kicker）品牌的锚文本：render_report.py 的 sub1 搜索串必须与模板逐字一致（断锚契约）
    _new_title_anchor = "<title>{{公司名}} {{报告期}}{{报告类型}}分析 — Bo-FinancialAnalyzer</title>"
    _new_kicker_anchor = "BO-FINANCIALANALYZER · {{上市地}}"
    naming_checks = [
        (SKILL.name == "bo-financial-analyzer",
         f"技能目录名 SKILL.name == 'bo-financial-analyzer'（现值：{SKILL.name}）"),
        (_fm_name_m is not None and _fm_name_m.group(1) == "bo-financial-analyzer",
         "SKILL.md frontmatter 含 name: bo-financial-analyzer"),
        ("# Bo-FinancialAnalyzer（上市公司财报与招股书分析器）" in _skill_md,
         "SKILL.md 一级标题为「# Bo-FinancialAnalyzer（上市公司财报与招股书分析器）」"),
        ("bo-equity-researcher" in _skill_md and "bo-equity-researcher" in _tmpl_html
         and "stock-deep-analysis" not in _skill_md
         and "stock-deep-analysis" not in _tmpl_html,
         "SKILL.md 与活动模板引用改用 bo-equity-researcher 且不再含 stock-deep-analysis"),
        (_new_title_anchor in _tmpl_html and _new_title_anchor in _render_src
         and "— Bo-FinancialAnalyzer</title>" in _render_src
         and _new_kicker_anchor in _tmpl_html and _new_kicker_anchor in _render_src
         and "BO-FINANCIALANALYZER · " in _render_src
         and "— financial-report-analysis</title>" not in (_tmpl_html + _render_src)
         and "FINANCIAL REPORT ANALYSIS" not in (_tmpl_html + _render_src),
         "模板与 render_report.py 的 HTML 标题/页眉品牌均为 Bo-FinancialAnalyzer（kicker 大写）"
         "且 sub1 锚文本与模板一致、旧品牌清零"),
    ]
    if not _block("更名命名契约（bo-financial-analyzer / Bo-FinancialAnalyzer）", naming_checks,
                  "更名命名契约未满足：Bo-FinancialAnalyzer 更名未落地，逐条核对上方 ❌。"):
        return 1

    failed = total - passed
    print(f"\n--- 汇总：通过 {passed} · 失败 {failed} ---")
    if failed:
        print("❌ 回归未通过：逐条核对上方 ❌；先确认是 calc.py 改坏了还是样本期望值需调整，"
              "禁止为了让测试变绿而改 fixture 数值。")
        return 1
    print("✅ 四例全绿：门禁既未误报干净样本、未漏报造假样本，也未错伤连亏样本与周期股样本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
