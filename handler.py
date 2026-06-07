import json
import os
import random
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from supabase import create_client

# ============================================================
# SUPABASE CONNECTION
# ============================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_supabase_client = None

def get_db():
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client

def db():
    return get_db()

# ============================================================
# HELPERS
# ============================================================

def ok(data):
    return json.dumps(data)

def err(message):
    return json.dumps({"error": message})

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

        # Check if trainer already exists
        existing = db().table("trainers").select("trainer").eq("trainer", name).execute()
        if existing.data:
            return err(f"Trainer '{display_name}' already exists! Choose a different name or resume your adventure.")

        share_code = str(random.randint(100000, 999999))
        db().table("trainers").insert({
            "trainer": name,
            "pin": pin,
            "version": game_version,
            "display_name": display_name,
            "game_mode": mode,
            "share_code": share_code
        }).execute()

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

        result = db().table("trainers").select("*").eq("trainer", name).execute()
        if not result.data:
            return err(f"Trainer '{trainer_name}' not found. Please start a new adventure.")

        row = result.data[0]
        if pin != "__skip_pin__" and row["pin"] != pin:
            return err("Incorrect PIN. Please try again.")

        game_version = row.get("version") or "FireRed"
        display_name = row.get("display_name") or trainer_name
        game_mode = row.get("game_mode") or "solo"
        share_code = row.get("share_code") or ""

        if not share_code:
            share_code = str(random.randint(100000, 999999))
            db().table("trainers").update({"share_code": share_code}).eq("trainer", name).execute()

        # Journey results
        journey_data = db().table("journey_results").select("*").eq("trainer", name).execute()
        trainer_journey = [
            {"section": r["section"], "spinType": r["spin_type"], "pokemon": r["pokemon"], "version": r.get("version", "")}
            for r in journey_data.data
        ]

        # Catches
        catches_data = db().table("trainer_catches").select("*").eq("trainer", name).execute()
        trainer_catches = [
            {
                "route": r["route_id"],
                "name": r["pokemon"],
                "version": r.get("version", ""),
                "fainted": r.get("status", "") == "fainted",
                "originalName": r.get("original_pokemon", ""),
                "traded": r.get("trade_status", "") == "traded"
            }
            for r in catches_data.data
        ]

        # Punishments
        pun_data = db().table("punishment_results").select("*").eq("trainer", name).execute()
        trainer_punishments = [
            {
                "punishment": r["punishment"],
                "fullText": r.get("full_text", ""),
                "duration": r.get("duration", 1),
                "sectionSpun": r.get("section_spun", ""),
                "expiresAfterSection": r.get("expires_after_section", "")
            }
            for r in pun_data.data
        ]

        # Friends
        pending_requests = []
        friends = []
        new_acceptances = []
        try:
            friends_data = db().table("friends").select("*").or_(
                f"requester.eq.{name},recipient.eq.{name}"
            ).execute()
            for r in friends_data.data:
                requester = r["requester"]
                recipient = r["recipient"]
                status = r["status"]
                if recipient == name and status == "pending":
                    pending_requests.append({"from": requester, "timestamp": r.get("timestamp", "")})
                if status == "accepted" and (requester == name or recipient == name):
                    friend_name = recipient if requester == name else requester
                    if friend_name not in friends:
                        friends.append(friend_name)
                if requester == name and status == "accepted":
                    if recipient not in new_acceptances:
                        new_acceptances.append(recipient)
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
            "friends": friends,
            "newAcceptances": new_acceptances
        })
    except Exception as e:
        return err(str(e))

def save_game_mode(body):
    try:
        name = body.get("trainerName", "").strip().lower()
        game_mode = body.get("gameMode", "solo").strip()
        db().table("trainers").update({"game_mode": game_mode}).eq("trainer", name).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

# ============================================================
# SECTION / ENCOUNTER / EVOLUTION DATA
# ============================================================

def get_section_data(params):
    try:
        result = db().table("sections").select("*").order("id").execute()
        return ok([{
            "shortName": r["short_name"],
            "fullName": r.get("full_name", ""),
            "bossImage": r.get("boss_image", ""),
            "levelCap": r.get("level_cap", "")
        } for r in result.data])
    except Exception as e:
        return err(str(e))

def get_encounter_data(params):
    try:
        version = params.get("version", ["FireRed"])[0]
        result = db().table("master_encounters").select("*").in_("version", ["Both", version]).order("id").execute()
        structured = []
        current_section = None
        for r in result.data:
            section_name = r["section"]
            route_name = r["route"]
            pkmn_name = r["pokemon"]
            if not current_section or current_section["name"] != section_name:
                current_section = {"name": section_name, "routes": []}
                structured.append(current_section)
            route_entry = next((rt for rt in current_section["routes"] if rt["name"] == route_name), None)
            if not route_entry:
                route_entry = {"name": route_name, "pokemon": []}
                current_section["routes"].append(route_entry)
            route_entry["pokemon"].append(pkmn_name)
        return ok(structured)
    except Exception as e:
        return err(str(e))

def get_evolution_data(params):
    try:
        result = db().table("evolutions").select("*").execute()
        evo_map = {}
        for r in result.data:
            base = r["base"]
            evolved = r["evolved"]
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
        result = db().table("evolutions").select("*").execute()
        next_evo_map = {}
        for r in result.data:
            s1 = r["base"]
            s2 = r["evolved"]
            s3 = r.get("stage3", "")
            if s1 and s2:
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
        result = db().table("trades").select("*").in_("version", ["Both", version]).execute()
        return ok([{"give": r["give"], "receive": r["receive"], "version": r["version"]} for r in result.data])
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

        wheel_result = db().table("wheels").select("pokemon").eq("section", section_name).in_("version", ["Both", version]).execute()
        section_pokemon = [r["pokemon"] for r in wheel_result.data]

        spun_result = db().table("journey_results").select("pokemon").eq("trainer", trainer_name).eq("section", section_name).in_("spin_type", ["Mandate", "Exclude"]).execute()
        spun = [r["pokemon"] for r in spun_result.data]

        available = [p for p in section_pokemon if p not in spun]
        list_to_use = available if available else section_pokemon
        random.shuffle(list_to_use)

        dex_result = db().table("pokedex").select("name,type1").execute()
        dex_map = {r["name"]: r.get("type1", "normal") for r in dex_result.data}

        wheel_items = [{"name": p, "image": "", "type": dex_map.get(p, "normal"), "weight": 1} for p in list_to_use]
        return ok({"wheelData": wheel_items, "currentGame": version, "targetRow": 0, "sectionName": section_name, "spinType": spin_type})
    except Exception as e:
        return err(str(e))

def get_elite4_wheel_data(params):
    try:
        version = params.get("version", ["FireRed"])[0]
        trainer_name = params.get("trainerName", [""])[0].lower()

        wheel_result = db().table("wheels").select("pokemon").eq("section", "Indigo Plateau").in_("version", ["Both", version]).execute()
        section_pokemon = [r["pokemon"] for r in wheel_result.data]

        excluded_result = db().table("journey_results").select("pokemon").eq("trainer", trainer_name).eq("spin_type", "Exclude").execute()
        excluded = [r["pokemon"] for r in excluded_result.data]

        caught_result = db().table("trainer_catches").select("pokemon").eq("trainer", trainer_name).execute()
        caught = [r["pokemon"] for r in caught_result.data]

        available = [p for p in section_pokemon if p not in excluded and p not in caught]
        if not available:
            return ok({"noNewPokemon": True})

        dex_result = db().table("pokedex").select("name,type1").execute()
        dex_map = {r["name"]: r.get("type1", "normal") for r in dex_result.data}

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

        wheel_result = db().table("wheels").select("pokemon").eq("section", section_name).in_("version", ["Both", version]).execute()
        section_pokemon = [r["pokemon"] for r in wheel_result.data]

        if section_name == "Indigo Plateau":
            excluded_result = db().table("journey_results").select("pokemon").eq("trainer", trainer_name).eq("spin_type", "Exclude").execute()
            excluded = [r["pokemon"] for r in excluded_result.data]
            caught_result = db().table("trainer_catches").select("pokemon").eq("trainer", trainer_name).execute()
            caught = [r["pokemon"] for r in caught_result.data]
            section_pokemon = [p for p in section_pokemon if p not in excluded and p not in caught]
            if not section_pokemon:
                return ok({"noNewPokemon": True})

        dex_result = db().table("pokedex").select("name,type1").execute()
        dex_map = {r["name"]: r.get("type1", "normal") for r in dex_result.data}

        random.shuffle(section_pokemon)
        picks = section_pokemon[:min(3, len(section_pokemon))]
        return ok({"picks": [{"name": p, "type": dex_map.get(p, "normal")} for p in picks], "sectionName": section_name})
    except Exception as e:
        return err(str(e))

def get_punishment_data(params):
    try:
        trainer_name = params.get("trainerName", [""])[0].lower()

        active_result = db().table("punishment_results").select("punishment").eq("trainer", trainer_name).execute()
        active_names = [r["punishment"] for r in active_result.data]

        pun_result = db().table("punishments").select("*").execute()
        formatted = []
        for r in pun_result.data:
            name = r["name"]
            if name in active_names:
                continue
            formatted.append({
                "name": name,
                "image": r.get("image", ""),
                "fullText": r.get("full_text", ""),
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

        def build_boss_entry(r):
            team = []
            for slot in range(1, 7):
                pkmn = r.get(f"slot{slot}_name", "")
                level = r.get(f"slot{slot}_level", "")
                if pkmn:
                    team.append({"name": pkmn, "level": level})
            return {
                "boss": r.get("boss", ""),
                "team": team,
                "notes": r.get("notes", ""),
                "version": r.get("version", "Both")
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
                result = db().table("bosses").select("*").eq("boss", ename).execute()
                if result.data:
                    entries.append(build_boss_entry(result.data[0]))
            champ_result = db().table("bosses").select("*").eq("boss", section_name).execute()
            for r in champ_result.data:
                entries.append(build_boss_entry(r))
            return ok({"multiRow": True, "entries": entries})

        result = db().table("bosses").select("*").eq("boss", section_name).in_("version", [version, "Both"]).execute()
        if not result.data:
            return ok(None)
        # Prefer exact version match
        match = next((r for r in result.data if r.get("version") == version), result.data[0])
        return ok({"multiRow": False, "entries": [build_boss_entry(match)]})
    except Exception as e:
        return err(str(e))

# ============================================================
# JOURNEY RESULTS
# ============================================================

def save_journey_result(body):
    try:
        trainer = body.get("trainerName", "unknown").strip().lower()
        db().table("journey_results").insert({
            "trainer": trainer,
            "section": body.get("sectionName", ""),
            "spin_type": body.get("spinType", ""),
            "pokemon": body.get("pokemon", ""),
            "version": body.get("version", "")
        }).execute()
        return ok("Success")
    except Exception as e:
        return err(str(e))

def delete_journey_result(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        section_name = body.get("sectionName", "").strip()
        spin_type = body.get("spinType", "").strip()
        db().table("journey_results").delete().eq("trainer", trainer).eq("section", section_name).eq("spin_type", spin_type).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def delete_2player_picks(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        section_name = body.get("sectionName", "").strip()
        db().table("journey_results").delete().eq("trainer", trainer).eq("section", section_name).in_("spin_type", ["Pick1", "Pick2", "Pick3"]).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

# ============================================================
# CATCHES
# ============================================================

def record_catch(body):
    try:
        trainer = body.get("trainerName", "unknown").strip().lower()
        pkmn_name = body.get("pkmnName", "")
        route_id = body.get("routeId", "")
        version = body.get("version", "FireRed")

        if pkmn_name == "__UNCATCH__":
            db().table("trainer_catches").delete().eq("trainer", trainer).eq("route_id", route_id).execute()
            return ok(True)

        existing = db().table("trainer_catches").select("id").eq("trainer", trainer).eq("route_id", route_id).execute()
        if existing.data:
            db().table("trainer_catches").update({"pokemon": pkmn_name, "version": version}).eq("trainer", trainer).eq("route_id", route_id).execute()
        else:
            db().table("trainer_catches").insert({
                "trainer": trainer,
                "route_id": route_id,
                "pokemon": pkmn_name,
                "version": version,
                "status": "",
                "original_pokemon": "",
                "trade_status": ""
            }).execute()
        return ok(True)
    except Exception as e:
        return err(str(e))

def save_fainted_pokemon(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        pkmn_name = body.get("pkmnName", "").strip()
        fainted = body.get("fainted", False)
        db().table("trainer_catches").update({"status": "fainted" if fainted else ""}).eq("trainer", trainer).eq("route_id", route_id).eq("pokemon", pkmn_name).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def save_pokemon_evolution(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        old_name = body.get("oldName", "").strip()
        new_name = body.get("newName", "").strip()
        db().table("trainer_catches").update({"pokemon": new_name}).eq("trainer", trainer).eq("route_id", route_id).eq("pokemon", old_name).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def save_pokemon_trade(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        old_name = body.get("oldName", "").strip()
        new_name = body.get("newName", "").strip()
        db().table("trainer_catches").update({
            "pokemon": new_name,
            "original_pokemon": old_name,
            "trade_status": "traded"
        }).eq("trainer", trainer).eq("route_id", route_id).eq("pokemon", old_name).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def undo_pokemon_trade(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        route_id = body.get("routeId", "").strip()
        current_name = body.get("currentName", "").strip()
        original_name = body.get("originalName", "").strip()
        db().table("trainer_catches").update({
            "pokemon": original_name,
            "original_pokemon": "",
            "trade_status": ""
        }).eq("trainer", trainer).eq("route_id", route_id).eq("pokemon", current_name).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

# ============================================================
# PUNISHMENTS
# ============================================================

def save_punishment_result(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        db().table("punishment_results").insert({
            "trainer": trainer,
            "punishment": body.get("punishment", ""),
            "full_text": body.get("fullText", ""),
            "duration": body.get("duration", 1),
            "section_spun": body.get("sectionSpun", ""),
            "expires_after_section": body.get("expiresAfterSection", "")
        }).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def delete_punishment_result(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        punishment = body.get("punishment", "").strip()
        section_spun = body.get("sectionSpun", "").strip()
        db().table("punishment_results").delete().eq("trainer", trainer).eq("punishment", punishment).eq("section_spun", section_spun).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

# ============================================================
# BOSS BATTLE LOG
# ============================================================

def save_boss_battle_log(body):
    try:
        trainer = body.get("trainerName", "").strip().lower()
        slots = body.get("slots", [])
        db().table("boss_battle_log").insert({
            "trainer": trainer,
            "section": body.get("sectionName", ""),
            "slot1": slots[0] if len(slots) > 0 else "",
            "slot2": slots[1] if len(slots) > 1 else "",
            "slot3": slots[2] if len(slots) > 2 else "",
            "slot4": slots[3] if len(slots) > 3 else "",
            "slot5": slots[4] if len(slots) > 4 else "",
            "slot6": slots[5] if len(slots) > 5 else "",
            "result": body.get("result", ""),
            "timestamp": datetime.now().isoformat()
        }).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def get_boss_battle_log(params):
    try:
        trainer = params.get("trainerName", [""])[0].lower()
        section_name = params.get("sectionName", [""])[0]
        result = db().table("boss_battle_log").select("*").eq("trainer", trainer).eq("section", section_name).execute()
        rows = [
            {"slots": [r[f"slot{i}"] for i in range(1,7) if r.get(f"slot{i}")], "result": r.get("result", "")}
            for r in result.data
        ]
        return ok(rows)
    except Exception as e:
        return err(str(e))

def get_defeated_sections(params):
    try:
        trainer = params.get("trainerName", [""])[0].lower()
        result = db().table("boss_battle_log").select("section").eq("trainer", trainer).eq("result", "Defeated").execute()
        defeated = []
        for r in result.data:
            sn = r["section"]
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
        result = db().table("trainers").select("trainer,display_name").execute()
        results = []
        for r in result.data:
            trainer_key = r["trainer"]
            display_name = r.get("display_name") or trainer_key
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

        existing = db().table("friends").select("*").or_(
            f"and(requester.eq.{req},recipient.eq.{rec}),and(requester.eq.{rec},recipient.eq.{req})"
        ).execute()

        if existing.data:
            r = existing.data[0]
            status = r["status"]
            if status == "accepted":
                return err("You are already friends!")
            if status == "pending":
                return ok({"success": True})
            if status == "declined":
                db().table("friends").update({"status": "pending", "timestamp": datetime.now().isoformat()}).eq("id", r["id"]).execute()
                return ok({"success": True})

        db().table("friends").insert({
            "requester": req,
            "recipient": rec,
            "status": "pending",
            "timestamp": datetime.now().isoformat()
        }).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def accept_friend_request(body):
    try:
        rec = body.get("recipientName", "").strip().lower()
        req = body.get("requesterName", "").strip().lower()
        db().table("friends").update({"status": "accepted"}).eq("requester", req).eq("recipient", rec).eq("status", "pending").execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def decline_friend_request(body):
    try:
        rec = body.get("recipientName", "").strip().lower()
        req = body.get("requesterName", "").strip().lower()
        db().table("friends").update({"status": "declined"}).eq("requester", req).eq("recipient", rec).eq("status", "pending").execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def remove_friend(body):
    try:
        t = body.get("trainerName", "").strip().lower()
        f = body.get("friendName", "").strip().lower()
        db().table("friends").delete().or_(
            f"and(requester.eq.{t},recipient.eq.{f}),and(requester.eq.{f},recipient.eq.{t})"
        ).execute()
        return ok({"success": True})
    except Exception as e:
        return err(str(e))

def get_friend_view_data(params):
    try:
        friend_name = params.get("friendTrainerName", [""])[0].strip().lower()

        trainer_result = db().table("trainers").select("*").eq("trainer", friend_name).execute()
        if not trainer_result.data:
            return err("Trainer not found.")
        row = trainer_result.data[0]
        display_name = row.get("display_name") or friend_name
        version = row.get("version") or "FireRed"
        game_mode = row.get("game_mode") or "solo"

        journey_data = db().table("journey_results").select("*").eq("trainer", friend_name).execute()
        catches_data = db().table("trainer_catches").select("*").eq("trainer", friend_name).execute()
        pun_data = db().table("punishment_results").select("*").eq("trainer", friend_name).execute()

        sections_result = db().table("sections").select("*").order("id").execute()
        sections_data = [{
            "shortName": r["short_name"],
            "fullName": r.get("full_name", ""),
            "bossImage": r.get("boss_image", ""),
            "levelCap": r.get("level_cap", "")
        } for r in sections_result.data]

        evo_result = db().table("evolutions").select("*").execute()
        evo_map = {}
        for r in evo_result.data:
            base = r["base"]
            evolved = r["evolved"]
            evo_map.setdefault(base, [])
            evo_map.setdefault(evolved, [])
            if evolved not in evo_map[base]:
                evo_map[base].append(evolved)
            if base not in evo_map[evolved]:
                evo_map[evolved].append(base)

        enc_result = db().table("master_encounters").select("*").in_("version", ["Both", version]).order("id").execute()
        encounter_data = {}
        for r in enc_result.data:
            sec = r["section"]
            route_name = r["route"]
            pkmn_name = r["pokemon"]
            encounter_data.setdefault(sec, [])
            route_entry = next((rt for rt in encounter_data[sec] if rt["name"] == route_name), None)
            if not route_entry:
                route_entry = {"name": route_name, "pokemon": []}
                encounter_data[sec].append(route_entry)
            route_entry["pokemon"].append(pkmn_name)

        bbl_result = db().table("boss_battle_log").select("section").eq("trainer", friend_name).eq("result", "Defeated").execute()
        defeated_sections = []
        for r in bbl_result.data:
            sn = r["section"]
            if sn not in defeated_sections:
                defeated_sections.append(sn)

        spin_map = {}
        for r in journey_data.data:
            sec = r["section"]
            type_ = r["spin_type"]
            pkmn = r["pokemon"]
            spin_map.setdefault(sec, {"picks": []})
            if type_ == "Mandate":
                spin_map[sec]["mandate"] = pkmn
            elif type_ == "Exclude":
                spin_map[sec]["exclude"] = pkmn
            elif type_ in ["Pick1", "Pick2", "Pick3"]:
                spin_map[sec]["picks"].append({"spinType": type_, "pokemon": pkmn})

        catch_map = {}
        for r in catches_data.data:
            catch_map[r["route_id"]] = {
                "name": r["pokemon"],
                "fainted": r.get("status", "") == "fainted",
                "originalName": r.get("original_pokemon", ""),
                "traded": r.get("trade_status", "") == "traded"
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

        all_mandate_names = [r["pokemon"] for r in journey_data.data if r["spin_type"] == "Mandate"]

        team_mandatory, team_regular, team_graveyard = [], [], []
        for r in catches_data.data:
            catch_name = r["pokemon"]
            fainted = r.get("status", "") == "fainted"
            traded = r.get("trade_status", "") == "traded"
            original_name = r.get("original_pokemon", "")
            route = r["route_id"]
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
        for p in pun_data.data:
            exp_idx = len(sections_data) - 1
            for i, sec in enumerate(sections_data):
                if sec["shortName"] == p.get("expires_after_section", ""):
                    exp_idx = i
                    break
            if exp_idx >= current_section_index:
                active_punishments.append([
                    p.get("trainer", ""),
                    p.get("punishment", ""),
                    p.get("full_text", ""),
                    p.get("duration", 1),
                    p.get("section_spun", ""),
                    p.get("expires_after_section", "")
                ])

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
        result = db().table("trainers").select("share_code,display_name").eq("trainer", friend_name).execute()
        if not result.data:
            return err("Trainer not found.")
        row = result.data[0]
        share_code = row.get("share_code", "")
        if not share_code:
            return err("This trainer hasn't generated a share link yet.")
        display_name = row.get("display_name") or friend_name
        base_url = os.environ.get("VERCEL_URL", "")
        if base_url and not base_url.startswith("http"):
            base_url = "https://" + base_url
        url = f"{base_url}/friend?code={friend_name}-{share_code}"
        return ok({"success": True, "url": url, "displayName": display_name})
    except Exception as e:
        return err(str(e))

def log_image_error(body):
    try:
        db().table("errors").insert({
            "timestamp": datetime.now().isoformat(),
            "trainer": body.get("trainerName", "unknown"),
            "image_type": body.get("imageType", ""),
            "game_version": body.get("gameVersion", ""),
            "game_section": body.get("gameSection", ""),
            "image_name": body.get("imageName", "")
        }).execute()
        return ok(True)
    except Exception as e:
        return err(str(e))

def get_web_app_url(params):
    base_url = os.environ.get("VERCEL_URL", "")
    if base_url and not base_url.startswith("http"):
        base_url = "https://" + base_url
    return ok(base_url)

# ============================================================
# PICKS STATE
# ============================================================

def get_picks_state(params):
    try:
        trainer = params.get("trainer", [""])[0].strip().lower()
        section_name = params.get("section", [""])[0].strip()

        result = db().table("journey_results").select("*").eq("trainer", trainer).eq("section", section_name).execute()
        picks = sorted(
            [{"spinType": r["spin_type"], "pokemon": r["pokemon"]} for r in result.data if r["spin_type"] in ["Pick1","Pick2","Pick3"]],
            key=lambda x: x["spinType"]
        )
        mandate = next((r["pokemon"] for r in result.data if r["spin_type"] == "Mandate"), None)
        exclude = next((r["pokemon"] for r in result.data if r["spin_type"] == "Exclude"), None)
        return ok({"success": True, "picks": picks, "mandate": mandate, "exclude": exclude})
    except Exception as e:
        return err(str(e))

# ============================================================
# SERVE PICKS PAGE
# ============================================================

def serve_picks_html(params):
    try:
        trainer = params.get("trainer", [""])[0].strip().lower()
        section_name = params.get("section", [""])[0].strip()

        journey_result = db().table("journey_results").select("*").eq("trainer", trainer).eq("section", section_name).execute()

        picks = sorted(
            [r for r in journey_result.data if r["spin_type"] in ["Pick1","Pick2","Pick3"]],
            key=lambda r: r["spin_type"]
        )
        mandate_row = next((r for r in journey_result.data if r["spin_type"] == "Mandate"), None)
        exclude_row = next((r for r in journey_result.data if r["spin_type"] == "Exclude"), None)

        trainer_result = db().table("trainers").select("display_name,version").eq("trainer", trainer).execute()
        display_name = trainer
        trainer_version = "FireRed"
        if trainer_result.data:
            display_name = trainer_result.data[0].get("display_name") or trainer
            trainer_version = trainer_result.data[0].get("version") or "FireRed"

        base_url = "https://lotto-locke-app.vercel.app"
        api_base = "https://lotto-locke-api.onrender.com"

        mandate = mandate_row["pokemon"] if mandate_row else None
        exclude = exclude_row["pokemon"] if exclude_row else None
        already_chosen = mandate and exclude

        def pkmn_img(name):
            img_name = name.lower().replace(" ", "-").replace(".", "").replace("'", "")
            if name == "Nidoran\u2640": img_name = "nidoran-f"
            if name == "Nidoran\u2642": img_name = "nidoran-m"
            return f"https://img.pokemondb.net/sprites/heartgold-soulsilver/normal/{img_name}.png"

        def build_picks_html(picks, mandate, exclude):
            if not picks:
                return '<p style="color:#aaa;text-align:center;">No picks have been generated for this section yet.</p>'
            html = ""
            for idx, pick_row in enumerate(picks):
                pkmn = pick_row["pokemon"]
                img_url = pkmn_img(pkmn)
                is_mandated = mandate == pkmn
                is_excluded = exclude == pkmn
                border = "#2ed573" if is_mandated else ("#ff4757" if is_excluded else "#444")
                bg = "#1a2e21" if is_mandated else ("#2e1a1a" if is_excluded else "#2a2a2a")
                html += f'<div style="background:{bg};border-radius:14px;padding:16px;text-align:center;border:2px solid {border};flex:1;min-width:110px;max-width:160px;">'
                html += f'<div style="color:#aaa;font-size:11px;margin-bottom:6px;">Option {idx+1}</div>'
                html += f'<img src="{img_url}" style="width:70px;height:70px;" onerror="this.onerror=null;">'
                html += f'<div style="font-weight:bold;font-size:14px;margin-top:6px;color:#fff;">{pkmn}</div>'
                if is_mandated:
                    html += f'<div style="background:#2ed573;color:#000;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">&#10003; Mandated<button class="unchoose-btn" data-type="Mandate" style="background:none;border:none;color:#000;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.6;">&#x2715;</button></div>'
                elif is_excluded:
                    html += f'<div style="background:#ff4757;color:#fff;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">&#10007; Excluded<button class="unchoose-btn" data-type="Exclude" style="background:none;border:none;color:#fff;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.7;">&#x2715;</button></div>'
                else:
                    html += '<div style="display:flex;flex-direction:column;gap:4px;margin-top:8px;">'
                    if not mandate:
                        html += f'<button class="choose-btn" data-pkmn="{pkmn}" data-type="Mandate" style="background:#2ed573;color:#000;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">&#10003; Mandate</button>'
                    if not exclude:
                        html += f'<button class="choose-btn" data-pkmn="{pkmn}" data-type="Exclude" style="background:#ff4757;color:#fff;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">&#10007; Exclude</button>'
                    html += '</div>'
                html += '</div>'
            return html

        picks_html = build_picks_html(picks, mandate, exclude)
        status_msg = '<div style="background:#1a2e21;border:1px solid #2ed573;border-radius:10px;padding:12px;margin-bottom:16px;color:#2ed573;font-size:13px;text-align:center;">Both picks have been made for this section!</div>' if already_chosen else ""

        html = f'''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{margin:0;padding:0;background:#1a1a1a;color:white;font-family:'Segoe UI',sans-serif;}}
.container{{max-width:560px;margin:0 auto;padding:20px 14px;}}
h1{{color:#ff4757;font-size:20px;margin-bottom:4px;}}
.subtitle{{color:#aaa;font-size:13px;margin-bottom:18px;}}
.picks-row{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:16px;}}
.start-btn{{display:block;max-width:280px;margin:24px auto 0;padding:14px;background:#ff4757;color:white;border:none;border-radius:12px;font-size:14px;font-weight:bold;cursor:pointer;text-align:center;text-decoration:none;}}
#status{{color:#2ed573;font-size:13px;margin-top:10px;text-align:center;min-height:20px;}}
</style>
</head><body>
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
var API_BASE = "{api_base}";
var TRAINER = "{trainer}";
var SECTION = "{section_name}";
var VERSION = "{trainer_version}";

function setStatus(msg) {{
    document.getElementById("status").innerText = msg;
}}

function disableButtons() {{
    var btns = document.querySelectorAll("button");
    for (var i = 0; i < btns.length; i++) btns[i].disabled = true;
}}

function choose(pkmn, spinType) {{
    disableButtons();
    setStatus("Saving...");
    fetch(API_BASE + "?action=saveJourneyResult", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{trainerName: TRAINER, sectionName: SECTION, spinType: spinType, pokemon: pkmn, version: VERSION}})
    }})
    .then(function() {{
        return fetch(API_BASE + "?action=getPicksState&trainer=" + encodeURIComponent(TRAINER) + "&section=" + encodeURIComponent(SECTION));
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(state) {{
        renderPicksFromState(state);
        setStatus("");
    }})
    .catch(function() {{ setStatus("Error saving. Please refresh the page."); }});
}}

function unchoose(spinType) {{
    disableButtons();
    setStatus("Removing...");
    fetch(API_BASE + "?action=deleteJourneyResult", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{trainerName: TRAINER, sectionName: SECTION, spinType: spinType}})
    }})
    .then(function() {{
        return fetch(API_BASE + "?action=getPicksState&trainer=" + encodeURIComponent(TRAINER) + "&section=" + encodeURIComponent(SECTION));
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(state) {{
        renderPicksFromState(state);
        setStatus("");
    }})
    .catch(function() {{ setStatus("Error. Please refresh the page."); }});
}}

function attachListeners() {{
    document.querySelectorAll(".choose-btn").forEach(function(btn) {{
        btn.addEventListener("click", function() {{
            choose(this.getAttribute("data-pkmn"), this.getAttribute("data-type"));
        }});
    }});
    document.querySelectorAll(".unchoose-btn").forEach(function(btn) {{
        btn.addEventListener("click", function() {{
            unchoose(this.getAttribute("data-type"));
        }});
    }});
}}

function renderPicksFromState(state) {{
    var picks = state.picks || [];
    var mandate = state.mandate;
    var exclude = state.exclude;
    var allChosen = mandate && exclude;
    var html = "";
    picks.forEach(function(pick, idx) {{
        var pkmn = pick.pokemon;
        var imgName = pkmn.toLowerCase().replace(/\s+/g, "-").replace(/\./g, "").replace(/'/g, "");
        if (pkmn === "Nidoran\u2640") imgName = "nidoran-f";
        if (pkmn === "Nidoran\u2642") imgName = "nidoran-m";
        var hgUrl = "https://img.pokemondb.net/sprites/heartgold-soulsilver/normal/" + imgName + ".png";
        var isMandated = mandate === pkmn;
        var isExcluded = exclude === pkmn;
        var border = isMandated ? "#2ed573" : (isExcluded ? "#ff4757" : "#444");
        var bg = isMandated ? "#1a2e21" : (isExcluded ? "#2e1a1a" : "#2a2a2a");
        html += '<div style="background:' + bg + ';border-radius:14px;padding:16px;text-align:center;border:2px solid ' + border + ';flex:1;min-width:110px;max-width:160px;">';
        html += '<div style="color:#aaa;font-size:11px;margin-bottom:6px;">Option ' + (idx+1) + '</div>';
        html += '<img src="' + hgUrl + '" style="width:70px;height:70px;" onerror="this.onerror=null;">';
        html += '<div style="font-weight:bold;font-size:14px;margin-top:6px;color:#fff;">' + pkmn + '</div>';
        if (isMandated) {{
            html += '<div style="background:#2ed573;color:#000;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">\u2713 Mandated<button class="unchoose-btn" data-type="Mandate" style="background:none;border:none;color:#000;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.6;">&#x2715;</button></div>';
        }} else if (isExcluded) {{
            html += '<div style="background:#ff4757;color:#fff;padding:4px 8px;border-radius:8px;font-size:11px;font-weight:bold;margin-top:6px;display:flex;align-items:center;justify-content:center;gap:6px;">\u2717 Excluded<button class="unchoose-btn" data-type="Exclude" style="background:none;border:none;color:#fff;font-size:14px;cursor:pointer;padding:0;line-height:1;opacity:0.7;">&#x2715;</button></div>';
        }} else {{
            html += '<div style="display:flex;flex-direction:column;gap:4px;margin-top:8px;">';
            if (!mandate) html += '<button class="choose-btn" data-pkmn="' + pkmn + '" data-type="Mandate" style="background:#2ed573;color:#000;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">\u2713 Mandate</button>';
            if (!exclude) html += '<button class="choose-btn" data-pkmn="' + pkmn + '" data-type="Exclude" style="background:#ff4757;color:#fff;border:none;border-radius:6px;padding:7px;font-weight:bold;cursor:pointer;font-size:11px;">\u2717 Exclude</button>';
            html += '</div>';
        }}
        html += '</div>';
    }});
    document.getElementById("picks-row").innerHTML = html;
    attachListeners();
    if (allChosen) {{
        var existing = document.getElementById("all-chosen-msg");
        if (!existing) {{
            var msg = document.createElement("div");
            msg.id = "all-chosen-msg";
            msg.style = "background:#1a2e21;border:1px solid #2ed573;border-radius:10px;padding:12px;margin-bottom:16px;color:#2ed573;font-size:13px;text-align:center;";
            msg.innerText = "Both picks have been made for this section!";
            document.getElementById("picks-row").parentNode.insertBefore(msg, document.getElementById("picks-row"));
        }}
    }}
}}

document.addEventListener("DOMContentLoaded", function() {{
    attachListeners();
}});
</script>
</body></html>'''
        return html, "text/html"
    except Exception as e:
        return f"<html><body style='background:#1a1a1a;color:white;padding:30px;'><h2>Error</h2><p>{str(e)}</p></body></html>", "text/html"

def serve_friend_view_html(params):
    try:
        code = params.get("code", [""])[0]
        if not code:
            return "<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Invalid link</h2></body></html>", "text/html"

        parts = code.rsplit("-", 1)
        if len(parts) != 2:
            return "<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Invalid link</h2></body></html>", "text/html"

        trainer_name, share_code = parts[0].lower(), parts[1]

        result = db().table("trainers").select("share_code").eq("trainer", trainer_name).execute()
        if not result.data or result.data[0].get("share_code") != share_code:
            return "<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Journey not found</h2><p style='color:#aaa;'>This link may be invalid or expired.</p></body></html>", "text/html"

        data_json = get_friend_view_data({"friendTrainerName": [trainer_name]})
        data = json.loads(data_json)
        if "error" in data:
            return f"<html><body style='background:#1a1a1a;color:white;padding:30px;text-align:center;'><h2>Error</h2><p>{data['error']}</p></body></html>", "text/html"

        base_url = "https://lotto-locke-app.vercel.app"

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
        "Indigo Plateau": {"emoji": "\U0001f3c6", "name": "Kanto Champion"},
        "Post-game": {"emoji": "\u2b50", "name": "Complete!"}
    }

    def pkmn_img(name):
        img = name.lower().replace(" ", "-").replace(".", "").replace("'", "")
        if name == "Nidoran\u2640": img = "nidoran-f"
        if name == "Nidoran\u2642": img = "nidoran-m"
        return f"https://img.pokemondb.net/sprites/heartgold-soulsilver/normal/{img}.png"

    def team_card(p):
        route_label = "Trade" if p.get("traded") else p.get("route", "").replace("route-", "").replace("-", " ")
        color = "#f0a500" if p.get("traded") else "#bbb"
        mand_class = " mandatory" if p.get("isMand") else ""
        faint_class = " fainted" if p.get("fainted") else ""
        skull = '<div class="fainted-overlay" style="cursor:default;pointer-events:none;">\U0001f480</div>' if p.get("fainted") else ""
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
            team_html += '<div id="team-graveyard-box"><div style="font-size:11px;font-weight:bold;color:#666;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">\U0001f480 Graveyard</div><div id="team-graveyard-grid">'
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
    STARTERS = ["Bulbasaur", "Charmander", "Squirtle"]
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

        boss_img = f'<img class="section-boss-img" src="{section["bossImage"]}" onerror="this.style.display=\'none\'">' if section.get("bossImage") else '<div class="section-boss-placeholder">&#127942;</div>'

        card = f'<div class="section-card{" current" if is_current else ""}{" completed" if is_completed else ""}">'
        card += f'<div class="section-card-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">'
        card += boss_img
        card += f'<div class="section-info"><div class="section-name">{section["shortName"]}'
        if is_current: card += ' <span class="current-badge">CURRENT</span>'
        card += f'</div><div class="section-fullname">{section["fullName"]}</div></div>'
        card += f'<div class="section-levelcap">Lv.{section["levelCap"]}</div>'
        if badge_html: card += badge_html
        card += '</div>'
        card += f'<div class="section-card-body{" open" if is_current else ""}">'

        step = 1
        if index > 0:
            card += f'<div class="step-label">Step {step}: Punishment Wheel</div>'
            step += 1
            sec_pun = next((p for p in active_punishments if len(p) > 4 and p[4] == section["shortName"]), None)
            if sec_pun:
                card += f'<div class="punishment-spin-result"><div style="flex:1;"><div class="punishment-spin-result-name">Punishment: {sec_pun[1]}</div><div style="color:#ccc;font-size:11px;margin-top:2px;">{sec_pun[2] if len(sec_pun)>2 else ""}</div><div style="font-size:10px;color:#ccc;margin-top:2px;">Until after: {sec_pun[5] if len(sec_pun)>5 else ""}</div></div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">No punishment spun yet.</div>'

        if game_mode == "solo":
            card += f'<div class="step-label">Step {step}: Exclude Wheel</div>'; step += 1
            if spins.get("exclude"):
                card += f'<div class="spin-result" style="border-left:4px solid #ff4757;"><img src="{pkmn_img(spins["exclude"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Excluded</div><div class="spin-result-name">{spins["exclude"]}</div></div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Not yet spun.</div>'
            card += f'<div class="step-label">Step {step}: Mandate Wheel</div>'; step += 1
            if spins.get("mandate"):
                card += f'<div class="spin-result" style="border-left:4px solid #2ed573;"><img src="{pkmn_img(spins["mandate"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Mandated</div><div class="spin-result-name">{spins["mandate"]}</div></div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Not yet spun.</div>'
        else:
            card += f'<div class="step-label">Step {step}: Friend\'s Picks</div>'; step += 1
            if spins.get("mandate") and spins.get("exclude"):
                card += f'<div class="spin-result" style="border-left:4px solid #ff4757;margin-bottom:4px;"><img src="{pkmn_img(spins["exclude"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Excluded</div><div class="spin-result-name">{spins["exclude"]}</div></div></div>'
                card += f'<div class="spin-result" style="border-left:4px solid #2ed573;"><img src="{pkmn_img(spins["mandate"])}" style="width:44px;height:44px;" onerror="this.onerror=null;"><div><div class="spin-result-label">Mandated</div><div class="spin-result-name">{spins["mandate"]}</div></div></div>'
            elif spins.get("picks"):
                card += '<div class="picks-container"><div class="picks-row">'
                for idx2, pick in enumerate(sorted(spins["picks"], key=lambda x: x["spinType"])):
                    is_mand = spins.get("mandate") == pick["pokemon"]
                    is_excl = spins.get("exclude") == pick["pokemon"]
                    card += f'<div class="pick-card{" pick-mandated" if is_mand else ""}{" pick-excluded" if is_excl else ""}"><div class="pick-card-label">Option {idx2+1}</div><img src="{pkmn_img(pick["pokemon"])}" style="width:56px;height:56px;" onerror="this.onerror=null;"><div class="pick-card-name">{pick["pokemon"]}</div>'
                    if is_mand: card += '<div class="pick-chosen-label pick-chosen-mandate">&#x2713; Mandated</div>'
                    elif is_excl: card += '<div class="pick-chosen-label pick-chosen-exclude">&#x2717; Excluded</div>'
                    card += '</div>'
                card += '</div></div>'
            else:
                card += '<div style="font-size:11px;color:#555;font-style:italic;padding:4px 0;">Picks not yet generated.</div>'

        if section["shortName"] == "Brock":
            card += f'<div class="step-label">Step {step}: Starter Pokemon</div>'; step += 1
            oaks = next((r for r in encounter_data.get(section["shortName"], []) if r["name"] == "Oak's Lab"), None)
            starter_pool = oaks["pokemon"] if oaks else STARTERS
            card += '<div class="starter-section"><div class="starter-section-label">&#127981; Oak\'s Lab</div><div class="pkmn-grid">'
            for pn in starter_pool:
                is_caught = starter_catch and starter_catch.get("name") == pn
                is_locked = starter_catch and not is_caught
                cc = "selected" if is_caught else ("locked" if is_locked else "")
                card += f'<div class="pkmn-card {cc}" style="cursor:default;"><img src="{pkmn_img(pn)}" onerror="this.onerror=null;" loading="lazy"><br>{pn}</div>'
            card += '</div></div>'

        card += f'<div class="step-label">Step {step}: Pokemon Caught</div>'; step += 1
        routes = encounter_data.get(section["shortName"], [])
        catch_routes = [r for r in routes if r["name"] != "Oak's Lab"] if section["shortName"] == "Brock" else routes
        if catch_routes:
            card += '<div class="encounter-section">'
            for route in catch_routes:
                route_id = "route-" + route["name"].replace(" ", "-").replace("'", "")
                caught_here = catch_map.get(route_id)
                card += f'<div class="route-row{" completed" if caught_here else ""}"><div class="route-label">{route["name"]}</div><div class="pkmn-grid">'
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
        pass

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

        if parsed.path == "/friend":
            html, _ = serve_friend_view_html(params)
            self.send_html(html)
            return
        if parsed.path == "/picks":
            html, _ = serve_picks_html(params)
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