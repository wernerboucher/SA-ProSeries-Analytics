import requests
from bs4 import BeautifulSoup
import csv
import time
import re
import os
import sys
import pandas as pd
from urllib.parse import urljoin
from datetime import datetime
from config import PLAYER_DIR, PLAYER_MERGED

# ================== CONFIG ==================

BASE_URL = "https://cricketarchive.com"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

os.makedirs(PLAYER_DIR, exist_ok=True)

# Maps CricketArchive team abbreviations to full team names
TEAM_MAP = {
    "BOL":  "Boland",
    "BOR":  "Iinyathi",
    "CG":   "Lions",
    "GAU":  "Lions",
    "CGT":  "Lions",
    "EP":   "EP",
    "EAS":  "Easterns",
    "FS":   "Knights",
    "GW":   "Heat",
    "GRIQ": "Heat",
    "KEI":  "Kei",
    "KZNC": "Dolphins",
    "KZNI": "Tuskers",
    "KZN":  "Dolphins",
    "LIM":  "Impalas",
    "MPUM": "Rhinos",
    "NC":   "Heat",
    "NOR":  "Titans",
    "NW":   "Dragons",
    "SWD":  "Badgers",
    "WP":   "WP",
}

# ================== HELPERS ==================

def clean_date(date_str):
    """Convert CricketArchive date format to YYYY/MM/DD."""
    if not date_str:
        return ""
    date_part = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)
    try:
        return datetime.strptime(date_part.strip(), "%d %B %Y").strftime("%Y/%m/%d")
    except ValueError:
        return ""


def get_player_table(url):
    """Return the player listing table from a CricketArchive batting stats page."""
    r    = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    for table in soup.find_all("table"):
        if table.find("a", href=lambda x: x and "/Archive/Players/" in x):
            return table
    return None


def get_players(table):
    """
    Extract player names, profile URLs and team abbreviations from a player table.
    Returns list of (name, url, team_abbr) tuples.
    """
    players = []
    for row in table.find_all("tr")[1:]:
        link = row.find("a", href=lambda x: x and "/Archive/Players/" in x)
        if not link:
            continue
        name      = link.get_text(strip=True)
        url       = urljoin(BASE_URL, link["href"])
        text      = row.find("td").get_text(strip=True)
        m         = re.search(r"\((.*?)\)", text)
        team_abbr = m.group(1) if m else ""
        players.append((name, url, team_abbr))
    return players


def parse_player_profile(url):
    """
    Scrape a player profile page for biographical and playing style data.
    Returns (common_name, full_name, dob, batting, bowling, bowl_action).
    """
    for attempt in range(3):
        try:
            r    = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            common_name  = ""
            h2 = soup.find("h2")
            if h2:
                center      = h2.find("center")
                common_name = center.get_text(strip=True) if center else h2.get_text(strip=True)

            full_name = dob_raw = batting = bowling = bowl_action = ""

            table = soup.find("table")
            if table:
                for row in table.find_all("tr"):
                    cols = row.find_all("td")
                    if len(cols) < 2:
                        continue
                    key   = cols[0].get_text(strip=True).rstrip(":")
                    value = cols[1].get_text(strip=True)

                    if key == "Full name":    full_name = value
                    elif key == "Born":       dob_raw   = value.split(",")[0]
                    elif key == "Batting":    batting   = value
                    elif key == "Bowling":    bowling   = value
                    elif "wicket-keeper" in key.lower():
                        bowl_action = "WK"

            return common_name or full_name, full_name, clean_date(dob_raw), batting, bowling, bowl_action

        except Exception:
            if attempt == 2:
                return "", "", "", "", "", ""
            time.sleep(0.5)


def load_existing_combos(merged_path):
    """
    Load (Player, TeamName) pairs already present in the merged player file
    to avoid re-scraping profiles on incremental runs.
    """
    combos = set()
    if os.path.exists(merged_path):
        try:
            df = pd.read_csv(merged_path)
            for _, row in df.iterrows():
                p = str(row.get("Player",   "")).strip()
                t = str(row.get("TeamName", "")).strip()
                if p and t:
                    combos.add((p, t))
        except Exception:
            pass
    return combos


def get_competition_name(url):
    """Derive a file-safe competition name from the tournament URL."""
    try:
        return url.split("/")[-2].replace(" ", "_")
    except Exception:
        return "competition"


# ================== MAIN ==================

def main():
    if len(sys.argv) > 1:
        table_url = sys.argv[1]
    else:
        table_url = input("Enter batting table URL: ").strip()

    existing_combos = load_existing_combos(PLAYER_MERGED)
    comp_name       = get_competition_name(table_url)
    output_file     = os.path.join(PLAYER_DIR, f"{comp_name}.csv")

    player_table = get_player_table(table_url)
    if not player_table:
        print("No player table found.")
        return

    players = get_players(player_table)
    print(f"Found {len(players)} players\n")

    with open(output_file, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.writer(f_out)
        writer.writerow(["Player", "TeamName", "Batting", "Bowling", "DOB",
                         "Full Name", "Common Name", "Bowl Action"])

        for i, (name, url, team_abbr) in enumerate(players, 1):
            team_name = TEAM_MAP.get(team_abbr.strip().upper(), team_abbr.strip())
            print(f"[{i}/{len(players)}] {name} — {team_name}")

            if (name, team_name) in existing_combos:
                print("  Already in player master, skipping.")
                continue

            common_name, full_name, dob, batting, bowling, bowl_action = parse_player_profile(url)
            writer.writerow([name, team_name, batting, bowling, dob,
                             full_name, common_name or name, bowl_action])
            time.sleep(1.2)

    print(f"\nDone — saved to {output_file}")


if __name__ == "__main__":
    main()
