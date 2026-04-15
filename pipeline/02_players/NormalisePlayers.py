import os
import re
import sys
import pandas as pd
from pathlib import Path
from config import PLAYER_DIR, PLAYER_DESC, PLAYER_MERGED

# ================== NAME HELPERS ==================

# South African compound surname prefixes
SURNAME_PREFIXES = {"van", "von", "de", "di", "du", "le", "la", "der", "den",
                    "st", "ter", "ten", "op", "janse", "jansen"}


def normalize_name(full_name):
    """
    Reduce a full name to initials + surname, preserving compound surnames.
    e.g. 'Courtney Leigh Gounden' → 'CL Gounden'
         'Nicole Clare de Klerk'  → 'NC de Klerk'
    """
    if pd.isna(full_name) or not str(full_name).strip():
        return ""
    name  = re.sub(r"\s+", " ", str(full_name).strip())
    name  = re.sub(r"\.+", "", name)
    name  = re.sub(r"[^\w\s-]", "", name)
    parts = name.split()
    if len(parts) <= 2:
        return name
    for length in range(min(4, len(parts)), 1, -1):
        tail = parts[-length:]
        if tail[0].lower() in SURNAME_PREFIXES:
            return f"{' '.join(parts[:-length])} {' '.join(tail)}".strip()
    return f"{parts[0]} {parts[-1]}"


def extract_surname(player_name):
    """
    Extract surname from an initialised player name, preserving compound surnames.
    e.g. 'NC de Klerk' → 'de Klerk', 'AC Candler' → 'Candler'
    """
    if pd.isna(player_name) or not str(player_name).strip():
        return ""
    parts = str(player_name).strip().split()
    if len(parts) <= 1:
        return player_name
    for length in range(3, 0, -1):
        if len(parts) >= length:
            tail = parts[-length:]
            if tail[0].lower() in SURNAME_PREFIXES:
                return " ".join(tail)
    return parts[-1]


# ================== ATTRIBUTE HELPERS ==================

def map_bat_hand(value):
    """Normalise batting hand to LH/RH."""
    if pd.isna(value):
        return ""
    s = str(value).lower()
    if "left"  in s: return "LH"
    if "right" in s: return "RH"
    return ""


def map_bowl_style(value):
    """Normalise bowling style description to a short label."""
    if pd.isna(value):
        return ""
    s = str(value).lower()
    if "off"                          in s: return "Off-Break"
    if "leg" in s or "googly"         in s: return "Leg-Break"
    if "slow left" in s or "orthodox" in s: return "Orthodox"
    if "medium"                        in s: return "Medium"
    if "fast"                          in s: return "Fast-Medium"
    return ""


def derive_bowl_arm(style):
    """Derive bowling arm from bowling style label."""
    if not style:
        return ""
    s = style.lower()
    if "left" in s and ("orthodox" in s or "arm" in s): return "LH"
    if any(k in s for k in ["off", "leg", "orthodox", "googly", "medium", "pace", "fast"]): return "RH"
    return ""


def derive_bowl_action(style):
    """Derive bowling action category (Spin/Pace/WK) from bowling style label."""
    if not style:
        return ""
    s = str(style).lower()
    if any(x in s for x in ["wicketkeeper", "wk", "keeper"]):        return "WK"
    if any(k in s for k in ["off-break", "leg-break", "orthodox",
                              "googly", "spin"]):                      return "Spin"
    if any(k in s for k in ["medium", "fast", "pace", "seam"]):       return "Pace"
    return ""


def detect_wicketkeeper(row):
    """Flag wicketkeepers based on Bowl Action or Bat Pos fields."""
    if str(row.get("Bowl Action", "")).strip().upper() == "WK": return "WK"
    if str(row.get("Bat Pos",     "")).strip().upper() == "WK": return "WK"
    return str(row.get("Bowl Action", "")).strip()


def first_non_empty(*values):
    """Return the first non-null, non-empty string from a list of candidates."""
    for v in values:
        if pd.notna(v) and str(v).strip():
            return str(v).strip()
    return ""


# ================== DUPLICATE DETECTION ==================

def is_pure_initials_only(full_name, player_name):
    """Return True if a player has no useful full name beyond their initials."""
    f, p = str(full_name or "").strip(), str(player_name or "").strip()
    return not f or f.upper() == p.upper() or len(f) <= 8


def surname_edit_distance(s1, s2):
    """Levenshtein distance between two surname strings for fuzzy matching."""
    s1, s2 = str(s1).lower().strip(), str(s2).lower().strip()
    if s1 == s2:
        return 0
    matrix = [[0] * (len(s2) + 1) for _ in range(len(s1) + 1)]
    for i in range(len(s1) + 1): matrix[i][0] = i
    for j in range(len(s2) + 1): matrix[0][j] = j
    for i in range(1, len(s1) + 1):
        for j in range(1, len(s2) + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            matrix[i][j] = min(matrix[i-1][j] + 1, matrix[i][j-1] + 1, matrix[i-1][j-1] + cost)
    return matrix[-1][-1]


# ================== LOAD EXTRACT FILES ==================

print("=== Player normalisation and merge ===\n")

df_desc = pd.read_csv(PLAYER_DESC)

extract_files = [
    f for f in os.listdir(PLAYER_DIR)
    if f.lower().endswith(".csv")
    and f != os.path.basename(PLAYER_DESC)
    and not any(x in f.lower() for x in ["merged", "combined", "result", "normalise", "output"])
]

df_extract_all = []
for fname in sorted(extract_files):
    df = pd.read_csv(Path(PLAYER_DIR) / fname)

    # Identify the team column regardless of its label
    team_col  = next((c for c in df.columns if c.lower() in
                      ["teamname", "team", "team name", "province", "side", "club"]), None)
    df["TeamName"] = df[team_col].astype(str).str.strip() if team_col else ""

    if "Batting Style" in df.columns:
        df["Bat Hand"]   = df["Batting Style"].apply(map_bat_hand)
    if "Bowling Style" in df.columns:
        df["Bowl Style"] = df["Bowling Style"].apply(map_bowl_style)

    keep = ["Player", "TeamName", "Bat Hand", "Bowl Style", "DOB",
            "Full Name", "Common Name", "Bowl Action"]
    df   = df[[c for c in keep if c in df.columns]]
    df["Player"] = df["Player"].astype(str).str.strip()
    df   = df[df["Player"].str.strip() != ""]
    df_extract_all.append(df)

df_extract = pd.concat(df_extract_all, ignore_index=True)
df_extract = df_extract.groupby(["Player", "TeamName"], as_index=False).first()

# ================== DUPLICATE REVIEW ==================
# Present likely duplicate players (same team, similar surname, one has no full name)
# for manual approval before merging.

print("=== Potential duplicates for review ===\n")
clusters = []
idx      = 0

for team, group in df_extract.groupby("TeamName"):
    group = group.copy()
    group["Normal Name"] = group["Full Name"].apply(normalize_name)

    for i, short_row in group.iterrows():
        if not is_pure_initials_only(short_row["Full Name"], short_row["Player"]):
            continue
        short_surname = short_row["Player"].split()[-1].lower()

        for j, long_row in group.iterrows():
            if i == j:
                continue
            long_surname = long_row["Player"].split()[-1].lower()
            dist         = surname_edit_distance(short_surname, long_surname)

            if dist <= 2 and len(long_row["Full Name"]) > len(short_row["Full Name"] or ""):
                idx += 1
                print(f"{idx:2d}. {short_row['Player']:20} ({short_row['Full Name'] or '—'})"
                      f"  →  {long_row['Player']} ({long_row['Full Name']})")
                print(f"    Team: {team}")
                clusters.append({"index": idx, "keep": long_row.name,
                                  "merge": short_row.name, "team": team})
                break

print("\nEnter your choice:")
print("  all     = apply all shown merges")
print("  none    = skip all")
print("  1,3,5   = apply only those numbers")

choice   = input("Choice: ").strip().lower()
approved = set()

if choice == "all":
    approved = set(range(1, idx + 1))
elif choice != "none":
    try:
        approved = {int(x.strip()) for x in choice.split(",")}
    except ValueError:
        approved = set()

for cluster in clusters:
    if cluster["index"] in approved:
        df_extract = df_extract.drop(index=cluster["merge"])

print(f"\nApplied {len(approved)} merges.\n")

# ================== MERGE WITH PLAYER DESC ==================

df_merged = pd.merge(df_extract, df_desc, on="Player", how="left", suffixes=("_ex", "_desc"))

df_merged["TeamName"] = df_merged.apply(
    lambda r: first_non_empty(r.get("TeamName_ex"), r.get("TeamName"), r.get("TeamName_desc")), axis=1
)

for col in ["Bat Hand", "Bowl Style", "DOB", "Full Name", "Bat Pos", "Bowl Action", "Bowl Arm"]:
    df_merged[col] = df_merged.apply(
        lambda r: first_non_empty(r.get(f"{col}_desc"), r.get(f"{col}_ex"), r.get(col)), axis=1
    )

df_merged["Bowl Arm"]    = df_merged.apply(lambda r: first_non_empty(r["Bowl Arm"],    derive_bowl_arm(r["Bowl Style"])),    axis=1)
df_merged["Bowl Action"] = df_merged.apply(lambda r: first_non_empty(r["Bowl Action"], derive_bowl_action(r["Bowl Style"])), axis=1)
df_merged["Bowl Action"] = df_merged.apply(detect_wicketkeeper, axis=1)
df_merged["Normal Name"] = df_merged["Full Name"].apply(normalize_name)

# ================== SAVE ==================

final_columns = ["Player", "Normal Name", "Full Name", "Common Name", "TeamName",
                 "Bat Hand", "Bat Pos", "Bowl Action", "Bowl Arm", "Bowl Style", "DOB"]

df_final          = df_merged.reindex(columns=final_columns, fill_value="").sort_values(["Player", "TeamName"])
df_final["Surname"] = df_final["Player"].apply(extract_surname)

output_path = Path(PLAYER_MERGED)
output_path.parent.mkdir(parents=True, exist_ok=True)
df_final.to_csv(output_path, index=False, encoding="utf-8-sig")

print(f"Saved {len(df_final)} rows to {output_path}")
print("\nMissing %:")
for col in final_columns:
    miss = (df_final[col] == "").mean() * 100
    print(f"  {col:15}  {miss:5.1f}%")
