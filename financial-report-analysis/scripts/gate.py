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
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


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
    a = ap.parse_args()

    fails = []

    r = run("calc.py", a.json)
    print(r.stdout, end="")
    if r.returncode != 0:
        fails.append("calc 存在 FAIL（禁止写报告/交付）")

    cmd = ["check_html.py", a.html, "--json", a.json] + (["--verbose"] if a.verbose else [])
    r = run(*cmd)
    for line in (r.stdout or "").splitlines():
        if line.startswith(("🔴", "🟡", "---", "✅ 通过", "❌", "===")) \
                or (a.verbose and line.lstrip().startswith("·")):
            print(line)
    if r.returncode != 0:
        fails.append("check_html 未通过（FAIL 未清零）")

    cmd = ["check_render.py", a.html] + (["--png", a.png] if a.png else [])
    r = run(*cmd)
    for line in (r.stdout or "").splitlines():
        if "汇总" in line or "跳过" in line:
            print(line)
    if r.returncode != 0:
        fails.append("check_render 发现问题（呈现未过）")

    print("\n=== gate 汇总：" + ("三道门禁全绿" if not fails else "；".join(fails)) + " ===")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
