"""
collect.py — Hourly hardware sensor snapshot from LibreHardwareMonitor.
Appends one row per sensor reading to logs/YYYY-MM-DD.csv.
Run via Windows Task Scheduler every hour (see setup_scheduler.ps1).
"""

import csv
import json
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent
CONFIG = tomllib.loads((ROOT / "config.toml").read_text())
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LHM_URL = CONFIG["machine"]["lhm_url"]
THRESHOLDS = CONFIG["thresholds"]

ALERT_LOG = ROOT / "alerts.log"

CSV_FIELDS = ["timestamp", "component", "hardware", "sensor_type", "value", "min", "max"]


def parse_value(s: str) -> float | None:
    """Extract numeric value from LHM strings like '72.3 °C' or '45 %'."""
    try:
        return float(s.split()[0].replace(",", "."))
    except (ValueError, IndexError, AttributeError):
        return None


def walk_tree(node: dict, hardware_name: str, rows: list, alerts: list, ts: str):
    """Recursively walk LHM JSON tree, collecting sensor readings."""
    name = node.get("Text", "")
    children = node.get("Children", [])

    # Detect hardware nodes (they have a Min/Max/Value structure in children)
    is_sensor = "Value" in node and node["Value"] not in ("-", "")

    if is_sensor:
        value = parse_value(node.get("Value", ""))
        min_v = parse_value(node.get("Min", ""))
        max_v = parse_value(node.get("Max", ""))
        sensor_type = node.get("SensorType", "")

        # Detect sensor type from value string when SensorType field is empty
        raw_val = node.get("Value", "")
        if not sensor_type:
            if "°C" in raw_val:
                sensor_type = "Temperature"
            elif "%" in raw_val:
                sensor_type = "Load"
            elif "MHz" in raw_val:
                sensor_type = "Clock"
            elif " W" in raw_val:
                sensor_type = "Power"
            elif " V" in raw_val:
                sensor_type = "Voltage"
            elif "RPM" in raw_val:
                sensor_type = "Fan"

        if value is not None:
            rows.append({
                "timestamp": ts,
                "component": name,
                "hardware": hardware_name,
                "sensor_type": sensor_type,
                "value": value,
                "min": min_v,
                "max": max_v,
            })
            check_alert(name, hardware_name, sensor_type, value, ts, alerts)

    # Track hardware name as we descend
    next_hw = name if not children or is_sensor else hardware_name
    for child in children:
        walk_tree(child, next_hw or hardware_name, rows, alerts, ts)


def check_alert(name: str, hardware: str, sensor_type: str, value: float,
                ts: str, alerts: list):
    label = f"{hardware} / {name}"

    if "Temperature" in sensor_type or "Temp" in name:
        name_lower = name.lower()
        if any(k.lower() in name_lower for k in ["cpu", "core", "package", "ccd"]):
            if value >= THRESHOLDS["cpu_temp_crit"]:
                alerts.append(f"CRITICAL  CPU  {label}: {value}°C (>= {THRESHOLDS['cpu_temp_crit']}°C)")
            elif value >= THRESHOLDS["cpu_temp_warn"]:
                alerts.append(f"WARNING   CPU  {label}: {value}°C (>= {THRESHOLDS['cpu_temp_warn']}°C)")
        elif any(k.lower() in name_lower for k in ["gpu"]):
            if value >= THRESHOLDS["gpu_temp_crit"]:
                alerts.append(f"CRITICAL  GPU  {label}: {value}°C (>= {THRESHOLDS['gpu_temp_crit']}°C)")
            elif value >= THRESHOLDS["gpu_temp_warn"]:
                alerts.append(f"WARNING   GPU  {label}: {value}°C (>= {THRESHOLDS['gpu_temp_warn']}°C)")
        elif any(k.lower() in name_lower for k in ["ssd", "nvme", "hdd", "drive", "storage"]):
            if value >= THRESHOLDS["drive_temp_crit"]:
                alerts.append(f"CRITICAL  DRIVE {label}: {value}°C (>= {THRESHOLDS['drive_temp_crit']}°C)")
            elif value >= THRESHOLDS["drive_temp_warn"]:
                alerts.append(f"WARNING   DRIVE {label}: {value}°C (>= {THRESHOLDS['drive_temp_warn']}°C)")


def collect():
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date_str = ts[:10]

    try:
        resp = requests.get(LHM_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"ERROR: Cannot reach LibreHardwareMonitor at {LHM_URL}: {e}", file=sys.stderr)
        print("Make sure LibreHardwareMonitor is running as Administrator with web server enabled.")
        sys.exit(1)

    rows = []
    alerts = []
    walk_tree(data, "", rows, alerts, ts)

    if not rows:
        print("WARNING: No sensor data parsed from LHM response.", file=sys.stderr)
        sys.exit(1)

    # Append to daily CSV
    csv_path = LOGS_DIR / f"{date_str}.csv"
    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    print(f"[{ts}] Logged {len(rows)} readings to {csv_path.name}")

    # Log alerts
    if alerts:
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            for a in alerts:
                line = f"[{ts}] {a}"
                f.write(line + "\n")
                print(line)


if __name__ == "__main__":
    collect()
