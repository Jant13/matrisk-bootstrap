from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
LIVE_DELTAS_DIR = ROOT / "live" / "deltas"
MONTHLY_OUT_DIR = ROOT / "bootstrap-monthly"

VALID_GAMES = {
    "bonoloto",
    "primitiva",
    "euromillones",
    "gordo",
    "eurojackpot",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_draws(data: Any) -> list[dict]:
    """
    Soporta varias formas:
    1) lista de sorteos
    2) dict con clave "draws"
    3) dict que ya es un solo sorteo
    """
    if isinstance(data, list):
        draws = data
    elif isinstance(data, dict) and isinstance(data.get("draws"), list):
        draws = data["draws"]
    elif isinstance(data, dict) and "gameId" in data and "date" in data:
        draws = [data]
    else:
        raise ValueError("Formato JSON no reconocido para extraer sorteos.")

    clean: list[dict] = []
    for d in draws:
        if isinstance(d, dict) and "gameId" in d and "date" in d:
            clean.append(d)

    return clean


def sort_draws(draws: list[dict]) -> list[dict]:
    return sorted(
        draws,
        key=lambda d: (
            str(d.get("date", "")),
            str(d.get("gameId", "")),
            str(d.get("id", "")),
        ),
    )


def build_monthly_payload(game_id: str, month_key: str, draws: list[dict]) -> dict:
    dates = [str(d.get("date", "")) for d in draws if d.get("date")]
    date_min = min(dates) if dates else ""
    date_max = max(dates) if dates else ""

    return {
        "schema": "matrisk-bootstrap-monthly",
        "manifestVersion": 1,
        "gameId": game_id,
        "month": month_key,
        "drawsCount": len(draws),
        "dateMin": date_min,
        "dateMax": date_max,
        "draws": draws,
    }


def write_gzip_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    path.write_bytes(gz)


def process_monthly_file(src_path: Path) -> tuple[str, str, int, Path]:
    game_id = src_path.parent.name
    if game_id not in VALID_GAMES:
        raise ValueError(f"Juego no válido en ruta: {game_id}")

    month_key = src_path.stem # ej. 2026-03
    data = load_json(src_path)
    draws = normalize_draws(data)

    # Filtrar por juego y ordenar
    draws = [d for d in draws if str(d.get("gameId")) == game_id]
    draws = sort_draws(draws)

    payload = build_monthly_payload(game_id, month_key, draws)
    out_path = MONTHLY_OUT_DIR / game_id / f"{month_key}.json.gz"
    write_gzip_json(out_path, payload)

    return game_id, month_key, len(draws), out_path


def main() -> None:
    if not LIVE_DELTAS_DIR.exists():
        raise RuntimeError(f"No existe la carpeta fuente: {LIVE_DELTAS_DIR}")

    monthly_files = sorted(LIVE_DELTAS_DIR.glob("*/*.json"))
    if not monthly_files:
        raise RuntimeError("No se encontraron archivos mensuales en live/deltas.")

    built = 0
    total_draws = 0

    print(f"Source: {LIVE_DELTAS_DIR}")
    print(f"Target: {MONTHLY_OUT_DIR}")
    print("")

    for src_path in monthly_files:
        game_id, month_key, count, out_path = process_monthly_file(src_path)
        built += 1
        total_draws += count
        print(f"OK {game_id} {month_key}: {count} draws -> {out_path}")

    print("")
    print(f"Monthly bootstrap build OK. Files: {built} | Draws: {total_draws}")


if __name__ == "__main__":
    main()