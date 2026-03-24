from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FILE = ROOT / "manifest.json"
LIVE_FILE = ROOT / "live" / "latest.json"
DELTAS_DIR = ROOT / "live" / "deltas"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest_cutoffs() -> dict[str, str]:
    data = load_json(MANIFEST_FILE)
    games = data.get("games", {})
    out: dict[str, str] = {}
    for game_id, meta in games.items():
        date_max = meta.get("dateMax")
        if isinstance(date_max, str):
            out[game_id] = date_max
    return out


def draw_key(draw: dict[str, Any]) -> str:
    return f"{draw['gameId']}::{draw['date']}"


def month_key(date_str: str) -> str:
    return date_str[:7]


def is_after_cutoff(draw: dict[str, Any], cutoffs: dict[str, str]) -> bool:
    game_id = draw.get("gameId")
    date = draw.get("date")
    if not game_id or not date:
        return False
    cutoff = cutoffs.get(game_id)
    if not cutoff:
        return True
    return date > cutoff


def normalize_draw(draw: dict[str, Any]) -> dict[str, Any]:
    out = dict(draw)
    out["gameId"] = str(out["gameId"])
    out["date"] = str(out["date"])
    return out


def load_live_latest() -> list[dict[str, Any]]:
    if not LIVE_FILE.exists():
        return []
    data = load_json(LIVE_FILE)
    return [normalize_draw(d) for d in data.get("draws", [])]


def iter_delta_files() -> list[Path]:
    if not DELTAS_DIR.exists():
        return []
    return sorted(p for p in DELTAS_DIR.rglob("*.json") if p.is_file())


def load_all_deltas() -> list[dict[str, Any]]:
    draws: list[dict[str, Any]] = []
    for path in iter_delta_files():
        data = load_json(path)
        for d in data.get("draws", []):
            draws.append(normalize_draw(d))
    return draws


def extract_draws_from_backup_json(data: dict[str, Any]) -> list[dict[str, Any]]:
    draws: list[dict[str, Any]] = []

    games = data.get("games", {})
    for game_id, game_data in games.items():
        historico = game_data.get("historico", [])
        for d in historico:
            row = dict(d)
            row["gameId"] = game_id
            draws.append(normalize_draw(row))

        matrix = game_data.get("matrix", {})
        matrix_draws = matrix.get("draws", [])
        for d in matrix_draws:
            row = dict(d)
            row["gameId"] = game_id
            draws.append(normalize_draw(row))

    return draws


def load_backup_source(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No existe: {path}")

    if path.suffix.lower() == ".json":
        return extract_draws_from_backup_json(load_json(path))

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            json_names = [n for n in zf.namelist() if n.lower().endswith(".json")]
            if not json_names:
                raise RuntimeError("El ZIP no contiene ningún JSON.")
            # cogemos el primer JSON encontrado
            raw = zf.read(json_names[0]).decode("utf-8")
            return extract_draws_from_backup_json(json.loads(raw))

    raise RuntimeError(f"Formato no soportado: {path.suffix}")


def write_monthly_deltas(draws: list[dict[str, Any]], cutoffs: dict[str, str]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for draw in draws:
        if not is_after_cutoff(draw, cutoffs):
            continue
        game_id = draw["gameId"]
        month = month_key(draw["date"])
        grouped.setdefault((game_id, month), []).append(draw)

    for (game_id, month), rows in grouped.items():
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            unique[draw_key(row)] = row

        ordered = sorted(unique.values(), key=lambda d: d["date"])
        path = DELTAS_DIR / game_id / f"{month}.json"
        save_json(
            path,
            {
                "schema": "matrisk-live-delta",
                "gameId": game_id,
                "month": month,
                "draws": ordered,
            },
        )


def rebuild_live_latest(cutoffs: dict[str, str]) -> None:
    draws = load_all_deltas()
    unique: dict[str, dict[str, Any]] = {}

    for draw in draws:
        if is_after_cutoff(draw, cutoffs):
            unique[draw_key(draw)] = draw

    ordered = sorted(unique.values(), key=lambda d: (d["date"], d["gameId"]))
    save_json(
        LIVE_FILE,
        {
            "schema": "matrisk-official-sync-payload",
            "generatedAt": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "draws": ordered,
        },
    )

    print(f"live/latest.json rebuilt with {len(ordered)} draws")


def main() -> None:
    cutoffs = load_manifest_cutoffs()

    all_draws: dict[str, dict[str, Any]] = {}

    for draw in load_all_deltas():
        all_draws[draw_key(draw)] = draw

    for draw in load_live_latest():
        all_draws[draw_key(draw)] = draw

    if len(sys.argv) > 1:
        backup_path = Path(sys.argv[1])
        for draw in load_backup_source(backup_path):
            all_draws[draw_key(draw)] = draw

    write_monthly_deltas(list(all_draws.values()), cutoffs)
    rebuild_live_latest(cutoffs)

    print("Backlog build OK.")


if __name__ == "__main__":
    main()