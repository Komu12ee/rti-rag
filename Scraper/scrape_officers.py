import json
from pathlib import Path
from datetime import datetime

import requests

URL = "https://rtionline.cg.gov.in/rti/api/Pio/GetListOfEmployees"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

OUT_DIR = PROJECT_ROOT / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://rtionline.cg.gov.in/listofregisteredofficers",
}

response = requests.get(URL, headers=headers, timeout=60)
response.raise_for_status()

data = response.json()

output_path = OUT_DIR / f"officers_raw_{timestamp}.json"

output_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("Downloaded successfully")
print("Status:", data.get("status"))
print("Rows:", len(data.get("table", [])))
print("Saved at:", output_path)