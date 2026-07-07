import json
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR
DATA_DIR = PROJECT_ROOT / "raw"

path = DATA_DIR / "officers_raw_20260626_174315.json"

# Automatically pick latest officers_raw_*.json
json_files = sorted(DATA_DIR.glob("officers_raw_20260626_174315.json"))

if not json_files:
    raise FileNotFoundError(f"No officers_raw_*.json file found in: {DATA_DIR}")

path = json_files[-1]

print(f"Reading file: {path}")

data = json.loads(path.read_text(encoding="utf-8"))
rows = data.get("table", [])

roles = Counter(
    (r.get("rtidesignation") or "").strip()
    for r in rows
)

print("\nTotal records:", len(rows))
print("Unique roles:", len(roles))
print("-" * 50)

for role, count in roles.most_common():
    print(f"{role or '<EMPTY ROLE>'}: {count}")