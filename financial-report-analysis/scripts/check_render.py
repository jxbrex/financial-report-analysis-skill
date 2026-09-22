#!/usr/bin/env python3
"""渲染测量门禁：headless Chrome/Edge 真渲染后注入 JS 测量 DOM。

    python scripts/check_render.py 报告.html                 # 测量门禁
    python scripts/check_render.py 报告.html --png out目录/   # 按章分片截图（Phase 8 视觉验收）
    python scripts/check_render.py 报告.html --chrome 路径    # 指定浏览器二进制

三项测量（渲染后状态，静态正则看不到）：
  1. SVG 文本重叠：每个 svg 内 <text> 两两 bounding rect 相交测试（两轴重叠均 >1px 才算）
  2. HTML 元素溢出 .sheet：文本后代右/左缘超出 .sheet boundingRect >1px（豁免 svg 内部元素）
  3. 横向裁剪：scrollWidth > clientWidth + 2 且 computed overflowX ≠ visible

门禁定位：可选门禁——找不到 Chrome/Edge（或 --chrome 路径不存在）→ 打印跳过声明 + exit 0，
check_html.py 的静态硬门禁地位不动；发现问题 exit 1。
框架结构自包含复制自 lieflat-cards/scripts/render.py（部署目录须独立，不跨 skill import）。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "google-chrome",
    "chromium",
    # debt: 上游只列了 macOS/Linux，这里补 Windows 常见安装位（含 Edge，同为 Chromium 内核）
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

VIRTUAL_TIME_BUDGET = 8000

# 测量视口：(宽, 高, 标签)——桌面 = .sheet 1040px + body 左右 padding 20px 留余量；
# 窄屏 = 390px（iPhone 12/13/14 逻辑宽），验证流式骨架与页面级横向溢出（v0.0.11）
VIEW_H = 2000
DESKTOP_W, MOBILE_W = 1100, 390
VIEWPORTS = ((DESKTOP_W, VIEW_H, "桌面"), (MOBILE_W, VIEW_H, "窄屏"))

SKIP_NOTE = ("渲染门禁跳过：未找到 Chrome/Edge（check_html.py 静态硬门禁仍然生效，"
             "本项为可选门禁，不阻塞交付）")

# 注入页面：测量三类呈现问题 + 章节高度（供 --png 分片用）
MEASURE_JS = """
<script id="fra-measure">
window.addEventListener('load', () => setTimeout(() => {
  const label = (el) => el.tagName.toLowerCase() +
    (el.className && typeof el.className === 'string'
      ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
  const report = {overlaps: [], spills: [], clipped: [], pageclip: [], sections: []};

  /* 1. SVG 文本重叠：本技能 SVG text 均单行，取整体 boundingRect 即可 */
  for (const svg of document.querySelectorAll('svg')) {
    const items = [...svg.querySelectorAll('text')].map(t =>
      ({t, r: t.getBoundingClientRect(), s: (t.textContent || '').trim()}));
    for (let i = 0; i < items.length; i++)
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i].r, b = items[j].r;
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ox > 1 && oy > 1)
          report.overlaps.push({
            svg: svg.id || '(no-id)',
            a: items[i].s.slice(0, 24), b: items[j].s.slice(0, 24),
            px: Math.round(Math.min(ox, oy))});
      }
  }

  const sheet = document.querySelector('.sheet');
  if (sheet) {
    const sb = sheet.getBoundingClientRect();
    const spilled = [];
    const clip = [];
    /* 处于有意横向滚动容器（overflow-x:auto/scroll，v0.0.11 宽表格卡片内横滑）内的
       元素，其超宽由滚动访问承载，不算溢出 .sheet */
    const inScroller = (el) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if (ox === 'auto' || ox === 'scroll') return true;
      }
      return false;
    };
    for (const el of sheet.querySelectorAll('*')) {
      if (el.closest('svg')) continue; /* svg 是 viewBox 缩放坐标系，溢出判据不适用 */
      if (inScroller(el)) continue;
      const copy = (el.textContent || '').trim();
      if (copy) {
        const r = el.getBoundingClientRect();
        if (r.width || r.height) {
          const right = r.right - sb.right, left = sb.left - r.left;
          if (right > 1) spilled.push({el, edge: 'right', px: Math.round(right),
                                       sel: label(el), text: copy.slice(0, 44)});
          else if (left > 1) spilled.push({el, edge: 'left', px: Math.round(left),
                                           sel: label(el), text: copy.slice(0, 44)});
        }
      }
      /* overflowX 为 auto/scroll 属有意滚动设计（v0.0.11 起宽表格卡片内横滑），
         内容可滚动访问不算裁剪；只有 hidden/clip（内容被切掉）才算问题 */
      if (el.scrollWidth > el.clientWidth + 2 &&
          ['hidden', 'clip'].includes(getComputedStyle(el).overflowX))
        clip.push({sel: label(el), px: el.scrollWidth - el.clientWidth});
    }
    /* 只留最内层溢出元素：外层容器因包含溢出后代而连带超界时不重复报 */
    const set = new Set(spilled.map(s => s.el));
    report.spills = spilled
      .filter(s => ![...s.el.querySelectorAll('*')].some(d => set.has(d)))
      .slice(0, 12)
      .map(({el, ...rest}) => rest);
    report.clipped = clip.slice(0, 12);

    /* 章节清单（.masthead / 各 .sect / .foot）：--png 分片截图按此高度开窗 */
    for (const el of document.querySelectorAll('.masthead, .sect, .foot')) {
      const head = el.querySelector('.secthead');
      report.sections.push({
        cls: el.className.trim().split(/\\s+/)[0],
        id: head ? head.id : '',
        h: Math.ceil(el.getBoundingClientRect().height)});
    }

    /* 页面级横向溢出：流式骨架（v0.0.11，.sheet max-width 而非定宽）下页面
       不得出现横向滚动条——骨架被改回定宽或某元素撑破视口时此处命中 */
    const de = document.documentElement;
    if (de.scrollWidth > window.innerWidth + 2)
      report.pageclip.push({px: de.scrollWidth - window.innerWidth});
  }

  /* 4. 字体回退检测：模板字体栈以朱雀仿宋为首选，document.fonts.check 验证其真实
     可用性；缺失（读者机器回退系统仿宋）是环境级降级，WARN 不计入 exit 1 */
  report.fontwarn = [];
  try {
    if (!document.fonts.check('12px "Zhuque Fangsong"'))
      report.fontwarn.push('朱雀仿宋未加载，正文回退系统仿宋（可读性降级，非报告内容问题）');
  } catch (e) {}

  /* 本机 Edge 的 --dump-dom stdout 为空（实测），测量结果改由同步 XHR 回传本地端口 */
  const x = new XMLHttpRequest();
  x.open('POST', 'http://127.0.0.1:%PORT%/report', false);
  x.send(JSON.stringify(report));
}, 400));
</script>
"""

# 截图分片：隐藏非目标章，body 收边（参考 render.py 的 ISOLATE_JS）
ISOLATE_JS = """
<script id="fra-isolate">
window.addEventListener('load', () => setTimeout(() => {
  const style = document.createElement('style');
  style.textContent =
    'html,body{margin:0!important;padding:0!important;background:none!important;' +
    'display:block!important;min-height:0!important}' +
    /* .sheet 居中由 body flex 承载，isolate 覆写 display 后必须补 margin:auto，
       否则分片截图左偏移、与真实版式（及 v0.0.11 后模板自身 margin 居中）不一致 */
    '.sheet{padding:0!important;margin:0 auto!important}';
  document.head.appendChild(style);
  const parts = [...document.querySelectorAll('.masthead, .sect, .foot')];
  parts.forEach((el, i) => { if (i !== %INDEX%) el.style.display = 'none'; });
}, 300));
</script>
"""


def find_chrome(explicit: str | None) -> str | None:
    """可选门禁语义：找不到返回 None（调用方声明跳过），不 exit。"""
    if explicit:
        return explicit if Path(explicit).exists() else None
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def chrome_run(chrome: str, page: Path, work: Path, ready, *flags: str,
               linger: float = 0.0) -> str:
    """Run headless Chrome until `ready(stdout)` is satisfied, then stop it.

    Some Chrome builds finish the work but never exit in headless mode, so this
    polls for the expected output instead of waiting on the process.
    Windows 实测：主进程会先退出、渲染子进程异步完成写盘/回调，故主进程退出后
    再续等 linger 秒（截图/测量回传的完成信号都可能迟到）。
    """
    profile = Path(tempfile.mkdtemp(prefix="fra-chrome-", dir=work))
    log = profile / "stdout.txt"
    deadline = time.time() + 60
    with open(log, "wb") as sink:
        proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                f"--user-data-dir={profile}",
                f"--virtual-time-budget={VIRTUAL_TIME_BUDGET}",
                "--hide-scrollbars",
                "--force-color-profile=srgb",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-extensions",
                "--disable-gpu",
                *flags,
                page.resolve().as_uri(),
            ],
            stdout=sink,
            stderr=subprocess.DEVNULL,
        )
        try:
            while time.time() < deadline:
                out = log.read_text(encoding="utf-8", errors="replace")
                if ready(out):
                    return out
                if proc.poll() is not None:
                    until = time.time() + linger
                    while time.time() < until:
                        if ready(out):
                            return out
                        time.sleep(0.25)
                    return log.read_text(encoding="utf-8", errors="replace")
                time.sleep(0.25)
            return log.read_text(encoding="utf-8", errors="replace")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def variant(html: str, snippet: str) -> str:
    """Inject `snippet` before </body>（本技能无 rAF 动画循环，不需要 PRELUDE 帧封顶）。"""
    if "</body>" in html:
        return html.replace("</body>", snippet + "</body>", 1)
    return html + snippet


def measure(chrome: str, html: str, work: Path, view_w: int,
            view_h: int = VIEW_H) -> dict:
    holder = {"event": threading.Event()}

    class _ReportHandler(BaseHTTPRequestHandler):
        """页面内测量脚本把结果 POST 回这里（--dump-dom 的 stdout 通道本机不可用）。"""

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            holder["payload"] = self.rfile.read(length).decode("utf-8")
            holder["event"].set()
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _ReportHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        page = work / f"measure-{view_w}.html"
        page.write_text(variant(html, MEASURE_JS.replace("%PORT%", str(port))),
                        encoding="utf-8")
        # 终止机制用 --screenshot 探针：本机 Edge 的 --dump-dom 会空输出并提前退出，
        # 而 screenshot 通道实测可靠（渲染完成后写盘并退出）
        chrome_run(
            chrome, page, work, lambda _out: holder["event"].is_set(),
            f"--screenshot={work / f'probe-{view_w}.png'}",
            f"--window-size={view_w},{view_h}",
            linger=20,
        )
    finally:
        srv.shutdown()
    if "payload" not in holder:
        sys.exit("无法测量页面：测量脚本未回传结果（页面可能未正常渲染）")
    return json.loads(holder["payload"])


def shoot(chrome: str, html: str, work: Path, index: int, height: int,
          dest: Path, scale: int):
    page = work / f"shot-{index}.html"
    page.write_text(variant(html, ISOLATE_JS.replace("%INDEX%", str(index))),
                    encoding="utf-8")
    dest.unlink(missing_ok=True)
    chrome_run(
        chrome, page, work,
        lambda _out: dest.exists() and dest.stat().st_size > 0,
        f"--screenshot={dest}",
        f"--window-size={DESKTOP_W},{height + 40}",
        f"--force-device-scale-factor={scale}",
        linger=20,
    )
    return dest.exists() and dest.stat().st_size > 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("source", type=Path, help="待检报告 HTML")
    ap.add_argument("--chrome", default=None, help="Chrome/Edge 二进制路径（不存在则跳过）")
    ap.add_argument("--png", type=Path, default=None,
                    help="按章分片截图输出目录（Phase 8 视觉验收用）")
    ap.add_argument("--scale", type=int, default=2, help="截图像素密度（默认 2）")
    args = ap.parse_args()

    if not args.source.exists():
        sys.exit(f"文件不存在：{args.source}")

    # Edge 进程 cwd 与调用 shell 无关，相对路径会写到未知位置——全部转绝对
    args.source = args.source.resolve()
    if args.png:
        args.png = args.png.resolve()

    chrome = find_chrome(args.chrome)
    if not chrome:
        print(SKIP_NOTE)
        return 0

    html = args.source.read_text(encoding="utf-8")
    # Edge 退出后缓存文件偶有占用残留，清理失败不致命（系统 temp 会回收）
    with tempfile.TemporaryDirectory(prefix="fra-render-",
                                     ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)

        problems = 0
        print(f"=== check_render.py 渲染测量 · {args.source.name} ===")
        sections = []
        for vw, vh, tag in VIEWPORTS:
            report = measure(chrome, html, work, vw, vh)
            if tag == "桌面":
                sections = report["sections"]  # --png 分片按桌面视口章节高度
            vp_problems = 0
            for item in report["overlaps"]:
                vp_problems += 1
                print(f"🔴 [{tag}·overlap] svg#{item['svg']}: “{item['a']}” × “{item['b']}” "
                      f"重叠 {item['px']}px")
            for item in report["spills"]:
                vp_problems += 1
                print(f"🔴 [{tag}·spill] 溢出 .sheet {item['edge']} 缘 {item['px']}px — "
                      f"{item['sel']} “{item['text']}”")
            for item in report["clipped"]:
                vp_problems += 1
                print(f"🔴 [{tag}·clipped] 横向裁剪 {item['px']}px — {item['sel']}")
            for item in report["pageclip"]:
                vp_problems += 1
                print(f"🔴 [{tag}·pageclip] 页面横向溢出 {item['px']}px — "
                      f"骨架非流式或元素撑破视口")
            if tag == "桌面":  # 字体回退是环境级降级，与视口无关，报一次
                for item in report.get("fontwarn") or []:
                    print(f"🟡 [font] {item}")
            n = lambda k: len(report[k])
            print(f"--- [{tag}] 汇总：overlap {n('overlaps')} · spill {n('spills')} · "
                  f"clipped {n('clipped')} · pageclip {n('pageclip')} ---")
            problems += vp_problems

        if args.png:
            args.png.mkdir(parents=True, exist_ok=True)
            for i, sec in enumerate(sections):
                name = sec["id"] or f"{sec['cls']}-{i:02d}"
                dest = args.png / f"{args.source.stem}-{name}.png"
                ok = shoot(chrome, html, work, i, sec["h"], dest, args.scale)
                print(f"  {'✅' if ok else '🔴'} 分片截图 {dest.name} "
                      f"({DESKTOP_W}x{sec['h'] + 40} @x{args.scale})")
                if not ok:
                    problems += 1

        if problems:
            print("❌ 渲染测量发现问题：修呈现后再交付（旧版式存量报告的问题记录在案、不追溯）。")
            return 1
        print("✅ 渲染测量 0 问题。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
