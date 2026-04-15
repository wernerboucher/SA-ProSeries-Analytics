import requests
import pandas as pd
from config import COMPS_MASTER_CSV

# ================== CONFIG ==================

BASE_URL = "https://api-tms.cricketpvcms.co.za/api/v1/competitions/listing"

# ================== FETCH ==================

all_rows = []
seen_ids = set()
page = 1

while True:
    print(f"Fetching page {page}...")

    r = requests.get(BASE_URL, params={"page": page, "per_page": 1000}, timeout=20)
    r.raise_for_status()

    data = r.json().get("data", [])
    if not data:
        print("No more data.")
        break

    new_count = 0
    for c in data:
        cid = c.get("id")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        all_rows.append(c)
        new_count += 1

    print(f"  Page {page}: {new_count} new competitions")
    page += 1

print(f"\nTotal unique competitions: {len(all_rows)}")

# ================== NORMALISE + SAVE ==================

records = [
    {
        "CompID":          c.get("id"),
        "CompetitionName": c.get("name"),
        "Status":          c.get("status"),
        "StartDate":       c.get("start_date"),
        "EndDate":         c.get("end_date"),
        "CreatedBy":       c.get("created_by"),
    }
    for c in all_rows
]

df = pd.DataFrame(records)
df.to_csv(COMPS_MASTER_CSV, index=False, encoding="utf-8")
print(f"Saved {len(df)} competitions to {COMPS_MASTER_CSV}")
