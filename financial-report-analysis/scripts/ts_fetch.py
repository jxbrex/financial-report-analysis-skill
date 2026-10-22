#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ts_fetch.py — financial-report-analysis 的 tushare HTTP 取数通道（Phase 1/2/6/7 双源核对）

用法：
    python scripts/ts_fetch.py income --params ts_code=600519.SH period=20241231 \
        --fields ts_code,period,total_revenue,n_income_attr_p
    python scripts/ts_fetch.py stk_holdernumber --params ts_code=600519.SH --limit 20
    python scripts/ts_fetch.py <api> ... --out rows.json     # 落盘（UTF-8 JSONL）
    python scripts/ts_fetch.py <api> ... --limit 0           # 不截断（默认截断 200 行）

退出码：0 = 取数成功（stdout 为 JSONL，每行一个对象）；1 = 失败（stderr 带原因）。

设计说明：
  - 走官方 HTTP API（api.tushare.pro），与 tushare MCP / Python SDK 等价——
    权限与频控跟 token 走，不跟通道走；本脚本让无 tushare MCP 的环境也能双源核对。
  - token 只读环境变量 TUSHARE_TOKEN（不落盘、不打印）；缺失给出设置提示。
  - 无缓存：报告生成为低频操作，且每次 CLI 调用都是新进程，进程内缓存没有意义；
    额度消耗 = 实际调用次数（report_rc 1次/分钟、hk_daily 1次/小时，与 MCP 同档）。
  - 40203 两义：无权限（本环境已知 anns_d / hk_income 等）或限流（hk_daily）——
    报错文案带提示，降级路径见 references/data-sources.md。
"""

import argparse
import json
import os
import sys
import urllib.request

# Windows 控制台默认 GBK，中文会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError): pass

TS_API = "https://api.tushare.pro"
TIMEOUT = 30
DEFAULT_LIMIT = 200

# 40203 无权限接口（本环境实测，与通道无关）：报错时给出可读提示。
KNOWN_40203 = ("anns_d", "hk_income", "hk_balancesheet", "hk_cashflow",
               "hk_fina_indicator", "yc_cb", "news")


def _token():
    tok = (os.environ.get("TUSHARE_TOKEN") or "").strip()
    if not tok:
        raise RuntimeError(
            "tushare token 未配置：请设置环境变量 TUSHARE_TOKEN 后重试"
            "（Windows: set TUSHARE_TOKEN=你的token；Linux/macOS: export TUSHARE_TOKEN=你的token）")
    return tok


def ts_call(api_name, params=None, fields=""):
    """tushare HTTP API：返回 list[dict]（fields↔items 对齐）。失败抛 RuntimeError。"""
    payload = {"api_name": api_name, "token": _token(),
               "params": params or {}, "fields": fields}
    req = urllib.request.Request(
        TS_API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read().decode("utf-8", errors="replace")
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"tushare {api_name} 响应非 JSON（前 80 字：{raw[:80]!r}）"
                           "——网关错误/维护页，稍候重试")
    if d.get("code") != 0:
        raise RuntimeError(f"tushare {api_name} 返回 code={d.get('code')}: {d.get('msg')}")
    data = d.get("data") or {}
    flds = data.get("fields") or []
    items = data.get("items") or []
    if any(len(row) != len(flds) for row in items):
        raise RuntimeError(f"tushare {api_name} 返回结构异常：fields {len(flds)} 列但存在不等长行"
                           "（接口字段可能已调整）——核对接口文档，勿当无数据")
    return [dict(zip(flds, row)) for row in items]


def _parse_params(tokens):
    """--params ts_code=600519.SH period=20241231 → dict。
    逗号片段无 = 时并入上一键值（tushare 原生逗号多值形态：ts_code=A.SH,B.SZ）。"""
    out = {}
    for tok in tokens or []:
        for pair in tok.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                if out:  # 多值续段：并入最近一个键
                    k = next(reversed(out))
                    out[k] = f"{out[k]},{pair}"
                    continue
                raise SystemExit(f"FAIL: --params 项 '{pair}' 不是 k=v 形式")
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main():
    ap = argparse.ArgumentParser(
        description="tushare HTTP 取数（financial-report-analysis 双源核对通道）")
    ap.add_argument("api_name",
                    help="接口名，如 income / balancesheet / cashflow / fina_indicator / stk_holdernumber / report_rc")
    ap.add_argument("--params", nargs="*", default=[],
                    help="查询参数，k=v 形式（空格或逗号分隔）")
    ap.add_argument("--fields", default="",
                    help="返回字段，逗号分隔；空 = 接口默认全字段")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"stdout 最多输出行数（默认 {DEFAULT_LIMIT}，0 或负数 = 全部；"
                         "--out 落盘始终全量）")
    ap.add_argument("--out", default="", help="落盘路径（JSONL）；缺省 stdout")
    args = ap.parse_args()

    params = _parse_params(args.params)
    try:
        rows = ts_call(args.api_name, params, args.fields)
    except RuntimeError as e:
        hint = ""
        if "40203" in str(e):
            hint = ("\n  40203 两义：无权限（本环境已知: " + "/".join(KNOWN_40203) +
                    "）或限流（hk_daily 1次/小时）——按 references/data-sources.md 降级路径处理")
        print(f"FAIL: {e}{hint}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"FAIL: 网络错误（{e}）", file=sys.stderr)
        return 1

    # 截断只约束 stdout 显示；落盘写全量 rows（v0.1.5 修复：--out 曾落截断版，双源核对丢行）；
    # limit 负数按 0 处理（全部）
    limit = args.limit if args.limit > 0 else 0
    shown = rows if limit == 0 else rows[:limit]
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in shown)
    if text:
        text += "\n"
    if args.out:
        full = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        if full:
            full += "\n"
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(full)
    sys.stdout.write(text)
    note = f"[ts_fetch] {args.api_name} -> {len(rows)} 行"
    if not rows:
        note += "（0 行：参数无匹配或服务端结构变更——核对参数与接口文档，勿直接当「无数据」落底稿）"
    if len(shown) < len(rows):
        note += (f"（已落盘全量 {len(rows)} 行，stdout 仅显示前 {len(shown)} 行；--limit 0 不截断）"
                 if args.out else f"（截断显示前 {len(shown)} 行，--limit 0 取全部）")
    print(note, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
