import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import random
from datetime import datetime

# ================== CONFIG ==================
COMPETITION_URLS = [
    "https://cricketarchive.com/Archive/Events/40/Hollywoodbets_Pro_20_2025-26.html",
    "https://cricketarchive.com/Archive/Events/40/Hollywoodbets_Pro_50_2025-26.html",
]

OUTPUT_PATH = r"D:\Docs\CSA API extract\partnerships_derived.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

# Innings are always in the 2nd and 4th tables (0-indexed: 1 and 3)
INNINGS_TABLE_INDICES = [1, 3]

session = requests.Session()
session.headers.update(HEADERS)


# ================== HELPERS ==================

def safe_get(url, tries=5):
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r
            elif r.status_code in [429, 403]:
                wait = 60 * (attempt + 1)
                print(f"  Blocked ({r.status_code}), waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  HTTP {r.status_code} for {url}")
        except Exception as e:
            print(f"  Retry {attempt + 1}/{tries} ({e})")
        time.sleep(random.uniform(3, 6))
    return None


def over_to_ball(over_str):
    """Convert '2.6' to sequential ball number e.g. 18"""
    try:
        parts = str(over_str).strip().split(".")
        overs = int(parts[0])
        balls = int(parts[1]) if len(parts) > 1 else 0
        return overs * 6 + balls
    except:
        return None


def name_matches(full_name, fow_name):
    """
    Match a FOW surname against a full scorecard name.
    FOW entries are always surnames only e.g. 'de Klerk', 'van Niekerk', 'Candler'.
    Full names are initialised surnames e.g. 'NC de Klerk', 'D van Niekerk', 'AC Candler'.
    Checks if the FOW name matches the suffix of the full name, which handles
    both simple and compound surnames naturally.
    """
    full_lower = full_name.lower().strip()
    fow_lower = fow_name.lower().strip()

    # Direct substring match — handles most simple cases
    if fow_lower in full_lower:
        return True

    # Suffix match — FOW name matches the end portion of the full name
    # e.g. 'de klerk' matches the last 2 words of 'nc de klerk'
    full_parts = full_lower.split()
    fow_parts = fow_lower.split()
    if len(fow_parts) <= len(full_parts) and full_parts[-len(fow_parts):] == fow_parts:
        return True

    # Hyphenated surname match e.g. 'viljoen-louw'
    for part in full_parts:
        if '-' in part and fow_lower in part:
            return True

    return False


def parse_date(soup):
    """Extract match date from page text."""
    date_pattern = re.search(
        r'on\s+(\d+(?:st|nd|rd|th)\s+\w+\s+\d{4})',
        soup.get_text()
    )
    if date_pattern:
        raw_date = date_pattern.group(1)
        try:
            clean = re.sub(r'(st|nd|rd|th)', '', raw_date)
            dt = datetime.strptime(clean.strip(), "%d %B %Y")
            return dt.strftime("%Y-%m-%d")
        except:
            return raw_date
    return None


def parse_competition(soup):
    """Extract competition name from page links."""
    for a in soup.find_all("a", href=True):
        if "/Archive/Events/" in a["href"]:
            return a.get_text(strip=True)
    return None


def parse_retirements(soup):
    """Extract retirement info from match notes."""
    retirement_notes = {}
    page_text = soup.get_text()
    for match in re.finditer(
        r'-->\s*([\w\s\-\.]+?)\s+retired hurt.*?'
        r'\((\d+\.\d+)\s+overs?\)'
        r'(?:.*?returned when.*?retired after\s+(\d+\.\d+)\s+overs?\))?',
        page_text, re.DOTALL
    ):
        player = match.group(1).strip()
        retired_over = match.group(2)
        returned_over = match.group(3) if match.group(3) else None
        retirement_notes[player] = {
            "retired_over": retired_over,
            "returned_over": returned_over
        }
        status = f"returned @ {returned_over}" if returned_over else "did not return"
        print(f"  Retirement: {player} @ {retired_over} overs ({status})")
    return retirement_notes


def get_innings_header_row(table):
    """
    Find the innings header row — identified by a td with colspan=2
    containing the word 'innings'. Works regardless of candyRowA/B alternation.
    """
    for row in table.find_all("tr"):
        td = row.find("td", attrs={"colspan": "2"})
        if td and "innings" in td.get_text().lower():
            return row
    return None


def parse_innings_table(table, match_id, innings_number):
    """
    Parse a single innings table, returning team name, batting order
    and fall of wickets.
    """
    header_row = get_innings_header_row(table)
    if not header_row:
        print(f"  FAILED: Match {match_id} innings {innings_number} — could not find innings header row")
        return None

    # Extract team name from the header row
    team_link = header_row.find("a")
    if team_link:
        team_name = team_link.get_text(strip=True)
    else:
        td = header_row.find("td", attrs={"colspan": "2"})
        team_name = re.sub(r'\s+innings.*', '', td.get_text(strip=True), flags=re.IGNORECASE).strip()

    if not team_name:
        print(f"  FAILED: Match {match_id} innings {innings_number} — could not extract team name")
        return None

    batting_order = []
    fall_of_wickets = []
    fow_found = False

    for row in table.find_all("tr"):
        # Skip the header row — without this the team name link was
        # being picked up as the first batter
        if row is header_row:
            continue

        row_text = row.get_text(" ", strip=True)

        if "Fall of wickets" in row_text:
            fow_found = True

        if fow_found:
            for fm in re.findall(
                r'(\d+)-(\d+)\s*\(([\w\s\.\-]+?),\s*([\d\.]+)\s*ov\)',
                row_text
            ):
                fall_of_wickets.append((
                    int(fm[0]),    # wicket number
                    int(fm[1]),    # runs at fall
                    fm[3],         # over string
                    fm[2].strip()  # dismissed player surname
                ))
            continue

        cols = row.find_all("td")
        if len(cols) < 2:
            continue

        name_tag = cols[0].find("a")
        if not name_tag:
            continue

        clean_name = re.sub(r'^[\*\+]+', '', name_tag.get_text(strip=True)).strip()
        dismissal = cols[1].get_text(strip=True).lower()

        if not clean_name or "did not bat" in dismissal:
            continue

        batting_order.append(clean_name)

    if not batting_order:
        print(f"  FAILED: Match {match_id} innings {innings_number} — no batting order found in table")
        return None

    return {
        "team": team_name,
        "batting_order": batting_order,
        "fall_of_wickets": fall_of_wickets,
    }


# ================== MATCH URL DISCOVERY ==================

def get_match_urls(tournament_url):
    resp = safe_get(tournament_url)
    if not resp:
        print(f"  Could not load: {tournament_url}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    matches = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/Scorecards/" in href and href.endswith(".html") and "commentary" not in href:
            full = href if href.startswith("http") else "https://cricketarchive.com" + href
            m = re.search(r'/(\d+)\.html$', href)
            if m:
                matches[m.group(1)] = full

    print(f"  Found {len(matches)} matches")
    return matches


# ================== SCORECARD PARSER ==================

def parse_scorecard(match_id, scorecard_url):
    resp = safe_get(scorecard_url)
    if not resp:
        print(f"  FAILED: Could not fetch scorecard for match {match_id}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    all_tables = soup.find_all("table")

    match_date = parse_date(soup)
    competition = parse_competition(soup)
    retirement_notes = parse_retirements(soup)

    if not match_date:
        print(f"  WARNING: Match {match_id} — could not parse match date")

    innings_list = []

    for inn_idx, table_idx in enumerate(INNINGS_TABLE_INDICES, 1):
        if table_idx >= len(all_tables):
            print(f"  FAILED: Match {match_id} innings {inn_idx} — table index {table_idx} not found "
                  f"(page has {len(all_tables)} tables)")
            continue

        innings_data = parse_innings_table(all_tables[table_idx], match_id, inn_idx)
        if not innings_data:
            continue

        innings_data.update({
            "match_id": match_id,
            "match_date": match_date,
            "competition": competition,
            "retirements": retirement_notes,
        })

        print(f"  Innings {inn_idx}: {innings_data['team']} | "
              f"{len(innings_data['batting_order'])} batters | "
              f"{len(innings_data['fall_of_wickets'])} wickets")

        innings_list.append(innings_data)

    return innings_list


# ================== PARTNERSHIP DERIVER ==================

def derive_partnerships(innings_data, innings_number):
    match_id = innings_data["match_id"]
    match_date = innings_data["match_date"]
    batting_team = innings_data["team"]
    batting_order = list(innings_data["batting_order"])
    fow = innings_data["fall_of_wickets"]
    retirements = innings_data["retirements"]

    if len(batting_order) < 2:
        print(f"  FAILED: Match {match_id} innings {innings_number} — "
              f"fewer than 2 batters, cannot derive partnerships")
        return []

    # Build retirement tracking keyed by batting order name
    retired_players = {}
    for ret_name, info in retirements.items():
        for batter in batting_order:
            if name_matches(batter, ret_name) or name_matches(ret_name, batter):
                retired_players[batter] = {
                    "retired_ball": over_to_ball(info["retired_over"]),
                    "returned_ball": over_to_ball(info["returned_over"]) if info["returned_over"] else None,
                    "has_retired": False,
                    "has_returned": False,
                }
                break

    partnerships = []
    partnership_no = 1
    start_ball = 1
    next_batter_idx = 2
    striker = batting_order[0]
    non_striker = batting_order[1]

    for wicket_no, runs_at, over_str, dismissed_name in fow:
        end_ball = over_to_ball(over_str)

        # Check for retirement before this wicket
        for player, ret_info in retired_players.items():
            if (not ret_info["has_retired"]
                    and ret_info["retired_ball"]
                    and end_ball >= ret_info["retired_ball"]):

                ret_ball = ret_info["retired_ball"]
                partnerships.append({
                    "match_id": match_id,
                    "match_date": match_date,
                    "batting_team": batting_team,
                    "innings": innings_number,
                    "partnership_no": partnership_no,
                    "partnership_key": f"{match_id}_{innings_number}_{partnership_no}",
                    "player1": striker,
                    "player2": non_striker,
                    "start_ball": start_ball,
                    "end_ball": ret_ball,
                    "end_over": ret_info["retired_ball"],
                    "dismissed": f"{player} retired hurt",
                })
                partnership_no += 1
                start_ball = ret_ball + 1
                ret_info["has_retired"] = True

                if player == striker and next_batter_idx < len(batting_order):
                    striker = batting_order[next_batter_idx]
                    next_batter_idx += 1
                elif player == non_striker and next_batter_idx < len(batting_order):
                    non_striker = batting_order[next_batter_idx]
                    next_batter_idx += 1

        # Record wicket partnership
        partnerships.append({
            "match_id": match_id,
            "match_date": match_date,
            "batting_team": batting_team,
            "innings": innings_number,
            "partnership_no": partnership_no,
            "partnership_key": f"{match_id}_{innings_number}_{partnership_no}",
            "player1": striker,
            "player2": non_striker,
            "start_ball": start_ball,
            "end_ball": end_ball,
            "end_over": over_str,
            "dismissed": dismissed_name,
        })

        partnership_no += 1
        start_ball = end_ball + 1

        # Check if a retired player returns
        for player, ret_info in retired_players.items():
            if (ret_info["returned_ball"]
                    and not ret_info["has_returned"]
                    and start_ball >= ret_info["returned_ball"]):
                batting_order.insert(next_batter_idx, player)
                ret_info["has_returned"] = True
                print(f"  {player} returns at ball {ret_info['returned_ball']}")

        # Identify dismissed batter and bring in next
        matched = False
        if name_matches(striker, dismissed_name):
            if next_batter_idx < len(batting_order):
                striker = batting_order[next_batter_idx]
                next_batter_idx += 1
            matched = True
        elif name_matches(non_striker, dismissed_name):
            if next_batter_idx < len(batting_order):
                non_striker = batting_order[next_batter_idx]
                next_batter_idx += 1
            matched = True

        if not matched:
            print(f"  WARNING: Could not match dismissed '{dismissed_name}' "
                  f"to striker '{striker}' or non-striker '{non_striker}' "
                  f"— match {match_id} innings {innings_number} wicket {wicket_no}")
            if next_batter_idx < len(batting_order):
                striker = batting_order[next_batter_idx]
                next_batter_idx += 1

    # Final (unbroken) partnership
    partnerships.append({
        "match_id": match_id,
        "match_date": match_date,
        "batting_team": batting_team,
        "innings": innings_number,
        "partnership_no": partnership_no,
        "partnership_key": f"{match_id}_{innings_number}_{partnership_no}",
        "player1": striker,
        "player2": non_striker,
        "start_ball": start_ball,
        "end_ball": None,
        "end_over": None,
        "dismissed": None,
    })

    return partnerships


# ================== MAIN ==================

def main():
    all_match_urls = {}
    for comp_url in COMPETITION_URLS:
        print(f"\nFetching matches from: {comp_url}")
        all_match_urls.update(get_match_urls(comp_url))
        time.sleep(random.uniform(2, 4))

    print(f"\nTotal unique matches: {len(all_match_urls)}")

    all_partnerships = []
    failed_matches = []

    for i, (match_id, scorecard_url) in enumerate(all_match_urls.items(), 1):
        print(f"\n[{i}/{len(all_match_urls)}] Match {match_id}")

        if i % 10 == 0:
            wait = random.uniform(25, 35)
            print(f"  Pausing {wait:.0f}s...")
            time.sleep(wait)

        innings_list = parse_scorecard(match_id, scorecard_url)

        if not innings_list:
            print(f"  FAILED: Match {match_id} — no innings parsed, queued for retry")
            failed_matches.append((match_id, scorecard_url))
            time.sleep(random.uniform(2, 4))
            continue

        for inn_idx, innings_data in enumerate(innings_list, 1):
            partnerships = derive_partnerships(innings_data, inn_idx)
            all_partnerships.extend(partnerships)
            print(f"  → {len(partnerships)} partnerships derived")

        time.sleep(random.uniform(1.5, 3))

    # Retry failed matches
    still_failed = []
    if failed_matches:
        print(f"\nRetrying {len(failed_matches)} failed matches after 60s pause...")
        time.sleep(60)
        for match_id, scorecard_url in failed_matches:
            print(f"  Retrying {match_id}...")
            innings_list = parse_scorecard(match_id, scorecard_url)
            if innings_list:
                for inn_idx, innings_data in enumerate(innings_list, 1):
                    partnerships = derive_partnerships(innings_data, inn_idx)
                    all_partnerships.extend(partnerships)
                    print(f"  → {len(partnerships)} partnerships derived")
            else:
                print(f"  FAILED again: Match {match_id} — skipping")
                still_failed.append(match_id)
            time.sleep(random.uniform(5, 10))

    if not all_partnerships:
        print("\nNo partnerships derived.")
        return

    df = pd.DataFrame(all_partnerships)

    # Drop duplicate final-partnership rows where player names repeat on same key
    df = df.drop_duplicates(
        subset=["match_id", "innings", "partnership_no", "player1", "player2"],
        keep="first"
    )

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8")

    print(f"\n{'=' * 50}")
    print(f"Saved {len(df)} partnerships to {OUTPUT_PATH}")
    print(f"Matches processed: {len(all_match_urls) - len(still_failed)}/{len(all_match_urls)}")
    if still_failed:
        print(f"Still failed after retry: {still_failed}")
    if not df.empty:
        print(f"Date range: {df['match_date'].min()} to {df['match_date'].max()}")
        print(f"Unique matches: {df['match_id'].nunique()}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
