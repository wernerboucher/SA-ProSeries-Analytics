import os

# ================== BASE PATH ==================
# Update BASE_DIR to match your local setup.
# All other paths are derived from it.

BASE_DIR = r"D:\Docs"

# ================== CSA TMS ==================

COMPS_MASTER_CSV = os.path.join(BASE_DIR, "CricketSA extracts", "competitions_master.csv")
COMPS_CSV        = os.path.join(BASE_DIR, "CricketSA extracts", "competitions.csv")
BBB_HTML_DIR     = os.path.join(BASE_DIR, "CricketSA extracts", "htmls")
BBB_CSV_DIR      = os.path.join(BASE_DIR, "CricketSA extracts", "extracted_csvs")

# ================== CRICKETARCHIVE ==================

CA_HTML_DIR      = os.path.join(BASE_DIR, "ball by ball htmls")
CA_CSV_DIR       = os.path.join(BASE_DIR, "ball by ball csvs")

# ================== PLAYERS ==================

PLAYER_DIR       = os.path.join(BASE_DIR, "Player Details")
PLAYER_DESC      = os.path.join(BASE_DIR, "Player Details", "PlayerDesc.csv")
PLAYER_MERGED    = os.path.join(BASE_DIR, "Player Details", "Result", "Merged_Player_Data.csv")

# ================== PARTNERSHIPS ==================

PARTNERSHIPS_CSV = os.path.join(BASE_DIR, "CSA API extract", "partnerships_derived.csv")
