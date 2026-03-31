from __future__ import annotations

import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "manifest.json"
MONTHLY_DIR = ROOT / "bootstrap-monthly"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def detect_draws_list(payload: dict) -> list:
    if isinstance(payload.get("draws"), list):
        return payload["draws"]
    if isinstance(payload.get("items"), list):
        return payload["items"]
    raise RuntimeError(f"No se encontró lista de sorteos en {payload!r}")


def extract_date(draw: dict) -> str:
    date = draw.get("date")
    if not date:
        raise RuntimeError(f"Sorteo sin date: {draw}")
    return date


def build_monthly_files() -> tuple[list[dict], str | None, int]:
    if not MONTHLY_DIR.exists():
        raise RuntimeError("No existe bootstrap-monthly")

    monthly_entries: list[dict] = []
    combined_date_max: str | None = None
    total_draws = 0

    for game_dir in sorted(p for p in MONTHLY_DIR.iterdir() if p.is_dir()):
        game_id = game_dir.name

        for gz_path in sorted(game_dir.glob("*.json.gz")):
            month = gz_path.stem.replace(".json", "") # 2026-03
            payload = load_gzip_json(gz_path)
            draws = detect_draws_list(payload)

            if not draws:
                continue

            dates = sorted(extract_date(d) for d in draws)
            date_min = dates[0]
            date_max = dates[-1]
            draws_count = len(draws)

            if combined_date_max is None or date_max > combined_date_max:
                combined_date_max = date_max

            total_draws += draws_count

            rel_path = gz_path.relative_to(ROOT).as_posix()

            monthly_entries.append(
                {
                    "id": f"{game_id}-{month}",
                    "gameId": game_id,
                    "month": month,
                    "path": rel_path,
                    "format": "gzip+json",
                    "schema": "matrisk-bootstrap-monthly",
                    "backupType": "matrisk_monthly_bootstrap",
                    "backupVersion": 1,
                    "draws": draws_count,
                    "dateMin": date_min,
                    "dateMax": date_max,
                }
            )

    return monthly_entries, combined_date_max, total_draws


def main() -> None:
    manifest = load_json(MANIFEST_PATH)

    base_historical_date_max = manifest.get("overall", {}).get("dateMax")
    if not base_historical_date_max:
        raise RuntimeError("manifest.json no contiene overall.dateMax")

    monthly_files, combined_date_max, total_draws = build_monthly_files()

    manifest["monthly"] = {
        "mode": "per-game-per-month",
        "baseHistoricalDateMax": base_historical_date_max,
        "combinedDateMax": combined_date_max or base_historical_date_max,
        "drawsTotal": total_draws,
        "files": monthly_files,
    }

    with MANIFEST_PATH.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Monthly manifest OK")
    print(f"Base historical max: {base_historical_date_max}")
    print(f"Combined date max: {manifest['monthly']['combinedDateMax']}")
    print(f"Monthly draws total: {total_draws}")
    print(f"Monthly files: {len(monthly_files)}")


if __name__ == "__main__":
    main()