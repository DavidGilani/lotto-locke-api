import json
import os
import re
import gspread
from google.oauth2.service_account import Credentials
from supabase import create_client

# ============================================================
# CONFIG - fill these in
# ============================================================
GOOGLE_CREDENTIALS_FILE = r"C:\Users\David278\lotto-locke-api\credentials.json"
SPREADSHEET_ID = "1wFTVtQRksAue0_O_rwwppnb5bAYIB0F-4k2NC5D_ZkM"
SUPABASE_URL = "https://ihgpiyvgojghyvcejmqp.supabase.co"        # paste from Supabase dashboard
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImloZ3BpeXZnb2pnaHl2Y2VqbXFwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDgxMTcxMywiZXhwIjoyMDk2Mzg3NzEzfQ.ZXE3ujk0K7XgUhCDXN8MqThismYih281cbAdNcFR-jU"    # paste the service_role key

# ============================================================
# CONNECTIONS
# ============================================================
print("Connecting to Google Sheets...")
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=scopes)
gc = gspread.authorize(creds)
ss = gc.open_by_key(SPREADSHEET_ID)

print("Connecting to Supabase...")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def migrate_sheet(sheet_name, table_name, transform_fn, batch_size=100):
    print(f"Migrating {sheet_name} -> {table_name}...")
    try:
        sheet = ss.worksheet(sheet_name)
        rows = sheet.get_all_values()
    except Exception as e:
        print(f"  Skipping {sheet_name}: {e}")
        return
    if len(rows) < 2:
        print(f"  No data in {sheet_name}")
        return
    records = []
    for row in rows[1:]:
        try:
            record = transform_fn(row)
            if record:
                records.append(record)
        except Exception as e:
            print(f"  Skipping row {row}: {e}")
    if not records:
        print(f"  No valid records in {sheet_name}")
        return
    # Insert in batches
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        supabase.table(table_name).insert(batch).execute()
    print(f"  Inserted {len(records)} records")

def g(row, idx, default=""):
    return row[idx].strip() if idx < len(row) else default

# ============================================================
# TRAINERS
# ============================================================
migrate_sheet("Trainers", "trainers", lambda row: {
    "trainer": g(row, 0).lower(),
    "pin": g(row, 1),
    "version": g(row, 2) or "FireRed",
    "display_name": g(row, 3) or g(row, 0),
    "game_mode": g(row, 4) or "solo",
    "share_code": g(row, 5)
} if g(row, 0) else None)

# ============================================================
# JOURNEY RESULTS
# ============================================================
migrate_sheet("Journey Results", "journey_results", lambda row: {
    "trainer": g(row, 0).lower(),
    "section": g(row, 1),
    "spin_type": g(row, 2),
    "pokemon": g(row, 3),
    "version": g(row, 4)
} if g(row, 0) and g(row, 1) else None)

# ============================================================
# TRAINER CATCHES
# ============================================================
migrate_sheet("Trainer Catches", "trainer_catches", lambda row: {
    "trainer": g(row, 0).lower(),
    "route_id": g(row, 1),
    "pokemon": g(row, 2),
    "version": g(row, 3),
    "status": g(row, 4),
    "original_pokemon": g(row, 5),
    "trade_status": g(row, 6)
} if g(row, 0) and g(row, 1) and g(row, 2) else None)

# ============================================================
# PUNISHMENT RESULTS
# ============================================================
migrate_sheet("Punishment Results", "punishment_results", lambda row: {
    "trainer": g(row, 0).lower(),
    "punishment": g(row, 1),
    "full_text": g(row, 2),
    "duration": int(g(row, 3) or 1),
    "section_spun": g(row, 4),
    "expires_after_section": g(row, 5)
} if g(row, 0) and g(row, 1) else None)

# ============================================================
# BOSS BATTLE LOG
# ============================================================
migrate_sheet("Boss Battle Log", "boss_battle_log", lambda row: {
    "trainer": g(row, 0).lower(),
    "section": g(row, 1),
    "slot1": g(row, 2),
    "slot2": g(row, 3),
    "slot3": g(row, 4),
    "slot4": g(row, 5),
    "slot5": g(row, 6),
    "slot6": g(row, 7),
    "result": g(row, 8),
    "timestamp": g(row, 9)
} if g(row, 0) and g(row, 1) else None)

# ============================================================
# FRIENDS
# ============================================================
migrate_sheet("Friends", "friends", lambda row: {
    "requester": g(row, 0).lower(),
    "recipient": g(row, 1).lower(),
    "status": g(row, 2),
    "timestamp": g(row, 3)
} if g(row, 0) and g(row, 1) else None)

# ============================================================
# SECTIONS (static)
# ============================================================
print("Migrating Sections (with boss images from formulas)...")
try:
    sheet = ss.worksheet("Sections")
    rows = sheet.get_all_values()
    formulas = sheet.spreadsheet.values_get(
        "Sections!C2:C50",
        params={"valueRenderOption": "FORMULA"}
    ).get("values", [])
    records = []
    for i, row in enumerate(rows[1:]):
        if not row or not row[0]:
            continue
        boss_image = ""
        try:
            formula = formulas[i][0] if i < len(formulas) and formulas[i] else ""
            if formula and "http" in formula:
                m = re.search(r'"(https?://[^"]+)"', formula)
                if m:
                    boss_image = m.group(1)
        except Exception:
            pass
        if not boss_image and len(row) > 2:
            boss_image = row[2].strip()
        records.append({
            "short_name": row[0].strip(),
            "full_name": row[1].strip() if len(row) > 1 else "",
            "boss_image": boss_image,
            "level_cap": row[3].strip() if len(row) > 3 else ""
        })
    if records:
        supabase.table("sections").insert(records).execute()
        print(f"  Inserted {len(records)} sections")
except Exception as e:
    print(f"  Error migrating sections: {e}")

# ============================================================
# EVOLUTIONS (static)
# ============================================================
migrate_sheet("Evolutions", "evolutions", lambda row: {
    "base": g(row, 0),
    "evolved": g(row, 1),
    "stage3": g(row, 2)
} if g(row, 0) and g(row, 1) else None)

# ============================================================
# TRADES (static)
# ============================================================
migrate_sheet("Trades", "trades", lambda row: {
    "give": g(row, 0),
    "receive": g(row, 1),
    "version": g(row, 2) or "Both"
} if g(row, 0) and g(row, 1) else None)

# ============================================================
# BOSSES (static)
# ============================================================
migrate_sheet("Bosses", "bosses", lambda row: {
    "boss": g(row, 0),
    "slot1_name": g(row, 1), "slot1_level": g(row, 2),
    "slot2_name": g(row, 3), "slot2_level": g(row, 4),
    "slot3_name": g(row, 5), "slot3_level": g(row, 6),
    "slot4_name": g(row, 7), "slot4_level": g(row, 8),
    "slot5_name": g(row, 9), "slot5_level": g(row, 10),
    "slot6_name": g(row, 11), "slot6_level": g(row, 12),
    "version": g(row, 13) or "Both",
    "notes": g(row, 14)
} if g(row, 0) else None)

# ============================================================
# PUNISHMENTS (static)
# ============================================================
migrate_sheet("Punishments", "punishments", lambda row: {
    "name": g(row, 0),
    "image": "",
    "full_text": g(row, 2)
} if g(row, 0) else None)

# ============================================================
# MASTER ENCOUNTERS (static)
# ============================================================
migrate_sheet("Master Encounters", "master_encounters", lambda row: {
    "section": g(row, 0),
    "route": g(row, 2),
    "pokemon": g(row, 4),
    "version": g(row, 5) or "Both"
} if g(row, 0) and g(row, 4) else None)

# ============================================================
# WHEELS (static)
# ============================================================
migrate_sheet("Wheels", "wheels", lambda row: {
    "section": g(row, 0),
    "pokemon": g(row, 1),
    "version": g(row, 2) or "Both"
} if g(row, 0) and g(row, 1) else None)

# ============================================================
# POKEDEX (static)
# ============================================================
migrate_sheet("Pokedex", "pokedex", lambda row: {
    "name": g(row, 0),
    "image": "",
    "type1": g(row, 2).lower() or "normal"
} if g(row, 0) else None)

print("\nMigration complete!")