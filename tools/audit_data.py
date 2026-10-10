#!/usr/bin/env python3
"""Validate site data and detect operators newly published by the game-data mirror."""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BASE = "https://raw.githubusercontent.com/fexli/ArknightsResource/master/gamedata/excel"
PROFESSIONS = {"PIONEER", "WARRIOR", "TANK", "SNIPER", "CASTER", "MEDIC", "SUPPORT", "SPECIAL"}


def fetch(name: str) -> dict:
    request = urllib.request.Request(f"{BASE}/{name}", headers={"User-Agent": "operator-material-planner-audit/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "data-audit-report.json")
    args = parser.parse_args()

    requirements = json.loads((DIST / "data/operator_material_requirements.json").read_text(encoding="utf-8"))["operators"]
    metadata_rows = json.loads((DIST / "data/operator_metadata.json").read_text(encoding="utf-8"))["operators"]
    recipes = json.loads((DIST / "data/material_recipes.json").read_text(encoding="utf-8"))["materials"]
    metadata = {row["name"]: row for row in metadata_rows}
    known_ids = {row["id"] for row in metadata_rows}

    characters = fetch("character_table.json")
    patches = fetch("char_patch_table.json").get("patchChars", {})
    upstream = {**characters, **patches}
    playable = {
        operator_id: row for operator_id, row in upstream.items()
        if operator_id.startswith("char_")
        and row
        and row.get("profession") in PROFESSIONS
        and not row.get("isNotObtainable", False)
    }
    known_names = set(metadata)
    new_operators = sorted(
        ({"id": operator_id, "name": row.get("name")} for operator_id, row in playable.items()
         if operator_id not in known_ids and row.get("name") not in known_names),
        key=lambda row: (row["name"] or "", row["id"]),
    )

    missing_metadata = sorted(set(requirements) - set(metadata))
    orphan_metadata = sorted(set(metadata) - set(requirements))
    missing_avatars = sorted(row["name"] for row in metadata_rows if not (DIST / f"assets/operators/{row['id']}.webp").is_file())

    referenced_materials = set()
    for operator in requirements.values():
        for stage in operator.get("elite_materials", {}).values():
            referenced_materials.update(item["name"] for item in stage)
        for ranks in operator.get("mastery_materials", {}).values():
            for stage in ranks.values():
                referenced_materials.update(item["name"] for item in stage)
        for module in operator.get("modules", {}).values():
            for key in ("stage_1", "stage_2", "stage_3"):
                referenced_materials.update(item["name"] for item in module.get(key, []))

    missing_recipes = sorted(referenced_materials - set(recipes))
    missing_material_images = sorted(
        name for name in referenced_materials
        if not (DIST / "assets/materials" / f"{name.replace('/', '／').replace(':', '：')}.png").is_file()
    )
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "operator_count": len(requirements),
        "metadata_count": len(metadata_rows),
        "upstream_playable_count": len(playable),
        "new_operators": new_operators,
        "missing_metadata": missing_metadata,
        "orphan_metadata": orphan_metadata,
        "missing_avatars": missing_avatars,
        "missing_recipes": missing_recipes,
        "missing_material_images": missing_material_images,
    }
    report["valid"] = not any(report[key] for key in (
        "new_operators", "missing_metadata", "orphan_metadata", "missing_avatars", "missing_recipes", "missing_material_images"
    ))
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
