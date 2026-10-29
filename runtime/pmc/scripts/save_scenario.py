"""Validate and persist a PMC scenario; never write to Lingxing."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4


RANGES = {"demandMultiplier": (0.1, 10), "transitDays": (1, 180),
          "expressDays": (1, 180), "airTransitDays": (0, 180),
          "purchaseLeadDays": (0, 365), "safetyDays": (0, 120),
          "cadenceDays": (1, 60), "cartonQty": (0, 100000),
          "moq": (0, 1000000), "minShipQty": (0, 1000000),
          "localAvailable": (0, 1000000)}


def _validate(draft: dict, allowed: set[tuple[str, str]]) -> tuple[str, str, dict]:
    if not isinstance(draft, dict):
        raise ValueError("scenario draft must be an object")
    store = str(draft.get("store") or "").strip()
    asin = str(draft.get("asin") or "").strip().upper()
    name = str(draft.get("name") or "").strip()
    if (store, asin) not in allowed or not name or len(name) > 60:
        raise ValueError("scenario store-ASIN absent from inventory snapshot, or name invalid")
    params = draft.get("params")
    if not isinstance(params, dict) or not params:
        raise ValueError("scenario params required")
    unknown = set(params) - set(RANGES) - {"seasonal"}
    if unknown:
        raise ValueError(f"unknown scenario parameter: {sorted(unknown)}")
    clean = {}
    for key, value in params.items():
        if key == "seasonal":
            if not isinstance(value, list) or len(value) > 12:
                raise ValueError("seasonal must be a bounded list")
            ranges = []
            for item in value:
                if not isinstance(item, dict):
                    raise ValueError("invalid seasonal row")
                start, end = dt.date.fromisoformat(item["from"]), dt.date.fromisoformat(item["to"])
                multiplier = float(item["multiplier"])
                if start > end or not 0 <= multiplier <= 10:
                    raise ValueError("invalid seasonal range")
                ranges.append({"from": start.isoformat(), "to": end.isoformat(), "multiplier": multiplier})
            clean[key] = ranges
            continue
        if value is None and key == "localAvailable":
            clean[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"scenario {key} must be numeric")
        low, high = RANGES[key]
        if not low <= value <= high:
            raise ValueError(f"scenario {key} outside {low}..{high}")
        clean[key] = value
    return store, asin, {"name": name, "params": clean}


def save_scenario(path: Path, draft: dict, *, allowed: set[tuple[str, str]],
                  make_default: bool = False) -> dict:
    store, asin, validated = _validate(draft, allowed)
    path = Path(path)
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("existing scenario state is invalid; no changes written") from error
        if not isinstance(state, dict) or not isinstance(state.get("scenarios"), list):
            raise ValueError("existing scenario state has invalid schema")
    else:
        state = {"version": 1, "updatedAt": None, "scenarios": []}
    matching = next((item for item in state["scenarios"] if item.get("store") == store
                     and item.get("asin") == asin and item.get("name") == validated["name"]), None)
    if make_default:
        for item in state["scenarios"]:
            if item.get("store") == store and item.get("asin") == asin:
                item["isDefault"] = False
    if matching is None:
        matching = {"id": "pmc-" + uuid4().hex[:12], "store": store, "asin": asin}
        state["scenarios"].append(matching)
    matching.update({**validated, "isDefault": bool(make_default) or bool(matching.get("isDefault"))})
    state["updatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + ".bak-" + dt.datetime.now().strftime("%Y%m%d%H%M%S"))
        shutil.copy2(path, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".scenario-",
                                         suffix=".json", delete=False) as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--default", action="store_true")
    args = parser.parse_args()
    draft = json.loads(args.draft.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    allowed = {(row["store"], row["asin"]) for row in snapshot["records"]}
    result = save_scenario(args.state, draft, allowed=allowed, make_default=args.default)
    print(json.dumps({"scenarios": len(result["scenarios"]), "updated_at": result["updatedAt"]}))


if __name__ == "__main__":
    main()
