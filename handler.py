import json
import os
import random
import math
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

SPREADSHEET_ID = "1wFTVtQRksAue0_O_rwwppnb5bAYIB0F-4k2NC5D_ZkM"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheet_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
    else:
        with open("credentials.json") as f:
            creds_dict = json.load(f)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def get_sheet(name):
    ss = get_sheet_client()
    return ss.worksheet(name)

def get_or_create_sheet(ss, name, headers):
    try:
        return ss.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        sheet = ss.add_worksheet(title=name, rows=1000, cols=20)
        sheet.append_row(headers)
        return sheet

# ============================================================
# HELPERS
# ============================================================

def ok(data):
    return json.dumps(data)

def err(message):
    return json.dumps({"error": message})

def rows_to_dicts(rows):
    if len(rows) < 2:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]

# ============================================================
# TRAINER FUNCTIONS
# ============================================================

def create_trainer(body):
    try:
        trainer_name = body.get("trainerName", "").strip()
        pin = str(body.get("pin", "")).strip()
        version = body.get("version", "FireRed").strip()
        game_mode = body.get("gameMode", "solo").strip()

        if not trainer_name:
            return err("Please enter a trainer name.")
        if not pin or len(pin) < 4:
            return err("Please enter a PIN of at least 4 digits.")

        name = trainer_name.lower()
        display_name = trainer_name
        valid_versions = ["FireRed", "LeafGreen"]
        game_version = version if version in valid_versions else "FireRed"
        mode = "2player" if game_mode == "2player" else "solo"

        ss = get_sheet_client()

        journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        journey_data = journey_sheet.get_all_values()
        if any(row[0].strip().lower() == name for row in journey_data[1:] if row):
            return err(f"Trainer '{display_name}' already exists! Choose a different name or resume your adventure.")

        catches_sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        catches_data = catches_sheet.get_all_values()
        if any(row[0].strip().lower() == name for row in catches_data[1:] if row):
            return err(f"Trainer '{display_name}' already exists! Please resume your adventure.")

        trainers_sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        share_code = str(random.randint(100000, 999999))
        trainers_sheet.append_row([name, pin, game_version, display_name, mode, share_code])

        return ok({"success": True, "trainerName": name, "displayName": display_name,
                   "version": game_version, "gameMode": mode, "shareCode": share_code})
    except Exception as e:
        return err(str(e))

def load_trainer(body):
    try:
        trainer_name = body.get("trainerName", "").strip()
        pin = str(body.get("pin", "")).strip()

        if not trainer_name:
            return err("Please enter a trainer name.")
        if not pin:
            return err("Please enter your PIN.")

        name = trainer_name.lower()
        ss = get_sheet_client()

        trainers_sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        trainer_data = trainers_sheet.get_all_values()
        trainer_row = None
        for row in trainer_data[1:]:
            if row and row[0].strip().lower() == name:
                trainer_row = row
                break

        if not trainer_row:
            return err(f"Trainer '{trainer_name}' not found. Please start a new adventure.")

        if pin != "__skip_pin__" and trainer_row[1].strip() != pin:
            return err("Incorrect PIN. Please try again.")

        game_version = trainer_row[2].strip() if len(trainer_row) > 2 else "FireRed"
        display_name = trainer_row[3].strip() if len(trainer_row) > 3 else trainer_name
        game_mode = trainer_row[4].strip() if len(trainer_row) > 4 else "solo"
        share_code = trainer_row[5].strip() if len(trainer_row) > 5 else ""

        if not share_code:
            share_code = str(random.randint(100000, 999999))
            row_idx = trainer_data.index(trainer_row) + 1
            trainers_sheet.update_cell(row_idx + 1, 6, share_code)

        journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        journey_data = journey_sheet.get_all_values()
        trainer_journey = [
            {"section": r[1].strip(), "spinType": r[2].strip(), "pokemon": r[3].strip(), "version": r[4].strip()}
            for r in journey_data[1:] if r and r[0].strip().lower() == name
        ]

        catches_sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        catches_data = catches_sheet.get_all_values()
        trainer_catches = [
            {
                "route": r[1].strip(),
                "name": r[2].strip(),
                "version": r[3].strip() if len(r) > 3 else "",
                "fainted": r[4].strip().lower() == "fainted" if len(r) > 4 else False,
                "originalName": r[5].strip() if len(r) > 5 else "",
                "traded": r[6].strip().lower() == "traded" if len(r) > 6 else False
            }
            for r in catches_data[1:] if r and r[0].strip().lower() == name
        ]

        pun_sheet = get_or_create_sheet(ss, "Punishment Results", ["Trainer","Punishment","FullText","Duration","SectionSpun","ExpiresAfterSection"])
        pun_data = pun_sheet.get_all_values()
        trainer_punishments = [
            {
                "punishment": r[1].strip(),
                "fullText": r[2].strip() if len(r) > 2 else "",
                "duration": int(r[3]) if len(r) > 3 and r[3].strip().isdigit() else 1,
                "sectionSpun": r[4].strip() if len(r) > 4 else "",
                "expiresAfterSection": r[5].strip() if len(r) > 5 else ""
            }
            for r in pun_data[1:] if r and r[0].strip().lower() == name
        ]

        pending_requests = []
        friends = []
        try:
            friends_sheet = get_or_create_sheet(ss, "Friends", ["Requester","Recipient","Status","Timestamp"])
            friends_data = friends_sheet.get_all_values()
            for r in friends_data[1:]:
                if not r or len(r) < 3:
                    continue
                requester = r[0].strip().lower()
                recipient = r[1].strip().lower()
                status = r[2].strip()
                if recipient == name and status == "pending":
                    pending_requests.append({"from": requester, "timestamp": r[3] if len(r) > 3 else ""})
                if status == "accepted" and (requester == name or recipient == name):
                    friend_name = recipient if requester == name else requester
                    if friend_name not in friends:
                        friends.append(friend_name)
        except Exception:
            pass

        return ok({
            "success": True,
            "trainerName": name,
            "displayName": display_name,
            "version": game_version,
            "gameMode": game_mode,
            "shareCode": share_code,
            "journeyResults": trainer_journey,
            "catches": trainer_catches,
            "punishments": trainer_punishments,
            "pendingRequests": pending_requests,
            "friends": friends
        })
    except Exception as e:
        return err(str(e))

def save_game_mode(body):
    try:
        name = body.get("trainerName", "").strip().lower()
        game_mode = body.get("gameMode", "solo").strip()
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        data = sheet.get_all_values()
        for i, row in enumerate(data[1:], start=2):
            if row and row[0].strip().lower() == name:
                sheet.update_cell(i, 5, game_mode)
                return ok({"success": True})
        return err("Trainer not found")
    except Exception as e:
        return err(str(e))

# ============================================================
# SECTION / ENCOUNTER / EVOLUTION DATA
# ============================================================

def get_section_data(params):
    try:
        ss = get_sheet_client()
        sheet = ss.worksheet("Sections")
        data = sheet.get_all_values()
        result = []
        for row in data[1:]:
            if not row or not row[0]:
                continue
            result.append({
                "shortName": row[0].strip(),
                "fullName": row[1].strip() if len(row) > 1 else "",
                "bossImage": row[2].strip() if len(row) > 2 else "",
                "levelCap": row[3].strip() if len(row) > 3 else ""
            })
        return ok(result)
    except Exception as e:
        return err(str(e))

def get_encounter_data(params):
    try:
        version = params.get("version", ["FireRed"])[0]
        ss = get_sheet_client()
        sheet = ss.worksheet("Master Encounters")
        data = sheet.get_all_values()
        structured = []
        current_section = None
        for row in data[1:]:
            if not row or not row[0]:
                continue
            section_name = row[0].strip()
            route_name = row[2].strip() if len(row) > 2 else ""
            pkmn_name = row[4].strip() if len(row) > 4 else ""
            game_val = row[5].strip() if len(row) > 5 else ""
            if game_val not in ["Both", version]:
                continue
            if not pkmn_name:
                continue
            if not current_section or current_section["name"] != section_name:
                current_section = {"name": section_name, "routes": []}
                structured.append(current_section)
            route_entry = next((r for r in current_section["routes"] if r["name"] == route_name), None)
            if not route_entry:
                route_entry = {"name": route_name, "pokemon": []}
                current_section["routes"].append(route_entry)
            route_entry["pokemon"].append(pkmn_name)
        return ok(structured)
    except Exception as e:
        return err(str(e))

def get_evolution_data(params):
    try:
        ss = get_sheet_client()
        sheet = ss.worksheet("Evolutions")
        data = sheet.get_all_values()
        evo_map = {}
        for row in data[1:]:
            if not row or not row[0]:
                continue
            base = row[0].strip()
            evolved = row[1].strip() if len(row) > 1 else ""
            if not base or not evolved:
                continue
            evo_map.setdefault(base, [])
            evo_map.setdefault(evolved, [])
            if evolved not in evo_map[base]:
                evo_map[base].append(evolved)
            if base not in evo_map[evolved]:
                evo_map[evolved].append(base)
        return ok(evo_map)
    except Exception as e:
        return err(str(e))

def get_full_evolution_map(params):
    try:
        ss = get_sheet_client()
        sheet = ss.worksheet("Evolutions")
        data = sheet.get_all_values()
        next_evo_map = {}
        for row in data[1:]:
            if not row or not row[0]:
                continue
            s1 = row[0].strip()
            s2 = row[1].strip() if len(row) > 1 else ""
            s3 = row[2].strip() if len(row) > 2 else ""
            if not s1:
                continue
            if s2:
                next_evo_map.setdefault(s1, [])
                if s2 not in next_evo_map[s1]:
                    next_evo_map[s1].append(s2)
            if s2 and s3:
                next_evo_map.setdefault(s2, [])
                if s3 not in next_evo_map[s2]:
                    next_evo_map[s2].append(s3)
        return ok(next_evo_map)
    except Exception as e:
        return err(str(e))

def get_trade_data(params):
    try:
        version = params.get("version", ["FireRed"])[0]
        ss = get_sheet_client()
        sheet = ss.worksheet("Trades")
        data = sheet.get_all_values()
        trades = []
        for row in data[1:]:
            if not row or not row[0]:
                continue
            give = row[0].strip()
            receive = row[1].strip() if len(row) > 1 else ""
            ver = row[2].strip() if len(row) > 2 else "Both"
            if not give or not receive:
                continue
            if ver in ["Both", version]:
                trades.append({"give": give, "receive": receive, "version": ver})
        return ok(trades)
    except Exception as e:
        return err(str(e))

# ============================================================
# WHEEL DATA
# ============================================================

def get_journey_wheel_data(params):
    try:
        section_name = params.get("sectionName", [""])[0]
        spin_type = params.get("spinType", [""])[0]
        version = params.get("version", ["FireRed"])[0]
        trainer_name = params.get("trainerName", [""])[0].lower()

        ss = get_sheet_client()
        wheel_sheet = ss.worksheet("Wheels")
        wheel_data = wheel_sheet.get_all_values()

        section_pokemon = [
            row[1].strip() for row in wheel_data[1:]
            if row and row[0].strip() == section_name and row[2].strip() in ["Both", version]
        ]

        journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        journey_data = journey_sheet.get_all_values()
        spun_for_section = [
            r[3].strip() for r in journey_data[1:]
            if r and r[0].strip().lower() == trainer_name
            and r[1].strip() == section_name
            and r[2].strip() in ["Mandate", "Exclude"]
        ]

        available = [p for p in section_pokemon if p not in spun_for_section]
        list_to_use = available if available else section_pokemon
        random.shuffle(list_to_use)

        pokedex_sheet = ss.worksheet("Pokedex")
        pokedex_data = pokedex_sheet.get_all_values()
        dex_map = {row[0].strip(): row[2].strip().lower() if len(row) > 2 else "normal" for row in pokedex_data[1:] if row}

        wheel_items = [{"name": p, "image": "", "type": dex_map.get(p, "normal"), "weight": 1} for p in list_to_use]

        return ok({"wheelData": wheel_items, "currentGame": version, "targetRow": 0, "sectionName": section_name, "spinType": spin_type})
    except Exception as e:
        return err(str(e))

def get_elite4_wheel_data(params):
    try:
        version = params.get("version", ["FireRed"])[0]
        trainer_name = params.get("trainerName", [""])[0].lower()

        ss = get_sheet_client()
        wheel_sheet = ss.worksheet("Wheels")
        wheel_data = wheel_sheet.get_all_values()

        section_pokemon = [
            row[1].strip() for row in wheel_data[1:]
            if row and row[0].strip() == "Indigo Plateau" and row[2].strip() in ["Both", version]
        ]

        journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        journey_data = journey_sheet.get_all_values()
        excluded = [r[3].strip() for r in journey_data[1:] if r and r[0].strip().lower() == trainer_name and r[2].strip() == "Exclude"]

        catches_sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        catches_data = catches_sheet.get_all_values()
        caught = [r[2].strip() for r in catches_data[1:] if r and r[0].strip().lower() == trainer_name]

        available = [p for p in section_pokemon if p not in excluded and p not in caught]
        if not available:
            return ok({"noNewPokemon": True})

        pokedex_sheet = ss.worksheet("Pokedex")
        pokedex_data = pokedex_sheet.get_all_values()
        dex_map = {row[0].strip(): row[2].strip().lower() if len(row) > 2 else "normal" for row in pokedex_data[1:] if row}

        random.shuffle(available)
        wheel_items = [{"name": p, "image": "", "type": dex_map.get(p, "normal"), "weight": 1} for p in available]

        return ok({"wheelData": wheel_items, "currentGame": version, "targetRow": 0, "sectionName": "Indigo Plateau", "spinType": ""})
    except Exception as e:
        return err(str(e))

def get_2player_picks(params):
    try:
        section_name = params.get("sectionName", [""])[0]
        version = params.get("version", ["FireRed"])[0]
        trainer_name = params.get("trainerName", [""])[0].lower()

        ss = get_sheet_client()
        wheel_sheet = ss.worksheet("Wheels")
        wheel_data = wheel_sheet.get_all_values()

        section_pokemon = [
            row[1].strip() for row in wheel_data[1:]
            if row and row[0].strip() == section_name and row[2].strip() in ["Both", version]
        ]

        if section_name == "Indigo Plateau":
            journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
            journey_data = journey_sheet.get_all_values()
            excluded = [r[3].strip() for r in journey_data[1:] if r and r[0].strip().lower() == trainer_name and r[2].strip() == "Exclude"]
            catches_sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
            catches_data = catches_sheet.get_all_values()
            caught = [r[2].strip() for r in catches_data[1:] if r and r[0].strip().lower() == trainer_name]
            section_pokemon = [p for p in section_pokemon if p not in excluded and p not in caught]
            if not section_pokemon:
                return ok({"noNewPokemon": True})

        pokedex_sheet = ss.worksheet("Pokedex")
        pokedex_data = pokedex_sheet.get_all_values()
        dex_map = {row[0].strip(): row[2].strip().lower() if len(row) > 2 else "normal" for row in pokedex_data[1:] if row}

        random.shuffle(section_pokemon)
        picks = section_pokemon[:min(3, len(section_pokemon))]

        return ok({"picks": [{"name": p, "type": dex_map.get(p, "normal")} for p in picks], "sectionName": section_name})
    except Exception as e:
        return err(str(e))

def get_punishment_data(params):
    try:
        trainer_name = params.get("trainerName", [""])[0].lower()
        ss = get_sheet_client()
        sheet = ss.worksheet("Punishments")
        data = sheet.get_all_values()

        active_names = []
        if trainer_name:
            pun_sheet = get_or_create_sheet(ss, "Punishment Results", ["Trainer","Punishment","FullText","Duration","SectionSpun","ExpiresAfterSection"])
            pun_data = pun_sheet.get_all_values()
            active_names = [r[1].strip() for r in pun_data[1:] if r and r[0].strip().lower() == trainer_name]

        formatted = []
        for row in data[1:]:
            if not row or not row[0]:
                continue
            name = row[0].strip()
            if name in active_names:
                continue
            full_text = row[2].strip() if len(row) > 2 else ""
            formatted.append({
                "name": name,
                "image": "",
                "fullText": full_text,
                "weight": random.randint(1, 3),
                "type": "normal"
            })

        if not formatted:
            return ok([{"name": "No Punishments", "image": "", "fullText": "No punishments available", "weight": 1, "type": "normal"}])

        random.shuffle(formatted)
        return ok(formatted)
    except Exception as e:
        return err(str(e))

# ============================================================
# BOSS DATA
# ============================================================

def get_boss_data(params):
    try:
        section_name = params.get("sectionName", [""])[0]
        version = params.get("version", ["FireRed"])[0]
        ss = get_sheet_client()
        sheet = ss.worksheet("Bosses")
        data = sheet.get_all_values()

        def build_boss_entry(row):
            team = []
            for slot in range(6):
                pkmn = row[1 + slot * 2].strip() if len(row) > 1 + slot * 2 else ""
                level = row[2 + slot * 2].strip() if len(row) > 2 + slot * 2 else ""
                if pkmn:
                    team.append({"name": pkmn, "level": level})
            return {
                "boss": row[0].strip() if row else "",
                "team": team,
                "notes": row[14].strip() if len(row) > 14 else "",
                "version": row[13].strip() if len(row) > 13 else "Both"
            }

        is_multi = section_name in ["Indigo Plateau", "Post-game"]
        if is_multi:
            elite_names = (
                ["Lorelei", "Bruno", "Agatha", "Lance"]
                if section_name == "Indigo Plateau"
                else ["Lorelei Rematch", "Bruno Rematch", "Agatha Rematch", "Lance Rematch"]
            )
            entries = []
            for ename in elite_names:
                for row in data[1:]:
                    if row and row[0].strip() == ename:
                        entries.append(build_boss_entry(row))
                        break
            for row in data[1:]:
                if row and row[0].strip() == section_name:
                    entries.append(build_boss_entry(row))
            return ok({"multiRow": True, "entries": entries})

        match = None
        for row in data[1:]:
            if not row or row[0].strip() != section_name:
                continue
            row_ver = row[13].strip() if len(row) > 13 else "Both"
            if row_ver in [version, "Both"]:
                match = row
                if row_ver == version:
                    break
        if not match:
            return ok(None)
        return ok({"multiRow": False, "entries": [build_boss_entry(match)]})
    except Exception as e:
        return err(str(e))

# ============================================================
# JOURNEY RESULTS
# ============================================================

def save_journey_result(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        trainer = body.get("trainerName", "unknown").strip().lower()
        sheet.append_row([
            trainer,
            body.get("sectionName", ""),
            body.get("spinType", ""),
            body.get("pokemon", ""),
            body.get("version", "")
        ])
        return ok("Success")
    except Exception as e:
        return err(str(e))

def delete_journey_result(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        trainer = body.get("trainerName", "").strip().lower()
        section_name = body.get("sectionName", "").strip()
        spin_type = body.get("spinType", "").strip()
        data = sheet.get_all_values()
        for i in range(len(data) - 1, 0, -1):
            r = data[i]
            if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() == spin_type:
                sheet.delete_rows(i + 1)
                break
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def delete_2player_picks(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        trainer = body.get("trainerName", "").strip().lower()
        section_name = body.get("sectionName", "").strip()
        data = sheet.get_all_values()
        to_delete = []
        for i in range(len(data) - 1, 0, -1):
            r = data[i]
            if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() in ["Pick1", "Pick2", "Pick3"]:
                to_delete.append(i + 1)
        for row_num in to_delete:
            sheet.delete_rows(row_num)
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

# ============================================================
# CATCHES
# ============================================================

def record_catch(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        trainer = body.get("trainerName", "unknown").strip().lower()
        pkmn_name = body.get("pkmnName", "")
        route_id = body.get("routeId", "")
        version = body.get("version", "FireRed")

        data = sheet.get_all_values()

        if pkmn_name == "__UNCATCH__":
            for i in range(len(data) - 1, 0, -1):
                r = data[i]
                if r and r[0].strip().lower() == trainer and r[1].strip() == route_id:
                    sheet.delete_rows(i + 1)
                    break
            return ok(True)

        for i, r in enumerate(data[1:], start=2):
            if r and r[0].strip().lower() == trainer and r[1].strip() == route_id:
                sheet.update(f"A{i}:D{i}", [[trainer, route_id, pkmn_name, version]])
                return ok(True)

        sheet.append_row([trainer, route_id, pkmn_name, version, "", "", ""])
        return ok(True)
    except Exception as e:
        return err(str(e))

def save_fainted_pokemon(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        pkmn_name = body.get("pkmnName", "").strip()
        fainted = body.get("fainted", False)
        data = sheet.get_all_values()
        for i, r in enumerate(data[1:], start=2):
            if r and r[0].strip().lower() == trainer and r[1].strip() == route_id and r[2].strip() == pkmn_name:
                sheet.update_cell(i, 5, "fainted" if fainted else "")
                return ok({"success": True})
        return err("Pokemon not found in catches")
    except Exception as e:
        return err(str(e))

def save_pokemon_evolution(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        old_name = body.get("oldName", "").strip()
        new_name = body.get("newName", "").strip()
        data = sheet.get_all_values()
        for i, r in enumerate(data[1:], start=2):
            if r and r[0].strip().lower() == trainer and r[1].strip() == route_id and r[2].strip() == old_name:
                sheet.update_cell(i, 3, new_name)
                return ok({"success": True})
        return err("Pokemon not found in catches")
    except Exception as e:
        return err(str(e))

def save_pokemon_trade(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        old_name = body.get("oldName", "").strip()
        new_name = body.get("newName", "").strip()
        data = sheet.get_all_values()
        for i, r in enumerate(data[1:], start=2):
            if r and r[0].strip().lower() == trainer and r[1].strip() == route_id and r[2].strip() == old_name:
                sheet.update_cell(i, 3, new_name)
                sheet.update_cell(i, 6, old_name)
                sheet.update_cell(i, 7, "traded")
                return ok({"success": True})
        return err("Pokemon not found in catches")
    except Exception as e:
        return err(str(e))

def undo_pokemon_trade(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        current_name = body.get("currentName", "").strip()
        original_name = body.get("originalName", "").strip()
        data = sheet.get_all_values()
        for i, r in enumerate(data[1:], start=2):
            if r and r[0].strip().lower() == trainer and r[1].strip() == route_id and r[2].strip() == current_name:
                sheet.update_cell(i, 3, original_name)
                sheet.update_cell(i, 6, "")
                sheet.update_cell(i, 7, "")
                return ok({"success": True})
        return err("Pokemon not found in catches")
    except Exception as e:
        return err(str(e))

# ============================================================
# PUNISHMENTS
# ============================================================

def save_punishment_result(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Punishment Results", ["Trainer","Punishment","FullText","Duration","SectionSpun","ExpiresAfterSection"])
        trainer = body.get("trainerName", "").strip().lower()
        sheet.append_row([
            trainer,
            body.get("punishment", ""),
            body.get("fullText", ""),
            body.get("duration", 1),
            body.get("sectionSpun", ""),
            body.get("expiresAfterSection", "")
        ])
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def delete_punishment_result(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Punishment Results", ["Trainer","Punishment","FullText","Duration","SectionSpun","ExpiresAfterSection"])
        trainer = body.get("trainerName", "").strip().lower()
        punishment = body.get("punishment", "").strip()
        section_spun = body.get("sectionSpun", "").strip()
        data = sheet.get_all_values()
        for i in range(len(data) - 1, 0, -1):
            r = data[i]
            if r and r[0].strip().lower() == trainer and r[1].strip() == punishment and r[4].strip() == section_spun:
                sheet.delete_rows(i + 1)
                break
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

# ============================================================
# BOSS BATTLE LOG
# ============================================================

def save_boss_battle_log(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Boss Battle Log", ["Trainer","Section","Slot1","Slot2","Slot3","Slot4","Slot5","Slot6","Result","Timestamp"])
        trainer = body.get("trainerName", "").strip().lower()
        section_name = body.get("sectionName", "")
        slots = body.get("slots", [])
        result = body.get("result", "")
        row = [trainer, section_name] + [slots[i] if i < len(slots) else "" for i in range(6)] + [result, datetime.now().isoformat()]
        sheet.append_row(row)
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def get_boss_battle_log(params):
    try:
        trainer = params.get("trainerName", [""])[0].lower()
        section_name = params.get("sectionName", [""])[0]
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Boss Battle Log", ["Trainer","Section","Slot1","Slot2","Slot3","Slot4","Slot5","Slot6","Result","Timestamp"])
        data = sheet.get_all_values()
        rows = [
            {"slots": [r[i].strip() for i in range(2, 8) if i < len(r) and r[i].strip()], "result": r[8].strip() if len(r) > 8 else ""}
            for r in data[1:] if r and r[0].strip().lower() == trainer and r[1].strip() == section_name
        ]
        return ok(rows)
    except Exception as e:
        return err(str(e))

def get_defeated_sections(params):
    try:
        trainer = params.get("trainerName", [""])[0].lower()
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Boss Battle Log", ["Trainer","Section","Slot1","Slot2","Slot3","Slot4","Slot5","Slot6","Result","Timestamp"])
        data = sheet.get_all_values()
        defeated = []
        for r in data[1:]:
            if r and r[0].strip().lower() == trainer and len(r) > 8 and r[8].strip() == "Defeated":
                sn = r[1].strip()
                if sn not in defeated:
                    defeated.append(sn)
        return ok(defeated)
    except Exception as e:
        return err(str(e))

# ============================================================
# FRIENDS
# ============================================================

def search_trainer(params):
    try:
        search_name = params.get("searchName", [""])[0].strip().lower()
        if not search_name or len(search_name) < 2:
            return err("Please enter at least 2 characters.")
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        data = sheet.get_all_values()
        results = []
        for row in data[1:]:
            if not row:
                continue
            trainer_key = row[0].strip().lower()
            display_name = row[3].strip() if len(row) > 3 else row[0].strip()
            if search_name in trainer_key or search_name in display_name.lower():
                results.append({"trainerName": trainer_key, "displayName": display_name})
        return ok({"results": results[:10]})
    except Exception as e:
        return err(str(e))

def send_friend_request(body):
    try:
        req = body.get("requesterName", "").strip().lower()
        rec = body.get("recipientName", "").strip().lower()
        if req == rec:
            return err("You can't send a friend request to yourself.")
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Friends", ["Requester","Recipient","Status","Timestamp"])
        data = sheet.get_all_values()
        for i, r in enumerate(data[1:], start=2):
            if not r or len(r) < 3:
                continue
            r0 = r[0].strip().lower()
            r1 = r[1].strip().lower()
            status = r[2].strip()
            if (r0 == req and r1 == rec) or (r0 == rec and r1 == req):
                if status == "accepted":
                    return err("You are already friends!")
                if status == "pending":
                    return ok({"success": True})
                if status == "declined":
                    sheet.update(f"A{i}:D{i}", [[req, rec, "pending", datetime.now().isoformat()]])
                    return ok({"success": True})
        sheet.append_row([req, rec, "pending", datetime.now().isoformat()])
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def accept_friend_request(body):
    try:
        rec = body.get("recipientName", "").strip().lower()
        req = body.get("requesterName", "").strip().lower()
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Friends", ["Requester","Recipient","Status","Timestamp"])
        data = sheet.get_all_values()
        for i, r in enumerate(data[1:], start=2):
            if r and r[0].strip().lower() == req and r[1].strip().lower() == rec and r[2].strip() == "pending":
                sheet.update_cell(i, 3, "accepted")
                return ok({"success": True})
        return err("Friend request not found.")
    except Exception as e:
        return err(str(e))

def decline_friend_request(body):
    try:
        rec = body.get("recipientName", "").strip().lower()
        req = body.get("requesterName", "").strip().lower()
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Friends", ["Requester","Recipient","Status","Timestamp"])
        data = sheet.get_all_values()
        for i, r in enumerate(data[1:], start=2):
            if r and r[0].strip().lower() == req and r[1].strip().lower() == rec and r[2].strip() == "pending":
                sheet.update_cell(i, 3, "declined")
                return ok({"success": True})
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def remove_friend(body):
    try:
        t = body.get("trainerName", "").strip().lower()
        f = body.get("friendName", "").strip().lower()
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Friends", ["Requester","Recipient","Status","Timestamp"])
        data = sheet.get_all_values()
        for i in range(len(data) - 1, 0, -1):
            r = data[i]
            if not r:
                continue
            r0 = r[0].strip().lower()
            r1 = r[1].strip().lower()
            if (r0 == t and r1 == f) or (r0 == f and r1 == t):
                sheet.delete_rows(i + 1)
                return ok({"success": True})
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def get_friend_view_data(params):
    try:
        friend_name = params.get("friendTrainerName", [""])[0].strip().lower()
        ss = get_sheet_client()

        trainers_sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        trainer_data = trainers_sheet.get_all_values()
        trainer_row = None
        for row in trainer_data[1:]:
            if row and row[0].strip().lower() == friend_name:
                trainer_row = row
                break
        if not trainer_row:
            return err("Trainer not found.")

        display_name = trainer_row[3].strip() if len(trainer_row) > 3 else trainer_row[0].strip()
        version = trainer_row[2].strip() if len(trainer_row) > 2 else "FireRed"
        game_mode = trainer_row[4].strip() if len(trainer_row) > 4 else "solo"

        journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        journey_data = journey_sheet.get_all_values()
        trainer_journey = [r for r in journey_data[1:] if r and r[0].strip().lower() == friend_name]

        catches_sheet = get_or_create_sheet(ss, "Trainer Catches", ["Trainer","RouteId","Pokemon","Version","Status","OriginalPokemon","TradeStatus"])
        catches_data = catches_sheet.get_all_values()
        trainer_catches = [r for r in catches_data[1:] if r and r[0].strip().lower() == friend_name]

        pun_sheet = get_or_create_sheet(ss, "Punishment Results", ["Trainer","Punishment","FullText","Duration","SectionSpun","ExpiresAfterSection"])
        pun_data = pun_sheet.get_all_values()
        trainer_puns = [r for r in pun_data[1:] if r and r[0].strip().lower() == friend_name]

        sections_sheet = ss.worksheet("Sections")
        sections_raw = sections_sheet.get_all_values()
        sections_data = []
        for row in sections_raw[1:]:
            if not row or not row[0]:
                continue
            sections_data.append({
                "shortName": row[0].strip(),
                "fullName": row[1].strip() if len(row) > 1 else "",
                "bossImage": row[2].strip() if len(row) > 2 else "",
                "levelCap": row[3].strip() if len(row) > 3 else ""
            })

        evo_sheet = ss.worksheet("Evolutions")
        evo_raw = evo_sheet.get_all_values()
        evo_map = {}
        for row in evo_raw[1:]:
            if not row or not row[0]:
                continue
            base = row[0].strip()
            evolved = row[1].strip() if len(row) > 1 else ""
            if not base or not evolved:
                continue
            evo_map.setdefault(base, [])
            evo_map.setdefault(evolved, [])
            if evolved not in evo_map[base]:
                evo_map[base].append(evolved)
            if base not in evo_map[evolved]:
                evo_map[evolved].append(base)

        enc_sheet = ss.worksheet("Master Encounters")
        enc_raw = enc_sheet.get_all_values()
        encounter_data = {}
        for row in enc_raw[1:]:
            if not row or not row[0]:
                continue
            sec = row[0].strip()
            route_name = row[2].strip() if len(row) > 2 else ""
            pkmn_name = row[4].strip() if len(row) > 4 else ""
            game_val = row[5].strip() if len(row) > 5 else ""
            if not pkmn_name or game_val not in ["Both", version]:
                continue
            encounter_data.setdefault(sec, [])
            route_entry = next((r for r in encounter_data[sec] if r["name"] == route_name), None)
            if not route_entry:
                route_entry = {"name": route_name, "pokemon": []}
                encounter_data[sec].append(route_entry)
            route_entry["pokemon"].append(pkmn_name)

        bbl_sheet = get_or_create_sheet(ss, "Boss Battle Log", ["Trainer","Section","Slot1","Slot2","Slot3","Slot4","Slot5","Slot6","Result","Timestamp"])
        bbl_data = bbl_sheet.get_all_values()
        defeated_sections = []
        for r in bbl_data[1:]:
            if r and r[0].strip().lower() == friend_name and len(r) > 8 and r[8].strip() == "Defeated":
                sn = r[1].strip()
                if sn not in defeated_sections:
                    defeated_sections.append(sn)

        spin_map = {}
        for r in trainer_journey:
            sec = r[1].strip()
            type_ = r[2].strip()
            pkmn = r[3].strip()
            spin_map.setdefault(sec, {"picks": []})
            if type_ == "Mandate":
                spin_map[sec]["mandate"] = pkmn
            elif type_ == "Exclude":
                spin_map[sec]["exclude"] = pkmn
            elif type_ in ["Pick1", "Pick2", "Pick3"]:
                spin_map[sec]["picks"].append({"spinType": type_, "pokemon": pkmn})

        catch_map = {}
        for r in trainer_catches:
            route = r[1].strip()
            catch_map[route] = {
                "name": r[2].strip(),
                "fainted": r[4].strip().lower() == "fainted" if len(r) > 4 else False,
                "originalName": r[5].strip() if len(r) > 5 else "",
                "traded": r[6].strip().lower() == "traded" if len(r) > 6 else False
            }

        current_section_index = 0
        for idx, sec in enumerate(sections_data):
            if sec["shortName"] in defeated_sections and idx + 1 > current_section_index:
                current_section_index = idx + 1
        if current_section_index >= len(sections_data) and sections_data:
            current_section_index = len(sections_data) - 1

        def get_family(pkmn_name):
            family = {pkmn_name: True}
            to_check = [pkmn_name]
            while to_check:
                cur = to_check.pop()
                for rel in evo_map.get(cur, []):
                    if rel not in family:
                        family[rel] = True
                        to_check.append(rel)
            return family

        all_mandate_names = [r[3].strip() for r in trainer_journey if r and r[2].strip() == "Mandate"]

        team_mandatory, team_regular, team_graveyard = [], [], []
        for r in trainer_catches:
            catch_name = r[2].strip()
            fainted = r[4].strip().lower() == "fainted" if len(r) > 4 else False
            traded = r[6].strip().lower() == "traded" if len(r) > 6 else False
            original_name = r[5].strip() if len(r) > 5 else ""
            route = r[1].strip()
            fam = get_family(catch_name)
            fam_orig = get_family(original_name) if original_name else {}
            is_mand = any(mn in fam or mn in fam_orig for mn in all_mandate_names)
            entry = {"name": catch_name, "route": route, "fainted": fainted, "traded": traded, "originalName": original_name, "isMand": is_mand}
            if fainted:
                team_graveyard.append(entry)
            elif is_mand:
                team_mandatory.append(entry)
            else:
                team_regular.append(entry)

        active_punishments = []
        for p in trainer_puns:
            exp_idx = len(sections_data) - 1
            for i, sec in enumerate(sections_data):
                if sec["shortName"] == (p[5].strip() if len(p) > 5 else ""):
                    exp_idx = i
                    break
            if exp_idx >= current_section_index:
                active_punishments.append(p)

        return ok({
            "displayName": display_name,
            "version": version,
            "gameMode": game_mode,
            "sectionsData": sections_data,
            "spinMap": spin_map,
            "catchMap": catch_map,
            "encounterData": encounter_data,
            "defeatedSections": defeated_sections,
            "currentSectionIndex": current_section_index,
            "teamMandatory": team_mandatory,
            "teamRegular": team_regular,
            "teamGraveyard": team_graveyard,
            "activePunishments": active_punishments,
            "evoMap": evo_map
        })
    except Exception as e:
        return err(str(e))

def get_friend_share_url(params):
    try:
        friend_name = params.get("friendTrainerName", [""])[0].strip().lower()
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        data = sheet.get_all_values()
        for row in data[1:]:
            if row and row[0].strip().lower() == friend_name:
                share_code = row[5].strip() if len(row) > 5 else ""
                if not share_code:
                    return err("This trainer hasn't generated a share link yet.")
                display_name = row[3].strip() if len(row) > 3 else friend_name
                base_url = os.environ.get("VERCEL_URL", "")
                if base_url and not base_url.startswith("http"):
                    base_url = "https://" + base_url
                url = f"{base_url}/friend?code={friend_name}-{share_code}"
                return ok({"success": True, "url": url, "displayName": display_name})
        return err("Trainer not found.")
    except Exception as e:
        return err(str(e))

def log_image_error(body):
    try:
        ss = get_sheet_client()
        sheet = get_or_create_sheet(ss, "Errors", ["Timestamp","Trainer","Image Type","Game Version","Game Section","Image Name"])
        sheet.append_row([
            datetime.now().isoformat(),
            body.get("trainerName", "unknown"),
            body.get("imageType", ""),
            body.get("gameVersion", ""),
            body.get("gameSection", ""),
            body.get("imageName", "")
        ])
        return ok(True)
    except Exception as e:
        return err(str(e))

def get_web_app_url(params):
    base_url = os.environ.get("VERCEL_URL", "")
    if base_url and not base_url.startswith("http"):
        base_url = "https://" + base_url
    return ok(base_url)

# ============================================================
# SERVE PICKS PAGE (friend 2-player pick page)
# ============================================================

def serve_picks_html(params):
    try:
        trainer = params.get("trainer", [""])[0].strip().lower()
        section_name = params.get("section", [""])[0].strip()

        ss = get_sheet_client()
        journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        journey_data = journey_sheet.get_all_values()

        picks = sorted(
            [r for r in journey_data[1:] if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() in ["Pick1","Pick2","Pick3"]],
            key=lambda r: r[2]
        )
        mandate_row = next((r for r in journey_data[1:] if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() == "Mandate"), None)
        exclude_row = next((r for r in journey_data[1:] if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() == "Exclude"), None)

        trainers_sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        trainer_data = trainers_sheet.get_all_values()
        display_name = trainer
        trainer_version = "FireRed"
        for row in trainer_data[1:]:
            if row and row[0].strip().lower() == trainer:
                display_name = row[3].strip() if len(row) > 3 else display_name
                trainer_version = row[2].strip() if len(row) > 2 else "FireRed"
                break

        base_url = os.environ.get("VERCEL_URL", "")
        if base_url and not base_url.startswith("http"):
            base_url = "https://" + base_url

        mandate = mandate_row[3].strip() if mandate_row else None
        exclude = exclude_row[3].strip() if exclude_row else None
        already_chosen = mandate and exclude

        def pkmn_img(name):
            img_name = name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            if name == "Nidoran♀": img_name = "nidoran-f"
            if name == "Nidoran♂": img_name = "nidoran-m"
            return f"https://img.pokemondb.net/sprites/heartgold-soulsilver/normal/{img_name}.png"

        picks_html = ""
        if not picks:
            picks_html = '<p style="color:#aaa;text-align:center;">No picks have been generated for this section yet.</p>'
        else:
            for idx, pick_row in enumerate(picks):
                pkmn = pick_row[3].strip()
                img_url = pkmn_img(pkmn)
                is_mandated = mandate == pkmn
                is_excluded = exclude == pkmn
                border = "#2ed573" if is_mandated else ("#ff4757" if is_excluded else "#444")
                bg = "#1a2e21" if is_mandated else ("#2e1a1a" if is_excluded else "#2a2a2a")
                safe_pkmn = pkmn.replace("\\", "\\\\").replace("'", "\\'")
                picks_html += f'<div style="background:{bg};border-radius:14px;padding:16px;text-align:center;border:2px solid {border};flex:1;min-width:110px;max-width:160px;">'
                picks_html += f'<div style="color:#aaa;font-size:11px;margin-bottom:6px;">Option {idx+1}</div>'
                picks_html += f'<img src="{img_url}" style="width:70px;height:70px;" onerror="this.onerror=null;">'
                picks_html += f'<div style="font-weight:bold;font-size:14px;margin-top:6px;color:#fff;">{pkmn}</div>'
                if is_mandated:
                    picks_html += '<div style="background:#2ed573;color:#000;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">&#10003; Mandated<button onclick="unchoose(\'Mandate\')" style="background:none;border:none;color:#000;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.6;">&#x2715;</button></div>'
                elif is_excluded:
                    picks_html += '<div style="background:#ff4757;color:#fff;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">&#10007; Excluded<button onclick="unchoose(\'Exclude\')" style="background:none;border:none;color:#fff;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.7;">&#x2715;</button></div>'
                else:
                    picks_html += '<div style="display:flex;flex-direction:column;gap:4px;margin-top:8px;">'
                    if not mandate:
                        picks_html += f'<button onclick="choose(\'{safe_pkmn}\',\'Mandate\')" style="background:#2ed573;color:#000;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">&#10003; Mandate</button>'
                    if not exclude:
                        picks_html += f'<button onclick="choose(\'{safe_pkmn}\',\'Exclude\')" style="background:#ff4757;color:#fff;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">&#10007; Exclude</button>'
                    picks_html += '</div>'
                picks_html += '</div>'

        status_msg = '<div style="background:#1a2e21;border:1px solid #2ed573;border-radius:10px;padding:12px;margin-bottom:16px;color:#2ed573;font-size:13px;text-align:center;">Both picks have been made for this section!</div>' if already_chosen else ""

        api_base = f"{base_url}/api"

        html = f'''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;padding:0;background:#1a1a1a;color:white;font-family:'Segoe UI',sans-serif;}}
.container{{max-width:560px;margin:0 auto;padding:20px 14px;}}
h1{{color:#ff4757;font-size:20px;margin-bottom:4px;}}
.subtitle{{color:#aaa;font-size:13px;margin-bottom:18px;}}
.picks-row{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:16px;}}
.start-btn{{display:block;max-width:280px;margin:24px auto 0;padding:14px;background:#ff4757;color:white;border:none;border-radius:12px;font-size:14px;font-weight:bold;cursor:pointer;text-align:center;text-decoration:none;}}
#status{{color:#2ed573;font-size:13px;margin-top:10px;text-align:center;min-height:20px;}}
</style></head><body>
<div class="container">
<h1>Pokemon Lotto-Locke</h1>
<div class="subtitle">{display_name}'s picks for <strong style="color:#fff;">{section_name}</strong></div>
{status_msg}
<div class="picks-row" id="picks-row">{picks_html}</div>
<div id="status"></div>
{"" if already_chosen else f"<p style='color:#aaa;font-size:12px;text-align:center;margin:0 0 4px;'>Tell {display_name} which Pokemon to mandate and which to exclude!</p>"}
<a href="{base_url}" class="start-btn">&#127918; Start Your Own Adventure</a>
</div>
<script>
var API_BASE="{api_base}";
var TRAINER="{trainer}";
var SECTION="{section_name}";
var VERSION="{trainer_version}";
function choose(pkmn,spinType){{
  var btns=document.querySelectorAll("button");for(var i=0;i<btns.length;i++)btns[i].disabled=true;
  document.getElementById("status").innerText="Saving...";
  fetch(API_BASE+"?action=saveJourneyResult",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{trainerName:TRAINER,sectionName:SECTION,spinType:spinType,pokemon:pkmn,version:VERSION}})}})
  .then(function(){{return fetch(API_BASE+"?action=getPicksState&trainer="+encodeURIComponent(TRAINER)+"&section="+encodeURIComponent(SECTION));}})
  .then(function(r){{return r.json();}})
  .then(function(state){{renderPicksFromState(state);document.getElementById("status").innerText="";}})
  .catch(function(){{document.getElementById("status").innerText="Error saving. Please refresh the page.";}});
}}
function unchoose(spinType){{
  var btns=document.querySelectorAll("button");for(var i=0;i<btns.length;i++)btns[i].disabled=true;
  document.getElementById("status").innerText="Removing...";
  fetch(API_BASE+"?action=deleteJourneyResult",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{trainerName:TRAINER,sectionName:SECTION,spinType:spinType}})}})
  .then(function(){{return fetch(API_BASE+"?action=getPicksState&trainer="+encodeURIComponent(TRAINER)+"&section="+encodeURIComponent(SECTION));}})
  .then(function(r){{return r.json();}})
  .then(function(state){{renderPicksFromState(state);document.getElementById("status").innerText="";}})
  .catch(function(){{document.getElementById("status").innerText="Error. Please refresh the page.";}});
}}
function renderPicksFromState(state){{
  var picks=state.picks||[];
  var mandate=state.mandate;
  var exclude=state.exclude;
  var allChosen=mandate&&exclude;
  var html="";
  picks.forEach(function(pick,idx){{
    var pkmn=pick.pokemon;
    var imgName=pkmn.toLowerCase().replace(/\\s+/g,"-").replace(/\\./g,"").replace(/'/g,"");
    if(pkmn==="Nidoran\u2640")imgName="nidoran-f";
    if(pkmn==="Nidoran\u2642")imgName="nidoran-m";
    var hgUrl="https://img.pokemondb.net/sprites/heartgold-soulsilver/normal/"+imgName+".png";
    var isMandated=mandate===pkmn;
    var isExcluded=exclude===pkmn;
    var border=isMandated?"#2ed573":(isExcluded?"#ff4757":"#444");
    var bg=isMandated?"#1a2e21":(isExcluded?"#2e1a1a":"#2a2a2a");
    html+='<div style="background:'+bg+';border-radius:14px;padding:16px;text-align:center;border:2px solid '+border+';flex:1;min-width:110px;max-width:160px;">';
    html+='<div style="color:#aaa;font-size:11px;margin-bottom:6px;">Option '+(idx+1)+'</div>';
    html+='<img src="'+hgUrl+'" style="width:70px;height:70px;" onerror="this.onerror=null;">';
    html+='<div style="font-weight:bold;font-size:14px;margin-top:6px;color:#fff;">'+pkmn+'</div>';
    var safePkmn=pkmn.replace(/\x27/g,"\\x27");
    if(isMandated){{html+='<div style="background:#2ed573;color:#000;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">\u2713 Mandated<button onclick="unchoose(\'Mandate\')" style="background:none;border:none;color:#000;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.6;">&#x2715;</button></div>';}}
    else if(isExcluded){{html+='<div style="background:#ff4757;color:#fff;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">\u2717 Excluded<button onclick="unchoose(\'Exclude\')" style="background:none;border:none;color:#fff;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.7;">&#x2715;</button></div>';}}
    else{{
      html+='<div style="display:flex;flex-direction:column;gap:4px;margin-top:8px;">';
      if(!mandate)html+='<button onclick="choose(\''+safePkmn+'\',\'Mandate\')" style="background:#2ed573;color:#000;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">\u2713 Mandate</button>';
      if(!exclude)html+='<button onclick="choose(\''+safePkmn+'\',\'Exclude\')" style="background:#ff4757;color:#fff;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">\u2717 Exclude</button>';
      html+='</div>';
    }}
    html+='</div>';
  }});
  document.getElementById("picks-row").innerHTML=html;
  if(allChosen){{
    var existing=document.getElementById("all-chosen-msg");
    if(!existing){{var msg=document.createElement("div");msg.id="all-chosen-msg";msg.style="background:#1a2e21;border:1px solid #2ed573;border-radius:10px;padding:12px;margin-bottom:16px;color:#2ed573;font-size:13px;text-align:center;";msg.innerText="Both picks have been made for this section!";document.getElementById("picks-row").parentNode.insertBefore(msg,document.getElementById("picks-row"));}}
  }}
}}
</script>
</body></html>'''
        return html, "text/html"
    except Exception as e:
        return f"<html><body><h2>Error</h2><p>{str(e)}</p></body></html>", "text/html"

def get_picks_state(params):
    try:
        trainer = params.get("trainer", [""])[0].strip().lower()
        section_name = params.get("section", [""])[0].strip()
        ss = get_sheet_client()
        journey_sheet = get_or_create_sheet(ss, "Journey Results", ["Trainer","Section","Type","Pokemon","Version"])
        journey_data = journey_sheet.get_all_values()
        picks = sorted(
            [{"spinType": r[2].strip(), "pokemon": r[3].strip()} for r in journey_data[1:]
             if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() in ["Pick1","Pick2","Pick3"]],
            key=lambda x: x["spinType"]
        )
        mandate = next((r[3].strip() for r in journey_data[1:] if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() == "Mandate"), None)
        exclude = next((r[3].strip() for r in journey_data[1:] if r and r[0].strip().lower() == trainer and r[1].strip() == section_name and r[2].strip() == "Exclude"), None)
        return ok({"success": True, "picks": picks, "mandate": mandate, "exclude": exclude})
    except Exception as e:
        return err(str(e))

def serve_friend_view_html(params):
    try:
        code = params.get("code", [""])[0]
        if not code:
            return "<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Invalid link</h2></body></html>", "text/html"

        parts = code.rsplit("-", 1)
        if len(parts) != 2:
            return "<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Invalid link</h2></body></html>", "text/html"

        trainer_name, share_code = parts[0].lower(), parts[1]

        ss = get_sheet_client()
        trainers_sheet = get_or_create_sheet(ss, "Trainers", ["Trainer","PIN","Version","DisplayName","GameMode","ShareCode"])
        trainer_data = trainers_sheet.get_all_values()
        valid = any(
            row and row[0].strip().lower() == trainer_name and len(row) > 5 and row[5].strip() == share_code
            for row in trainer_data[1:]
        )
        if not valid:
            return "<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Journey not found</h2><p style='color:#aaa;'>This link may be invalid or expired.</p></body></html>", "text/html"

        data_json = get_friend_view_data({"friendTrainerName": [trainer_name]})
        data = json.loads(data_json)
        if "error" in data:
            return f"<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Error</h2><p>{data['error']}</p></body></html>", "text/html"

        base_url = os.environ.get("VERCEL_URL", "")
        if base_url and not base_url.startswith("http"):
            base_url = "https://" + base_url

        html = build_friend_view_html(data, base_url)
        return html, "text/html"
    except Exception as e:
        return f"<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Error</h2><p>{str(e)}</p></body></html>", "text/html"

def build_friend_view_html(data, base_url):
    display_name = data.get("displayName", "")
    version = data.get("version", "FireRed")
    game_mode = data.get("gameMode", "solo")
    sections_data = data.get("sectionsData", [])
    spin_map = data.get("spinMap", {})
    catch_map = data.get("catchMap", {})
    encounter_data = data.get("encounterData", {})
    defeated_sections = data.get("defeatedSections", [])
    current_section_index = data.get("currentSectionIndex", 0)
    team_mandatory = data.get("teamMandatory", [])
    team_regular = data.get("teamRegular", [])
    team_graveyard = data.get("teamGraveyard", [])
    active_punishments = data.get("activePunishments", [])
    evo_map = data.get("evoMap", {})

    BADGE_MAP = {
        "Brock": {"url": "https://archives.bulbagarden.net/media/upload/d/dd/Boulder_Badge.png", "name": "Boulder Badge"},
        "Misty": {"url": "https://archives.bulbagarden.net/media/upload/9/9c/Cascade_Badge.png", "name": "Cascade Badge"},
        "Surge": {"url": "https://archives.bulbagarden.net/media/upload/a/a6/Thunder_Badge.png", "name": "Thunder Badge"},
        "Erika": {"url": "https://archives.bulbagarden.net/media/upload/b/b5/Rainbow_Badge.png", "name": "Rainbow Badge"},
        "Koga": {"url": "https://archives.bulbagarden.net/media/upload/7/7d/Soul_Badge.png", "name": "Soul Badge"},
        "Sabrina": {"url": "https://archives.bulbagarden.net/media/upload/6/6b/Marsh_Badge.png", "name": "Marsh Badge"},
        "Blaine": {"url": "https://archives.bulbagarden.net/media/upload/1/12/Volcano_Badge.png", "name": "Volcano Badge"},
        "Giovanni": {"url": "https://archives.bulbagarden.net/media/upload/7/78/Earth_Badge.png", "name": "Earth Badge"},
        "Indigo Plateau": {"emoji": "🏆", "name": "Kanto Champion"},
        "Post-game": {"emoji": "⭐", "name": "Complete!"}
    }

    def pkmn_img(name):
        img = name.lower().replace(" ", "-").replace(".", "").replace("'", "")
        if name == "Nidoran♀": img = "nidoran-f"
        if name == "Nidoran♂": img = "nidoran-m"
        return f"https://img.pokemondb.net/sprites/heartgold-soulsilver/normal/{img}.png"

    def team_card(p):
        route_label = "Trade" if p.get("traded") else p.get("route","").replace("route-","").replace("-"," ")
        color = "#f0a500" if p.get("traded") else "#bbb"
        mand_class = " mandatory" if p.get("isMand") else ""
        faint_class = " fainted" if p.get("fainted") else ""
        skull = '<div class="fainted-overlay" style="cursor:default;pointer-events:none;">💀</div>' if p.get("fainted") else ""
        return f'<div class="team-member{mand_class}{faint_class}">{skull}<img src="{pkmn_img(p["name"])}" style="width:56px;height:56px;" onerror="this.onerror=null;"><div style="font-weight:bold;margin-top:4px;font-size:10px;color:#fff;">{p["name"]}</div><div style="font-size:9px;color:{color};">{route_label}</div></div>'

    team_html = ""
    if team_mandatory or team_regular or team_graveyard:
        team_html = '<div id="team-section"><div id="team-section-title">My Team</div><div id="team-content">'
        if team_mandatory:
            team_html += '<div id="team-mandatory-box"><h3>Mandated</h3><div id="team-mandatory-grid">'
            for p in team_mandatory: team_html += team_card(p)
            team_html += '</div></div>'
        team_html += '<div id="team-regular-grid">'
        for p in team_regular: team_html += team_card(p)
        team_html += '</div></div>'
        if team_graveyard:
            team_html += '<div id="team-graveyard-box"><div style="font-size:11px;font-weight:bold;color:#666;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">💀 Graveyard</div><div id="team-graveyard-grid">'
            for p in team_graveyard: team_html += team_card(p)
            team_html += '</div></div>'
        team_html += '</div>'

    pun_html = ""
    if active_punishments:
        pun_html = '<div class="punishment-banner"><h4>Active Punishments</h4>'
        for p in active_punishments:
            pun_html += f'<div class="punishment-item"><div class="punishment-item-name">{p[1] if len(p)>1 else ""}</div><div class="punishment-item-text">{p[2] if len(p)>2 else ""}</div><div class="punishment-item-duration">Until after: {p[5] if len(p)>5 else ""}</div></div>'
        pun_html += '</div>'

    sections_html = ""
    STARTERS = ["Bulbasaur","Charmander","Squirtle"]
    starter_catch = catch_map.get("route-oaks-lab")

    for index, section in enumerate(sections_data):
        is_current = index == current_section_index
        is_completed = index < current_section_index
        spins = spin_map.get(section["shortName"], {"picks": []})
        badge = BADGE_MAP.get(section["shortName"])
        badge_html = ""
        if is_completed and badge:
            if "emoji" in badge:
                badge_html = f'<div class="section-badge-wrap"><span class="section-badge-emoji" title="{badge["name"]}">{badge["emoji"]}</span></div>'
            elif "url" in badge:
                badge_html = f'<div class="section-badge-wrap"><img class="section-badge-img" src="{badge["url"]}" title="{badge["name"]}" onerror="this.style.display=\'none\'"></div>'

        boss_img = f'<img class="section-boss-img" src="{section["bossImage"]}" onerror="this.style.display=\'none\'">' if section.get("bossImage") else '<div class="section-boss-placeholder">🏆</div>'
        current_class = " current" if is_current else ""
        completed_class = " completed" if is_completed else ""

        card = f'<div class="section-card{current_class}{completed_class}">'
        card += f'<div class="section-card-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">'
        card += boss_img
        card += f'<div class="section-info"><div class="section-name">{section["shortName"]}'
        if is_current: card += ' <span class="current-badge">CURRENT</span>'
        card += f'</div><div class="section-fullname">{section["fullName"]}</div></div>'
        card += f'<div class="section-levelcap">Lv.{section["levelCap"]}</div>'
        if badge_html: card += badge_html
        card += '</div>'
        card += f'<div class="section-card-body{"  open" if is_current else ""}">'

        step = 1
        if index > 0:
            card += f'<div class="step-label">Step {step}: Punishment Wheel</div>'
            step += 1
            sec_pun = next((p for p in active_punishments if len(p) > 4 and p[4].strip() == section["shortName"]), None)
            if sec_pun:
                card += f'<div class="punishment-spin-result"><div style="flex:1;"><div class="punishment-spin-result-name">Punishment: {sec_pun[1]}</div><div style="color:#ccc;font-size:11px;margin-top:2px;">{sec_pun[2] if len(sec_pun)>2 else ""}</div><div style="font-size:10px;color:#ccc;margin-top:2px;">Until after: {sec_pun[5] if len(sec_pun)>5 else ""}</div></div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">No punishment spun yet.</div>'

        if game_mode == "solo":
            card += f'<div class="step-label">Step {step}: Exclude Wheel</div>'
            step += 1
            if spins.get("exclude"):
                card += f'<div class="spin-result" style="border-left:4px solid #ff4757;"><img src="{pkmn_img(spins["exclude"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Excluded</div><div class="spin-result-name">{spins["exclude"]}</div></div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Not yet spun.</div>'
            card += f'<div class="step-label">Step {step}: Mandate Wheel</div>'
            step += 1
            if spins.get("mandate"):
                card += f'<div class="spin-result" style="border-left:4px solid #2ed573;"><img src="{pkmn_img(spins["mandate"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Mandated</div><div class="spin-result-name">{spins["mandate"]}</div></div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Not yet spun.</div>'
        else:
            card += f'<div class="step-label">Step {step}: Friend\'s Picks</div>'
            step += 1
            if spins.get("mandate") and spins.get("exclude"):
                card += f'<div class="spin-result" style="border-left:4px solid #ff4757;margin-bottom:4px;"><img src="{pkmn_img(spins["exclude"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Excluded</div><div class="spin-result-name">{spins["exclude"]}</div></div></div>'
                card += f'<div class="spin-result" style="border-left:4px solid #2ed573;"><img src="{pkmn_img(spins["mandate"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Mandated</div><div class="spin-result-name">{spins["mandate"]}</div></div></div>'
            elif spins.get("picks"):
                card += '<div class="picks-container"><div class="picks-row">'
                for idx2, pick in enumerate(sorted(spins["picks"], key=lambda x: x["spinType"])):
                    is_mand = spins.get("mandate") == pick["pokemon"]
                    is_excl = spins.get("exclude") == pick["pokemon"]
                    mand_class = " pick-mandated" if is_mand else ""
                    excl_class = " pick-excluded" if is_excl else ""
                    card += f'<div class="pick-card{mand_class}{excl_class}"><div class="pick-card-label">Option {idx2+1}</div><img src="{pkmn_img(pick["pokemon"])}" style="width:56px;height:56px;" onerror="this.onerror=null;"><div class="pick-card-name">{pick["pokemon"]}</div>'
                    if is_mand: card += '<div class="pick-chosen-label pick-chosen-mandate">&#x2713; Mandated</div>'
                    elif is_excl: card += '<div class="pick-chosen-label pick-chosen-exclude">&#x2717; Excluded</div>'
                    card += '</div>'
                card += '</div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Picks not yet generated.</div>'

        if section["shortName"] == "Brock":
            card += f'<div class="step-label">Step {step}: Starter Pokemon</div>'
            step += 1
            oaks = next((r for r in encounter_data.get(section["shortName"], []) if r["name"] == "Oak's Lab"), None)
            starter_pool = oaks["pokemon"] if oaks else STARTERS
            card += '<div class="starter-section"><div class="starter-section-label">&#127981; Oak\'s Lab</div><div class="pkmn-grid">'
            for pn in starter_pool:
                is_caught = starter_catch and starter_catch.get("name") == pn
                is_locked = starter_catch and not is_caught
                cc = "selected" if is_caught else ("locked" if is_locked else "")
                card += f'<div class="pkmn-card {cc}" style="cursor:default;"><img src="{pkmn_img(pn)}" onerror="this.onerror=null;" loading="lazy"><br>{pn}</div>'
            card += '</div></div>'

        card += f'<div class="step-label">Step {step}: Pokemon Caught</div>'
        step += 1
        routes = encounter_data.get(section["shortName"], [])
        catch_routes = [r for r in routes if r["name"] != "Oak's Lab"] if section["shortName"] == "Brock" else routes
        if catch_routes:
            card += '<div class="encounter-section">'
            for route in catch_routes:
                route_id = "route-" + route["name"].replace(" ", "-").replace("'", "")
                caught_here = catch_map.get(route_id)
                completed_cls = " completed" if caught_here else ""
                card += f'<div class="route-row{completed_cls}"><div class="route-label">{route["name"]}</div><div class="pkmn-grid">'
                for pn in route["pokemon"]:
                    is_caught = caught_here and caught_here.get("name") == pn
                    cc = "selected" if is_caught else ("locked" if caught_here else "")
                    card += f'<div class="pkmn-card {cc}" style="cursor:default;"><img src="{pkmn_img(pn)}" onerror="this.onerror=null;" loading="lazy"><br>{pn}</div>'
                card += '</div></div>'
            card += '</div>'
        else:
            card += '<div style="color:#555;font-size:11px;font-style:italic;padding:4px 0;">No catchable Pokemon in this section.</div>'

        is_defeated = section["shortName"] in defeated_sections
        card += f'<div class="step-label">Step {step}: Boss Battle</div>'
        if is_defeated:
            card += '<div style="background:#1a2e21;border:1px solid #2ed573;border-radius:8px;padding:8px 10px;font-size:12px;color:#2ed573;">&#x2713; Boss Defeated</div>'
        elif index < current_section_index:
            card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Result not recorded.</div>'
        else:
            card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Not yet reached.</div>'

        card += '</div></div>'
        sections_html += card

    css = '''html,body{margin:0;padding:0;background:#1a1a1a;color:white;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;}
#top-bar{display:flex;flex-direction:row;align-items:center;justify-content:center;background:#111;border-bottom:1px solid #222;padding:4px 12px;min-height:44px;position:relative;}
#trainer-badge-text{font-size:11px;color:#2ed573;text-align:center;flex:1;padding:0 80px;}
.view-badge{background:#333;border:1px solid #555;border-radius:8px;padding:5px 10px;font-size:11px;color:#aaa;position:absolute;right:8px;}
#main-view{max-width:780px;margin:0 auto;padding:12px 16px;box-sizing:border-box;}
#team-section{margin-bottom:16px;}
#team-section-title{font-size:13px;font-weight:bold;color:#2ed573;margin:0 0 10px 0;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #2ed573;padding-bottom:6px;}
#team-content{display:flex;flex-direction:row;gap:12px;flex-wrap:wrap;}
#team-mandatory-box{border:2px solid #2ed573;border-radius:12px;padding:10px;flex-shrink:0;width:100%;box-sizing:border-box;}
#team-mandatory-box h3{margin:0 0 8px 0;color:#2ed573;font-size:11px;text-transform:uppercase;letter-spacing:1px;}
#team-mandatory-grid,#team-regular-grid,#team-graveyard-grid{display:flex;flex-wrap:wrap;gap:8px;}
#team-regular-grid{flex:1;min-width:0;}
#team-graveyard-box{margin-top:10px;border-top:1px solid #333;padding-top:10px;}
.team-member{background:#2a2a2a;border-radius:10px;padding:8px;text-align:center;border:2px solid #444;position:relative;width:80px;box-sizing:border-box;flex-shrink:0;}
.team-member.mandatory{border-color:#2ed573;background:#1a2e21;}
.team-member.fainted img{filter:grayscale(100%);opacity:0.55;}
.fainted-overlay{position:absolute;top:3px;right:5px;font-size:14px;line-height:1;cursor:default;}
.punishment-banner{background:#1a0030;border:2px solid #4b0082;border-radius:12px;padding:10px 14px;margin-bottom:14px;}
.punishment-banner h4{margin:0 0 8px 0;color:#cc88ff;font-size:12px;text-transform:uppercase;letter-spacing:1px;}
.punishment-item{display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid #2a0050;font-size:12px;}
.punishment-item:last-child{border-bottom:none;}
.punishment-item-name{font-weight:bold;color:#cc88ff;width:90px;min-width:90px;flex-shrink:0;font-size:11px;}
.punishment-item-text{color:#ccc;flex:1;min-width:0;word-wrap:break-word;}
.punishment-item-duration{color:#ccc;font-size:10px;white-space:nowrap;flex-shrink:0;}
.punishment-spin-result{display:flex;align-items:flex-start;gap:8px;background:#1a0030;border:1px solid #4b0082;border-radius:10px;padding:8px 10px;margin-top:6px;font-size:12px;}
.punishment-spin-result-name{font-weight:bold;color:#cc88ff;font-size:12px;}
.section-card{background:#1e1e1e;border-radius:14px;border:2px solid #333;margin-bottom:14px;overflow:hidden;}
.section-card.current{border-color:#ff4757;box-shadow:0 0 18px rgba(255,71,87,0.2);}
.section-card.completed{border-color:#2ed573;opacity:0.88;}
.section-card-header{display:flex;align-items:center;padding:12px 14px;gap:12px;cursor:pointer;}
.section-boss-img{width:54px;height:54px;object-fit:contain;background:#2a2a2a;border-radius:50%;padding:3px;flex-shrink:0;}
.section-boss-placeholder{width:54px;height:54px;background:#2a2a2a;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:22px;}
.section-info{flex:1;min-width:0;}
.section-name{font-size:14px;font-weight:bold;color:#fff;}
.section-fullname{font-size:11px;color:#bbb;margin-top:1px;}
.section-levelcap{background:#2a2a2a;padding:3px 8px;border-radius:16px;font-size:11px;font-weight:bold;color:#ffa500;white-space:nowrap;flex-shrink:0;}
.current-badge{background:#ff4757;color:white;font-size:9px;font-weight:bold;padding:1px 6px;border-radius:8px;margin-left:6px;}
.section-badge-wrap{flex-shrink:0;width:36px;height:36px;display:flex;align-items:center;justify-content:center;}
.section-badge-img{width:36px;height:36px;object-fit:contain;filter:drop-shadow(0 0 4px rgba(255,215,0,0.6));}
.section-badge-emoji{font-size:26px;line-height:1;}
.section-card-body{padding:0 14px 14px 14px;display:none;}
.section-card-body.open{display:block;}
.step-label{font-size:10px;font-weight:bold;color:#666;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px 0;}
.spin-result{display:flex;align-items:center;gap:10px;background:#2a2a2a;border-radius:10px;padding:8px 10px;margin-top:6px;font-size:12px;}
.spin-result-label{font-size:10px;color:#aaa;}
.spin-result-name{font-weight:bold;font-size:13px;color:#fff;}
.starter-section{margin-bottom:8px;background:#1a2030;border:1px solid #4a6fa5;border-radius:10px;padding:8px 10px;}
.starter-section-label{font-size:10px;font-weight:bold;color:#7ec8e3;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;}
.route-row{display:flex;align-items:flex-start;margin-bottom:6px;background:#252525;border-radius:8px;border:1px solid #333;}
.route-row.completed{border-color:#2ed573;background:#1a2e21;opacity:0.85;}
.route-label{width:80px;min-width:80px;padding:8px 6px;font-weight:bold;color:#ffa500;background:#2a2a2a;border-radius:8px 0 0 8px;font-size:10px;flex-shrink:0;word-wrap:break-word;line-height:1.3;}
.pkmn-grid{display:flex;flex-wrap:wrap;padding:6px;gap:4px;flex:1;min-width:0;}
.pkmn-card{text-align:center;width:62px;font-size:9px;padding:3px;border-radius:6px;flex-shrink:0;}
.pkmn-card img{width:48px;height:48px;object-fit:contain;display:block;margin:0 auto;}
.pkmn-card.selected{background:#2ed573!important;color:black;font-weight:bold;}
.pkmn-card.locked{opacity:0.2;}
.pkmn-card.locked img{filter:grayscale(100%);}
.picks-container{margin-top:8px;}.picks-row{display:flex;gap:10px;flex-wrap:wrap;}
.pick-card{background:#2a2a2a;border:2px solid #444;border-radius:12px;padding:10px;text-align:center;flex:1;min-width:100px;max-width:160px;}
.pick-card.pick-mandated{border-color:#2ed573;background:#1a2e21;}
.pick-card.pick-excluded{border-color:#ff4757;background:#2e1a1a;}
.pick-card img{width:56px;height:56px;display:block;margin:0 auto;}
.pick-card-name{font-weight:bold;font-size:12px;margin:4px 0;color:#fff;}
.pick-card-label{font-size:10px;color:#aaa;margin-bottom:6px;}
.pick-chosen-label{font-size:10px;font-weight:bold;padding:4px;border-radius:6px;margin-top:4px;}
.pick-chosen-mandate{background:rgba(46,213,115,0.2);color:#2ed573;}
.pick-chosen-exclude{background:rgba(255,71,87,0.2);color:#ff4757;}
.start-btn{display:block;max-width:280px;margin:24px auto;padding:14px;background:#ff4757;color:white;border:none;border-radius:12px;font-size:14px;font-weight:bold;cursor:pointer;text-align:center;text-decoration:none;}
@media(min-width:600px){#team-mandatory-box{width:auto;flex-shrink:0;min-width:160px;}#team-content{flex-wrap:nowrap;align-items:flex-start;}.team-member{width:90px;}.team-member img{width:64px;height:64px;}.pkmn-card{width:76px;font-size:11px;}.pkmn-card img{width:60px;height:60px;}.route-label{width:110px;min-width:110px;font-size:12px;padding:10px;}}'''

    return f'''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>{display_name}'s Lotto-Locke</title><style>{css}</style></head><body>
<div id="top-bar"><span id="trainer-badge-text">Viewing {display_name}'s run - {version}</span><span class="view-badge">&#128064; Read-only</span></div>
<div id="main-view">{team_html}{pun_html}<div id="sections-container">{sections_html}</div>
<a href="{base_url}" class="start-btn">&#127918; Start Your Own Adventure</a></div>
</body></html>'''

# ============================================================
# MAIN REQUEST HANDLER
# ============================================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
}

GET_ACTIONS = {
    "getSectionData": get_section_data,
    "getEncounterData": get_encounter_data,
    "getEvolutionData": get_evolution_data,
    "getFullEvolutionMap": get_full_evolution_map,
    "getTradeData": get_trade_data,
    "getJourneyWheelData": get_journey_wheel_data,
    "getElite4WheelData": get_elite4_wheel_data,
    "get2PlayerPicks": get_2player_picks,
    "getPunishmentData": get_punishment_data,
    "getBossData": get_boss_data,
    "getBossBattleLog": get_boss_battle_log,
    "getDefeatedSections": get_defeated_sections,
    "getWebAppUrl": get_web_app_url,
    "searchTrainer": search_trainer,
    "getFriendViewData": get_friend_view_data,
    "getFriendShareUrl": get_friend_share_url,
    "getPicksState": get_picks_state,
}

POST_ACTIONS = {
    "createTrainer": create_trainer,
    "loadTrainer": load_trainer,
    "saveGameMode": save_game_mode,
    "saveJourneyResult": save_journey_result,
    "deleteJourneyResult": delete_journey_result,
    "delete2PlayerPicks": delete_2player_picks,
    "recordCatch": record_catch,
    "saveFaintedPokemon": save_fainted_pokemon,
    "savePokemonEvolution": save_pokemon_evolution,
    "savePokemonTrade": save_pokemon_trade,
    "undoPokemonTrade": undo_pokemon_trade,
    "savePunishmentResult": save_punishment_result,
    "deletePunishmentResult": delete_punishment_result,
    "saveBossBattleLog": save_boss_battle_log,
    "logImageError": log_image_error,
    "sendFriendRequest": send_friend_request,
    "acceptFriendRequest": accept_friend_request,
    "declineFriendRequest": decline_friend_request,
    "removeFriend": remove_friend,
}

class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress default logging

    def send_json(self, body, status=200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(encoded)

    def send_html(self, body, status=200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        action = params.get("action", [""])[0]

        # Special HTML pages
        if action == "servePicks":
            html, _ = serve_picks_html(params)
            self.send_html(html)
            return
        if action == "serveFriendView":
            html, _ = serve_friend_view_html(params)
            self.send_html(html)
            return

        if action in GET_ACTIONS:
            result = GET_ACTIONS[action](params)
            self.send_json(result)
        else:
            self.send_json(err(f"Unknown action: {action}"), 400)

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        action = params.get("action", [""])[0]

        content_length = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_length > 0:
            try:
                body = json.loads(self.rfile.read(content_length))
            except Exception:
                body = {}

        if action in POST_ACTIONS:
            result = POST_ACTIONS[action](body)
            self.send_json(result)
        else:
            self.send_json(err(f"Unknown action: {action}"), 400)