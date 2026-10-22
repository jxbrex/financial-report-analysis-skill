#!/usr/bin/env python3
"""渲染测量门禁：headless Chrome/Edge 真渲染后注入 JS 测量 DOM。

    python scripts/check_render.py 报告.html                 # 测量门禁
    python scripts/check_render.py 报告.html --png out目录/   # 按章分片截图（Phase 8 视觉验收）
    python scripts/check_render.py 报告.html --chrome 路径    # 指定浏览器二进制

测量项（渲染后状态，静态正则看不到；编号与注入 JS 里的分段注释一致）：
  1. SVG 文本重叠：每个 svg 内 <text> 两两 bounding rect 相交测试（两轴重叠均 >1px 才算）
  1b. SVG 文本出视口（v0.0.25）：text 矩形出所属 svg 左右缘 >3px → 计入门禁——
     2/3 号判据对 svg 内元素免测（viewBox 缩放坐标系），出界文字被视口静默裁切
     （赢合 2026H1 segbridge 长标签左端被裁、三道门禁全绿漏检的实证）
  2. HTML 元素溢出 .sheet：文本后代右/左缘超出 .sheet boundingRect >1px（豁免 svg 内部元素）
  3. 横向裁剪：scrollWidth > clientWidth + 2 且 computed overflowX ≠ visible（含页面级）
  4. 字体回退：朱雀仿宋不可用时正文回退系统仿宋（环境级降级，🟡 不计入门禁）
  5. 关键 SVG 非空（v0.0.22）：KEY_SVG_IDS 内「存在但无任何子元素」的 svg → 计入门禁
     （空图无元素可测，1~3 恰好全部漏检）

门禁定位：可选门禁——找不到 Chrome/Edge（或 --chrome 路径不存在）→ 打印跳过声明 + exit 0，
check_html.py 的静态硬门禁地位不动；发现问题 exit 1。
框架结构自包含复制自 lieflat-cards/scripts/render.py（部署目录须独立，不跨 skill import）。
"""
from __future__ import annotations

import argparse
import json
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
SCALE = 2                       # 截图像素密度（--png 分片截图用）
VIEWPORTS = ((DESKTOP_W, VIEW_H, "桌面"), (MOBILE_W, VIEW_H, "窄屏"))

SKIP_NOTE = ("渲染门禁跳过：未找到 Chrome/Edge（check_html.py 静态硬门禁仍然生效，"
             "本项为可选门禁，不阻塞交付）")

# 关键 SVG 清单（v0.0.22，长城 2026H1 JS 团灭事故固化：数据槽区 const 重复声明 →
# 整段 <script> SyntaxError → 建图代码全不执行 → 所有 SVG 空白；且「空图无元素可测」
# 让重叠/溢出/裁剪三项测量恰好全部漏检，必须点名查子元素数）。
# 页面中不存在的 id 不查——ncrline hist<3 期、holders 非 A 股等整卡降级删除是合法形态。
# trend=旧版式双面板图（v0.0.22 前）、revchart/npchart=v0.0.22 四宫格拆出的左右图——
# 「存在才查」逻辑兼容新旧版式，新旧 id 都留在清单里。
# ◆ 为什么是白名单而不是「查页面全部 svg」（这条别在瘦身时简化掉）：存量版式的
#   spark-* 迷你折线在数据不足时**合法留空**——万科A 2026H1 实测 spark-c2s/spark-dol
#   两个空图，改查全部 svg 会对已交付报告误报；dupont5/bridge 等更早版式 id 不入册
#   也无妨：JS 团灭打死的是全部图，每版式至少一个 id 在册即足以检出，清单不追穷举。
KEY_SVG_IDS = ("trend", "revchart", "npchart", "ncrline", "capexbars", "effline",
               "ocfbridge", "segbridge", "dupontstack", "holders", "sankey")

# 注入页面：测量上述五项呈现问题 + 章节高度（供 --png 分片用）
MEASURE_JS = """
<script id="fra-measure">
window.addEventListener('load', () => setTimeout(() => {
  const label = (el) => el.tagName.toLowerCase() +
    (el.className && typeof el.className === 'string'
      ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
  const report = {overlaps: [], spills: [], clipped: [], pageclip: [], svgclip: [], sections: []};

  /* 1. SVG 文本重叠：本技能 SVG text 均单行，取整体 boundingRect 即可 */
  for (const svg of document.querySelectorAll('svg')) {
    const items = [...svg.querySelectorAll('text')].map(t =>
      ({t, r: t.getBoundingClientRect(), s: (t.textContent || '').trim()}));
    /* 1b. SVG 文本出视口（v0.0.25，赢合 2026H1 segbridge「锂电池专用生产设备」级长
       标签左端探出视口被裁、三道门禁全绿漏检的实证）：2/3 号判据对 svg 内元素免测
       （下方 closest('svg') continue），出界文字被视口静默裁切。text 矩形与所属 svg
       矩形比对，左右出界 >3px 才报（吸收 halo 描边 1.25px 与抗锯齿余量） */
    const sr = svg.getBoundingClientRect();
    for (const it of items) {
      if (!it.r.width && !it.r.height) continue;
      const dl = sr.left - it.r.left, dr = it.r.right - sr.right;
      if (dl > 3 || dr > 3)
        report.svgclip.push({svg: svg.id || '(no-id)', text: it.s.slice(0, 24),
          edge: dl > 3 ? 'left' : 'right', px: Math.round(Math.max(dl, dr))});
    }
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

  /* 2. HTML 元素溢出 .sheet + 3. 横向裁剪（元素级与页面级）——分段判据见下方各注释 */
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

  /* 5. 关键 SVG 非空（v0.0.22，长城 2026H1 JS 团灭事故）：建图脚本 SyntaxError
     未执行时这些 svg 存在但没有任何子元素——重叠/溢出测量恰好全部漏检。
     id 清单由 Python 侧 KEY_SVG_IDS 注入；页面不存在的 id 不查（整卡降级合法）。
     判据用 childElementCount 而非图形标签清单：本技能建图只产 path/rect/line/
     circle/text，标签清单会漏掉将来新增的标签，且空 <g> 包装会被误判成已画 */
  report.emptysvg = [];
  for (const id of %KEYIDS%) {
    const el = document.getElementById(id);
    if (el && el.tagName.toLowerCase() === 'svg' && el.childElementCount === 0)
      report.emptysvg.push(id);
  }

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
                        out = log.read_text(encoding="utf-8", errors="replace")  # 重读：迟到的
                        if ready(out):                                          # 异步写盘/回调
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
        page.write_text(variant(html, MEASURE_JS.replace("%PORT%", str(port))
                                .replace("%KEYIDS%", json.dumps(KEY_SVG_IDS))),
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
            for item in report.get("svgclip") or []:
                vp_problems += 1
                print(f"🔴 [{tag}·svgclip] svg#{item['svg']} 文本 “{item['text']}” "
                      f"出视口 {item['edge']} 缘 {item['px']}px——文字被视口裁切")
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
                # 关键 SVG 空图与视口无关（JS 失败是确定性的），只报一次、计入门禁。
                # 归因按命中数分支，别把两种成因混成一句话：多图齐空=建图脚本整体
                # 没跑（const 重名团灭整段 <script>）；单图空=该图数据缺、按模板约定
                # 本该删掉这个 svg（模板四宫格/现金时序卡的降级注释）
                empty = report.get("emptysvg") or []
                blame = ("建图 JS 未执行：数据槽区 const 重复声明会团灭整个 <script> 块"
                         "（v0.0.22）" if len(empty) >= 2 else
                         "该图数据缺：按模板约定删对应 svg 并在 srcline 注明"
                         "（单图空不是 JS 团灭）")
                for svg_id in empty:
                    vp_problems += 1
                    print(f"🔴 [{tag}·empty-svg] svg#{svg_id} 存在但无任何子元素——{blame}")
            n = lambda k: len(report.get(k) or [])
            # empty-svg 只在桌面视口计数与打印，窄屏不重复报一个没有明细的数字
            es = str(n("emptysvg")) if tag == "桌面" else "—（桌面已报）"
            print(f"--- [{tag}] 汇总：overlap {n('overlaps')} · spill {n('spills')} · "
                  f"clipped {n('clipped')} · pageclip {n('pageclip')} · svgclip {n('svgclip')} · "
                  f"empty-svg {es} ---")
            problems += vp_problems

        if args.png:
            args.png.mkdir(parents=True, exist_ok=True)
            _stale = [p for p in args.png.glob(f"{args.source.stem}-*.png")]
            if _stale:  # 报告改短重跑时上次多出的旧分片会残留——提示先清空，防拿旧图验收
                print(f"  🟡 截图目录已有 {len(_stale)} 张同名前缀旧分片——"
                      f"本次未覆盖的将是旧图，建议先清空目录")
            _seen = set()
            for i, sec in enumerate(sections):
                name = sec["id"] or f"{sec['cls']}-{i:02d}"
                if name in _seen:  # 章节 id 重复（手工编辑复制粘贴错误）——加序号防静默覆盖
                    print(f"  🔴 章节 id「{name}」重复——分片名加序号后缀（直接覆盖会丢前章截图）")
                    problems += 1
                    name = f"{name}-{i:02d}"
                _seen.add(name)
                dest = args.png / f"{args.source.stem}-{name}.png"
                ok = shoot(chrome, html, work, i, sec["h"], dest, SCALE)
                print(f"  {'✅' if ok else '🔴'} 分片截图 {dest.name} "
                      f"({DESKTOP_W}x{sec['h'] + 40} @x{SCALE})")
                if not ok:
                    problems += 1

        if problems:
            print("❌ 渲染测量发现问题：修呈现后再交付（旧版式存量报告的问题记录在案、不追溯）。")
            return 1
        print("✅ 渲染测量 0 问题。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
