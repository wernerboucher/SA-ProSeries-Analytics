import os
import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from config import COMPS_CSV, BBB_HTML_DIR, BBB_CSV_DIR

# ================== HELPERS ==================

def clean_name(name):
    """Strip team abbreviations in parentheses from player names."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def extract_runs(text):
    """Parse runs off bat from delivery description text."""
    text = text.lower()
    if "six" in text:
        return 6
    if "four" in text:
        return 4
    m = re.search(r"(\d+)\s*run", text)
    return int(m.group(1)) if m else 0


def extract_extras(text):
    """Parse extras value from delivery description text."""
    text = text.lower()
    if any(k in text for k in ["wide", "no ball", "bye", "leg bye"]):
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else 1
    return 0


def parse_innings_lookup(summary):
    """
    Build a team → innings label lookup from a match summary dict.
    Returns e.g. {'Western Province Women': '1st', 'Dolphins': '2nd'}.
    """
    lookup = {}
    if not isinstance(summary, dict):
        return lookup
    inns = summary.get("innings", [])
    for i, inn in enumerate(inns[:2]):
        team = inn.get("teamName", "")
        if team:
            lookup[team] = "1st" if i == 0 else "2nd"
    return lookup


def parse_result(summary):
    """Derive match result string from summary dict."""
    if isinstance(summary, str):
        return summary
    if not isinstance(summary, dict):
        return ""
    inns = summary.get("innings", [])
    if len(inns) < 2:
        return ""
    try:
        r1, r2 = int(inns[0].get("score", 0)), int(inns[1].get("score", 0))
        t1, t2 = inns[0].get("teamName", ""), inns[1].get("teamName", "")
        if r2 > r1:
            return f"{t2} won"
        if r1 > r2:
            return f"{t1} won"
        return "Tie"
    except:
        return ""


# ================== MAIN ==================

os.makedirs(BBB_CSV_DIR, exist_ok=True)

config = pd.read_csv(COMPS_CSV)

print("START")

with sync_playwright() as p:
    browser = p.firefox.launch(headless=False, slow_mo=500)
    page = browser.new_page()

    for _, comp in config.iterrows():
        cid   = str(comp["CompID"])
        cname = comp["CompetitionName"]
        season = comp["Season"]
        fmt   = comp["Format"]

        html_dir = os.path.join(BBB_HTML_DIR, cid)
        os.makedirs(html_dir, exist_ok=True)

        csv_path = os.path.join(BBB_CSV_DIR, f"BallByBall_{cid}_{fmt}_{season}.csv")

        print(f"\nCompetition: {cname}")

        # ================== FETCH MATCH LIST ==================

        url  = (f"https://api-tms.cricketpvcms.co.za/api/v1/"
                f"competitions/{cid}/schedule?group_by=date&include_summary=true")
        data = requests.get(url, timeout=20).json()

        match_ids      = []
        match_info     = {}
        innings_lookup = {}

        for group in data.get("data", {}).values():
            for m in group:
                mid = str(m.get("id"))
                match_ids.append(mid)
                innings_lookup[mid] = parse_innings_lookup(m.get("summary"))

                info = {"Date": "", "Team1": "", "Team2": "", "Venue": "",
                        "Result": parse_result(m.get("summary")), "Toss": ""}

                for s in m.get("match_settings", []):
                    key = s.get("key")
                    d   = s.get("data") if isinstance(s.get("data"), dict) else {}
                    if key == "match_date":   info["Date"]  = s.get("value", "")
                    elif key == "home_team":  info["Team1"] = d.get("team_name", "")
                    elif key == "away_team":  info["Team2"] = d.get("team_name", "")
                    elif key == "venue":      info["Venue"] = d.get("field_name", "")
                    elif key == "toss":       info["Toss"]  = s.get("display_name", "")

                match_info[mid] = info

        # ================== SCRAPE + PARSE ==================

        rows_out = []

        for mid in match_ids:
            info   = match_info[mid]
            lookup = innings_lookup.get(mid, {})
            html_path = os.path.join(html_dir, f"{mid}.html")

            # Download the ball-by-ball page if not already cached
            if not os.path.exists(html_path):
                url = (f"https://cricketpvcms.co.za/tournaments/completed/{cid}/{mid}")
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    time.sleep(4)
                    page.get_by_role("tab", name="Ball by Ball").click()
                    time.sleep(5)
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(page.content())
                except Exception:
                    print(f"  FAILED to download match {mid}")
                    continue

            with open(html_path, encoding="utf-8") as f:
                soup = BeautifulSoup(f, "lxml")

            deliveries   = list(reversed(soup.find_all("div", class_=re.compile("delivery-row"))))
            innings      = ""
            batting      = ""
            last_header  = None
            current_over = None
            ball_count   = 0

            for r in deliveries:

                # Detect innings header text to track which team is batting
                header = r.find_previous(string=re.compile(r"(1st|2nd)\s+innings:", re.I))
                if header and header != last_header:
                    last_header = header
                    m = re.search(r"(1st|2nd)\s+innings:\s*(.+)", header.strip(), re.I)
                    if m:
                        innings = m.group(1)
                        batting = m.group(2)

                ball_elem    = r.find(class_=re.compile("ball-number"))
                players_elem = r.find(class_=re.compile("players"))
                desc_elem    = r.find(class_=re.compile("description"))

                ball    = ball_elem.get_text(strip=True)    if ball_elem    else ""
                players = players_elem.get_text(strip=True) if players_elem else ""
                desc    = desc_elem.get_text(strip=True)    if desc_elem    else ""

                bowler, batter = "", ""
                if " to " in players:
                    a, b   = players.split(" to ", 1)
                    bowler = clean_name(a)
                    batter = clean_name(b)

                over, ballnum = ("", "")
                if "." in ball:
                    over, ballnum = ball.split(".")

                if over != current_over:
                    current_over = over
                    ball_count   = 1
                else:
                    ball_count  += 1

                runs    = extract_runs(desc)
                extras  = extract_extras(desc)
                desc_lc = desc.lower()

                extra_raw = ("wd" if "wide"     in desc_lc else
                             "nb" if "no ball"  in desc_lc else
                             "lb" if "leg bye"  in desc_lc else
                             "b"  if "bye"      in desc_lc else "")

                rows_out.append({
                    "MatchID":         mid,
                    "Date":            info["Date"],
                    "Team1":           info["Team1"],
                    "Team2":           info["Team2"],
                    "BattingTeam":     batting,
                    "Innings":         lookup.get(batting, ""),
                    "Result":          info["Result"],
                    "Venue":           info["Venue"],
                    "Toss":            info["Toss"],
                    "Over":            over,
                    "BallNumber":      ballnum,
                    "BallCountOver":   ball_count,
                    "Batter":          batter,
                    "Bowler":          bowler,
                    "Description":     desc,
                    "RunsOffBat":      runs,
                    "Extras":          extras,
                    "TotalRuns":       runs + extras,
                    "IsWicket":        1 if "out" in desc_lc else 0,
                    "BowlerWicket":    1 if "out" in desc_lc and "run out" not in desc_lc else 0,
                    "ExtrasRaw":       extra_raw,
                    "Season":          season,
                    "Format":          fmt,
                    "CompetitionID":   cid,
                    "CompetitionName": cname,
                })

        pd.DataFrame(rows_out).to_csv(csv_path, index=False, encoding="utf-8")
        print(f"  Saved {len(rows_out)} deliveries to {csv_path}")

    browser.close()

print("\nDONE")
