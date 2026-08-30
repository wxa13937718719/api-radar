from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

LINK_PATTERN = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)\)")
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")


def _bold(value: str) -> str:
    return BOLD_PATTERN.sub(r"<strong>\1</strong>", value)


def _inline_markdown(value: str) -> str:
    output: list[str] = []
    position = 0
    for match in LINK_PATTERN.finditer(value):
        output.append(_bold(html.escape(value[position:match.start()])))
        label = _bold(html.escape(match.group(1)))
        url = html.escape(match.group(2), quote=True)
        output.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}<span>↗</span></a>')
        position = match.end()
    output.append(_bold(html.escape(value[position:])))
    return "".join(output)


def markdown_to_html(value: str) -> str:
    blocks: list[str] = []
    lines = value.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("### "):
            blocks.append(f"<h3>{_inline_markdown(line[4:])}</h3>")
            index += 1
            continue
        if line.startswith("## "):
            blocks.append(f"<h2>{_inline_markdown(line[3:])}</h2>")
            index += 1
            continue
        if line.startswith("# "):
            blocks.append(f"<h2>{_inline_markdown(line[2:])}</h2>")
            index += 1
            continue
        if line.startswith(("- ", "* ")):
            items = []
            while index < len(lines) and lines[index].strip().startswith(("- ", "* ")):
                items.append(f"<li>{_inline_markdown(lines[index].strip()[2:])}</li>")
                index += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue
        paragraph = [line]
        index += 1
        while index < len(lines) and lines[index].strip() and not lines[index].strip().startswith(("# ", "## ", "### ", "- ", "* ")):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(f"<p>{'<br>'.join(_inline_markdown(item) for item in paragraph)}</p>")
    return "".join(blocks)


def render_notification_html(report: dict[str, Any]) -> str:
    briefing = ((report.get("recommendations") or {}).get("briefing") or {})
    text = str(briefing.get("text") or "今天尚未生成可用简报。")
    source = str(briefing.get("source") or "rules")
    model = briefing.get("model")
    generated = datetime.fromisoformat(str(report["generated_at"])).astimezone()
    scans = report.get("scans") or []
    successful_scans = sum(item.get("return_code") == 0 for item in scans)
    intelligence = report.get("intelligence") or {}
    official_sources = int(intelligence.get("successful") or 0)
    changed_sources = int(intelligence.get("changed") or 0)
    source_label = f"本地模型 · {model}" if source == "llm" and model else "规则回退"
    article = markdown_to_html(text)
    date_label = generated.strftime("%Y年%m月%d日 · %H:%M")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API Radar 今日情报</title>
<style>
:root{{--ink:#13233a;--muted:#627287;--line:#dce5ea;--paper:#f7fafb;--navy:#0b1c31;--cyan:#0b8793;--orange:#ef7652}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(circle at 20% 0%,#183753 0,#0b1c31 42%,#071321 100%);color:var(--ink);font-family:Inter,"Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;min-height:100vh;padding:36px}}
.shell{{max-width:940px;margin:auto}}
.top{{display:flex;align-items:center;justify-content:space-between;color:#dceaf1;margin-bottom:18px}}
.brand{{display:flex;align-items:center;gap:12px;font-size:18px;font-weight:780;letter-spacing:.2px}}
.mark{{width:38px;height:38px;border-radius:12px;background:linear-gradient(145deg,var(--orange),#f39b68);display:grid;place-items:center;box-shadow:0 9px 24px #0005;position:relative}}
.mark:before,.mark:after{{content:"";position:absolute;border:1px solid #fff9;border-radius:50%}}
.mark:before{{width:19px;height:19px}}.mark:after{{width:7px;height:7px;background:white}}
.date{{font-size:12px;color:#9fb2c1;letter-spacing:.5px}}
.card{{background:linear-gradient(180deg,#fff 0,var(--paper) 100%);border-radius:24px;overflow:hidden;box-shadow:0 26px 80px #0008;border:1px solid #ffffff36}}
.hero{{padding:30px 38px 24px;border-bottom:1px solid var(--line);position:relative}}
.hero:after{{content:"";position:absolute;left:38px;bottom:-1px;width:94px;height:3px;background:linear-gradient(90deg,var(--orange),#f3aa69);border-radius:4px}}
.kicker{{font-size:11px;color:var(--cyan);font-weight:800;letter-spacing:1.8px;margin-bottom:9px}}
h1{{margin:0;font-size:31px;line-height:1.22;letter-spacing:-.6px;color:#10233a}}
.sub{{margin-top:9px;color:var(--muted);font-size:13px}}
.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border-bottom:1px solid var(--line)}}
.metric{{background:#f9fbfc;padding:17px 24px}}
.metric span{{display:block;color:#778797;font-size:11px;letter-spacing:.7px;margin-bottom:5px}}
.metric strong{{font-size:19px;color:#18334b}}
.article{{padding:30px 38px 22px;max-height:510px;overflow:auto;scrollbar-color:#a9bdc8 transparent}}
.article p{{font-size:15px;line-height:1.9;margin:0 0 18px;color:#2e4356}}
.article h2,.article h3{{color:#102c44;margin:23px 0 10px;line-height:1.35}}
.article h2{{font-size:20px}}.article h3{{font-size:16px}}
.article ul{{margin:4px 0 20px;padding-left:22px;color:#2e4356}}
.article li{{font-size:14px;line-height:1.75;margin:6px 0}}
.article strong{{color:#102c44;font-weight:800;background:linear-gradient(transparent 67%,#ffe1d5 0)}}
.article a{{display:inline;color:#087f8b;font-weight:700;text-decoration:none;border-bottom:1px solid #81c2c7}}
.article a span{{font-size:10px;margin-left:3px}}
.footer{{padding:16px 38px 20px;border-top:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;color:#738596;font-size:11px}}
.source{{padding:5px 9px;border-radius:999px;background:#e7f3f3;color:#176c72;font-weight:700}}
@media(max-width:700px){{body{{padding:12px}}.top{{padding:4px 4px 0}}.date{{display:none}}.hero,.article{{padding-left:22px;padding-right:22px}}.metrics{{grid-template-columns:1fr 1fr 1fr}}.metric{{padding:14px 12px}}h1{{font-size:25px}}}}
</style>
</head>
<body>
<main class="shell">
  <header class="top"><div class="brand"><div class="mark"></div>API Radar</div><div class="date">{html.escape(date_label)}</div></header>
  <section class="card">
    <div class="hero"><div class="kicker">DAILY API INTELLIGENCE</div><h1>今天的模型市场，什么值得行动？</h1><div class="sub">官方来源监测 · 价格快照 · 限制与风险 · 个性化建议</div></div>
    <div class="metrics">
      <div class="metric"><span>PROVIDER 扫描</span><strong>{successful_scans}/{len(scans)}</strong></div>
      <div class="metric"><span>官方来源可用</span><strong>{official_sources}</strong></div>
      <div class="metric"><span>检测到变化</span><strong>{changed_sources}</strong></div>
    </div>
    <article class="article">{article}</article>
    <footer class="footer"><span>结论仅基于已采集的公开事实；点击文中链接核对官方原文。</span><span class="source">{html.escape(source_label)}</span></footer>
  </section>
</main>
</body>
</html>"""


def render_report_file(report_path: Path, output_path: Path) -> Path:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_notification_html(report), encoding="utf-8")
    return output_path
