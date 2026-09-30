#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_regression.py — financial-report-analysis 的金标准回归测试

【它在测什么】
三个冻结样本（fixture）经 Phase 7.5 门禁 scripts/calc.py 后，必须同时满足门禁结论
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
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows 控制台默认 GBK，中文/emoji 会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent          # …/financial-report-analysis/tests
SKILL = HERE.parent                             # …/financial-report-analysis
CALC = SKILL / "scripts" / "calc.py"

MOUTAI = HERE / "moutai_2025.json"
KANGDEXIN = HERE / "kangdexin_2018.json"
VANKE = HERE / "vanke_2026h1.json"
WANHUA = HERE / "wanhua_2026h1.json"

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


def recon_hits(data):
    """verdict != 闭合 的 recon 条目（即门禁认定的勾稽异常）。"""
    return [(k, v.get("verdict")) for k, v in (data.get("recon") or {}).items()
            if isinstance(v, dict) and v.get("verdict") and v.get("verdict") != "闭合"]


def check_moutai(case, proc, data):
    """干净样本：抓误报。"""
    case.expect(proc.returncode == 0,
                f"calc.py exit 0（实际 {proc.returncode}）")
    summary = parse_summary(proc.stdout)
    if not case.expect(summary is not None, "汇总行可解析（calc.py 输出格式未变）"):
        return
    case.expect(summary["FAIL"] == 0, f"FAIL == 0（实际 {summary['FAIL']}）")
    case.expect(summary["WARN"] == 0,
                f"WARN == 0 —— 干净样本零误报（实际 {summary['WARN']}）")

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
    case.expect((data.get("meta") or {}).get("schema_version") == "1.4",
                f"schema_version == 1.4（实际 {((data.get('meta') or {}).get('schema_version'))}）")

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
    case.expect(proc.returncode == 0,
                f"calc.py exit 0（实际 {proc.returncode}）")
    summary = parse_summary(proc.stdout)
    if not case.expect(summary is not None, "汇总行可解析（calc.py 输出格式未变）"):
        return
    case.expect(summary["FAIL"] == 0, f"FAIL == 0（实际 {summary['FAIL']}）")

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
    # v0.0.12：造假样本的破产双模型必须真的算出来（非 SKIP）——失真时应 FAIL 而非静默
    case.expect("Altman" in (proc.stdout or ""),
                "新检查生效：康得新 Altman/Ohlson 复算被执行（v0.0.12）")
    asserts = data.get("assertions") or []
    case.expect(len(asserts) >= 1, f"断言表已落库（assertions >= 1，实际 {len(asserts)}）")
    bad = [a for a in asserts if isinstance(a, dict) and a.get("verdict") == "不成立"]
    case.expect(all(a.get("evidence") for a in bad),
                f"判「不成立」的断言均带反证（{len(bad)} 条）")
    # v0.0.15（schema 1.3）：口径断裂样本的五年归因必须合法降级（整块缺失/null + SKIP 行）
    case.expect((data.get("meta") or {}).get("schema_version") == "1.4",
                f"schema_version == 1.4（实际 {((data.get('meta') or {}).get('schema_version'))}）")
    d5 = (data.get("derived") or {}).get("dupont5y") or {}
    case.expect(all(d5.get(k) is None for k in
                    ("margin_effect", "turnover_effect", "leverage_effect")),
                "康得新 dupont5y 三效应全 null（2019 追溯重述口径断裂，合法降级）")
    case.expect("dupont5y" in (proc.stdout or ""),
                "新检查生效：calc.py 输出含 dupont5y 行（降级路径被执行）")


def check_vanke(case, proc, data):
    """万科 2026H1 半年报（连亏地产）：扣非双版/双驱动护栏的真实触发样本（v0.0.17 固化）。"""
    case.expect(proc.returncode == 0,
                f"calc.py exit 0（实际 {proc.returncode}）")
    summary = parse_summary(proc.stdout)
    if not case.expect(summary is not None, "汇总行可解析（calc.py 输出格式未变）"):
        return
    case.expect(summary["FAIL"] == 0, f"FAIL == 0（实际 {summary['FAIL']}）")
    # 已知合法 WARN 恰好 2 条：interest_arrears（单期付息错期）+ recon-coverage（B2/B3 附注未披露）
    case.expect(summary["WARN"] == 2,
                f"WARN == 2（interest_arrears + recon-coverage 合法两条，实际 {summary['WARN']}）")
    case.expect((data.get("meta") or {}).get("schema_version") == "1.4",
                f"schema_version == 1.4（实际 {((data.get('meta') or {}).get('schema_version'))}）")
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
    case.expect(proc.returncode == 0, f"calc.py exit 0（实际 {proc.returncode}）")
    sm = parse_summary(proc.stdout or "")
    case.expect(sm is not None, "汇总行可解析（calc.py 输出格式未变）")
    if sm:
        case.expect(sm["FAIL"] == 0, f"FAIL == 0（实际 {sm['FAIL']}）")
        case.expect(sm["WARN"] == 2,
                    f"WARN == 2（interest_arrears 单期 + recon-coverage 16/17 合法两条，实际 {sm['WARN']}）")
    meta = data.get("meta") or {}
    case.expect(meta.get("schema_version") == "1.4",
                f"schema_version == 1.4（实际 {meta.get('schema_version')}）")
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
    ap = argparse.ArgumentParser(description="financial-report-analysis 金标准回归测试")
    ap.add_argument("--verbose", action="store_true", help="附带 calc.py 的完整原始输出")
    args = ap.parse_args()

    print("=== financial-report-analysis 金标准回归 · calc.py 三例 ===")
    print(f"技能根：{SKILL}")
    print(f"门禁：  {CALC}")

    missing = [p for p in (CALC, MOUTAI, KANGDEXIN, VANKE, WANHUA) if not p.exists()]
    if missing:
        for p in missing:
            print(f"❌ 缺少文件：{p}")
        print("\n--- 汇总：通过 0 · 失败 1 ---")
        return 1

    total = passed = 0
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

    # 报告机检冒烟测试（P2 遗留项）：只确认 check_html.py 可运行，不校验内容，
    # 防止脚本语法错误/路径写死在无人察觉的情况下失效
    smoke = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "check_html.py"),
         str(SKILL / "assets" / "report-template.html")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    smoke_run = smoke.returncode in (0, 1) and "汇总" in (smoke.stdout or "")
    # v0.0.6 T5：s8-shape（下期跟踪清单阈值化）新检查必须真的被执行到
    smoke_s8 = "s8-shape" in (smoke.stdout or "")
    # v0.0.7：figtitle-style（结论式标题）新检查必须真的被执行到
    smoke_fig = "figtitle-style" in (smoke.stdout or "")
    # v0.0.12：缩写展开 / 桥图项数 / 归因标题 / 检验判定列 四个新检查必须真的被执行到
    smoke_v12 = all(c in (smoke.stdout or "") for c in
                    ("abbrev", "ocf-bridge-shape", "figtitle-attribution", "inspection-verdict"))
    # v0.0.15：s1 杜邦双卡形态检查必须被执行；dupont-stack 在 T8（--json）路径断言
    smoke_v15 = "s1-v15-shape" in (smoke.stdout or "")
    # v0.0.18：内部引用禁词 / srcline 拼接纪律 两条新 FAIL 规则必须被执行
    smoke_v18 = all(c in (smoke.stdout or "") for c in ("internal-ref", "srcline-dup"))
    # v0.0.19：三态措辞 / 小数位 / 断言计数 三条新检查必须真的被执行到
    smoke_v19 = all(c in (smoke.stdout or "") for c in
                    ("recon-label", "decimal-places", "assertion-count"))
    print(f"\n【报告机检冒烟】check_html.py 跑模板："
          f"{'✅' if smoke_run else '❌'} 可运行（exit {smoke.returncode}）· "
          f"{'✅' if smoke_s8 else '❌'} s8-shape 检查存活 · "
          f"{'✅' if smoke_fig else '❌'} figtitle-style 检查存活 · "
          f"{'✅' if smoke_v12 else '❌'} v0.0.12 四检查存活 · "
          f"{'✅' if smoke_v15 else '❌'} v0.0.15 s1-v15-shape 存活 · "
          f"{'✅' if smoke_v18 else '❌'} v0.0.18 两检查存活 · "
          f"{'✅' if smoke_v19 else '❌'} v0.0.19 三检查存活")
    if not (smoke_run and smoke_s8 and smoke_fig and smoke_v12 and smoke_v15
            and smoke_v18 and smoke_v19):
        print("❌ 回归未通过：check_html.py 无法正常运行或 s8-shape / figtitle-style / "
              "v0.0.12 / v0.0.15 / v0.0.18 / v0.0.19 检查缺失。")
        return 1

    # ── T8 数字回验三断言（v0.0.6）──
    # ①级：故意改错一个数字必须 FAIL 且指出位置；②级：src 行号回原文核对必须被执行
    def run_check_html(html):
        return subprocess.run(
            [sys.executable, str(SKILL / "scripts" / "check_html.py"),
             str(html), "--json", str(MOUTAI)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")

    t8_ok = run_check_html(HERE / "t8_demo.html")
    t8_bad = run_check_html(HERE / "t8_demo_bad.html")
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
    print("\n【T8 数字回验（check_html --json）】")
    for ok, desc in t8_checks:
        print(f"  {'✅' if ok else '❌'} {desc}")
        total += 1
        passed += ok
    if not all(ok for ok, _ in t8_checks):
        print("❌ 回归未通过：T8 数字回验断言失败，逐条核对上方 ❌。")
        return 1

    # ── v0.0.18 新规则构造用例（禁词 / 嵌套 srcline / 分位映射错配，各一反例）──
    def _run_html_str(s):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(s)
            tmp = f.name
        try:
            return subprocess.run(
                [sys.executable, str(SKILL / "scripts" / "check_html.py"),
                 tmp, "--json", str(MOUTAI)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
        finally:
            os.unlink(tmp)

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
    print("\n【v0.0.18 新规则构造用例】")
    for ok, desc in v18_checks:
        print(f"  {'✅' if ok else '❌'} {desc}")
        total += 1
        passed += ok
    if not all(ok for ok, _ in v18_checks):
        print("❌ 回归未通过：v0.0.18 新规则构造用例失败，逐条核对上方 ❌。")
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
    print("\n【v0.0.19 新规则构造用例】")
    for ok, desc in v19_checks:
        print(f"  {'✅' if ok else '❌'} {desc}")
        total += 1
        passed += ok
    if not all(ok for ok, _ in v19_checks):
        print("❌ 回归未通过：v0.0.19 新规则构造用例失败，逐条核对上方 ❌。")
        return 1

    # ── 分位白描映射双写契约锁（v0.0.18）：check_html_text.py 与 calc_models.py 各持一份
    # PCTILE_LABEL（跨家族 import 会造成耦合，故双写；check_html.py 再导出本锁的 import 锚点），
    # 本断言防单边漂移
    sys.path.insert(0, str(SKILL / "scripts"))
    from check_html import PCTILE_LABEL as _PL_CHECK
    from calc_models import PCTILE_LABEL as _PL_FILL
    pl_ok = _PL_CHECK == _PL_FILL
    print(f"\n【分位白描映射契约锁】{'✅' if pl_ok else '❌'} check_html.PCTILE_LABEL == calc_models.PCTILE_LABEL")
    total += 1
    passed += pl_ok
    if not pl_ok:
        print("❌ 回归未通过：白描映射双写漂移，同步两处后再提交。")
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
    else:
        render_ok = render_smoke.returncode == 0 and "渲染测量 0 问题" in render_out
        print(f"\n【渲染测量冒烟】check_render.py 跑 t8_demo.html："
              f"{'✅' if render_ok else '❌'} exit {render_smoke.returncode}")
        total += 1
        passed += render_ok
        if not render_ok:
            print("❌ 回归未通过：渲染测量冒烟未绿，看上方 check_render 输出。")
            return 1

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
        elif isinstance(node, str):
            out[pre[:-1]] = node
        return out

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
            bad = []
            for k in sorted(set(a) | set(b)):
                x, y = a.get(k), b.get(k)
                if isinstance(x, str) or isinstance(y, str):
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
    print("\n【--fill 幂等金标准（v0.0.13）】")
    for ok, desc in fill_checks:
        print(f"  {'✅' if ok else '❌'} {desc}")
        total += 1
        passed += ok
    gate_help = subprocess.run([sys.executable, str(SKILL / "scripts" / "gate.py"), "--help"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"  {'✅' if gate_help.returncode == 0 else '❌'} gate.py 单入口可运行（--help exit 0）")
    total += 1
    passed += gate_help.returncode == 0
    # v0.0.17：ts_fetch 冒烟——零测试短板补齐（只验可运行与用法文本，不触网）
    ts_help = subprocess.run([sys.executable, str(SKILL / "scripts" / "ts_fetch.py"), "--help"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
    ts_ok = ts_help.returncode == 0 and "api_name" in (ts_help.stdout or "")
    print(f"  {'✅' if ts_ok else '❌'} ts_fetch.py 取数通道可运行（--help exit 0 且含 api_name）")
    total += 1
    passed += ts_ok
    if not all(ok for ok, _ in fill_checks) or gate_help.returncode != 0 or not ts_ok:
        print("❌ 回归未通过：--fill 幂等或 gate.py / ts_fetch.py 断言失败。")
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
    print("\n【--min-recon 硬门禁（v0.0.17）】")
    for ok, desc in mr_checks:
        print(f"  {'✅' if ok else '❌'} {desc}")
        total += 1
        passed += ok
    if not all(ok for ok, _ in mr_checks):
        print("❌ 回归未通过：--min-recon 硬门禁断言失败。")
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
    print("\n【md_clean 金标准（v0.0.17 合成样本，自包含）】")
    for ok, desc in md_checks:
        print(f"  {'✅' if ok else '❌'} {desc}")
        total += 1
        passed += ok
    if not all(ok for ok, _ in md_checks):
        print("❌ 回归未通过：md_clean 金标准断言失败。")
        return 1

    # ── v0.0.15 构造用例（公式层直测，不动 fixture 文件）──
    # 扣非双版触发 / 双驱动护栏 / 话语权型杠杆升档——两条规则无真实 fixture 覆盖
    # （茅台非经 0.03% 不触发、杠杆非主驱动），用 deepcopy 构造临界场景验证
    sys.path.insert(0, str(SKILL / "scripts"))
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
    print("\n【v0.0.15 构造用例（扣非双版/双驱动/升档）】")
    for ok, desc in constructed:
        print(f"  {'✅' if ok else '❌'} {desc}")
        total += 1
        passed += ok
    if not all(ok for ok, _ in constructed):
        print("❌ 回归未通过：v0.0.15 构造用例断言失败。")
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
