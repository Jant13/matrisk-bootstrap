from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "manifest.json"


def utc_now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, payload: dict) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\r\n")
    data = path.read_bytes()
    return data


def save_gzip_json(path: Path, payload: dict) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    raw = text.encode("utf-8")
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gz)
    return gz


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_draws_key(payload: dict) -> str:
    if isinstance(payload.get("draws"), list):
        return "draws"
    if isinstance(payload.get("items"), list):
        return "items"
    raise RuntimeError("No se encontró lista de sorteos en el payload.")


def detect_draws_list(payload: dict) -> list:
    key = detect_draws_key(payload)
    return payload[key]


def extract_date(draw: dict) -> str:
    d = draw.get("date")
    if not d:
        raise RuntimeError(f"Sorteo sin date: {draw}")
    return d


def draw_key(draw: dict) -> str:
    # Dedupe robusto
    if "id" in draw and draw["id"]:
        return f"id::{draw['id']}"
    return json.dumps(draw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def month_is_closed(month_str: str, today_month: str) -> bool:
    # "2026-03" < "2026-04" funciona bien en formato YYYY-MM
    return month_str < today_month


def update_common_payload_metadata(payload: dict, draws: list) -> None:
    if not draws:
        return

    dates = sorted(extract_date(d) for d in draws)
    date_min = dates[0]
    date_max = dates[-1]
    count = len(draws)

    for key in ("dateMin", "minDate"):
        if key in payload:
            payload[key] = date_min

    for key in ("dateMax", "maxDate"):
        if key in payload:
            payload[key] = date_max

    for key in ("drawsTotal", "drawCount", "matrixDraws", "totalDraws"):
        if key in payload and isinstance(payload[key], int):
            payload[key] = count

    if "generatedAt" in payload:
        payload["generatedAt"] = utc_now_z()

    if "updatedAt" in payload:
        payload["updatedAt"] = utc_now_z()


def main() -> None:
    manifest = load_json(MANIFEST_PATH)
    today_month = date.today().strftime("%Y-%m")

    monthly = manifest.get("monthly", {})
    monthly_files = monthly.get("files", [])

    closed_entries = [m for m in monthly_files if month_is_closed(m["month"], today_month)]

    if not closed_entries:
        print("No hay meses cerrados para promocionar.")
        return

    base_files_by_game = {}
    for item in manifest.get("files", []):
        game_id = item.get("gameId")
        if game_id:
            base_files_by_game[game_id] = item

    games_meta = manifest.get("games", {})

    grouped = defaultdict(list)
    for entry in closed_entries:
        grouped[entry["gameId"]].append(entry)

    promoted_games = 0
    promoted_draws = 0

    for game_id, entries in grouped.items():
        base_entry = base_files_by_game.get(game_id)
        if not base_entry:
            raise RuntimeError(f"No existe entrada base en manifest.files para gameId={game_id}")

        base_gz_path = ROOT / base_entry["path"]
        base_payload = load_gzip_json(base_gz_path)
        base_key = detect_draws_key(base_payload)
        base_draws = detect_draws_list(base_payload)

        existing = {draw_key(d): d for d in base_draws}
        added_here = 0

        for entry in sorted(entries, key=lambda x: x["month"]):
            monthly_path = ROOT / entry["path"]
            monthly_payload = load_gzip_json(monthly_path)
            monthly_draws = detect_draws_list(monthly_payload)

            for d in monthly_draws:
                k = draw_key(d)
                if k not in existing:
                    existing[k] = d
                    added_here += 1

        merged_draws = sorted(existing.values(), key=extract_date)
        base_payload[base_key] = merged_draws
        update_common_payload_metadata(base_payload, merged_draws)

        # Guardar base .json.gz y alt .json
        gz_bytes = save_gzip_json(base_gz_path, base_payload)
        raw_json_bytes = json.dumps(base_payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"

        alt_path = None
        alt_info = base_entry.get("alt")
        if isinstance(alt_info, dict) and alt_info.get("path"):
            alt_path = ROOT / alt_info["path"]
        elif base_entry.get("altPath"):
            alt_path = ROOT / base_entry["altPath"]

        if alt_path is not None:
            json_bytes = save_json(alt_path, base_payload)
        else:
            json_bytes = raw_json_bytes

        dates = sorted(extract_date(d) for d in merged_draws)
        date_min = dates[0]
        date_max = dates[-1]
        count = len(merged_draws)

        # Actualizar manifest.files (base)
        base_entry["draws"] = count
        base_entry["dateMin"] = date_min
        base_entry["dateMax"] = date_max
        base_entry["bytesCompressed"] = len(gz_bytes)
        base_entry["bytesUncompressed"] = len(json_bytes)
        base_entry["sha256"] = sha256_bytes(gz_bytes)

        if isinstance(base_entry.get("alt"), dict):
            base_entry["alt"]["bytes"] = len(json_bytes)
            base_entry["alt"]["sha256"] = sha256_bytes(json_bytes)

        # Compatibilidad con estructura antigua
        if "altPath" in base_entry and isinstance(base_entry["altPath"], str):
            pass

        # Actualizar manifest.games
        if game_id in games_meta:
            games_meta[game_id]["draws"] = count
            games_meta[game_id]["dateMin"] = date_min
            games_meta[game_id]["dateMax"] = date_max
            if "matrixDraws" in games_meta[game_id]:
                games_meta[game_id]["matrixDraws"] = count

        promoted_games += 1
        promoted_draws += added_here
        print(f"OK {game_id}: +{added_here} sorteos promocionados al histórico")

    # Recalcular overall
    all_games = manifest.get("games", {})
    draw_counts = []
    date_mins = []
    date_maxs = []

    for game_id, meta in all_games.items():
        if "draws" in meta:
            draw_counts.append(int(meta["draws"]))
        if meta.get("dateMin"):
            date_mins.append(meta["dateMin"])
        if meta.get("dateMax"):
            date_maxs.append(meta["dateMax"])

    if draw_counts:
        manifest["overall"]["drawsTotal"] = sum(draw_counts)
    if date_mins:
        manifest["overall"]["dateMin"] = min(date_mins)
    if date_maxs:
        manifest["overall"]["dateMax"] = max(date_maxs)

    manifest["generatedAt"] = utc_now_z()

    # Guardar manifest con overall y files actualizados
    save_json(MANIFEST_PATH, manifest)

    print("")
    print(f"Promoción mensual OK. Juegos tocados: {promoted_games} | Sorteos nuevos añadidos: {promoted_draws}")
    print(f"Nuevo overall.dateMax: {manifest['overall']['dateMax']}")
    print(f"Nuevo overall.drawsTotal: {manifest['overall']['drawsTotal']}")


if __name__ == "__main__":
    main()