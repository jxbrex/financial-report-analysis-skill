#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gate.py — 三道门禁单入口（v0.0.13）：calc.py → check_html.py --json → check_render.py。

用法：
    python scripts/gate.py <报告.html> <data.json> [--png 截图目录]
退出码：0 = 三道全过（WARN 逐条列出不阻塞，与 check_html 语义一致）；1 = 任一 FAIL/异常。
省掉三次命令编排与漏跑；输出只保留各门禁的摘要行与 WARN/FAIL 明细，不刷屏。
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Windows 控制台默认 GBK，emoji 与中文会触发 UnicodeEncodeError；强制 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError): pass


def run(script, *args):
    return subprocess.run([sys.executable, str(HERE / script), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="calc → check_html --json → check_render 单入口")
    ap.add_argument("html")
    ap.add_argument("json")
    ap.add_argument("--png", default=None, help="check_render 按章分片截图目录（视觉验收用）")
    ap.add_argument("--verbose", action="store_true",
                    help="透传 check_html --verbose（T8 等明细不截断）并打印明细行——排障用")
    ap.add_argument("--min-recon", default=None, metavar="N|auto",
                    help="透传 calc.py --min-recon：recon 覆盖不足即 FAIL"
                         "（A 股年报 15/半年报 13/季报 8，港股半年报 8；auto 按 meta 校准，v0.1.2）")
    ap.add_argument("--chrome", default=None,
                    help="透传 check_render --chrome（Chrome/Edge 可执行文件路径；无浏览器机器渲染门禁跳过）")
    a = ap.parse_args()

    fails = []

    r = run("calc.py", a.json, *(["--min-recon", str(a.min_recon)] if a.min_recon is not None else []))
    print(r.stdout, end="")
    if r.returncode != 0:
        fails.append("calc 存在 FAIL（禁止写报告/交付）")
        if (r.stderr or "").strip():  # FAIL 明细走 stderr，必须回显（与 check_render 分支同规）
            print(r.stderr.strip()[:2000], file=sys.stderr)

    cmd = ["check_html.py", a.html, "--json", a.json] + (["--verbose"] if a.verbose else [])
    r = run(*cmd)
    for line in (r.stdout or "").splitlines():
        if line.lstrip().startswith(("🔴", "🟡", "---", "✅ 通过", "❌", "===")) \
                or (a.verbose and line.lstrip().startswith("·")):
            print(line)
    if r.returncode != 0:
        fails.append("check_html 未通过（FAIL 未清零）")
        if (r.stderr or "").strip():  # 与 calc/check_render 分支同规：stderr 回显，防明细被吞
            print(r.stderr.strip()[:2000], file=sys.stderr)

    cmd = (["check_render.py", a.html] + (["--png", a.png] if a.png else [])
           + (["--chrome", a.chrome] if a.chrome else []))
    r = run(*cmd)
    render_skipped = False
    for line in (r.stdout or "").splitlines():
        # 🔴 明细（哪张图/重叠几像素）与结论行一并透传——单入口的排障价值就在这；
        # 截图分片行是过程噪音，--verbose 才透
        if ("汇总" in line or "跳过" in line or line.lstrip().startswith(("🔴", "❌", "✅ 渲染"))
                or (a.verbose and line.lstrip().startswith(("·", "✅", "🔴")))):
            print(line)
        if "渲染门禁跳过" in line:
            render_skipped = True
    if r.returncode != 0:
        fails.append("check_render 发现问题（呈现未过）")
        if (r.stderr or "").strip():  # 「无法测量页面」类 sys.exit 走 stderr，必须回显
            print(r.stderr.strip()[:2000], file=sys.stderr)

    summary = ("；".join(fails) if fails else
               "两道硬门禁绿 + 渲染门禁跳过（无浏览器，呈现未测——换机/装浏览器后须重跑）"
               if render_skipped else "三道门禁全绿")
    print(f"\n=== gate 汇总：{summary} ===")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
