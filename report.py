"""
report.py — Generate daily HTML temperature report from logs/YYYY-MM-DD.csv.
Run via Windows Task Scheduler at end of day (e.g. 23:55).
Usage: python report.py [YYYY-MM-DD]   (default: today)
"""

import csv
import sys
import tomllib
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = tomllib.loads((ROOT / "config.toml").read_text())
LOGS_DIR = ROOT / "logs"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
ALERT_LOG = ROOT / "alerts.log"

MACHINE = CONFIG["machine"]["friendly"]
THRESHOLDS = CONFIG["thresholds"]
CPU_KW = [k.lower() for k in CONFIG["report"]["cpu_keywords"]]
GPU_KW = [k.lower() for k in CONFIG["report"]["gpu_keywords"]]
DRIVE_KW = [k.lower() for k in CONFIG["report"]["drive_keywords"]]


def load_csv(date_str: str) -> list[dict]:
    path = LOGS_DIR / f"{date_str}.csv"
    if not path.exists():
        print(f"No log file for {date_str}: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def categorize(name: str) -> str:
    n = name.lower()
    if any(k in n for k in CPU_KW):
        return "CPU"
    if any(k in n for k in GPU_KW):
        return "GPU"
    if any(k in n for k in DRIVE_KW):
        return "Drive"
    return "Other"


def load_alerts(date_str: str) -> list[str]:
    if not ALERT_LOG.exists():
        return []
    lines = []
    with open(ALERT_LOG, encoding="utf-8") as f:
        for line in f:
            if date_str in line:
                lines.append(line.strip())
    return lines


def build_chart_data(rows: list[dict]) -> dict:
    """Build {component: {timestamps: [...], values: [...]}} for temp sensors only."""
    series = defaultdict(lambda: {"timestamps": [], "values": []})
    for r in rows:
        if "Temperature" not in r.get("sensor_type", "") and "Temp" not in r.get("component", ""):
            continue
        try:
            val = float(r["value"])
        except (ValueError, TypeError):
            continue
        key = r["component"]
        series[key]["timestamps"].append(r["timestamp"][11:16])  # HH:MM
        series[key]["values"].append(round(val, 1))
    return dict(series)


def build_summary(rows: list[dict]) -> list[dict]:
    """Per-component min/avg/max for temperature sensors."""
    buckets = defaultdict(list)
    for r in rows:
        if "Temperature" not in r.get("sensor_type", "") and "Temp" not in r.get("component", ""):
            continue
        try:
            buckets[r["component"]].append(float(r["value"]))
        except (ValueError, TypeError):
            continue
    summary = []
    for comp, vals in sorted(buckets.items()):
        avg = sum(vals) / len(vals)
        cat = categorize(comp)
        warn = (cat == "CPU" and max(vals) >= THRESHOLDS["cpu_temp_warn"]) or \
               (cat == "GPU" and max(vals) >= THRESHOLDS["gpu_temp_warn"]) or \
               (cat == "Drive" and max(vals) >= THRESHOLDS["drive_temp_warn"])
        crit = (cat == "CPU" and max(vals) >= THRESHOLDS["cpu_temp_crit"]) or \
               (cat == "GPU" and max(vals) >= THRESHOLDS["gpu_temp_crit"]) or \
               (cat == "Drive" and max(vals) >= THRESHOLDS["drive_temp_crit"])
        summary.append({
            "component": comp,
            "category": cat,
            "min": round(min(vals), 1),
            "avg": round(avg, 1),
            "max": round(max(vals), 1),
            "readings": len(vals),
            "warn": warn,
            "crit": crit,
        })
    return summary


def status_badge(row: dict) -> str:
    if row["crit"]:
        return '<span class="badge crit">CRITICAL</span>'
    if row["warn"]:
        return '<span class="badge warn">WARNING</span>'
    return '<span class="badge ok">OK</span>'


def generate_html(date_str: str) -> str:
    rows = load_csv(date_str)
    chart_data = build_chart_data(rows)
    summary = build_summary(rows)
    alerts = load_alerts(date_str)

    # Build chart datasets JSON
    colors = [
        "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
        "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
    ]
    datasets = []
    for i, (name, data) in enumerate(sorted(chart_data.items())):
        color = colors[i % len(colors)]
        datasets.append({
            "label": name,
            "data": data["values"],
            "borderColor": color,
            "backgroundColor": color + "22",
            "tension": 0.3,
            "pointRadius": 3,
        })

    # All timestamps (use first component's for x-axis labels)
    labels = []
    if chart_data:
        first = next(iter(chart_data.values()))
        labels = first["timestamps"]

    import json
    datasets_json = json.dumps(datasets)
    labels_json = json.dumps(labels)

    # Summary table rows
    table_rows = ""
    for r in summary:
        badge = status_badge(r)
        row_class = "crit-row" if r["crit"] else ("warn-row" if r["warn"] else "")
        table_rows += f"""
        <tr class="{row_class}">
            <td>{r['component']}</td>
            <td><span class="cat cat-{r['category'].lower()}">{r['category']}</span></td>
            <td>{r['min']}°C</td>
            <td>{r['avg']}°C</td>
            <td>{r['max']}°C</td>
            <td>{r['readings']}</td>
            <td>{badge}</td>
        </tr>"""

    # Alert section
    alert_html = ""
    if alerts:
        items = "\n".join(f"<li>{a}</li>" for a in alerts)
        alert_html = f'<div class="alert-box"><h3>⚠ Threshold Alerts</h3><ul>{items}</ul></div>'
    else:
        alert_html = '<div class="alert-box ok-box"><h3>✓ No threshold alerts</h3></div>'

    total_readings = len(rows)
    crits = sum(1 for r in summary if r["crit"])
    warns = sum(1 for r in summary if r["warn"] and not r["crit"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hardware Report — {date_str} — {MACHINE}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f1117; color: #e0e0e0; padding: 24px; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; color: #fff; }}
  .subtitle {{ color: #888; font-size: 0.9rem; margin-bottom: 24px; }}
  .cards {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .card {{ background: #1a1d27; border-radius: 8px; padding: 16px 20px; flex: 1; min-width: 140px; }}
  .card .num {{ font-size: 2rem; font-weight: 700; }}
  .card .lbl {{ font-size: 0.75rem; color: #888; margin-top: 4px; }}
  .num.red {{ color: #e74c3c; }}
  .num.yellow {{ color: #f39c12; }}
  .num.green {{ color: #2ecc71; }}
  .chart-box {{ background: #1a1d27; border-radius: 8px; padding: 20px; margin-bottom: 24px; }}
  .chart-box h2 {{ font-size: 1rem; margin-bottom: 16px; color: #aaa; }}
  table {{ width: 100%; border-collapse: collapse; background: #1a1d27;
           border-radius: 8px; overflow: hidden; margin-bottom: 24px; }}
  th {{ background: #23273a; padding: 10px 14px; text-align: left;
        font-size: 0.75rem; color: #888; text-transform: uppercase; }}
  td {{ padding: 10px 14px; font-size: 0.85rem; border-top: 1px solid #23273a; }}
  tr.warn-row td {{ background: #2a2200; }}
  tr.crit-row td {{ background: #2a0a0a; }}
  .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }}
  .badge.ok {{ background: #1a3a1a; color: #2ecc71; }}
  .badge.warn {{ background: #3a2a00; color: #f39c12; }}
  .badge.crit {{ background: #3a0a0a; color: #e74c3c; }}
  .cat {{ padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; }}
  .cat-cpu {{ background: #1a2a3a; color: #3498db; }}
  .cat-gpu {{ background: #2a1a3a; color: #9b59b6; }}
  .cat-drive {{ background: #1a3a2a; color: #2ecc71; }}
  .cat-other {{ background: #2a2a2a; color: #888; }}
  .alert-box {{ background: #2a1500; border: 1px solid #f39c12; border-radius: 8px;
                padding: 16px 20px; margin-bottom: 24px; }}
  .alert-box h3 {{ color: #f39c12; margin-bottom: 10px; }}
  .alert-box ul {{ padding-left: 20px; font-size: 0.85rem; line-height: 1.8; }}
  .ok-box {{ background: #0a2a0a; border-color: #2ecc71; }}
  .ok-box h3 {{ color: #2ecc71; }}
  .footer {{ color: #444; font-size: 0.75rem; text-align: center; margin-top: 32px; }}
</style>
</head>
<body>
<h1>Hardware Temperature Report</h1>
<div class="subtitle">{MACHINE} &nbsp;·&nbsp; {date_str} &nbsp;·&nbsp; {total_readings} readings</div>

<div class="cards">
  <div class="card"><div class="num {'red' if crits else 'green'}">{crits}</div><div class="lbl">Critical alerts</div></div>
  <div class="card"><div class="num {'yellow' if warns else 'green'}">{warns}</div><div class="lbl">Warnings</div></div>
  <div class="card"><div class="num">{len(summary)}</div><div class="lbl">Sensors tracked</div></div>
  <div class="card"><div class="num">{total_readings // max(len(summary),1)}</div><div class="lbl">Snapshots</div></div>
</div>

{alert_html}

<div class="chart-box">
  <h2>Temperature Timeline</h2>
  <canvas id="tempChart" height="80"></canvas>
</div>

<table>
  <thead><tr>
    <th>Component</th><th>Type</th><th>Min</th><th>Avg</th><th>Max</th><th>Readings</th><th>Status</th>
  </tr></thead>
  <tbody>{table_rows}</tbody>
</table>

<div class="footer">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · temps-jdm-laptop</div>

<script>
new Chart(document.getElementById('tempChart'), {{
  type: 'line',
  data: {{
    labels: {labels_json},
    datasets: {datasets_json}
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ labels: {{ color: '#aaa', font: {{ size: 11 }} }} }},
      tooltip: {{ backgroundColor: '#1a1d27', titleColor: '#fff', bodyColor: '#ccc' }}
    }},
    scales: {{
      x: {{ ticks: {{ color: '#666' }}, grid: {{ color: '#1e2030' }} }},
      y: {{
        ticks: {{ color: '#666', callback: v => v + '°C' }},
        grid: {{ color: '#1e2030' }},
        title: {{ display: true, text: 'Temperature (°C)', color: '#666' }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    html = generate_html(date_str)
    out = REPORTS_DIR / f"{date_str}.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report written to {out}")


if __name__ == "__main__":
    main()
