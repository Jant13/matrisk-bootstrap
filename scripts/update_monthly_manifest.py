from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "manifest.json"
MONTHLY_ROOT = ROOT / "bootstrap-monthly"


def utc_now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def load_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def detect_draws(payload: dict) -> list:
    if isinstance(payload.get("draws"), list):
        return payload["draws"]
    if isinstance(payload.get("items"), list):
        return payload["items"]
    raise RuntimeError(f"No se encontró lista de sorteos en {payload.keys()}")


def month_from_filename(path: Path) -> str:
    name = path.name
    if not name.endswith(".json.gz"):
        raise RuntimeError(f"Nombre mensual inválido: {name}")
    return name[:-8] # quita ".json.gz"


def is_open_month(month_str: str, current_month: str) -> bool:
    # Mantener solo el mes actual o futuros
    return month_str >= current_month


def main() -> None:
    manifest = load_json(MANIFEST_PATH)

    current_month = date.today().strftime("%Y-%m")
    monthly_entries = []
    monthly_draws_total = 0

    if MONTHLY_ROOT.exists():
        for gz_path in sorted(MONTHLY_ROOT.glob("*/*.json.gz")):
            game_id = gz_path.parent.name
            month_key = month_from_filename(gz_path)

            if not is_open_month(month_key, current_month):
                continue

            payload = load_gzip_json(gz_path)
            draws = detect_draws(payload)

            if not draws:
                continue

            dates = sorted(d["date"] for d in draws)
            date_min = dates[0]
            date_max = dates[-1]
            draw_count = len(draws)

            monthly_entries.append(
                {
                    "id": f"{game_id}-{month_key}",
                    "gameId": game_id,
                    "month": month_key,
                    "path": f"bootstrap-monthly/{game_id}/{month_key}.json.gz",
                    "format": "gzip+json",
                    "schema": "matrisk-bootstrap-monthly",
                    "backupType": "matrisk_monthly_bootstrap",
                    "backupVersion": 1,
                    "draws": draw_count,
                    "dateMin": date_min,
                    "dateMax": date_max,
                }
            )

            monthly_draws_total += draw_count

    base_historical_date_max = manifest.get("overall", {}).get("dateMax")
    if not base_historical_date_max:
        raise RuntimeError("manifest.json no contiene overall.dateMax")

    if monthly_entries:
        combined_date_max = max([base_historical_date_max] + [e["dateMax"] for e in monthly_entries])
    else:
        combined_date_max = base_historical_date_max

    manifest["monthly"] = {
        "mode": "per-game-per-month",
        "baseHistoricalDateMax": base_historical_date_max,
        "combinedDateMax": combined_date_max,
        "drawsTotal": monthly_draws_total,
        "files": monthly_entries,
    }

    manifest["generatedAt"] = utc_now_z()
    save_json(MANIFEST_PATH, manifest)

    print("Monthly manifest OK")
    print(f"Base historical max: {base_historical_date_max}")
    print(f"Combined date max: {combined_date_max}")
    print(f"Monthly draws total: {monthly_draws_total}")
    print(f"Monthly files: {len(monthly_entries)}")


if __name__ == "__main__":
    main()
