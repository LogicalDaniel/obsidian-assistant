"""Write an HTML view of ``benchmark/last_run.json``.

    uv run python benchmark/report.py

``run.py`` writes the same file after a live run.
"""

from __future__ import annotations

import json
from pathlib import Path

REPORT = Path(__file__).resolve().parent / "last_run.json"
HTML = Path(__file__).resolve().parent / "last_run.html"


def write_report(rows: list[dict], path: Path) -> None:
    payload = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    path.write_text(_PAGE.replace("/*__DATA__*/", payload), encoding="utf-8")


def main() -> None:
    rows = json.loads(REPORT.read_text(encoding="utf-8"))
    write_report(rows, HTML)
    print(f"wrote {HTML.name}")


_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Benchmark</title>
<style>
  :root { color-scheme: light; --line: #e4e0d8; --ink: #1c1915; --muted: #6d675e; --ok: #1f7a4d; --bad: #a33b32; --paper: #f7f4ee; }
  body { margin: 0; font: 15px/1.5 "Segoe UI", sans-serif; color: var(--ink); background: var(--paper); }
  header, main { max-width: 1100px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 22px; font-weight: 650; margin: 0 0 8px; }
  .meta { color: var(--muted); }
  .cards { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
  button.card, button.filter { border: 1px solid var(--line); background: white; border-radius: 8px; padding: 8px 12px; cursor: pointer; color: inherit; }
  button.on { border-color: var(--ink); }
  table { width: 100%; border-collapse: collapse; background: white; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { font-size: 12px; color: var(--muted); font-weight: 600; }
  tr.task { cursor: pointer; }
  tr.fail td.id { color: var(--bad); }
  tr.ok td.id { color: var(--ok); }
  tr.detail { display: none; background: #fffdf8; }
  tr.detail.open { display: table-row; }
  .answer, .checks, .trace { white-space: pre-wrap; margin: 8px 0; }
  .bad { color: var(--bad); }
  .okc { color: var(--ok); }
</style>
</head>
<body>
<header>
  <h1>Benchmark</h1>
  <div class="meta" id="meta"></div>
  <div class="cards" id="cards"></div>
  <button class="filter on" id="all" type="button">全部</button>
  <button class="filter" id="failed" type="button">只看失败</button>
</header>
<main>
  <table>
    <thead>
      <tr><th>任务</th><th>类别</th><th>结果</th><th>步数</th><th>输入</th><th>缓存</th><th>耗时</th></tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</main>
<script>
const rows = /*__DATA__*/;
const body = document.getElementById("rows");
let category = "";
let failedOnly = false;

function esc(text) {
  return String(text ?? "").replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
}

function render() {
  const passed = rows.filter((row) => row.passed).length;
  document.getElementById("meta").textContent = passed + " / " + rows.length + " 通过";
  const counts = new Map();
  for (const row of rows) {
    const name = row.category || "note-qa";
    const item = counts.get(name) || { ok: 0, n: 0 };
    item.n += 1;
    if (row.passed) item.ok += 1;
    counts.set(name, item);
  }
  const cards = document.getElementById("cards");
  cards.innerHTML = "";
  for (const [name, item] of counts) {
    const button = document.createElement("button");
    button.className = "card" + (category === name ? " on" : "");
    button.type = "button";
    button.textContent = name + "  " + item.ok + "/" + item.n;
    button.onclick = () => { category = category === name ? "" : name; render(); };
    cards.appendChild(button);
  }
  body.innerHTML = "";
  for (const row of rows) {
    if (category && (row.category || "note-qa") !== category) continue;
    if (failedOnly && row.passed) continue;
    const tr = document.createElement("tr");
    tr.className = "task " + (row.passed ? "ok" : "fail");
    tr.innerHTML = "<td class='id'>" + esc(row.id) + "</td><td>" + esc(row.category) + "</td><td>"
      + (row.passed ? "通过" : "失败") + "</td><td>" + esc(row.steps) + "</td><td>"
      + esc(row.input_tokens) + "</td><td>" + esc(row.cached_tokens) + "</td><td>"
      + esc(row.elapsed_ms) + " ms</td>";
    const detail = document.createElement("tr");
    detail.className = "detail";
    const cell = document.createElement("td");
    cell.colSpan = 7;
    const trace = (row.trace || []).map((item) => {
      let label = (item.name || "") + (item.path ? " " + item.path : "");
      const marks = [];
      if (item.revealed) marks.push("revealed");
      if (item.compacted) marks.push("compacted");
      if (marks.length) label += " (" + marks.join(", ") + ")";
      return label;
    }).join("\\n");
    const checks = (row.checks || []).map((check) => (check.passed ? "ok   " : "fail ") + check.name).join("\\n");
    cell.innerHTML = "<div class='trace'>" + esc(trace) + "</div><div class='answer'>" + esc(row.answer || row.error || "")
      + "</div><div class='checks'>" + esc(checks) + "</div>";
    detail.appendChild(cell);
    tr.onclick = () => detail.classList.toggle("open");
    body.appendChild(tr);
    body.appendChild(detail);
  }
}

document.getElementById("all").onclick = () => { category = ""; failedOnly = false; document.getElementById("all").classList.add("on"); document.getElementById("failed").classList.remove("on"); render(); };
document.getElementById("failed").onclick = () => { failedOnly = true; document.getElementById("failed").classList.add("on"); document.getElementById("all").classList.remove("on"); render(); };
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
