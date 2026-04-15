import os
import sys
import re
import pandas as pd
from bs4 import BeautifulSoup
from config import CA_HTML_DIR, CA_CSV_DIR, PLAYER_MERGED

# ================== CONFIG ==================

season      = "2025-26"
comp_format = "Pro50"

if "--season" in sys.argv:
    season = sys.argv[sys.argv.index("--season") + 1]
if "--format" in sys.argv:
    comp_format = sys.argv[sys.argv.index("--format") + 1]

html_folder = os.path.join(CA_HTML_DIR, f"{comp_format} {season}")
csv_folder  = os.path.join(CA_CSV_DIR,  f"{comp_format} {season}")
os.makedirs(csv_folder, exist_ok=True)

player_master = pd.read_csv(PLAYER_MERGED)

# ================== FIXTURES LOOKUP ==================

# Locate the fixtures CSV saved by ballbyballextract.py
fixtures_path = next(
    (os.path.join(html_folder, f) for f in os.listdir(html_folder)
     if f.startswith("fixtures_") and f.endswith(".csv")),
    None
)

if not fixtures_path:
    print(f"ERROR: No fixtures_*.csv found in {html_folder}")
    sys.exit(1)

print(f"Using fixtures file: {os.path.basename(fixtures_path)}")

fixtures = pd.read_csv(fixtures_path)
fixtures_dict = {}
for _, row in fixtures.iterrows():
    match_id   = str(row.get("MatchID", "")).strip()
    match_text = str(row.get("Match",   "")).strip()
    if " v " in match_text:
        team_a, team_b = [t.strip() for t in match_text.split(" v ")]
        fixtures_dict[match_id] = (team_a, team_b)

print(f"Loaded {len(fixtures_dict)} matches from fixtures.\n")

# ================== HELPERS ==================

def extract_batting_team(soup):
    """Read batting team name from the innings header in commentary HTML."""
    center_tag = soup.find("center")
    if center_tag:
        text = center_tag.get_text(strip=True)
        if text.lower().endswith(" innings"):
            text = text[:-7].strip()
        return text
    return "Unknown"


def extract_dismissal(comment_text):
    """Derive method of dismissal from commentary text."""
    text = str(comment_text).lower()
    if "run out"                    in text: return "run out"
    if "lbw"                        in text: return "lbw"
    if re.search(r'\bst\b',  text):          return "stumped"
    if re.search(r'\bc\b',   text):          return "caught"
    if re.search(r'\bb\b',   text):          return "bowled"
    return ""


def clean_player_name(name):
    """Remove bracketed suffixes and strip whitespace from a player name."""
    if not name:
        return ""
    return re.sub(r"\(.*?\)", "", str(name)).strip()


def split_runs(runs_text):
    """
    Split a runs cell into runs off bat (int) and extras description (str).
    Cells may contain values like '1' or '1; wide'.
    """
    runs_off_bat = 0
    extras       = ""
    for part in str(runs_text).strip().split(";"):
        part = part.strip()
        if re.search(r"[a-zA-Z]", part):
            extras = f"{extras}; {part}" if extras else part
        else:
            try:
                runs_off_bat = int(part)
            except ValueError:
                pass
    return runs_off_bat, extras


def resolve_player(raw_name, team):
    """
    Attempt to match a raw player name from commentary against the player master.
    Falls back to the raw name if no match is found.
    """
    if not raw_name:
        return raw_name
    raw   = clean_player_name(raw_name)
    match = player_master[
        ((player_master["Player"].str.strip()      == raw) |
         (player_master["Common Name"].str.strip() == raw) |
         (player_master["Normal Name"].str.strip() == raw)) &
        (player_master["TeamName"].str.strip()     == team)
    ]
    return match.iloc[0]["Player"] if not match.empty else raw


# ================== PARSE HTML FILES ==================

matches_data = {}

for file in os.listdir(html_folder):
    if not file.endswith(".html"):
        continue

    m = re.match(r"match_(\d+)_i(\d+)\.html", file)
    if not m:
        continue

    match_id = m.group(1)
    innings  = int(m.group(2))

    with open(os.path.join(html_folder, file), "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    batting_team  = extract_batting_team(soup)
    fielding_team = "Unknown"

    if match_id in fixtures_dict:
        team_a, team_b = fixtures_dict[match_id]
        fielding_team  = team_b if batting_team == team_a else team_a

    rows_data = []

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cols = [td.get_text(strip=True) for td in tr.find_all("td")]
            if not cols:
                continue

            # Skip header row
            if len(cols) >= 4 and cols[0].lower() == "over":
                continue

            # Delivery row — first column is a numeric over number
            if len(cols) >= 4 and re.match(r"^\d+$", cols[0]):
                over      = cols[0]
                ball      = cols[1]
                bowler, batter = "", ""

                if " to " in cols[3]:
                    parts  = cols[3].split(" to ")
                    bowler = clean_player_name(parts[0])
                    batter = clean_player_name(parts[1])
                else:
                    batter = clean_player_name(cols[3])

                runs_off_bat, extras = split_runs(cols[2])

                rows_data.append({
                    "MatchID":           match_id,
                    "Innings":           innings,
                    "BattingTeam":       batting_team,
                    "FieldingTeam":      fielding_team,
                    "Over":              over,
                    "Ball":              ball,
                    "Batter":            resolve_player(batter, batting_team),
                    "Bowler":            resolve_player(bowler, fielding_team),
                    "RunsOffBat":        runs_off_bat,
                    "Extras":            extras,
                    "Wicket":            False,
                    "Comment":           "",
                    "MethodOfDismissal": "",
                    "Season":            season,
                })

            # Commentary row following a delivery — append to the last delivery
            elif rows_data and cols:
                comment_text                          = " ".join(cols)
                rows_data[-1]["Wicket"]               = True
                rows_data[-1]["Comment"]              = comment_text
                rows_data[-1]["MethodOfDismissal"]    = extract_dismissal(comment_text)

    if rows_data:
        df = pd.DataFrame(rows_data)
        if match_id in matches_data:
            matches_data[match_id] = pd.concat([matches_data[match_id], df], ignore_index=True)
        else:
            matches_data[match_id] = df

# ================== SAVE ==================

for match_id, df in matches_data.items():
    csv_file = os.path.join(csv_folder, f"match_{match_id}.csv")
    df.to_csv(csv_file, index=False, encoding="utf-8")
    print(f"Saved: {csv_file}")

print("\nDone.")
