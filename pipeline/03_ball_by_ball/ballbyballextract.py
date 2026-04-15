import requests
from bs4 import BeautifulSoup
import os
import time
import re
import sys
import pandas as pd
from pathlib import Path
from config import CA_HTML_DIR

# ================== CONFIG ==================

tournament_url = "https://cricketarchive.com/Archive/Events/40/Hollywoodbets_Pro_50_2025-26.html"

if "--url" in sys.argv:
    idx = sys.argv.index("--url")
    tournament_url = sys.argv[idx + 1]

# Derive season folder name from command line args or use default
season     = "2025-26"
comp_format = "Pro50"

if "--season" in sys.argv:
    season = sys.argv[sys.argv.index("--season") + 1]
if "--format" in sys.argv:
    comp_format = sys.argv[sys.argv.index("--format") + 1]

save_folder = os.path.join(CA_HTML_DIR, f"{comp_format} {season}")
os.makedirs(save_folder, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Personal research project; contact: werboucher@gmail.com)"
})

# ================== HELPERS ==================

def safe_get(url, tries=3):
    """GET with retry on failure."""
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        print(f"  Retry {attempt + 1}/{tries} for {url}")
        time.sleep(2)
    return None


def get_match_urls(tournament_url):
    """Return all scorecard URLs from a CricketArchive tournament page."""
    resp = safe_get(tournament_url)
    if not resp:
        print("Could not load tournament page.")
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    matches = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/Scorecards/" in href and href.endswith(".html") and "commentary" not in href:
            full = href if href.startswith("http") else "https://cricketarchive.com" + href
            matches.add(full)
    return list(matches)


# ================== FIXTURES TABLE ==================

def save_fixtures_table(tournament_url):
    """
    Extract the fixtures table from the tournament page and save as CSV.
    Used by converttocsv.py to assign fielding teams.
    """
    print("Extracting fixtures table...")
    resp = session.get(tournament_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    for table in soup.find_all("table"):
        text = table.get_text().lower()
        if not any(word in text for word in ["date", "match", "ground", "venue", "result", "vs"]):
            continue

        rows = []
        for tr in table.find_all("tr"):
            cols = tr.find_all("td")
            if len(cols) < 5:
                continue

            date        = cols[1].get_text(strip=True)
            match_link  = cols[4].find("a")
            match_text  = match_link.get_text(strip=True) if match_link else ""
            match_href  = match_link.get("href")          if match_link else ""
            match_id    = re.search(r'/(\d+)\.html$', match_href).group(1) if match_href else ""
            ground_link = cols[5].find("a")
            ground_text = ground_link.get_text(strip=True) if ground_link else ""
            code        = cols[6].get_text(strip=True) if len(cols) > 6 else ""

            rows.append([date, match_text, ground_text, match_id, code])

        if rows:
            df       = pd.DataFrame(rows, columns=["Date", "Match", "Ground", "MatchID", "Code"])
            csv_path = os.path.join(save_folder, f"fixtures_{Path(tournament_url).stem}.csv")
            df.to_csv(csv_path, index=False, encoding="utf-8")
            print(f"  Fixtures saved: {csv_path} ({len(df)} matches)")
            return True

    print("  Could not find fixtures table.")
    return False


# ================== COMMENTARY DOWNLOADER ==================

def download_commentary(match_url):
    """Download innings commentary HTML files for a match. Skips if already cached."""
    m = re.search(r'/(\d+)\.html$', match_url)
    if not m:
        return
    match_id = m.group(1)
    base     = match_url.rsplit('/', 1)[0] + '/'

    for inn in [1, 2]:
        comm_url = f"{base}{match_id}/{match_id}_commentary_i{inn}_page.html"
        filename = os.path.join(save_folder, f"match_{match_id}_i{inn}.html")

        if os.path.exists(filename):
            print(f"  Already cached: {filename}")
            continue

        r = safe_get(comm_url)
        if r and len(r.text) > 5000:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  Saved: {filename}")
        else:
            print(f"  No commentary for innings {inn}")

        time.sleep(0.1)


# ================== RUN ==================

print(f"Tournament: {tournament_url}")
print(f"Output folder: {save_folder}\n")

save_fixtures_table(tournament_url)

matches = get_match_urls(tournament_url)
print(f"\nFound {len(matches)} matches. Downloading commentary...\n")

for i, url in enumerate(matches, 1):
    print(f"[{i}/{len(matches)}] {url}")
    download_commentary(url)
    time.sleep(0.1)

print("\nDone.")
