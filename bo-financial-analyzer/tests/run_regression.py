#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_regression.py — bo-financial-analyzer 的金标准回归测试

【它在测什么】
五个冻结样本（fixture）经 Phase 7.5 门禁 scripts/calc.py 后，必须同时满足门禁结论
与样本语义，用来抓「改坏门禁」这一类回归：
  · tests/moutai_2025.json     贵州茅台 2025 年报 —— 干净样本，抓**误报**（假阳性）
  · tests/kangdexin_2018.json  康得新 2018 年报   —— 造假样本，抓**漏报**（假阴性）
  · tests/vanke_2026h1.json    万科A 2026 半年报  —— 连亏地产样本（v0.0.17 固化）：
                               扣非双版/双驱动护栏的真实触发锚点 + fill 块级 note 保留
  · tests/wanhua_2026h1.json   万华化学 2026 半年报 —— 周期股样本（v0.0.18 固化，N3 落地）：
                               周期证据链 + 双驱动护栏第二真实样本 + ROIC/内生增长率首验锚点
  · tests/qingyue_2022.json    清越科技 2022 年报 —— 新准则造假样本（v0.1.7 固化，N5）：
                               外部处罚 × 收入 KAM × 少计减值 + 三期现金背离

断言清单
  [共同] calc.py exit code == 0（FAIL 清零），汇总 FAIL == 0
  [茅台] WARN == 0；recon 中 verdict 为「无法解释/可解释」的条目 == 0；
         A2 倒挤分红降级 SKIP；v0.0.12 四项新检查输出行存在
  [康得新] signals >= 11 条；其中 level=='r' 的红色信号 >= 6 条；
           recon 命中（verdict != 闭合）>= 3 条；Altman 复算被执行
  [万科] WARN == 2（interest_arrears + recon-coverage 两条合法 WARN）；
         dupont_dt.triggered（扣非双版）与 dupont.driver_fragile（双驱动）真实命中；
         Altman 危险区 + Ohlson 中；risk_models 块级 note 存活
  [清越] 三期净现比均 <0.5；非经占比约45.42%；标准无保留+收入KAM与处罚交叉；
         应收计提率真实下降但不得以未达增速差阈值为由放行；闭合≠真实；
         A2 权益扣减与期后拟派分红不混用
门禁改钝（干净样本冒出 WARN、造假样本不再报警）都会让本脚本 exit 1。

【怎么跑】
    python tests/run_regression.py              # 简洁清单
    python tests/run_regression.py --verbose    # 附带 calc.py 的完整原始输出
    退出码：0 = 全部通过；1 = 有断言失败（清单里 ❌ 的行即原因）

【改动纪律】
只要动了 scripts/calc.py 或 references/extraction-schema.md，提交前必须跑本脚本，
且必须五例全绿；改错比率、删 src、破坏桥闭合等反例应能把它打红。

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
QINGYUE = HERE / "qingyue_2022.json"
YINGHE = HERE / "yinghe_2026h1.json"
BREO_B2 = HERE / "breo_2025_b2.json"
YINGHE_LEVERAGE = HERE / "yinghe_2025_leverage.json"
MIDEA_LEVERAGE_NEGATIVE = HERE / "midea_2025_leverage_negative.json"

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
    """五例公共序言：exit 0 + 汇总行可解析 + FAIL==0 + schema 1.6（可选 WARN 数锚，
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
    case.expect(any("[SKIP] A2 " in line for line in (proc.stdout or "").splitlines()),
                "A2 拒绝用旧底稿的倒挤分红制造闭合；缺权益扣减额时降级 SKIP")

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


def check_qingyue(case, proc, data):
    """清越科技 2022：新准则造假样本，锁现金质量与外部硬证据的交叉核验。"""
    if _prologue(case, proc, data) is None:
        return
    case.expect(not any("[WARN] A2 " in line for line in (proc.stdout or "").splitlines()),
                "A2 使用本期权益扣减分红，不把期后拟派利润误扣一次")

    rr = (data.get("derived") or {}).get("ratios") or {}
    ncr = (rr.get("net_cash_ratio") or {}).get("hist") or []
    case.expect(len(ncr) == 3 and all(isinstance(x, (int, float)) and x < 0.5 for x in ncr),
                f"2020-2022 净现比连续三期 <0.5（实际 {ncr}）")
    nonrecurring = (rr.get("nonrecurring_share") or {}).get("cur")
    case.expect(isinstance(nonrecurring, (int, float))
                and abs(nonrecurring - 0.45417664) < 0.0001,
                f"非经常项占归母净利约 45.42%（实际 {nonrecurring}）")

    notes = data.get("notes") or {}
    audit = notes.get("audit") or {}
    kams = audit.get("kam") or []
    case.expect(audit.get("opinion") == "标准无保留"
                and any("收入" in (k.get("topic") or "") for k in kams),
                "标准无保留意见与收入确认 KAM 同时保留，不以审计意见排除异常")
    ar_provision = notes.get("ar_provision") or {}
    ar_cur = (ar_provision.get("cur") or 0) / ((data["statements"]["balance"]["ar"]["cur"])
                                               + ar_provision.get("cur", 0))
    ar_prev = (ar_provision.get("prev") or 0) / ((data["statements"]["balance"]["ar"]["prev"])
                                                 + ar_provision.get("prev", 0))
    case.expect(abs(ar_cur - 0.006287694) < 0.000001
                and abs(ar_prev - 0.009297236) < 0.000001 and ar_cur < ar_prev,
                f"应收计提率由约 0.93% 降至 0.63%（实际 {ar_prev:.4%}→{ar_cur:.4%}）")

    sigs = {s.get("id"): s for s in (data.get("signals") or []) if isinstance(s, dict)}
    for sig_id in ("QY_NCR", "QY_NONRECURRING", "QY_KAM_PENALTY", "QY_AR_PENALTY"):
        case.expect(sigs.get(sig_id, {}).get("level") == "r"
                    and bool(sigs.get(sig_id, {}).get("source")),
                    f"{sig_id} 红色信号已落库，且有出处（实际 {sigs.get(sig_id)}）")
    case.expect("csrc.gov.cn" in (sigs.get("QY_AR_PENALTY") or {}).get("source", "")
                and "20pct" not in (sigs.get("QY_AR_PENALTY") or {}).get("data", ""),
                "应收减值由处罚硬证据升级，不虚称达到 20pct 增速差阈值")
    case.expect(any(v.get("verdict") == "闭合" for v in (data.get("recon") or {}).values()
                    if isinstance(v, dict))
                and any("闭合≠真实" in str(s.get("evidence", "")) for s in sigs.values()),
                "勾稽闭合与期后处罚并存，明确闭合≠真实")


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

    print("=== bo-financial-analyzer 金标准回归 · calc.py 五例 ===")
    print(f"技能根：{SKILL}")
    print(f"门禁：  {CALC}")

    missing = [p for p in (CALC, MOUTAI, KANGDEXIN, VANKE, WANHUA, QINGYUE) if not p.exists()]
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
        ("清越科技 2022 年报 · 新准则造假样本（外部处罚交叉验证）", QINGYUE, check_qingyue),
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
                   "wanhua_2026h1.json", "qingyue_2022.json"):
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

    # 牧原实证：编号主表不得漏识别、后被政策说明文字冒充（索引行必须落在 clean md 实际标题）
    with tempfile.TemporaryDirectory() as _tdi:
        _mi = Path(_tdi) / "numbered.md"
        _mi.write_text(
            "第三节 管理层讨论与分析\n\n本期收入 123.45 亿元，经营讨论正文保留。\n\n"
            "3、合并利润表\n\n| 项目 | 本期 |\n| --- | --- |\n| 营业收入 | 100.00 |\n\n"
            "会计政策变更\n\n合并利润表 母公司利润表\n\n| 营业成本 | 80.00 |\n\n"
            "三、关键审计事项\n\n关键审计事项是我们根据职业判断确定的事项，正文不得冒名。\n",
            encoding="utf-8")
        _ri = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                              str(_mi), "--out-dir", _tdi], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        _ic = (Path(_tdi) / "numbered.clean.md").read_text(encoding="utf-8")
        _ii = json.loads((Path(_tdi) / "numbered.index.json").read_text(encoding="utf-8"))
        _iline = _ic.splitlines().index("3、合并利润表") + 1
        _kline = _ic.splitlines().index("三、关键审计事项") + 1
    if not _block("md_clean 编号主表索引（牧原实证）",
                  [(_ri.returncode == 0 and _ii.get("blocks", {}).get("合并利润表") == _iline,
                    "编号主表入索引且指向实际标题，不被后续政策说明冒名"),
                   (_ii.get("blocks", {}).get("关键审计事项") == _kline,
                    "中文编号标题入索引，后续正文不得冒名")],
                  "编号主表索引失效。"):
        return 1

    with tempfile.TemporaryDirectory() as _tds:
        _missing = Path(_tds) / "missing.md"
        _missing.write_text(
            "合并资产负债表\n合并利润表\n合并现金流量表\n\n"
            "一、 基本情况\n\n"
            "流动资产 非流动资产 资产合计 流动负债 非流动负债 负债合计 营业收入\n"
            "| 资产合计 | 79,952,858,979 | 69,051,541,911 |\n", encoding="utf-8")
        _rmiss = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                                 str(_missing), "--out-dir", _tds],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        _normal = Path(_tds) / "normal.md"
        _normal.write_text(
            "合并资产负债表\n合并利润表\n合并现金流量表\n\n"
            "| 流动资产合计 | 100.00 |\n| 非流动资产合计 | 200.00 |\n| 资产总计 | 300.00 |\n\n"
            "一、 基本情况\n\n附注正文。\n", encoding="utf-8")
        _rnorm = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                                 str(_normal), "--out-dir", _tds],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        _plain = Path(_tds) / "plain.md"
        _plain.write_text("一、 基本情况\n\n流动资产 非流动资产 资产合计\n", encoding="utf-8")
        _rplain = subprocess.run([sys.executable, str(SKILL / "scripts" / "md_clean.py"),
                                  str(_plain), "--out-dir", _tds],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
        _missing_idx = json.loads((Path(_tds) / "missing.index.json").read_text(encoding="utf-8"))
        _missing_warn = _missing_idx.get("statement_warnings") or []
        _groups = ("流动资产合计", "非流动资产合计", "资产总计")
    if not _block("md_clean 图片型主表缺失告警", [
        (_rmiss.returncode == 0 and "主表文本完整性提示" in (_rmiss.stdout or "")
         and "不阻断清洗" in (_rmiss.stdout or "")
         and all(k in (_rmiss.stdout or "") for k in _groups)
         and len(_missing_warn) == 1 and all(k in _missing_warn[0] for k in _groups),
         "目录三表齐全但附注前主表资产行缺失：三组缺失名全部告警且写入sidecar，附注内同名行不得冒充主表"),
        (_rnorm.returncode == 0 and "主表文本完整性提示" not in (_rnorm.stdout or ""),
         "三类资产行齐全的正常主表不误报"),
        (_rplain.returncode == 0 and "主表文本完整性提示" not in (_rplain.stdout or ""),
         "无合并三表目录时不猜测、不告警"),
    ], "图片型主表缺失告警失败。"):
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
    d3["derived"]["ratios"]["equity_multiplier"]["prev"] = 1.10  # 权益乘数上升，构造正向杠杆主驱动
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

    # ── B2 完整存货流与杠杆升档真实样本（专用小底稿，非完整报告 fixture）──
    from calc_common import build_ratio_calcs as _brc_real, ratio_hist_expect as _rhe_real
    _b2real = load_json(BREO_B2)
    _flow = _b2real["notes"]["inventory_flow"]
    _b2node = _b2real["recon"]["B2_inv_roll"]
    _b2lhs = (_flow["purchase"]["cur"] + _flow["direct_labor"]["cur"]
              + _flow["outsourcing"]["cur"] + _flow["manufacturing_freight"]["cur"]
              + _b2real["statements"]["balance"]["inventory"]["prev"]
              - _b2real["statements"]["income"]["cost"]["cur"])
    _b2adjusted = _b2lhs - _flow["period_expense_use"]["cur"] - _flow["provision_writeoff"]["cur"]
    _b2rep = _Rep()
    _calc.check_recon(_b2real, _b2rep)
    _b2checks = [
        (round(_b2lhs, 2) == 12598.78 == _b2node["lhs"],
         f"倍轻松真实B2：完整增加额代入简化式 lhs={_b2lhs:.2f}"),
        (round(_b2adjusted, 2) == 11055.37 == _b2node["rhs"],
         f"倍轻松真实B2：期间领用+跌价转销解释后期末={_b2adjusted:.2f} 精确闭合"),
        (abs(_b2lhs - _b2node["rhs"]) / _b2node["rhs"] > 0.05
         and not any(lv == _FAIL for lv, _, _ in _b2rep.rows)
         and any(code == "B2_inv_roll" and lv == "OK" for lv, code, _ in _b2rep.rows),
         "倍轻松真实B2：简化式偏差>5%但披露调整项完整，判可解释且门禁无FAIL"),
    ]
    if not _block("B2 完整存货生产入库真实样本", _b2checks, "B2真实样本复算失败。"):
        return 1

    _lyreal = load_json(YINGHE_LEVERAGE)
    _lycur = _brc_real(_lyreal)
    _lyi = _lyreal["statements"]["income"]
    _lyb = _lyreal["statements"]["balance"]
    _lyprev = {
        ("income", "revenue"): _lyi["revenue"]["prev"],
        ("income", "np_at"): _lyi["np_at"]["prev"],
        ("income", "np_total"): _lyi["np_total"]["prev"],
        ("income", "income_tax"): _lyi["income_tax"]["prev"],
        ("income", "fin_exp"): _lyi["fin_exp"]["prev"],
        ("balance", "equity_at"): _lyb["equity_at"]["prev"],
        ("balance", "total_assets"): _lyb["total_assets"]["prev"],
        "total_assets_prev": _lyb["total_assets"]["hist"][0],
    }
    _lyreal["derived"]["ratios"] = {
        name: {"cur": _lycur[name], "prev": _rhe_real(name, _lyprev)}
        for name in ("net_margin", "asset_turnover", "equity_multiplier", "roe", "dfl")
    }
    _lydu = calc_dupont.compute_dupont(_lyreal)
    _lyld = _lydu["leverage_drill"]
    _lyh1 = calc_dupont.compute_dupont(load_json(YINGHE))
    _mireal = load_json(MIDEA_LEVERAGE_NEGATIVE)
    _micur = _brc_real(_mireal)
    _mii = _mireal["statements"]["income"]
    _mib = _mireal["statements"]["balance"]
    _miprev = {
        ("income", "revenue"): _mii["revenue"]["prev"],
        ("income", "np_at"): _mii["np_at"]["prev"],
        ("income", "np_total"): _mii["np_total"]["prev"],
        ("income", "income_tax"): _mii["income_tax"]["prev"],
        ("income", "fin_exp"): _mii["fin_exp"]["prev"],
        ("balance", "equity_at"): _mib["equity_at"]["prev"],
        ("balance", "total_assets"): _mib["total_assets"]["prev"],
        "total_assets_prev": _mib["total_assets"]["hist"][0],
    }
    _mireal["derived"]["ratios"] = {
        name: {"cur": _micur[name], "prev": _rhe_real(name, _miprev)}
        for name in ("net_margin", "asset_turnover", "equity_multiplier", "roe", "dfl")
    }
    _midu = calc_dupont.compute_dupont(_mireal)
    _mild = _midu["leverage_drill"]
    _lychecks = [
        (_lydu["driver"] == "杠杆" and abs(_lydu["leverage_effect"] - 0.01935) < 0.00005
         and abs(_lydu["leverage_effect"]) > max(abs(_lydu["margin_effect"]), abs(_lydu["turnover_effect"])),
         f"赢合2025FY真实杠杆：效应={_lydu['leverage_effect']:+.5f} 为第一驱动"),
        (abs(_lyld["ni_share"] - 0.9735) < 0.0001 and abs(_lyld["dfl_delta"] - 0.0047) < 0.0001
         and _lyld["quality_upgrade"] is True,
         f"赢合2025FY真实杠杆：无息={_lyld['ni_share']:.4%} ΔDFL={_lyld['dfl_delta']:+.4f} → 升档"),
        (_lyh1["driver"] == "杠杆" and _lyh1["leverage_drill"]["quality_upgrade"] is False,
         f"赢合2026H1阴性对照：ΔDFL={_lyh1['leverage_drill']['dfl_delta']:+.4f}>0.1 → 不升档"),
        (_midu["driver"] == "杠杆" and _midu["leverage_effect"] < 0
         and _mild["ni_share"] > 0.7 and abs(_mild["dfl_delta"]) < 0.1
         and _mild["quality_upgrade"] is False,
         f"美的2025FY真实负样本：杠杆效应={_midu['leverage_effect']:+.5f}<0，"
         f"无息={_mild['ni_share']:.2%} ΔDFL={_mild['dfl_delta']:+.4f} → 不得升档"),
    ]
    if not _block("杠杆升档真实触发样本", _lychecks, "杠杆真实样本复算失败。"):
        return 1

    # ── calc FAIL 判据阳性（v0.1.1 全库审计补口）──
    # 变异实证：五例都是合法样本只断言 exit 0，门禁 FAIL 判据被改钝/误删时回归照样全绿
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

        def _cip_nonzero(d):
            d["notes"].pop("cip_projects", None)
            d["statements"]["balance"]["cip"]["cur"] = 19.7268
        rr_cn, h_cn = _replay(_cip_nonzero, "yh_cip_nonzero")

        def _cip_missing(d):
            d["notes"].pop("cip_projects", None)
            d["statements"]["balance"]["cip"]["cur"] = None
        rr_cm, h_cm = _replay(_cip_missing, "yh_cip_missing")

        def _no_missing(d):
            for a in d.get("assertions") or []:
                a.pop("missing", None)
        rr_g, h_gap = _replay(_no_missing, "yh_gap")

        def _seg_off(d):
            d["statements"]["income"]["by_segment"][0]["rev_cur"] += 5.0
        rr_s, h_seg = _replay(_seg_off, "yh_seg")
        def _seg_missing(d):
            for _seg in d["statements"]["income"]["by_segment"]:
                _seg["rev_prev"] = None
        rr_se, h_se = _replay(_seg_missing, "yh_seg_empty")
        rr_o, h_ocf = _replay(lambda d: d["derived"].pop("ocf_bridge", None), "yh_ocf")
        def _recon_gap(d):
            d["recon"]["B2_inv_roll"] = {"lhs": None, "rhs": None, "verdict": "",
                                         "explanation": "未披露完整增加额，未执行", "src": "构造缺口"}
        rr_rg, h_recon_gap = _replay(_recon_gap, "yh_recon_gap")

        def _cip_semantics(d):
            d["notes"]["cip_projects"] = [
                {"name": "流量存量分列", "budget": 10.0, "invested_cur": 1.23,
                 "closing_balance": 4.56, "progress": 0.5, "transferred": 0.2, "src": "构造"},
                {"name": "仅披露期末", "budget": None, "invested_cur": None,
                 "closing_balance": 7.89, "progress": None, "transferred": None, "src": "构造"},
            ]
        rr_cs, h_cip_semantics = _replay(_cip_semantics, "yh_cip_semantics")
    render_pos_checks = [
        (anchor_fail, "断锚阳性：锚复制成双份必 exit 1 且打印断锚清单（v0.1.1）"),
        (rr_h.returncode == 0 and 'id="holders"' not in h_holders
         and "时序不足 3 期降级" in h_holders,
         "降级①：删 holder_ts → 户数图卡降级两期文字行（holders_drop）"),
        (rr_c.returncode == 0 and "在建工程（期末余额为零" in h_cip,
         "降级②：删 cip_projects → 真实零余额在建降级行（cip_empty）"),
        (rr_cn.returncode == 0 and "在建工程（期末余额19.73亿，无项目附注）" in h_cn
         and "⚠️ 观察" in h_cn and "期末余额为零" not in h_cn and "无挂账" not in h_cn,
         "降级②b：非零在建缺项目附注 → 显示真实余额并观察，不冒充零余额（牧原 Q3 实证）"),
        (rr_cm.returncode == 0 and "在建工程（期末余额未披露，无项目附注）" in h_cm
         and "⚠️ 观察" in h_cm and "期末余额为零" not in h_cm,
         "降级②c：在建余额未披露 → 保持未知，不写成零"),
        (rr_g.returncode == 0 and "数据缺口声明" not in h_gap,
         "降级③：断言全无 missing → 数据缺口声明行整行删（gap_drop）"),
        (rr_s.returncode == 0 and '"其他"' in h_seg,
         "降级④：分部合计≠Δ收入 → SEG_BRIDGE 补「其他」桶闭合（SEG 轴）"),
        (rr_o.returncode == 0 and 'id="ocfbridge"' not in h_ocf
         and "OCF 调节桥未披露" in h_ocf,
         "降级⑤：删 ocf_bridge → 桥卡降级声明（ocf_drop，v0.1.1 新增）"),
        (rr_se.returncode == 0 and "const SEG_BRIDGE=[];" in h_se
         and 'id="segbridge"' not in h_se and "分部收入变动桥未绘制" in h_se
         and "（收入变动 +18.26 亿）" in h_se and "（分部合计" not in h_se,
         "降级⑥：分部上期金额缺失 → 空桥删 svg 换声明，端点行只称收入变动（恒瑞 Q3 实证）"),
        (rr_rg.returncode == 0 and "B2 存货 roll-forward" in h_recon_gap
         and "⚠️ 未执行" in h_recon_gap
         and re.search(r"：13 条闭合[^\n]*1 项未执行（B2）", h_recon_gap),
         "未执行勾稽不得计入闭合：B2空verdict须入清单并单列未执行计数"),
        ("13 条闭合 · 2 项可解释 · 1 项未执行（B2）" in h_recon_gap,
         "勾稽汇总须同时列出闭合、可解释与未执行数量"),
        ("+6.29 倍 / 1257.8%" in h_recon_gap and "+6.29 亿 / 1257.8%" not in h_recon_gap,
         "D3母公司其他应收款比率的偏差单位必须为倍而非亿"),
        (rr_cs.returncode == 0 and "本期投入（亿元）" in h_cip_semantics
         and "期末余额（亿元）" in h_cip_semantics
         and re.search(r"流量存量分列</td><td>10.0</td><td>1.23</td><td>4.56</td>", h_cip_semantics)
         and re.search(r"仅披露期末</td><td>—</td><td>—</td><td>7.89</td>", h_cip_semantics),
         "在建工程本期投入与期末余额必须分字段、分列呈现，缺数保持未知"),
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

    # 万华 2025FY：三因子 hist 为 5/4/5 期时，累计归因窗口是 2022→2025，
    # 首端必须统一右对齐到倒数第 4 期，不能分别取各序列第 1 期。
    _d5_window = {"derived": {"ratios": {
        "net_margin": {"hist": [0.1694, 0.098, 0.0959, 0.0716, 0.0616]},
        "asset_turnover": {"hist": [0.8466, 0.7727, 0.6665, 0.6595]},
        "equity_multiplier": {"hist": [2.7783, 2.6136, 2.8542, 3.0999, 2.9824]}},
        "dupont5y": {"period_start": "2022", "period_end": "2025", "percentile": {
            "net_margin": 0.0, "asset_turnover": 0.0, "equity_multiplier": 0.6667}}}}
    _d5_rows = _bs13(_d5_window)["s1"]["dupont5y"]["rows"]
    _d5_equal = copy.deepcopy(_d5_window)
    _d5_equal["derived"]["ratios"]["asset_turnover"]["hist"] = [0.95, 0.8466, 0.7727, 0.6665, 0.6595]
    _d5_equal_rows = _bs13(_d5_equal)["s1"]["dupont5y"]["rows"]
    if not _block("万华2025FY五年归因首端窗口回归", [
        ([r["start"] for r in _d5_rows] == ["9.80%", "0.85", "2.61"],
         f"5/4/5期 hist 首端统一取2022（实际 {[r['start'] for r in _d5_rows]}）"),
        ([r["start"] for r in _d5_equal_rows] == ["16.94%", "0.95", "2.78"],
         "5/5/5期等长序列仍取原首端，不受右对齐修复影响"),
    ], "五年归因首端窗口修复失败，检查 calc_slots 与 compute_dupont5y 的窗口规则。"):
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

    # 中国船舶 2025FY：fill 后的 26.645 在展示层仍须按四舍五入为 26.65，
    # 且归母 78.48 + 少数股东 26.65 = 总净利 105.13，不能出现 0.01 亿显示断链。
    _sk_round_data = load_json(YINGHE)
    _sk_round_data["derived"]["sankey"].update({"np": 105.13, "np_at": 78.48, "minority": 26.645})
    _sk_rounded = _bsk(_sk_round_data)
    _sk_round_data["derived"]["sankey"]["minority"] = 26.6449
    _sk_round_down = _bsk(_sk_round_data)
    if not _block("中国船舶桑基少数股东舍入回归", [
        (_sk_rounded["minority"] == 26.65
         and round(_sk_rounded["np_at"] + _sk_rounded["minority"], 2) == _sk_rounded["np"],
         f"26.645应四舍五入为26.65且显示层闭合（实际 {_sk_rounded}）"),
        (_sk_round_down["minority"] == 26.64,
         f"26.6449未达入位边界仍应为26.64（实际 {_sk_round_down['minority']}）"),
    ], "桑基少数股东舍入修复失败，检查展示层舍入规则。"):
        return 1

    _d4_label_data = copy.deepcopy(base)
    _d4_label_data["recon"].setdefault("D4_parent_invest", {}).update(
        {"verdict": "可解释", "explanation": "构造D4异常行"})
    _d4_labels = [r["eq"] for r in _bs15(_d4_label_data)["s2"]["recon_rows"]]
    if not _block("D4母公司投资收益行名回归", [
        ("D4 母公司投资收益/净利润" in _d4_labels
         and "D4 母公司长期股权投资" not in _d4_labels,
         f"D4异常勾稽行须与公式同名（实际 {_d4_labels}）"),
    ], "D4行名修复失败，检查 calc_slots._RECON_NAME。"):
        return 1

    _rate_data = copy.deepcopy(base)
    _rate_data["recon"]["A7_implied_rate"] = {"lhs": 0.055, "rhs": 0.05, "verdict": "可解释",
                                              "explanation": "构造利率差", "src": "构造"}
    _rate_data["recon"]["A8_invest_income"] = {"lhs": 0.10574907939407949, "rhs": 0.1,
                                                "verdict": "可解释", "explanation": "构造收益率差", "src": "构造"}
    _rate_dev = {r["eq"]: r["deviation"] for r in _bs15(_rate_data)["s2"]["recon_rows"]}
    if not _block("利率型勾稽偏差单位回归", [
        (_rate_dev.get("A7 隐含利率检验") == "+0.50pct / 10.0%"
         and _rate_dev.get("A8 投资收益合理性") == "+0.57pct / 5.7%"
         and all("亿" not in v for v in _rate_dev.values()),
         f"A7/A8利率差须用pct而非亿（实际 {_rate_dev}）"),
    ], "利率型偏差单位修复失败，检查 calc_slots.recon_rows。"):
        return 1

    _closed_data = copy.deepcopy(base)
    _closed_data["recon"] = {
        **{f"A{i:02d}": {"lhs": 1, "rhs": 1, "verdict": "闭合", "explanation": "", "src": "构造"}
           for i in range(1, 14)},
        "A14": {"lhs": 2, "rhs": 1, "verdict": "可解释", "explanation": "构造A", "src": "构造"},
        "A15": {"lhs": 2, "rhs": 1, "verdict": "可解释", "explanation": "构造B", "src": "构造"},
        "B2_inv_roll": {"lhs": None, "rhs": None, "verdict": "",
                        "explanation": "未披露生产入库", "src": "构造"},
    }
    _closed_path = HERE / "_closed_count_tmp.md"
    try:
        _wfs15(_closed_data, str(_closed_path))
        _closed_text = _closed_path.read_text(encoding="utf-8")
    finally:
        _closed_path.unlink(missing_ok=True)
    if not _block("fillsheet 闭合计数剔除未执行", [
        ("✅ 闭合 13 条一行汇总" in _closed_text and "✅ 闭合 14 条一行汇总" not in _closed_text,
         "13闭合+2可解释+1未执行时，fillsheet只能汇总13条闭合"),
    ], "fillsheet 闭合计数仍把未执行计入。"):
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

        # ③④ watchlist badge 白名单 + 文本单次转义共用一张真实 render 构造卡
        cp_c = _fill_copy(lambda d: d.update(watchlist=[{
            "indicator": "测试<跟踪卡>", "current": "1.0 & 可比", "badge": "bogus",
            "upper": "2", "upper_meaning": "偏高", "lower": "0", "lower_meaning": "偏低",
            "tripwire": "增速<5% & OCF<0 则复核", "source": "测试&来源"}, {
            "indicator": "旧底稿来源卡", "current": "1.0", "badge": "disc",
            "upper": "2", "upper_meaning": "偏高", "lower": "0", "lower_meaning": "偏低",
            "tripwire": "熔断句", "source": "clean L150-L158/L162、L456"}]), "v15_badge")
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
        ('<div class="figtitle">测试&lt;跟踪卡&gt;</div>' in h_c
         and '<div class="wv">1.0 &amp; 可比' in h_c
         and '<div class="wb">&gt; 2 偏高 / &lt; 0 偏低；增速&lt;5% &amp; OCF&lt;0 则复核</div>' in h_c
         and '<div class="srcline">数据来源：测试&amp;来源</div>' in h_c
         and "&amp;gt;" not in h_c and "&amp;lt;" not in h_c,
         "⑬④watchlist 标题/读数/阈值/来源只转义一次，不产生 &amp;gt;/&amp;lt;"),
        ('<div class="srcline">数据来源：公司定期报告</div>' in h_c
         and "数据来源：clean" not in h_c,
         "⑬⑤旧式 clean L 来源定位归一为公司定期报告，不留空来源或斜杠残渣"),
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
    # 数字政通 2025FY：五年归因标量也须进入 % 权威池；近值撞窗消除，独立错值仍报警。
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as _jd5:
        json.dump({"meta": {"company": "构造样本", "code": "000000", "period": "20251231",
                            "report_type": "年报", "unit": "亿元"},
                   "derived": {"ratios": {"asset_turnover": {"cur": 0.1471, "prev": 0.1545}},
                               "dupont5y": {"turnover_effect": 0.147, "margin_effect": -0.3317}},
                   "recon": {"A8_invest_income": {"lhs": 0.1544065}}},
                  _jd5, ensure_ascii=False)
        _jd5p = _jd5.name
    try:
        t8_d5_ok = _run_html_str(
            _SECT + '<div class="card"><p>周转率累计贡献 +14.70pct</p></div></div>', _jd5p)
        t8_d5_bad = _run_html_str(
            _SECT + '<div class="card"><p>净利率累计贡献 -33.19pct</p></div></div>', _jd5p)
        t8_recon_pct = _run_html_str(
            _SECT + '<div class="card"><p>隐含收益率 15.44%</p></div></div>', _jd5p)
    finally:
        os.unlink(_jd5p)
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
        ("[FAIL] num-vs-json" not in (t8_d5_ok.stdout or ""),
         "数字政通：五年归因+14.70pct不得误撞周转率14.71%"),
        ("[FAIL] num-vs-json" in (t8_d5_bad.stdout or "")
         and "相近但不等" in (t8_d5_bad.stdout or ""),
         "数字政通：独立归因效应-33.19pct与底稿-33.17pct不符仍必FAIL"),
        ("[FAIL] num-vs-json" not in (t8_recon_pct.stdout or ""),
         "数字政通：A8隐含收益率15.44%不得误撞周转率15.45%"),
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

    # ── v0.1.7 季报类型归一化：三份真实 Q3 底稿共同根因的自包含回归锁 ──
    from calc_common import hist_periods as _hp17
    from calc_risk import compute_altman as _ca17
    _d17 = json.loads(YINGHE.read_text(encoding="utf-8"))
    _d17["meta"].update({"period": "20260930", "report_type": "季报"})
    _alt17, _why17 = _ca17(_d17)
    _d17_ref = json.loads(YINGHE.read_text(encoding="utf-8"))
    _d17_ref["meta"].update({"period": "20260930", "report_type": "三季报"})
    _alt17_ref, _why17_ref = _ca17(_d17_ref)
    v17_type = [
        (_hp17({"period": "20260930", "report_type": "季报"}, 5)
         == ["2022Q3", "2023Q3", "2024Q3", "2025Q3", "2026Q3"],
         "v0.1.7①：通用季报 + 0930 倒推五期 Q3 标签"),
        (_hp17({"period": "20260331", "report_type": "季报"}, 2) == ["2025Q1", "2026Q1"],
         "v0.1.7①：通用季报 + 0331 倒推 Q1 标签"),
        (_hp17({"period": "20260630", "report_type": "季报"}, 2) is None,
         "v0.1.7①：通用季报遇到 0630 不猜季度，返回 None"),
        (_hp17({"period": "20260930", "report_type": "三季报"}, 2) == ["2025Q3", "2026Q3"],
         "v0.1.7①：显式三季报标签行为零漂移"),
        (_alt17_ref is not None and _alt17 == _alt17_ref and _alt17.get("annualized") is True,
         f"v0.1.7①：通用季报 Altman 与显式三季报一致且流量年化（ref={_alt17_ref}, got={_alt17}）"),
    ]
    if not _block("v0.1.7 季报类型归一化构造用例", v17_type,
                  "v0.1.7 季报类型归一化失败，逐条核对上方 ❌。"):
        return 1

    _r17_a4 = _auto_run("A股", "季报", drop=10)
    _r17_long4 = _auto_run("A股（创业板）+H股（03750.HK）", "季报", drop=10)
    _r17_long3 = _auto_run("A股（创业板）+H股（03750.HK）", "季报", drop=11)
    v17_auto = [
        ("覆盖下限 4" in (_r17_a4.stdout or "")
         and "未达 --min-recon 4" not in (_r17_a4.stdout or ""),
         "v0.1.7②：A股季报 4/17 达真实样本最低可执行数，不升覆盖率 FAIL"),
        ("覆盖下限 4" in (_r17_long4.stdout or "")
         and "未达 --min-recon 4" not in (_r17_long4.stdout or ""),
         "v0.1.7②：A股+H股长市场名按主上市地识别，4/17 不升覆盖率 FAIL"),
        ("未达 --min-recon 4" in (_r17_long3.stdout or ""),
         "v0.1.7②：长市场名季报降至 3/17 必升覆盖率 FAIL（阈值方向）"),
    ]
    if not _block("v0.1.7 auto 市场识别与季报下限构造用例", v17_auto,
                  "v0.1.7 auto 修复失败，逐条核对上方 ❌。"):
        return 1

    _tmpl17 = (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
    _contrast_ok = _run_html_str(_tmpl17, json_path=None)
    _contrast_muted = _run_html_str(
        re.sub(r"--muted:rgba\(58,42,28,\.\d+\)", "--muted:rgba(58,42,28,.20)", _tmpl17),
        json_path=None)
    _contrast_warn = _run_html_str(
        re.sub(r"--warn:#[0-9A-Fa-f]{6}", "--warn:#B8860B", _tmpl17), json_path=None)
    _contrast_faint = _run_html_str(
        _tmpl17.replace("color:var(--muted)", "color:var(--faint)", 1), json_path=None)
    v17_contrast = [
        ("[OK  ] text-contrast" in (_contrast_ok.stdout or ""),
         "v0.1.7③：活动模板 muted/warn 文字对比度达 WCAG AA 且 faint 不承载文字"),
        ("[FAIL] text-contrast" in (_contrast_muted.stdout or ""),
         "v0.1.7③：muted 透明度改坏为 .20 必 FAIL"),
        ("[FAIL] text-contrast" in (_contrast_warn.stdout or ""),
         "v0.1.7③：warn 改回旧浅色 #B8860B 必 FAIL（含徽章实底）"),
        ("[FAIL] text-contrast" in (_contrast_faint.stdout or "")
         and "faint" in (_contrast_faint.stdout or ""),
         "v0.1.7③：faint 装饰色重新用于文字必 FAIL"),
        ("[OK  ] text-contrast" in (t8_ok.stdout or "")
         and "不适用" in (t8_ok.stdout or ""),
         "v0.1.7③：无模板色 token 的通用页面明确不适用，不误报"),
    ]
    if not _block("v0.1.7 小字对比度门禁构造用例", v17_contrast,
                  "v0.1.7 对比度门禁失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 中国化学实战反馈：SGR 回退、激励槽、S5/X6 文案 ──
    from calc_common import build_ratio_calcs as _brc17
    from calc_slots import build_slots as _bs17
    _d17_sgr = json.loads(YINGHE.read_text(encoding="utf-8"))
    _sgr_ref = _brc17(_d17_sgr)["sustainable_growth"]
    _d17_sgr["statements"]["cashflow"].pop("dividend_paid", None)
    _sgr_fallback = _brc17(_d17_sgr)["sustainable_growth"]
    _d17_m = json.loads(MOUTAI.read_text(encoding="utf-8"))
    _d17_k = json.loads(KANGDEXIN.read_text(encoding="utf-8"))
    _d17_inc = json.loads(YINGHE.read_text(encoding="utf-8"))
    _d17_inc["derived"]["threshold_check"]["incentive_line"] = {
        "actual": 0.094, "target": 0.0925, "ratio": 0.094 / 0.0925,
        "hit": True, "src": "构造激励公告"}
    _inc17 = _bs17(_d17_inc)["s2"]["threshold"]["incentive"]
    _d17_year = json.loads(YINGHE.read_text(encoding="utf-8"))
    _d17_year["meta"]["report_type"] = "年报"
    _d17_q3 = json.loads(YINGHE.read_text(encoding="utf-8"))
    _d17_q3["meta"].update({"report_type": "季报", "period": "20260930"})
    _x6_year = _bs17(_d17_year)["s7"]["inspection"]["x6"]
    _x6_q3 = _bs17(_d17_q3)["s7"]["inspection"]["x6"]
    _x6_h1 = _bs17(_d17_inc)["s7"]["inspection"]["x6"]
    v17_feedback = [
        (_sgr_ref is not None and _sgr_fallback == _sgr_ref,
         f"v0.1.7④：cashflow 分红字段缺失时回退 balance，SGR={_sgr_fallback}"),
        (round(_brc17(_d17_m)["sustainable_growth"], 4) == 0.0721,
         "v0.1.7④：茅台仍优先现金流真实分红，SGR 0.0721 零漂移"),
        (_brc17(_d17_k)["sustainable_growth"] is None,
         "v0.1.7④：cashflow 明确 null 时不许回退 balance 造出 SGR"),
        (_inc17["read"] == "9.40%" and _inc17["target"] == "9.25%"
         and _inc17["dist"] == "+0.15pct",
         f"v0.1.7④：激励槽位输出 actual/target/dist（{_inc17}）"),
        ("年度口径" in _x6_year, "v0.1.7④：X6 年报显示年度口径"),
        ("半年口径" in _x6_h1, "v0.1.7④：X6 半年报保持半年口径"),
        ("三季口径" in _x6_q3, "v0.1.7④：X6 通用季报+0930 显示三季口径"),
        ("本期投入（亿元）" in _tmpl17 and "期末余额（亿元）" in _tmpl17
         and "本年转固（亿元）" in _tmpl17 and "<th>预计转固时点</th>" not in _tmpl17,
         "S5 表头分列 invested_cur/closing_balance，并与 transferred 的流量语义一致"),
        ((lambda s: s.count('"dividend_paid"') >= 2
          and "cashflow 无此键才回退 balance" in s and "两处均未提取才置 null" in s)
         ((SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")),
         "v0.1.7④：schema 同时登记 cashflow 优先与 balance 回退，显式 null 不回退"),
    ]
    if not _block("v0.1.7 中国化学反馈修复构造用例", v17_feedback,
                  "v0.1.7 中国化学反馈修复失败，逐条核对上方 ❌。"):
        return 1

    def _pctile17(label):
        rows = ''.join(f'<tr><td>{name}</td><td><span class="badge disc">{label}</span></td></tr>'
                       for name in ('净利率', '总资产周转率', '权益乘数'))
        return _run_html_str(
            _S1H + '<div class="card"><table class="data">'
            '<tr><th>因子</th><th>五年位置</th></tr>' + rows +
            '</table><svg id="ncrline"></svg><div>周期定位：非周期行业</div></div></div>',
            json_path=None)
    _pct17_n4 = _pctile17('2/4')
    _pct17_n5 = _pctile17('2/5')
    _pct17_bad_order = _pctile17('5/4')
    _pct17_bad_n = _pctile17('2/1')
    v17_pctile = [
        ('[WARN] s1-v15-shape' not in (_pct17_n4.stdout or ''),
         'v0.1.7⑤：四年窗口 X/4 白描不再被 X/5 旧正则误报'),
        ('[WARN] s1-v15-shape' not in (_pct17_n5.stdout or ''),
         'v0.1.7⑤：X/5 存量形态保持兼容'),
        ('[WARN] s1-v15-shape' in (_pct17_bad_order.stdout or ''),
         'v0.1.7⑤：5/4 分子大于分母不得视作合法白描'),
        ('[WARN] s1-v15-shape' in (_pct17_bad_n.stdout or ''),
         'v0.1.7⑤：X/1 非有效窗口不得豁免'),
    ]
    if not _block('v0.1.7 X/N 分位形态构造用例', v17_pctile,
                  'v0.1.7 X/N 分位形态修复失败，逐条核对上方 ❌。'):
        return 1

    # ── v0.1.7 T8② PDF 数字内部空格归一化（中国化学实战）──
    from check_html_t8 import _value_in_text as _vit17, check_json_vs_md as _cjm17
    from check_html_common import Report as _Report17
    _pdf17_two = '货币资金 4 2,984,543,907.21 5 0,066,643,108.35'
    with tempfile.TemporaryDirectory() as _td17:
        _md17 = Path(_td17) / 'spaced.md'
        _md17.write_text('净利润 7 ,077,046,813.43 元\n', encoding='utf-8')
        _data17 = {'meta': {'source_md': str(_md17)},
                   'statements': {'income': {'np_total': {'cur': 70.7705, 'src': 'L1'}}}}
        _rep17 = _Report17()
        _cjm17(_data17, Path(_td17) / 'data.json', _rep17)
    _t8_integration17 = any(r[0] == 'OK' and r[1] == 'json-md' and '1 处全部命中' in r[2]
                            for r in _rep17.rows)
    v17_pdf = [
        (_vit17(70.7705, '净利润 7 ,077,046,813.43 元'),
         'v0.1.7⑥：首位数字与千位逗号之间的空格可回核'),
        (_vit17(429.85, '货币资金 4 2,984,543,907.21 元'),
         'v0.1.7⑥：首个数字组被拆开时可按亿元回核'),
        (_vit17(429.85, _pdf17_two) and _vit17(500.67, _pdf17_two),
         'v0.1.7⑥：同一行两列分别命中，不吞换行、不跨行粘连'),
        (not _vit17(12.50, '1 2.50'),
         'v0.1.7⑥：无千位逗号的相邻数字不得归一化成 12.50'),
        (_vit17(1315.30, '现金 131,530 百万元'),
         'v0.1.7⑥：既有百万档与千位符行为保持'),
        (_t8_integration17,
         'v0.1.7⑥：check_json_vs_md 端到端命中，调用点不得先删千位逗号'),
        (_vit17(31.41, '投资收益 十八、5  3,141,125,633.31 元'),
         'v0.1.7⑥：附注编号与金额之间的双空格不合并'),
        (_vit17(31.41, '投资收益 十八、5 3,141,125,633.31 元'),
         'v0.1.7⑥：先查原文再查归一化，单空格编号不得遮住原值'),
    ]
    if not _block('v0.1.7 T8② PDF 数字空格构造用例', v17_pdf,
                  'v0.1.7 T8② 数字空格修复失败，逐条核对上方 ❌。'):
        return 1

    # ── v0.1.7 SVG 可访问名称（非装饰图 role=img + 非空名称）──
    _svg17_tpl = _run_html_str(_tmpl17, json_path=None)
    _svg17_plain = _run_html_str('<svg id="chart"></svg>', json_path=None)
    _svg17_decorative = _run_html_str('<svg aria-hidden="true"></svg>', json_path=None)
    _svg17_labelled = _run_html_str('<h1 id="chart-title">趋势</h1><svg role="img" aria-labelledby="chart-title"></svg>', json_path=None)
    _svg17_dangling = _run_html_str('<svg role="img" aria-labelledby="missing"></svg>', json_path=None)
    _svg17_empty = _run_html_str('<svg role="img" aria-label=""></svg>', json_path=None)
    v17_svg = [
        ('[OK  ] svg-a11y' in (_svg17_tpl.stdout or ''),
         'v0.1.7⑦：活动模板全部非装饰 SVG 具备 role=img 与可访问名称'),
        ('[FAIL] svg-a11y' in (_svg17_plain.stdout or ''),
         'v0.1.7⑦：无角色无名称 SVG 必 FAIL'),
        ('[FAIL] svg-a11y' not in (_svg17_decorative.stdout or ''),
         'v0.1.7⑦：aria-hidden 装饰 SVG 不误报'),
        ('[FAIL] svg-a11y' not in (_svg17_labelled.stdout or ''),
         'v0.1.7⑦：有效 aria-labelledby 引用判合规'),
        ('[FAIL] svg-a11y' in (_svg17_dangling.stdout or ''),
         'v0.1.7⑦：悬空 aria-labelledby 引用必 FAIL'),
        ('[FAIL] svg-a11y' in (_svg17_empty.stdout or ''),
         'v0.1.7⑦：空 aria-label 必 FAIL'),
    ]
    if not _block('v0.1.7 SVG 可访问名称构造用例', v17_svg,
                  'v0.1.7 SVG 可访问名称检查失败，逐条核对上方 ❌。'):
        return 1

    # ── v0.1.7 ncrline 近 1 均值标签真实渲染回归（恒瑞 Q3）──
    if "渲染门禁跳过" in render_out:
        print("\n【v0.1.7 ncrline 标签避让】SKIP（本机无 Chrome/Edge）")
    else:
        _script17 = re.search(r'<script>(.*?)</script>', _tmpl17, re.S).group(1)
        _ncr17 = ("const NCR_TS={labels:['2022Q3','2023Q3','2024Q3','2025Q3','2026Q3'],"
                  "ncr:[0.6893,1.2404,0.9926,1.5841,1.1329],"
                  "fcf:[0.2058,0.8459,0.6626,1.286,0.7472],mean:1.1279};")
        _script17 = re.sub(r"const NCR_TS=\{.*?\};", _ncr17, _script17, count=1)
        if "0.6893" not in _script17:
            raise RuntimeError("模板 NCR_TS 槽替换失败——槽形态变了？")
        _svg17 = re.search(r'<svg id="ncrline"[^>]*>.*?</svg>', _tmpl17, re.S).group(0)
        _page17 = ('<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8"><style>'
                   ':root{--ink:rgb(58,42,28);--muted:rgba(58,42,28,.70);'
                   '--faint:rgba(58,42,28,.32);--grid:rgba(58,42,28,.16);'
                   '--data:rgb(171,94,38);--data2:rgb(203,158,108);--faintdata:rgb(233,213,187);'
                   '--der:rgb(122,84,52);--good:#0F7B4F;--warn:#866000;--bad:#C0392B}'
                   'body{padding:40px 20px}.sheet{width:100%;max-width:1040px;margin:0 auto}'
                   'svg{width:100%;height:auto;display:block}</style></head><body>'
                   '<div class="sheet">' + _svg17 + '<script>' + _script17 +
                   '</script></div></body></html>')
        _ncr17_path = HERE / '_v17_ncrline.html'
        _ncr17_path.write_text(_page17, encoding='utf-8')
        try:
            _ncr17 = subprocess.run([sys.executable, str(SKILL / 'scripts' / 'check_render.py'),
                                     str(_ncr17_path)], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace')
        finally:
            _ncr17_path.unlink(missing_ok=True)
        _cross_slot17 = ("const NCR_TS={labels:['2021','2022','2023','2024','2025'],"
                         "ncr:[0.49,0.21,0.98,-0.02,-0.12],fcf:[0.08,0.01,0.53,0.15,0.75],mean:0.31};")
        _cross_page17 = re.sub(r"const NCR_TS=\{.*?\};", _cross_slot17, _page17, count=1)
        _cross_path17 = HERE / '_v17_ncr_cross.html'
        _cross_path17.write_text(_cross_page17, encoding='utf-8')
        try:
            _cross17 = subprocess.run([sys.executable, str(SKILL / 'scripts' / 'check_render.py'),
                                       str(_cross_path17)], capture_output=True, text=True,
                                      encoding='utf-8', errors='replace')
        finally:
            _cross_path17.unlink(missing_ok=True)
        if _ncr17.returncode != 0 or _cross17.returncode != 0:
            print(_ncr17.stdout + _cross17.stdout)
        if not _block('v0.1.7 ncrline 近 1 标签渲染用例',
                      [(_ncr17.returncode == 0,
                        f'v0.1.7⑧：均值1.13与y=1标签在真实浏览器不重叠（exit={_ncr17.returncode}）'),
                       (_cross17.returncode == 0,
                        f'数字政通：-0.02与0.15跨线标签在真实浏览器不重叠（exit={_cross17.returncode}）')],
                      'v0.1.7 ncrline 标签仍重叠。'):
            return 1

    # ── v0.1.7 牧原实战：杜邦同层标签 + 负值柱碰年份轴的真实渲染回归 ──
    if "渲染门禁跳过" in render_out:
        print("\n【v0.1.7 牧原图表标签】SKIP（本机无 Chrome/Edge）")
    else:
        _label_cases = [
            ('stackH', 'dupontstack', 'DUPONT_STACK',
             "const DUPONT_STACK={steps:[['净利率',-4.2],['周转率',2.3],['杠杆',-3.4]],gap:0.4};"),
            ('npchart', 'npchart', 'TREND',
             "const TREND={labels:['2021','2022','2023','2024','2025'],"
             "rev:[788.9,1248.26,1108.61,1379.47,1441.45],"
             "np:[69.04,132.66,-42.63,178.81,154.87],"
             "np_dt:[67.85,130.3,-40.26,187.47,159.88],"
             "ocf:[162.95,230.11,98.93,375.43,300.56],"
             "roe:[0.127,0.1848,-0.0679,0.2482,0.1993],"
             "gm:[null,null,null,20.75,17.82],capex:[358.52,157.39,170.16,123.81,95.29],"
             "rd:[8.08,11.42,16.58,17.47,16.48]};"),
        ]
        _label_results = []
        for _case, _svgid, _slot, _data in _label_cases:
            _js_label = re.search(r'<script>(.*?)</script>', _tmpl17, re.S).group(1)
            _js_label = re.sub(rf"(?m)^const {_slot}=.*$", _data, _js_label, count=1)
            if _data not in _js_label:
                raise RuntimeError(f"模板 {_slot} 槽替换失败——不得在未执行脚本时假绿")
            _svgtag = re.search(rf'<svg id="{_svgid}"[^>]*>.*?</svg>', _tmpl17, re.S).group(0)
            _style_label = re.search(r'<style>.*?</style>', _tmpl17, re.S).group(0)
            _page_label = ('<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8">'
                           + _style_label + '</head><body><div class="sheet"><div class="card">'
                           + _svgtag + '</div><script>' + _js_label + '</script></div></body></html>')
            _label_path = HERE / f'_v17_{_svgid}.html'
            _label_path.write_text(_page_label, encoding='utf-8')
            try:
                _lr = subprocess.run([sys.executable, str(SKILL / 'scripts' / 'check_render.py'),
                                      str(_label_path)], capture_output=True, text=True,
                                     encoding='utf-8', errors='replace')
            finally:
                _label_path.unlink(missing_ok=True)
            if _lr.returncode != 0:
                print(_lr.stdout)
            _label_results.append(_lr)
        if not _block('v0.1.7 牧原图表标签真实渲染用例',
                      [(_label_results[0].returncode == 0,
                        'v0.1.7⑨：stackH 周转率/口径差同层标签不重叠'),
                       (_label_results[1].returncode == 0,
                        'v0.1.7⑩：npchart 2023 负值标签不碰年份轴')],
                      '牧原图表标签重叠修复失效，看上方真实渲染明细。'):
            return 1

    # ── v0.1.7 牧原 Q3：watchlist 改善/风险侧的方向不可由字段名猜 ──
    def _watch_run(item, name):
        d = copy.deepcopy(base)
        d["watchlist"] = [item]
        return _run_calc_json(d, name)

    _watch_high = {"indicator": "完全成本", "current": "11.5元/kg",
                   "tripwire": "若连续两季度高于13元/kg，则降本叙事下修",
                   "upper": "—", "upper_meaning": "不另设奖励线",
                   "lower": "13元/kg", "lower_meaning": "突破则成本反弹",
                   "source": "构造公司公告", "badge": "disc"}
    _watch_low = {"indicator": "发出商品占比", "current": "28.3%",
                  "tripwire": "若连续两期高于30%，则验收梗阻成立",
                  "upper": "20%", "upper_meaning": "回落至20%以下=验收顺畅",
                  "lower": "35%", "lower_meaning": "突破35%则风险确认",
                  "source": "构造公司公告", "badge": "disc"}
    _watch_high_bad = _watch_run(_watch_high, "watch_high_bad.json")
    _watch_high_ok = _watch_run({**_watch_high, "lower_op": ">"}, "watch_high_ok.json")
    _watch_low_bad = _watch_run(_watch_low, "watch_low_bad.json")
    _watch_low_ok = _watch_run({**_watch_low, "upper_op": "<", "lower_op": ">"},
                               "watch_low_ok.json")
    _watch_invalid = _watch_run({**_watch_low, "upper_op": "≥"}, "watch_invalid.json")
    _watch_slot = _bs17({**base, "watchlist": [
        {**_watch_low, "upper_op": "<", "lower_op": ">"}]})["s8"]["cards"][0]["wb"]
    _watch_qual = _bs17({**base, "watchlist": [{
        "indicator": "定性卡", "current": "未披露", "tripwire": "若下份报告仍未披露则继续观察",
        "source": "公司定期报告", "badge": "der"}]})["s8"]["cards"][0]["wb"]
    _watch_partial = _bs17({**base, "watchlist": [{
        "indicator": "单侧阈值卡", "current": "8%", "lower": "10%", "lower_meaning": "低于10%观察",
        "tripwire": "若低于10%则观察", "source": "公司定期报告", "badge": "der"}]})["s8"]["cards"][0]["wb"]
    _schema_watch = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    v17_watch = [
        (_watch_high_bad.returncode == 0 and "[WARN] watchlist-direction" in _watch_high_bad.stdout,
         "v0.1.7⑪：风险侧写「突破/反弹」却配 < 符号 → WARN，不自动改值"),
        (_watch_high_ok.returncode == 0 and "[WARN] watchlist-direction" not in _watch_high_ok.stdout
         and "[OK  ] watchlist-direction" in _watch_high_ok.stdout,
         "v0.1.7⑪：风险侧显式 lower_op=> 后方向警告消失"),
        (_watch_low_bad.returncode == 0 and "[WARN] watchlist-direction" in _watch_low_bad.stdout,
         "v0.1.7⑪：改善侧写「回落/以下」却配 > 符号 → WARN"),
        (_watch_low_ok.returncode == 0 and "[WARN] watchlist-direction" not in _watch_low_ok.stdout
         and "[OK  ] watchlist-direction" in _watch_low_ok.stdout,
         "v0.1.7⑪：改善侧显式 upper_op=< 后方向警告消失"),
        (_watch_invalid.returncode == 1 and "[FAIL] watchlist-direction" in _watch_invalid.stdout,
         "v0.1.7⑪：方向符号只许 < 或 >，非法值必 FAIL"),
        (_watch_slot.startswith("&lt; 20%") and " / &gt; 35%" in _watch_slot,
         f"v0.1.7⑪：S8 槽按 upper_op/lower_op 输出方向（{_watch_slot[:60]}）"),
        (_watch_qual.startswith("定性观察，无数值阈值；若下份报告仍未披露"),
         f"定性跟踪卡无upper/lower时不得残留空阈值壳（{_watch_qual}）"),
        (_watch_partial.startswith("&lt; 10% 低于10%观察；") and " / " not in _watch_partial
         and "&gt;  " not in _watch_partial,
         f"仅单侧有阈值时不得生成另一侧空壳（{_watch_partial}）"),
        ('`upper_op`' in _schema_watch and '`lower_op`' in _schema_watch
         and "默认分别为" in _schema_watch,
         "v0.1.7⑪：schema 登记可选方向字段与兼容默认值"),
    ]
    if not _block("v0.1.7 watchlist 阈值方向构造用例", v17_watch,
                  "watchlist 阈值方向校验失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 牧原 Q3：平均余额的年初期初同样适用于季报 ──
    _schema_hye = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    _framework_hye = (SKILL / "references" / "frameworks.md").read_text(encoding="utf-8")
    v17_hye = [
        ("半年报与季报" in _schema_hye and "仅半年报" not in _schema_hye
         and "hist_ye[i]=第 i 期" in _schema_hye,
         "v0.1.7⑫：schema 明确 hist_ye 适用于半年报与季报，不再写仅半年报"),
        ("半年报与季报" in _framework_hye and "季报=9-30" in _framework_hye
         and "半年报/季报绝不取上年同期期末" in _framework_hye,
         "v0.1.7⑫：方法库明确季报年初期初与同比期末不得混用"),
    ]
    if not _block("v0.1.7 hist_ye 季报口径文档契约", v17_hye,
                  "hist_ye 季报口径文档未同步，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 牧原 Q3：来源行号残渣与 DFL 空值呈现 ──
    from calc_slots import _SRC as _SRC17
    _src_two = _SRC17("公司2026Q3报告 L75/L82/L174/L286")
    _src_many = _SRC17("公司2026Q3报告 L174/L230/L255/L439；1倍为公式覆盖线")
    _src_model = _SRC17("公司2026Q3报告；L2 级辅助驾驶为正文术语")
    _dfl_data = copy.deepcopy(base)
    _dfl_data["derived"]["dupont"]["leverage_drill"]["dfl_delta"] = None
    _dfl_slot = _bs17(_dfl_data)["s1"]["dupont"]["leverage_drill"]["dfl"]
    v17_text_clean = [
        (_src_two == "公司2026Q3报告",
         f"v0.1.7⑬：两位及三位行号混合链完整剥离，不留下 L75/L82//（{_src_two}）"),
        (_src_many == "公司2026Q3报告；1倍为公式覆盖线",
         f"v0.1.7⑬：多行号来源不留 ///，且保留后续阈值依据（{_src_many}）"),
        ("L2 级辅助驾驶" in _src_model,
         "v0.1.7⑬：来源内 L2 型号/术语不误剥"),
        (_dfl_slot == "—",
         f"v0.1.7⑬：DFL 同比缺值槽显示 —，不把 None 注入报告（{_dfl_slot}）"),
    ]
    if not _block("v0.1.7 来源与空值文本清理构造用例", v17_text_clean,
                  "来源或 DFL 空值清理失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 牧原 Q3：回看卡机械填充，tripwire 冻结原文不回写 ──
    def _review_render(items, name):
        d = copy.deepcopy(base)
        if items is not None:
            d["review"] = items
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / f"{name}.json"
            cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(CALC), str(cp), "--fill"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = Path(td) / f"{name}.html"
            rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                 str(cp), "-o", str(out)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
            html = out.read_text(encoding="utf-8") if out.exists() else ""
            chk = subprocess.run([sys.executable, str(SKILL / "scripts" / "check_html.py"),
                                  str(out)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace") if out.exists() else None
        return rr, html, chk

    _review_items = [
        {"tripwire": "若合同负债<5%且收入下降，则需求走弱", "verdict": "兑现",
         "actual": "合同负债实际4%", "attribution": "口径一致"},
        {"tripwire": "若毛利率连续两期低于10%，则盈利下修", "verdict": "未兑现",
         "actual": "实际仍为12%", "attribution": "假设错：价格下降快于预期"},
        {"tripwire": "若短债覆盖低于1倍，则压力升级", "verdict": "待观察",
         "actual": "期末尚未披露", "attribution": "时点未到期"},
    ]
    _rr_review, _h_review, _ck_review = _review_render(_review_items, "review_filled")
    _rr_noreview, _h_noreview, _ = _review_render(None, "review_empty")
    _review_seg = _h_review.split('id="review"', 1)[-1].split('id="s0"', 1)[0]
    _schema_review = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    v17_review = [
        (_rr_review.returncode == 0 and '<div class="v">1/3</div>' in _h_review
         and _review_seg.count("<tr><td>") == 3 and "{{" not in _review_seg
         and "若合同负债&lt;5%且收入下降，则需求走弱" in _review_seg
         and "实际仍为12%；假设错：价格下降快于预期" in _review_seg
         and '<span class="badge r">未兑现</span>' in _review_seg,
         "v0.1.7⑭：回看计数/行数/归因自动填充，tripwire 仅作 HTML 转义"),
        (_rr_noreview.returncode == 0 and 'id="review"' not in _h_noreview
         and 'href="#review"' not in _h_noreview,
         "v0.1.7⑭：无 review 时仍删除回看章和导航"),
        (_ck_review is not None and "[OK  ] review-shape" in _ck_review.stdout,
         "v0.1.7⑭：机械填充后的回看归因机检通过"),
        ("顶层 `review[]`" in _schema_review and "watchlist[].review" in _schema_review,
         "v0.1.7⑭：schema 区分本期顶层回看数组与上期 watchlist 子块"),
    ]
    if not _block("v0.1.7 回看卡机械填充构造用例", v17_review,
                  "回看卡机械填充失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 SGR：估算分红可以计算，但结果证据等级必须继承 est ──
    def _sgr_parts17(d):
        d["derived"]["ratios"]["sustainable_growth"]["cur"] = _brc17(d)["sustainable_growth"]
        row = next(r for r in _bs17(d)["s1"]["table4"] if r["key"] == "sustainable_growth")
        return d["derived"]["ratios"]["sustainable_growth"]["cur"], row["badge"]

    _sgr_est = copy.deepcopy(base)
    _sgr_est["statements"]["cashflow"]["dividend_paid"] = {
        "cur": 1.0, "prev": None, "level": "est", "src": "构造估算分红"}
    _sgr_est_result = _sgr_parts17(_sgr_est)
    _sgr_est_fallback = copy.deepcopy(base)
    _sgr_est_fallback["statements"]["cashflow"].pop("dividend_paid", None)
    _sgr_est_fallback["statements"]["balance"]["dividend_paid"] = {
        "cur": 1.0, "prev": None, "level": "est", "src": "构造估算分红回退"}
    _sgr_est_fallback_result = _sgr_parts17(_sgr_est_fallback)
    _sgr_der = copy.deepcopy(base)
    _sgr_der["statements"]["cashflow"]["dividend_paid"]["level"] = "der"
    _sgr_der_result = _sgr_parts17(_sgr_der)
    with tempfile.TemporaryDirectory() as _td_sgr:
        _cp_sgr = Path(_td_sgr) / "sgr_est.json"
        _cp_sgr.write_text(json.dumps(_sgr_est, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, str(CALC), str(_cp_sgr), "--fill"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        _out_sgr = Path(_td_sgr) / "sgr_est.html"
        _rr_sgr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                  str(_cp_sgr), "-o", str(_out_sgr)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
        _h_sgr = _out_sgr.read_text(encoding="utf-8") if _out_sgr.exists() else ""
    _schema_sgr = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    _framework_sgr = (SKILL / "references" / "frameworks.md").read_text(encoding="utf-8")
    v17_sgr_est = [
        (_sgr_est_result[0] is not None and _sgr_est_result[1] == "est",
         f"v0.1.7⑮：cashflow est 分红仍计算 SGR，但徽章=est（{_sgr_est_result}）"),
        (_sgr_est_fallback_result[0] is not None and _sgr_est_fallback_result[1] == "est",
         f"v0.1.7⑮：cashflow 无键回退 balance est 时徽章同样=est（{_sgr_est_fallback_result}）"),
        (_sgr_der_result[0] is not None and _sgr_der_result[1] == "der",
         "v0.1.7⑮：der 分红对应的 SGR 徽章不变"),
        ("est 输入可计算" in _schema_sgr and "徽章继承" in _schema_sgr
         and "徽章继承" in _framework_sgr,
         "v0.1.7⑮：schema 与方法库登记 est 计算及徽章继承边界"),
        (_rr_sgr.returncode == 0
         and '内生增长率（留存率×ROE） <span class="badge est">估算</span>' in _h_sgr,
         "v0.1.7⑮：最终 HTML 的 SGR 徽章也必须为估算，不只修中间槽"),
    ]
    if not _block("v0.1.7 SGR 估算分红证据等级构造用例", v17_sgr_est,
                  "SGR 估算分红证据等级失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 牧原 Q3：降级声明不是归因图，不要求前瞻词 ──
    _fig_drop17 = _run_html_str(
        '<div class="figtitle">OCF 调节桥未披露：补充资料缺失，本卡降级为声明</div>')
    _fig_true17 = _run_html_str('<div class="figtitle">净利桥：毛利是第一驱动</div>')
    v17_fig_drop = [
        ("[OK  ] figtitle-attribution" in _fig_drop17.stdout
         and "[WARN] figtitle-attribution" not in _fig_drop17.stdout,
         "v0.1.7⑯：未披露/降级声明不计入归因前瞻警告"),
        ("[WARN] figtitle-attribution" in _fig_true17.stdout,
         "v0.1.7⑯：真正归因标题缺前瞻词仍必须 WARN"),
    ]
    if not _block("v0.1.7 归因标题降级豁免构造用例", v17_fig_drop,
                  "归因标题降级豁免失效，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 牧原 Q3：非空短断言不是截断，空字段才需回填 ──
    from check_html_t8 import check_assert_truncation as _cat17
    from check_html_common import Report as _HtmlRep17
    _short_rep17 = _HtmlRep17()
    _short_text17 = "净利润下降主要系生猪价格下降"
    _cat17(f"<div>{_short_text17}</div><div>毛利转负</div>", {"assertions": [
        {"id": "Q2", "text": _short_text17, "evidence": "毛利转负"}]}, _short_rep17)
    _empty_rep17 = _HtmlRep17()
    _cat17("<div>毛利由正转负，与猪价下行方向一致</div>", {"assertions": [
        {"id": "E1", "text": "", "evidence": "毛利由正转负，与猪价下行方向一致"}]}, _empty_rep17)
    v17_short_assert = [
        (not any(lv in (_FAIL, "WARN") and code == "assert-trunc"
                 for lv, code, *_ in _short_rep17.rows),
         "v0.1.7⑰：非空短断言/短证据不作截断或缺字段警告"),
        (any(lv == "WARN" and code == "assert-trunc" and "E1" in msg
             for lv, code, msg, *_ in _empty_rep17.rows),
         "v0.1.7⑰：空 text 仍须 WARN 回填"),
    ]
    if not _block("v0.1.7 短断言截断误报构造用例", v17_short_assert,
                  "短断言截断误报修复失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 牧原年报：Q4 卡机械读数，缺数据不编造 ──
    def _q4_render17(q4, name, report_type="年报"):
        d = copy.deepcopy(base if report_type == "年报" else load_json(YINGHE))
        d["derived"]["q4"] = q4
        d["meta"]["report_type"] = report_type
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / f"{name}.json"
            cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(CALC), str(cp), "--fill"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = Path(td) / f"{name}.html"
            rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                 str(cp), "-o", str(out)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
            return rr, out.read_text(encoding="utf-8") if out.exists() else ""

    _q4_values17 = {"rev": 323.5496, "np": 7.0799, "rev_share": 0.2244612596,
                    "gm_q4": 0.1467897698, "gm_q1q3": 0.1872665885,
                    "impair_share": 0.8401627348, "exp_ratio_q4": 0.0749037485,
                    "exp_ratio_q1q3": 0.0617183502, "src": "构造年报与三季报差额"}
    _rr_q4, _h_q4 = _q4_render17(_q4_values17, "q4_filled")
    _rr_q4_empty, _h_q4_empty = _q4_render17({}, "q4_empty")
    _rr_q4_h1, _h_q4_h1 = _q4_render17(_q4_values17, "q4_h1", "半年报")
    _rr_q4_hot, _h_q4_hot = _q4_render17(dict(_q4_values17, rev_share=0.45), "q4_hot")
    _q4_table17 = _h_q4.split("Q4 收入占全年", 1)[-1].split("</table>", 1)[0]
    _q4_empty_table17 = _h_q4_empty.split("Q4 收入占全年", 1)[-1].split("</table>", 1)[0]
    def _q4_s2row17(html):
        m = re.search(r'<tr><td>Q4 集中度</td>.*?</tr>', html, re.S)
        return m.group(0) if m else ""
    _q4_s2_hot17 = _q4_s2row17(_h_q4_hot)
    _q4_s2_safe17 = _q4_s2row17(_h_q4)
    _q4_s2_empty17 = _q4_s2row17(_h_q4_empty)
    _q4_s2_h117 = _q4_s2row17(_h_q4_h1)
    v17_q4 = [
        (_rr_q4.returncode == 0 and all(x in _q4_table17 for x in
         ("22.45%", "14.68% vs 18.73%", "84.02%", "7.49% vs 6.17%"))
         and "观察" in _q4_table17 and "待结合附注核对" in _q4_table17
         and "{{" not in _q4_table17,
         "v0.1.7⑱：Q4 前四项读数/触线判定自动生成，转固项不冒充已披露"),
        (_rr_q4_empty.returncode == 0 and "—" in _q4_empty_table17
         and "无法核验" in _q4_empty_table17 and "22.45%" not in _q4_empty_table17,
         "v0.1.7⑱：q4 缺数时显示空与无法核验，不带入旧值"),
        (_rr_q4_h1.returncode == 0 and "Q4 收入占全年" not in _h_q4_h1,
         "v0.1.7⑱：非年报仍删除 Q4 卡"),
        (_rr_q4_hot.returncode == 0 and "Q4 收入占 45.00%" in _q4_s2_hot17
         and "+5.0pct" in _q4_s2_hot17 and '<span class="badge y">🟡 贴线</span>' in _q4_s2_hot17
         and "{{" not in _q4_s2_hot17,
         f"年报二期：Q4>40%时S2行机械填读数/距离/贴线徽章且无孔（{_q4_s2_hot17}）"),
        ("Q4 收入占 22.45%" in _q4_s2_safe17 and "-17.6pct" in _q4_s2_safe17
         and '<span class="badge g">✅ 远离</span>' in _q4_s2_safe17 and "{{" not in _q4_s2_safe17,
         f"年报二期：Q4≤40%时S2行机械填远距离徽章（{_q4_s2_safe17}）"),
        ("{{" in _q4_s2_empty17,
         "年报二期：年报缺rev_share时S2行保留判断孔，不填零或编造"),
        ("—（半年报不适用）" in _q4_s2_h117 and "{{" not in _q4_s2_h117
         and "22.45%" not in _q4_s2_h117,
         "年报二期：非年报S2行仍整行不适用，不带入Q4读数"),
    ]
    if not _block("v0.1.7 Q4 卡机械填充构造用例", v17_q4,
                  "Q4 卡机械填充失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 预期对照：同年度年报才可算，披露日后的预测不得混入 ──
    _exp_valid17 = copy.deepcopy(base)
    _rev17 = _exp_valid17["statements"]["income"]["revenue"]["cur"]
    _np17 = _exp_valid17["statements"]["income"]["np_at"]["cur"]
    _exp_valid17["expectations"] = [
        {"institution": "构造A", "date": "2026-04-01", "forecast_rev_2025": round(_rev17 * 0.98, 2),
         "forecast_np_2025": round(_np17 * 0.95, 2), "src": "构造研报A"},
        {"institution": "构造B", "date": "2026-04-10", "forecast_rev_2025": _rev17,
         "forecast_np_2025": _np17, "src": "构造研报B"},
        {"institution": "披露后不可见", "date": "2026-05-01", "forecast_rev_2025": _rev17 * 2,
         "forecast_np_2025": _np17 * 2, "src": "构造未来研报"},
    ]
    _exp_rows17 = _bs17(_exp_valid17)["s7"].get("expect_rows") or []
    _exp_none17 = _bs17(base)["s7"].get("expect_rows") or []
    _exp_h1_data17 = load_json(YINGHE)
    _exp_h1_data17["expectations"] = [{"institution": "构造研报", "date": "2026-08-01",
                                       "forecast_np_2026": 90.0, "src": "构造全年预测"}]
    _exp_h1_rows17 = _bs17(_exp_h1_data17)["s7"].get("expect_rows") or []
    _exp_mixed17 = copy.deepcopy(_exp_valid17)
    _exp_mixed17["meta"]["disclose_date"] = "2026-04-20"
    _exp_mixed17["expectations"][0]["date"] = "20260401"
    _exp_mixed17["expectations"][2]["date"] = "20260501"
    _exp_mixed_slots17 = _bs17(_exp_mixed17)["s7"]
    _exp_reverse17 = copy.deepcopy(_exp_valid17)
    _exp_reverse17["meta"]["disclose_date"] = "20260420"
    _exp_reverse_slots17 = _bs17(_exp_reverse17)["s7"]
    with tempfile.TemporaryDirectory() as _td_exp:
        _cp_exp = Path(_td_exp) / "expect.json"
        _cp_exp.write_text(json.dumps(_exp_valid17, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, str(CALC), str(_cp_exp), "--fill"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        _out_exp = Path(_td_exp) / "expect.html"
        _rr_exp = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                  str(_cp_exp), "-o", str(_out_exp)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
        _h_exp = _out_exp.read_text(encoding="utf-8") if _out_exp.exists() else ""
    with tempfile.TemporaryDirectory() as _td_exp_h1:
        _cp_exp_h1 = Path(_td_exp_h1) / "expect_h1.json"
        _cp_exp_h1.write_text(json.dumps(_exp_h1_data17, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, str(CALC), str(_cp_exp_h1), "--fill"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        _out_exp_h1 = Path(_td_exp_h1) / "expect_h1.html"
        _rr_exp_h1 = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                     str(_cp_exp_h1), "-o", str(_out_exp_h1)],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
        _h_exp_h1 = _out_exp_h1.read_text(encoding="utf-8") if _out_exp_h1.exists() else ""
    _exp_table17 = _h_exp.split('<tr><th>指标</th><th>实际</th><th>一致预期</th>', 1)[-1].split("</table>", 1)[0]
    _exp_h1_table17 = _h_exp_h1.split('<tr><th>指标</th><th>实际</th><th>一致预期</th>', 1)[-1].split("</table>", 1)[0]
    _schema_exp17 = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    v17_expect = [
        (len(_exp_rows17) == 2 and _exp_rows17[0]["delta"] == "+1.01%"
         and _exp_rows17[1]["delta"] == "+2.56%",
         f"v0.1.7⑲：同年度预测中位数与偏离复算正确，披露日后预测剔除（{_exp_rows17}）"),
        (len(_exp_none17) == 2 and all(r["delta"] == "不适用" for r in _exp_none17),
         "v0.1.7⑲：无同年度预期时不计算偏离"),
        (len(_exp_h1_rows17) == 2
         and all(r["delta"] == "不适用" and "全年预测" in r["forecast"] for r in _exp_h1_rows17),
         "v0.1.7⑲：半年报/季报不与全年预测直接比较"),
        (_rr_exp.returncode == 0 and "+1.01%" in _exp_table17 and "+2.56%" in _exp_table17
         and "{{" not in _exp_table17,
         "v0.1.7⑲：最终预期表的 actual/forecast/偏离度全部机械填充"),
        (_rr_exp_h1.returncode == 0 and "不适用" in _exp_h1_table17
         and "{{" not in _exp_h1_table17 and "up|dn" not in _exp_h1_table17,
         "v0.1.7⑲：非年报不适用行也清除单元格 class 占位符"),
        ("forecast_rev_YYYY" in _schema_exp17 and "披露日后" in _schema_exp17,
         "v0.1.7⑲：schema 登记预测字段与同年度/披露日边界"),
        (_exp_mixed_slots17.get("expect_rows") == _exp_rows17
         and "最新 2026-04-10" in _exp_mixed_slots17.get("expect_src", ""),
         "万华实战：紧凑研报日期遇横线披露日，披露前保留且披露后剔除"),
        (_exp_reverse_slots17.get("expect_rows") == _exp_rows17
         and "最新 2026-04-10" in _exp_reverse_slots17.get("expect_src", ""),
         "万华实战：横线研报日期遇紧凑披露日，披露后研报仍须剔除"),
    ]
    if not _block("v0.1.7 预期对照表构造用例", v17_expect,
                  "预期对照表机械填充失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 大动表：只呈现有出处的结构化解释，缺清单不冒充全已解释 ──
    def _big_render17(items, name):
        d = copy.deepcopy(base)
        if items is not None:
            d["big_moves"] = items
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / f"{name}.json"
            cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(CALC), str(cp), "--fill"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = Path(td) / f"{name}.html"
            rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                 str(cp), "-o", str(out)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
            return rr, out.read_text(encoding="utf-8") if out.exists() else ""

    _big_items17 = [
        {"subject": "货币资金", "change": "+65.11%", "explanation": "H股募资到账",
         "source": "构造定期报告主要变动说明"},
        {"subject": "资产减值损失", "change": "+120.30%", "explanation": "存货跌价增加",
         "source": "构造定期报告主要变动说明"},
    ]
    _rr_big, _h_big = _big_render17(_big_items17, "big_filled")
    _rr_big_empty, _h_big_empty = _big_render17(None, "big_empty")
    _big_table17 = _h_big.split("变动 &gt;30% 的科目", 1)[-1].split('<tr class="total">', 1)[0]
    _big_empty17 = _h_big_empty.split("变动 &gt;30% 的科目", 1)[-1].split('<tr class="total">', 1)[0]
    _schema_big17 = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    v17_big = [
        (_rr_big.returncode == 0 and "货币资金" in _big_table17 and "+65.11%" in _big_table17
         and "H股募资到账" in _big_table17 and "资产减值损失" in _big_table17
         and "{{科目}}" not in _big_table17,
         "v0.1.7⑳：大动科目/幅度/管理层解释由 big_moves 机械生成"),
        (_rr_big_empty.returncode == 0 and "无结构化大动清单" in _big_empty17
         and "不据此宣称全部已解释" in _big_empty17 and "{{科目}}" not in _big_empty17,
         "v0.1.7⑳：缺大动清单时明确降级，不宣称全部已解释"),
        ("`big_moves[]`" in _schema_big17 and "`explanation`" in _schema_big17,
         "v0.1.7⑳：schema 登记大动表字段与来源要求"),
    ]
    if not _block("v0.1.7 大动表机械填充构造用例", v17_big,
                  "大动表机械填充失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 海康实证：高管增减持按同口径合计，不从股东名册倒推 ──
    def _mgmt_render17(total, name):
        d = copy.deepcopy(base)
        if total is not None:
            d.setdefault("notes", {}).setdefault("shareholders", {})["mgmt_changes_total"] = total
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / f"{name}.json"
            cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(CALC), str(cp), "--fill"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = Path(td) / f"{name}.html"
            rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                 str(cp), "-o", str(out)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
            return rr, out.read_text(encoding="utf-8") if out.exists() else ""

    _rr_mgmt_up, _h_mgmt_up = _mgmt_render17(
        {"increase": 469500, "decrease": 0, "src": "L1137", "note": "构造直接持股合计"}, "mgmt_up")
    _rr_mgmt_down, _h_mgmt_down = _mgmt_render17(
        {"increase": 100000, "decrease": 500000, "src": "构造公告", "note": "构造减持"}, "mgmt_down")
    _rr_mgmt_none, _h_mgmt_none = _mgmt_render17(None, "mgmt_none")
    _schema_mgmt17 = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    v17_mgmt = [
        (_rr_mgmt_up.returncode == 0 and "净增持 46.95 万股" in _h_mgmt_up
         and '<span class="up">净增持 46.95 万股</span>' in _h_mgmt_up
         and "up|dn" not in _h_mgmt_up.split("高管增减持（合计）", 1)[-1].split("</tr>", 1)[0],
         "v0.1.7㉑：高管净增持按股→万股换算并染 up"),
        (_rr_mgmt_down.returncode == 0 and "净减持 40.00 万股" in _h_mgmt_down
         and '<span class="dn">净减持 40.00 万股</span>' in _h_mgmt_down,
         "v0.1.7㉑：高管净减持方向与金额正确"),
        (_rr_mgmt_none.returncode == 0 and "不从股东名册倒推" in _h_mgmt_none
         and "up|dn" not in _h_mgmt_none.split("高管增减持（合计）", 1)[-1].split("</tr>", 1)[0],
         "v0.1.7㉑：缺同口径合计时明确未知，不从前十大名册倒推"),
        ("mgmt_changes_total" in _schema_mgmt17 and "increase−decrease" in _schema_mgmt17,
         "v0.1.7㉑：schema 登记高管交易合计字段与股/万股口径"),
    ]
    if not _block("v0.1.7 高管增减持构造用例", v17_mgmt,
                  "高管增减持填充失败，逐条核对上方 ❌。"):
        return 1

    # ── v0.1.7 海康实证：户数允许数值或旧底稿 value 对象，单位不漂移 ──
    def _holder_num17(value):
        d = load_json(YINGHE)
        d["notes"]["shareholders"]["holder_num_cur"] = value
        try:
            return _bs17(d)["s6"]["holders"]["cur_w"]
        except (TypeError, AttributeError):
            return None

    _holder_obj17 = _holder_num17({"value": 47512, "unit": "户", "src": "构造原文"})
    _holder_num17_value = _holder_num17(47512)
    _holder_bad17 = _holder_num17({"value": "未披露"})
    _schema_holder17 = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    v17_holder = [
        (_holder_obj17 == 4.75 and _holder_num17_value == 4.75,
         f"v0.1.7㉒：value 对象与纯数值均得到相同万户读数（{_holder_obj17}/{_holder_num17_value}）"),
        (_holder_bad17 is None,
         "v0.1.7㉒：value 非数值时保持未知，不强行转换"),
        ("value 对象" in _schema_holder17 and "holder_num_cur" in _schema_holder17,
         "v0.1.7㉒：schema 登记户数旧底稿 value 对象兼容"),
    ]
    if not _block("v0.1.7 户数结构兼容构造用例", v17_holder,
                  "户数结构兼容失败，逐条核对上方 ❌。"):
        return 1

    # ── 招股书首验：主期=最近审计FY，期后审阅数据不混入年度hist ──
    _d_ipo = load_json(KANGDEXIN)
    _d_ipo["meta"].update({"period": "20181231", "report_type": "招股书"})
    _d_ipo_ref = load_json(KANGDEXIN)
    _alt_ipo, _ = _ca17(_d_ipo)
    _alt_ipo_ref, _ = _ca17(_d_ipo_ref)
    _r_ipo14 = _auto_run("A股（北交所）", "招股书")
    _r_ipo13 = _auto_run("A股（北交所）", "招股书", drop=1)
    ipo_calc_checks = [
        (_hp17({"period": "20251231", "report_type": "招股书"}, 3) == ["2023", "2024", "2025"],
         "招股书①：最近审计FY倒推三年标签，不虚构五年"),
        (_hp17({"period": "20260630", "report_type": "招股书"}, 3) is None,
         "招股书①：期后半年不得冒充主数据期"),
        (_alt_ipo is not None and _alt_ipo == _alt_ipo_ref
         and _alt_ipo.get("annualized") is False,
         f"招股书①：主表按年度口径计算Altman（ref={_alt_ipo_ref}, got={_alt_ipo}）"),
        ("覆盖下限 14" in (_r_ipo14.stdout or "")
         and "未达 --min-recon 14" not in (_r_ipo14.stdout or ""),
         "招股书②：南方乳业首验14/17下限，达标不升FAIL"),
        ("未达 --min-recon 14" in (_r_ipo13.stdout or ""),
         "招股书②：降至13/17必升FAIL，阈值方向钉死"),
    ]
    if not _block("招股书期间与计算口径构造用例", ipo_calc_checks,
                  "招股书计算支持失败，逐条核对上方 ❌。"):
        return 1

    # ── 招股书专章槽位：计划/预计/实际与审阅/未审分层 ──
    _d_ipo_slots = load_json(YINGHE)
    _d_ipo_slots["meta"].update({"period": "20251231", "report_type": "招股书"})
    _ipo_min = {
        "issue_terms": {"issue_price": 14.21, "shares_offered": 3518.5185,
                        "post_issue_total_shares": 18518.5185, "pe_post": 11.99},
        "use_of_proceeds_plan": {"planned_raise": 5.50, "projects": [
            {"name": "养殖基地", "total_investment": 4.436720, "planned_raise": 4.0,
             "build_period": "2年", "benefit_assumption": None}]},
        "use_of_proceeds_final": {"net_proceeds": 4.636207, "shortfall_vs_planned_raise": 0.863793},
        "reviewed_financials_2026h1": {
            "balance": {"total_assets": {"cur": 27.107424, "prev": 26.666432},
                        "src": "构造审阅表"},
            "income": {"revenue": {"cur": 8.962650, "prev": 8.538167},
                       "np_at": {"cur": 1.029070, "prev": 1.226262}, "src": "构造审阅表"},
            "cashflow": {"ocf": {"cur": 2.076495, "prev": 2.094677}, "src": "构造审阅表"}},
        "shareholding_pre_post": {"table": [
            {"holder": "控股股东", "pre_pct": 0.5101, "post_pct": 0.4132}]}
    }
    _d_ipo_slots.setdefault("notes", {}).setdefault("operating_extract", {})["ipo"] = _ipo_min
    _d_ipo_slots["notes"]["operating_extract"]["post_listing_validation"] = {
        "data": {"listing_announcement": {"net_proceeds_actual": 463950822.09},
                 "q3_report": {"audit": "未经审计", "9m": {"np_at_cur": 163163160.84}}}}
    _slots_ipo = _bs13(_d_ipo_slots).get("ipo")
    _slots_non_ipo = _bs13(load_json(YINGHE)).get("ipo")
    _tmpl_ipo = (SKILL / "assets" / "report-template.html").read_text(encoding="utf-8")
    _schema_ipo = (SKILL / "references" / "extraction-schema.md").read_text(encoding="utf-8")
    _rt_ipo = (SKILL / "references" / "report-types.md").read_text(encoding="utf-8")
    _d_ipo_future = copy.deepcopy(_d_ipo_slots)
    _ipo_future = _d_ipo_future["notes"]["operating_extract"]["ipo"]
    _ipo_future["reviewed_financials_2027q1"] = _ipo_future.pop("reviewed_financials_2026h1")
    _q3_future = _d_ipo_future["notes"]["operating_extract"]["post_listing_validation"]["data"]["q3_report"]
    _q3_future["date"] = "2027-10-30"
    _q3_future["9m"]["np_at_prev"] = 176129218.10
    _slots_ipo_future = _bs13(_d_ipo_future).get("ipo")
    ipo_slot_checks = [
        (isinstance(_slots_ipo, dict) and _slots_ipo.get("issue", {}).get("price_raw") == 14.21
         and _slots_ipo.get("planned_raise_raw") == 5.50
         and _slots_ipo.get("expected_net_raw") == 4.636207
         and _slots_ipo.get("actual_net_raw") == 4.6395082209,
         f"招股书③：发行/拟募/预计/实际原值入槽（{_slots_ipo}）"),
        (isinstance(_slots_ipo, dict) and len(_slots_ipo.get("plan_rows", [])) == 1
         and len(_slots_ipo.get("equity_rows", [])) == 1
         and len(_slots_ipo.get("interim_rows", [])) >= 4,
         "招股书③：募投/股权/期后行均由数据生成"),
        (isinstance(_slots_ipo, dict)
         and _slots_ipo.get("issue_rows", [{}])[1].get("value", "").startswith("3,518.52")
         and _slots_ipo.get("post_rows", [{}])[0].get("cur") == "46,395.08",
         "招股书③：万股/万元大额显示带千位符，原值精度留底稿"),
        (isinstance(_slots_ipo, dict) and "审阅" in _slots_ipo.get("interim_note", "")
         and "非审计" in _slots_ipo.get("interim_note", "")
         and "未审" in _slots_ipo.get("post_note", ""),
         "招股书③：审阅非审计与上市后未审标签不丢"),
        (_slots_ipo.get("interim_note") == "2026H1为审阅数据、非审计；资产负债表较2025年末，利润与现金流同比2025H1。",
         "招股书③：南方乳业审阅期间文案零漂移"),
        (isinstance(_slots_ipo_future, dict) and _slots_ipo_future.get("interim_rows")
         and "2027Q1为审阅数据" in _slots_ipo_future.get("interim_note", "")
         and any(x.get("scope") == "较2026年末" for x in _slots_ipo_future["interim_rows"])
         and any(x.get("scope") == "同比2026Q1" for x in _slots_ipo_future["interim_rows"]),
         "招股书③：2027Q1审阅块与2026年比较期按实际键名读取"),
        (isinstance(_slots_ipo_future, dict)
         and any(x.get("item", "").startswith("2027年前9月归母") for x in _slots_ipo_future.get("post_rows", [])),
         "招股书③：上市后报告年份按公告日读取，不写死2026"),
        (not _slots_non_ipo, "招股书③：非招股书不产生IPO槽"),
        ('id="ipo"' in _tmpl_ipo and "{{IPO_ISSUE_ROWS}}" in _tmpl_ipo
         and "{{IPO_PLAN_ROWS}}" in _tmpl_ipo and "{{IPO_EQUITY_ROWS}}" in _tmpl_ipo
         and "{{IPO_INTERIM_ROWS}}" in _tmpl_ipo,
         "招股书③：活动模板含条件专章与四类机械槽"),
        ("period_basis" in _schema_ipo and "最近审计" in _rt_ipo
         and "审阅" in _rt_ipo and "不得混入" in _schema_ipo,
         "招股书③：schema与方法库登记审计主期/期后审阅分层"),
    ]
    if not _block("招股书专章槽位构造用例", ipo_slot_checks,
                  "招股书专章槽位失败，逐条核对上方 ❌。"):
        return 1

    # ── 招股书render：条件专章/不适用裁剪/三年图轴/同名补桶 ──
    def _render_ipo_test(d, stem):
        from calc_models import fill_derived as _fill_ipo
        _fill_ipo(d)
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / f"{stem}.json"
            cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            sp = Path(td) / f"{stem}.fillsheet.json"
            sp.write_text(json.dumps(_bs13(d), ensure_ascii=False), encoding="utf-8")
            out = Path(td) / f"{stem}.html"
            rr = subprocess.run([sys.executable, str(SKILL / "scripts" / "render_report.py"),
                                 str(cp), "-o", str(out)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
            return rr, out.read_text(encoding="utf-8") if out.exists() else ""
    _rr_ipo, _h_ipo = _render_ipo_test(_d_ipo_slots, "ipo_min")
    _rr_ipo_non, _h_ipo_non = _render_ipo_test(load_json(YINGHE), "ipo_non")
    _d_ipo_no_d5 = copy.deepcopy(_d_ipo_slots)
    _d_ipo_no_d5["statements"]["balance"]["total_assets"].pop("hist", None)
    _d_ipo_no_d5["derived"] = {}
    _rr_ipo_no_d5, _h_ipo_no_d5 = _render_ipo_test(_d_ipo_no_d5, "ipo_no_d5")
    _d_non_ipo_no_d5 = load_json(YINGHE)
    _d_non_ipo_no_d5["statements"]["balance"]["total_assets"].pop("hist", None)
    _d_non_ipo_no_d5["derived"] = {}
    _rr_non_ipo_no_d5, _h_non_ipo_no_d5 = _render_ipo_test(_d_non_ipo_no_d5, "non_ipo_no_d5")
    def _ipo_labels(html, key):
        m = re.search(rf"(?m)^const {key}=.*?\blabels:(\[[^\]]*\])", html)
        return json.loads(m.group(1)) if m else None
    _d_other_bucket = {"meta": {"report_type": "招股书", "period": "20251231"},
                       "statements": {"income": {"revenue": {"cur": 11, "prev": 10},
                                      "by_segment": [{"name": "其他", "rev_cur": 1, "rev_prev": 1}]}}}
    _seg_other = json.loads(re.search(r"(?m)^const SEG_BRIDGE=(.*);$",
        _bs13(_d_other_bucket)["js"]["SEG_BRIDGE"]).group(1))
    _d_other_both = {"meta": {"report_type": "招股书", "period": "20251231"},
                     "statements": {"income": {"revenue": {"cur": 11, "prev": 10},
                                    "by_segment": [{"name": "其他", "rev_cur": 1, "rev_prev": 1},
                                                   {"name": "其他业务", "rev_cur": 0.5, "rev_prev": 0}]}}}
    _seg_other_both = json.loads(re.search(r"(?m)^const SEG_BRIDGE=(.*);$",
        _bs13(_d_other_both)["js"]["SEG_BRIDGE"]).group(1))
    ipo_render_checks = [
        (_rr_ipo.returncode == 0 and 'id="ipo"' in _h_ipo
         and "{{IPO_" not in _h_ipo and "14.21 元/股" in _h_ipo
         and "46,395.08" in _h_ipo,
         f"招股书④：专章机械槽全部填充（{_rr_ipo.stdout}{_rr_ipo.stderr}）"),
        (_rr_ipo_non.returncode == 0 and 'id="ipo"' not in _h_ipo_non
         and "{{IPO_" not in _h_ipo_non,
         "招股书④：非招股书整章与导航不残留"),
        (all(((_ipo_labels(_h_ipo, k) or [])[-3:] == ["2023", "2024", "2025"])
             for k in ("TREND", "NCR_TS", "EFF_TS")),
         "招股书④：五张趋势图共用年度审计标签，不再空轴；真实三年样本在任务4锁"),
        ('id="s6"' in _h_ipo and 'id="holders"' not in _h_ipo
         and "发行前后股权" in _h_ipo and "上市前不适用" in _h_ipo
         and "全年预测不与累计实际直接比较" not in _h_ipo,
         "招股书④：户数与机构预期整卡裁剪，旧表身/闭合标签不残留"),
        ("招股书不适用" in _h_ipo and "—（半年报不适用）" not in _h_ipo,
         "招股书④：Q4不适用标签按真实报告类型显示"),
        (len({name for name, _ in _seg_other}) == len(_seg_other)
         and ["其他业务", 1.0] in _seg_other,
         f"招股书④：既有其他分部与自动补桶不同名（{_seg_other}）"),
        (len({name for name, _ in _seg_other_both}) == len(_seg_other_both)
         and ["其他调整", 0.5] in _seg_other_both
         and abs(sum(v for _, v in _seg_other_both) - 1.0) < 1e-9,
         f"招股书④：其他与其他业务并存时补桶仍唯一且闭合（{_seg_other_both}）"),
        ("missing" not in _bs13(_d_ipo_slots)["ipo"],
         "招股书④：IPO槽不暴露未消费的missing键，空行缺口仍由render处理"),
        (_rr_ipo_no_d5.returncode == 0 and "{{period_start}}" not in _h_ipo_no_d5
         and "累计归因与因子分位降级" in _h_ipo_no_d5 and "五年位置" not in _h_ipo_no_d5,
         "招股书④：累计归因序列不足时整卡降级，不留分位空孔"),
        (_rr_non_ipo_no_d5.returncode == 0 and "累计归因与因子分位降级" in _h_non_ipo_no_d5
         and "招股书只披露三年审计主表" not in _h_non_ipo_no_d5
         and "数据来源：招股说明书三年审计主表" not in _h_non_ipo_no_d5,
         "招股书④：非招股书缺累计归因时也不得出现招股书专属措辞"),
    ]
    if not _block("招股书渲染与同名补桶构造用例", ipo_render_checks,
                  "招股书渲染/补桶失败，逐条核对上方 ❌。"):
        return 1

    # ── 招股书T8：上市公告原始元值须换算成亿元/万元，且不能豁免真实笔误 ──
    from check_html_t8 import check_numbers_vs_json as _check_t8post
    from check_html_common import Report as _ReportT8Post
    def _t8post(text, collision=True):
        d = {"derived": {"ratios": {"dso": {"cur": 15.1488, "prev": 13.6938 if collision else 50.0}}},
             "notes": {"operating_extract": {"post_listing_validation": {"data": {
                 "q3_report": {"unit": "元", "9m": {"revenue_cur": 1370592912.02,
                                                   "np_dt_cur": 159913386.24}},
                 "listing_announcement": {"unit": "元", "net_proceeds_actual": 463950822.09}}}}}}
        rep = _ReportT8Post()
        _check_t8post(text, text, d, rep)
        return rep
    _t8post_ok = _t8post("<td>13.71</td><td>46,395.08</td>")
    _t8post_bad = _t8post("<td>13.72</td>", collision=False)
    t8_post_checks = [
        (not any(lv == "FAIL" for lv, _, _, _ in _t8post_ok.rows)
         and any("2 处数字匹配" in msg for _, _, msg, _ in _t8post_ok.rows),
         f"招股书⑤：公告元值换算亿/万后按显示精度匹配（{_t8post_ok.rows}）"),
        (any(lv == "FAIL" for lv, _, _, _ in _t8post_bad.rows),
         "招股书⑤：改掉显示值仍必FAIL，单位补口不是豁免"),
    ]
    def _t8round(text):
        d = {"derived": {"ratios": {"dio": {"cur": 45.9508, "prev": 47.945}}}}
        rep = _ReportT8Post()
        _check_t8post(text, text, d, rep)
        return rep
    _t8round_ok = _t8round("<td>47.95</td>")
    _t8round_bad = _t8round("<td>47.96</td>")
    _t8post_range = _t8post("公司预计2026年1-9月营业收入136,008.03～137,208.03万元（同比+2.71%～+3.62%），归母净利润15,967.69～16,967.69万元（同比-9.34%～-3.66%）", collision=False)
    t8_post_checks += [
        (not any(lv == "FAIL" for lv, _, _, _ in _t8round_ok.rows),
         f"招股书⑤：半个显示单位边界不受浮点尾差误伤（{_t8round_ok.rows}）"),
        (any(lv == "FAIL" for lv, _, _, _ in _t8round_bad.rows),
         "招股书⑤：超出显示精度仍必FAIL，容差不扩大"),
        (not any(lv == "FAIL" for lv, _, _, _ in _t8post_range.rows),
         f"招股书⑤：预计区间端点不与实际值误撞（{_t8post_range.rows}）"),
    ]
    if not _block("招股书期后数字回验构造用例", t8_post_checks,
                  "招股书T8单位换算失败，逐条核对上方 ❌。"):
        return 1

    # ── 清越实战：interest_arrears 是机械差额，fill 不得漏算，检查器不得照单全收 ──
    from calc_models import fill_derived as _fill_ia
    from calc import check_interest_arrears as _check_ia
    from calc_common import Report
    _ia = load_json(QINGYUE)
    _ia["derived"].pop("interest_arrears", None)
    _ia["derived"]["interest_arrears"] = {"note": "付息含资本化部分，需保留该口径说明"}
    _fill_ia(_ia)
    _ia_node = _ia["derived"]["interest_arrears"]
    _ia_bad = copy.deepcopy(_ia)
    _ia_bad["derived"]["interest_arrears"]["cur"] = 0.0
    _ia_bad_rep = Report()
    _check_ia(_ia_bad, _ia_bad_rep)
    _ia_missing = copy.deepcopy(_ia)
    _ia_missing["statements"]["cashflow"]["interest_paid"]["cur"] = None
    _fill_ia(_ia_missing)
    _ia_missing_rep = Report()
    _check_ia(_ia_missing, _ia_missing_rep)
    interest_arrears_checks = [
        (isinstance(_ia_node.get("cur"), (int, float))
         and abs(_ia_node["cur"] - (-0.0419)) < 1e-9,
         f"清越：利息费用0.1925−实际付息0.2344=应付未付-0.0419（实际 {_ia_node.get('cur')}）"),
        (_ia_node.get("note") == "付息含资本化部分，需保留该口径说明",
         "interest_arrears 保留人工口径注释，不被机械填充覆盖"),
        (any(lv == "FAIL" for lv, _, _ in _ia_bad_rep.rows),
         f"interest_arrears 填0但输入可复算时必FAIL（{_ia_bad_rep.rows}）"),
        (_ia_missing["derived"]["interest_arrears"].get("cur") is None
         and any(lv == "SKIP" for lv, _, _ in _ia_missing_rep.rows),
         "缺实际付息时保持未知并SKIP，不把缺失当0"),
    ]
    if not _block("interest_arrears 自动填充与复算构造用例", interest_arrears_checks,
                  "利息差额机械字段漏算或失去复算，逐条核对上方 ❌。"):
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
    print("✅ 五例全绿：门禁既未误报干净样本、未漏报造假样本，也未错伤连亏样本与周期股样本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
