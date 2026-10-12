#!/usr/bin/env python3
"""Regenerate the site's operator/material data from PRTS.

The updater is deliberately conservative: it builds everything in memory, validates
the result, and only then replaces tracked files.  PRTS page revision IDs are kept
so unchanged pages can reuse the currently published records on later runs.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DATA = DIST / "data"
STATE_PATH = ROOT / "data-update-state.json"
REPORT_PATH = ROOT / "data-update-report.json"
API = "https://prts.wiki/api.php"
GAME_BASE = "https://raw.githubusercontent.com/fexli/ArknightsResource/master"
USER_AGENT = "operator-material-planner-updater/1.0 (https://github.com/Confetti-lxy/operator-material-planner)"
EXCLUDED_MATERIALS = {"芯片助剂", "模组数据块", "数据增补仪", "数据增补条"}
COLORS = {0: "灰色", 1: "绿色", 2: "蓝色", 3: "紫色", 4: "金色"}
PAGE_OVERRIDES: dict[str, str] = {}
PROFESSIONS = {
    "PIONEER": "先锋", "WARRIOR": "近卫", "TANK": "重装", "SNIPER": "狙击",
    "CASTER": "术师", "MEDIC": "医疗", "SUPPORT": "辅助", "SPECIAL": "特种",
}
NAME_OVERRIDES = {
    "阿米娅": "char_002_amiya", "阿米娅(近卫)": "char_1001_amiya2", "阿米娅(医疗)": "char_1037_amiya3",
}
AVATAR_ID_OVERRIDES = {"char_1037_amiya3": "char_1037_amiya3_2"}


def request_json(url: str, params: dict[str, str] | None = None, retries: int = 4) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except Exception as exc:
            error = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed after {retries} attempts: {url}: {error}")


def cargo_query(table: str, fields: str, where: str = "", limit: int = 2000) -> list[dict]:
    params = {"action": "cargoquery", "tables": table, "fields": fields, "limit": str(limit), "format": "json"}
    if where:
        params["where"] = where
    payload = request_json(API, params)
    if "error" in payload:
        raise RuntimeError(f"PRTS Cargo error: {payload['error']}")
    return [row["title"] for row in payload.get("cargoquery", [])]


def page_source(title: str) -> tuple[int, str]:
    payload = request_json(API, {
        "action": "parse", "page": title, "prop": "wikitext|revid", "format": "json", "formatversion": "2",
    })
    if "parse" not in payload:
        raise RuntimeError(f"PRTS page not found: {title}: {payload.get('error')}")
    return int(payload["parse"]["revid"]), payload["parse"]["wikitext"]


def page_revisions(titles: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for start in range(0, len(titles), 50):
        payload = request_json(API, {
            "action": "query", "prop": "revisions", "titles": "|".join(titles[start:start + 50]),
            "rvprop": "ids", "format": "json", "formatversion": "2",
        })
        for page in payload.get("query", {}).get("pages", []):
            if not page.get("missing") and page.get("revisions"):
                result[page["title"]] = int(page["revisions"][0]["revid"])
        time.sleep(0.15)
    return result


def page_sources(titles: list[str], batch_size: int = 10) -> dict[str, tuple[int, str]]:
    """Fetch source for several pages per request to be polite to PRTS."""
    result: dict[str, tuple[int, str]] = {}
    for start in range(0, len(titles), batch_size):
        payload = request_json(API, {
            "action": "query", "prop": "revisions", "titles": "|".join(titles[start:start + batch_size]),
            "rvprop": "ids|content", "rvslots": "main", "format": "json", "formatversion": "2",
        })
        for page in payload.get("query", {}).get("pages", []):
            if page.get("missing") or not page.get("revisions"): continue
            revision = page["revisions"][0]
            result[page["title"]] = (int(revision["revid"]), revision["slots"]["main"]["content"])
        time.sleep(0.3)
    return result


def split_top_level(value: str, separator: str) -> list[str]:
    parts, start, curly, square = [], 0, 0, 0
    i = 0
    while i < len(value):
        pair = value[i:i + 2]
        if pair == "{{": curly += 1; i += 2; continue
        if pair == "}}": curly = max(0, curly - 1); i += 2; continue
        if pair == "[[": square += 1; i += 2; continue
        if pair == "]]": square = max(0, square - 1); i += 2; continue
        if value[i] == separator and curly == 0 and square == 0:
            parts.append(value[start:i]); start = i + 1
        i += 1
    parts.append(value[start:])
    return parts


def templates(text: str, wanted: set[str] | None = None):
    i = 0
    while True:
        start = text.find("{{", i)
        if start < 0: return
        depth, pos = 1, start + 2
        while pos < len(text) and depth:
            if text.startswith("{{", pos): depth += 1; pos += 2
            elif text.startswith("}}", pos): depth -= 1; pos += 2
            else: pos += 1
        if depth: return
        raw = text[start + 2:pos - 2]
        pieces = split_top_level(raw, "|")
        name = pieces[0].strip().replace("Template:", "")
        if wanted is None or name in wanted:
            params, positional = {}, []
            for piece in pieces[1:]:
                equals = split_top_level(piece, "=")
                if len(equals) > 1:
                    params[equals[0].strip()] = "=".join(equals[1:]).strip()
                else:
                    positional.append(piece.strip())
            yield name, params, positional, raw
        i = pos


def material_costs(text: str, allowed: set[str]) -> list[dict]:
    costs = []
    for _, _, positional, _ in templates(text, {"材料消耗"}):
        if len(positional) < 2 or positional[0] not in allowed:
            continue
        quantity = positional[1].strip().lower().replace("万", "0000").replace("w", "0000")
        if not quantity.isdigit():
            raise ValueError(f"unsupported quantity {positional[1]!r} for {positional[0]}")
        costs.append({"name": positional[0], "quantity": int(quantity)})
    return costs


def parse_operator(name: str, rarity: int, text: str, allowed: set[str]) -> dict:
    result = {"rarity": rarity, "elite_materials": {}, "mastery_materials": {}, "modules": {}}
    elite = next(templates(text, {"精英化材料"}), None)
    if elite:
        for source, target in (("精1", "0_to_1"), ("精2", "1_to_2")):
            costs = material_costs(elite[1].get(source, ""), allowed)
            if source in elite[1]: result["elite_materials"][target] = costs

    skill_names = []
    for _, params, _, _ in templates(text, {"技能", "技能2"}):
        skill_name = re.sub(r"<.*?>", "", params.get("技能名", "")).strip()
        if skill_name and skill_name not in skill_names: skill_names.append(skill_name)
    upgrades = next(templates(text, {"技能升级材料"}), None)
    numerals = "一二三"
    if upgrades:
        for index, skill_name in enumerate(skill_names[:3]):
            stages = {}
            for level, label in zip((8, 9, 10), ("Ⅰ", "Ⅱ", "Ⅲ")):
                costs = material_costs(upgrades[1].get(f"{numerals[index]}{level}", ""), allowed)
                if costs: stages[label] = costs
            if stages: result["mastery_materials"][skill_name] = stages

    for _, params, _, _ in templates(text, {"模组"}):
        if params.get("基础证章", "").lower() in {"yes", "1", "true"}: continue
        module_name = params.get("名称", "").strip()
        module_type = params.get("类型", "").strip().translate(str.maketrans({"α": "Α", "β": "Β", "γ": "Γ"}))
        if not module_name or not module_type: continue
        stages = {"name": module_name, "stage_1": [], "stage_2": [], "stage_3": []}
        for source, target in (("材料消耗", "stage_1"), ("材料消耗2", "stage_2"), ("材料消耗3", "stage_3")):
            costs = material_costs(params.get(source, ""), allowed)
            if source in params: stages[target] = costs
        result["modules"][module_type] = stages
    return result


def parse_recipe(name: str, rarity: int, text: str, allowed: set[str]) -> dict:
    entry = {"rarity": rarity, "color": COLORS[rarity], "craftable": False, "recipe": None}
    recipe = next(templates(text, {"道具配方/加工站"}), None)
    if not recipe: return entry
    params = recipe[1]
    ingredients = []
    for index in range(1, 10):
        ingredient = params.get(f"原料{index}", "").strip()
        if not ingredient: continue
        if ingredient not in allowed:
            raise ValueError(f"recipe for {name} references unknown material {ingredient}")
        ingredients.append({"name": ingredient, "quantity": int(params.get(f"原料{index}数量", "1"))})
    if ingredients:
        entry["craftable"] = True
        entry["recipe"] = {
            "output_quantity": int(params.get("产物数量", "1")),
            "lmd_cost": int(params.get("龙门币消耗", "0")),
            "morale_cost": int(params.get("心情消耗", "0")),
            "workshop_level": int(params.get("加工站等级需求", "0")),
            "ingredients": ingredients,
        }
    return entry


def unique(values): return list(dict.fromkeys(value for value in values if value))


def build_metadata(requirements: dict, old_metadata: dict) -> tuple[dict, list[dict]]:
    characters = request_json(f"{GAME_BASE}/gamedata/excel/character_table.json")
    patches = request_json(f"{GAME_BASE}/gamedata/excel/char_patch_table.json").get("patchChars", {})
    equip = request_json(f"{GAME_BASE}/gamedata/excel/uniequip_table.json")
    factions = request_json(f"{GAME_BASE}/gamedata/excel/handbook_team_table.json")
    all_rows = {**characters, **patches}
    by_name: dict[str, list[tuple[str, dict]]] = {}
    for operator_id, row in all_rows.items():
        if row and row.get("name"): by_name.setdefault(row["name"], []).append((operator_id, row))
    old_by_name = {row["name"]: row for row in old_metadata.get("operators", [])}
    branch_table = equip.get("subProfDict", {})
    output, new_rows = [], []
    for name, requirement in requirements.items():
        wanted = NAME_OVERRIDES.get(name)
        candidates = by_name.get(name, [])
        if wanted: candidates = [(wanted, all_rows[wanted])] if wanted in all_rows else []
        candidates = [(key, row) for key, row in candidates if key.startswith("char_")]
        if not candidates: raise ValueError(f"game metadata missing for {name}")
        operator_id, row = sorted(candidates, key=lambda item: (item[1].get("sortIndex", 999999), item[0]))[0]
        branch_id = row.get("subProfessionId")
        faction_ids = unique([row.get("nationId"), row.get("groupId"), row.get("teamId")])
        avatar_id = AVATAR_ID_OVERRIDES.get(operator_id, operator_id)
        previous = old_by_name.get(name, {})
        if previous:
            entry = dict(previous)
            entry["rarity"] = requirement["rarity"]
            entry["has_modules"] = bool(requirement.get("modules"))
            output.append(entry)
            continue
        entry = {
            "id": operator_id, "name": name, "appellation": row.get("appellation"),
            "rarity": int(row.get("rarity", requirement["rarity"] - 1)) + 1,
            "profession_id": row.get("profession"), "profession": PROFESSIONS.get(row.get("profession"), row.get("profession")),
            "branch_id": branch_id, "branch": branch_table.get(branch_id, {}).get("subProfessionName"),
            "position": row.get("position"), "tags": row.get("tagList") or [],
            "nation_id": row.get("nationId"), "group_id": row.get("groupId"), "team_id": row.get("teamId"),
            "primary_faction": factions.get(row.get("groupId") or row.get("teamId") or row.get("nationId"), {}).get("powerName"),
            "faction_ids": faction_ids, "factions": [factions[key]["powerName"] for key in faction_ids if key in factions],
            "is_alter": bool(row.get("isSpChar")), "is_obtainable": not bool(row.get("isNotObtainable")),
            "sort_index": row.get("sortIndex"), "has_modules": bool(requirement.get("modules")),
            "avatar": f"operator_images/{operator_id}.png",
            "avatar_source": f"{GAME_BASE}/avatar/ASSISTANT/{avatar_id}.png",
        }
        output.append(entry)
        if name not in old_by_name: new_rows.append(entry)
    output.sort(key=lambda row: (row["sort_index"] if row["sort_index"] is not None else 999999, row["name"]))
    metadata_meta = dict(old_metadata.get("_meta", {}))
    metadata_meta["operator_count"] = len(output)
    if new_rows: metadata_meta["generated_at"] = datetime.now(timezone.utc).isoformat()
    return {"_meta": metadata_meta,
            "operators": output, "by_name": {row["name"]: row["id"] for row in output}}, new_rows


def download_new_avatars(rows: list[dict], dry_run: bool) -> list[str]:
    if not rows or dry_run: return [row["name"] for row in rows]
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required when a new operator avatar must be converted to WebP") from exc
    added = []
    for row in rows:
        destination = DIST / "assets/operators" / f"{row['id']}.webp"
        if destination.exists(): continue
        request = urllib.request.Request(row["avatar_source"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
        image = Image.open(io.BytesIO(payload)).convert("RGBA")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=destination.parent, suffix=".webp")
        os.close(fd)
        try:
            image.save(temp_name, "WEBP", quality=88, method=6)
            os.replace(temp_name, destination)
        finally:
            if os.path.exists(temp_name): os.unlink(temp_name)
        added.append(row["name"])
    return added


def validate(requirements: dict, recipes: dict, metadata: dict, old_count: int) -> None:
    names = set(requirements)
    materials = set(recipes)
    if len(materials) < 60: raise ValueError(f"material count unexpectedly fell to {len(materials)}")
    if len(names) < old_count: raise ValueError(f"operator count unexpectedly fell from {old_count} to {len(names)}")
    if names != {row["name"] for row in metadata["operators"]}: raise ValueError("requirements/metadata operator sets differ")
    for name, operator in requirements.items():
        for stages in [operator.get("elite_materials", {}), *operator.get("mastery_materials", {}).values(), *operator.get("modules", {}).values()]:
            for key, costs in stages.items():
                if key == "name": continue
                for cost in costs:
                    if cost["name"] not in materials or not isinstance(cost["quantity"], int) or cost["quantity"] <= 0:
                        raise ValueError(f"invalid material cost in {name}: {cost}")


def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="fetch and validate without replacing tracked data")
    parser.add_argument("--full", action="store_true", help="ignore revision cache and parse every page")
    args = parser.parse_args()
    old_requirements_doc = json.loads((DATA / "operator_material_requirements.json").read_text(encoding="utf-8"))
    old_recipes_doc = json.loads((DATA / "material_recipes.json").read_text(encoding="utf-8"))
    old_metadata = json.loads((DATA / "operator_metadata.json").read_text(encoding="utf-8"))
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"operators": {}, "materials": {}}

    material_rows = cargo_query("item", "name,rarity,category1,itemId,sortId", "category1='材料'")
    material_info = {row["name"]: int(row["rarity"]) for row in material_rows
                     if row.get("itemId") and row["name"] not in EXCLUDED_MATERIALS and int(row["rarity"]) in COLORS}
    allowed = set(material_info)
    operator_rows = cargo_query("chara", "cn=name,rarity,charIndex")
    operator_info = {row["name"]: int(row["rarity"]) + 1 for row in operator_rows
                     if row.get("name") and int(row.get("charIndex", "-1")) > 0}
    if not operator_info: raise RuntimeError("PRTS returned no operators")

    operator_pages = {name: PAGE_OVERRIDES.get(name, name) for name in operator_info}
    operator_revs = page_revisions(list(operator_pages.values()))
    material_revs = page_revisions(list(material_info))
    requirements, recipes = {}, {}
    changed_operators, changed_materials = [], []
    operator_fetch = [page for name, page in operator_pages.items()
        if args.full or str(state.get("operators", {}).get(name)) != str(operator_revs.get(page))
        or name not in old_requirements_doc["operators"]]
    material_fetch = [name for name in material_info
        if args.full or str(state.get("materials", {}).get(name)) != str(material_revs.get(name))
        or name not in old_recipes_doc["materials"]]
    operator_sources = page_sources(operator_fetch)
    material_sources = page_sources(material_fetch)
    for name, rarity in operator_info.items():
        page = operator_pages[name]; revision = operator_revs.get(page)
        can_reuse = (not args.full and str(state.get("operators", {}).get(name)) == str(revision)
                     and name in old_requirements_doc["operators"])
        if can_reuse: requirements[name] = old_requirements_doc["operators"][name]
        else:
            if page not in operator_sources: raise RuntimeError(f"PRTS returned no source for {page}")
            actual_revision, source = operator_sources[page]
            requirements[name] = parse_operator(name, rarity, source, allowed)
            operator_revs[page] = actual_revision; changed_operators.append(name)
    for name, rarity in material_info.items():
        revision = material_revs.get(name)
        can_reuse = (not args.full and str(state.get("materials", {}).get(name)) == str(revision)
                     and name in old_recipes_doc["materials"])
        if can_reuse: recipes[name] = old_recipes_doc["materials"][name]
        else:
            if name not in material_sources: raise RuntimeError(f"PRTS returned no source for {name}")
            actual_revision, source = material_sources[name]
            recipes[name] = parse_recipe(name, rarity, source, allowed)
            material_revs[name] = actual_revision; changed_materials.append(name)

    metadata, new_rows = build_metadata(requirements, old_metadata)
    validate(requirements, recipes, metadata, len(old_requirements_doc["operators"]))
    requirements_doc = {"_meta": {"source": "https://prts.wiki/w/干员一览", "exported_at": datetime.now(timezone.utc).date().isoformat(),
        "operator_count": len(requirements), "allowed_material_count": len(allowed),
        "description": "仅保留普通材料的直接需求；不包含龙门币、芯片、技巧概要及模组专用道具。"},
        "operators": {name: requirements[name] for name in [
            *[name for name in old_requirements_doc["operators"] if name in requirements],
            *sorted(set(requirements) - set(old_requirements_doc["operators"])),
        ]}}
    recipes_doc = {"_meta": {"source": "https://prts.wiki/w/道具一览", "description": "材料的直接加工站合成配方；不递归展开下位材料。",
        "material_count": len(recipes)}, "materials": dict(sorted(recipes.items(), key=lambda item: (item[1]["rarity"], item[0])))}
    next_state = {"updated_at": datetime.now(timezone.utc).isoformat(),
        "operators": {name: operator_revs.get(page) for name, page in operator_pages.items()},
        "materials": {name: material_revs.get(name) for name in material_info}}
    if requirements_doc["operators"] == old_requirements_doc["operators"]:
        requirements_doc["_meta"] = old_requirements_doc["_meta"]
    if metadata["operators"] == old_metadata["operators"] and metadata.get("by_name") == old_metadata.get("by_name"):
        metadata = old_metadata
    if (state.get("operators") == next_state["operators"] and state.get("materials") == next_state["materials"]):
        next_state = state
    avatars = download_new_avatars(new_rows, args.dry_run)
    requirement_differences = sorted(name for name in set(requirements) | set(old_requirements_doc["operators"])
        if requirements.get(name) != old_requirements_doc["operators"].get(name))
    recipe_differences = sorted(name for name in set(recipes) | set(old_recipes_doc["materials"])
        if recipes.get(name) != old_recipes_doc["materials"].get(name))
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "dry_run": args.dry_run,
        "operator_count": len(requirements), "material_count": len(recipes),
        "changed_operators": changed_operators, "changed_materials": changed_materials,
        "requirement_differences": requirement_differences, "recipe_differences": recipe_differences,
        "new_operator_avatars": avatars, "valid": True}
    if not args.dry_run:
        write_json(DATA / "operator_material_requirements.json", requirements_doc)
        write_json(DATA / "material_recipes.json", recipes_doc)
        write_json(DATA / "operator_metadata.json", metadata)
        write_json(STATE_PATH, next_state)
    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
