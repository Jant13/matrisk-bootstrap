from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
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
    path.write_text(text, encoding="utf-8", newline="\r\n")


def load_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def detect_draws_list(payload: dict) -> list:
    if isinstance(payload.get("draws"), list):
        return payload["draws"]

    if isinstance(payload.get("items"), list):
        return payload["items"]

    if isinstance(payload.get("historico"), list):
        return payload["historico"]

    matrix = payload.get("matrix")
    if isinstance(matrix, dict) and isinstance(matrix.get("draws"), list):
        return matrix["draws"]

    raise RuntimeError("No se encontró lista de sorteos en el payload.")


def draw_key(draw: dict) -> str:
    # Mismo criterio de deduplicación que
    # promote_closed_months_to_bootstrap.py
    if "id" in draw and draw["id"]:
        return f"id::{draw['id']}"

    return json.dumps(
        draw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def month_from_filename(path: Path) -> str:
    name = path.name

    if not name.endswith(".json.gz"):
        raise RuntimeError(f"Nombre mensual inválido: {name}")

    return name.removesuffix(".json.gz")


def historical_path_for_game(manifest: dict, game_id: str) -> Path | None:
    """
    Localiza el bootstrap histórico real correspondiente al juego.
    Se obtiene de manifest.files para no asumir nombres de archivo.
    """
    files = manifest.get("files", [])

    if not isinstance(files, list):
        return None

    for entry in files:
        if not isinstance(entry, dict):
            continue

        if entry.get("gameId") != game_id:
            continue

        relative_path = entry.get("path")

        if not isinstance(relative_path, str) or not relative_path:
            return None

        return ROOT / relative_path

    return None


def load_historical_keys(
    manifest: dict,
    game_id: str,
    cache: dict[str, set[str]],
) -> set[str] | None:
    """
    Carga una sola vez por juego todos los identificadores de sorteos
    presentes realmente en el bootstrap histórico.

    Devuelve None si no puede comprobarse el histórico. En ese caso
    aplicaremos el criterio conservador: mantener el mensual publicado.
    """
    if game_id in cache:
        return cache[game_id]

    historical_path = historical_path_for_game(manifest, game_id)

    if historical_path is None:
        return None

    if not historical_path.exists():
        return None

    try:
        if historical_path.name.endswith(".json.gz"):
            payload = load_gzip_json(historical_path)
        else:
            payload = load_json(historical_path)

        draws = detect_draws_list(payload)
        keys = {draw_key(draw) for draw in draws}

        cache[game_id] = keys
        return keys

    except Exception as exc:
        print(
            f"WARN {game_id}: no se pudo comprobar el histórico "
            f"({exc}). Se mantendrán sus mensuales por seguridad."
        )
        return None


def monthly_is_fully_in_historical(
    monthly_draws: list,
    historical_keys: set[str] | None,
) -> tuple[bool, int]:
    """
    Comprueba sorteo por sorteo.

    Solo devuelve True cuando TODOS los sorteos del mensual están
    realmente presentes en el bootstrap histórico.

    Si no podemos comprobar el histórico, devuelve False para conservar
    el mensual y evitar cualquier pérdida de cobertura.
    """
    if historical_keys is None:
        return False, len(monthly_draws)

    missing = 0

    for draw in monthly_draws:
        if draw_key(draw) not in historical_keys:
            missing += 1

    return missing == 0, missing


def main() -> None:
    manifest = load_json(MANIFEST_PATH)

    monthly_entries = []
    monthly_draws_total = 0

    # Evita descomprimir el histórico repetidamente para cada mes.
    historical_keys_cache: dict[str, set[str]] = {}

    if MONTHLY_ROOT.exists():
        for gz_path in sorted(MONTHLY_ROOT.glob("*/*.json.gz")):
            game_id = gz_path.parent.name
            month_key = month_from_filename(gz_path)

            payload = load_gzip_json(gz_path)
            draws = detect_draws_list(payload)

            if not draws:
                continue

            dates = sorted(
                draw["date"]
                for draw in draws
                if isinstance(draw, dict) and draw.get("date")
            )

            if not dates:
                raise RuntimeError(
                    f"{gz_path}: no se encontraron fechas válidas."
                )

            date_min = dates[0]
            date_max = dates[-1]
            draw_count = len(draws)

            historical_keys = load_historical_keys(
                manifest,
                game_id,
                historical_keys_cache,
            )

            fully_covered, missing_count = (
                monthly_is_fully_in_historical(
                    draws,
                    historical_keys,
                )
            )

            # REGLA DE RELEVO SEGURO:
            #
            # Un mensual solo desaparece del manifest cuando TODOS
            # sus sorteos están realmente presentes en el histórico
            # del mismo juego.
            #
            # No dependemos del cambio de mes, de una hora concreta
            # ni únicamente de dateMax.
            if fully_covered:
                print(
                    f"SKIP {game_id} {month_key}: "
                    f"todos sus {draw_count} sorteos "
                    f"ya están en histórico"
                )
                continue

            monthly_entries.append(
                {
                    "id": f"{game_id}-{month_key}",
                    "gameId": game_id,
                    "month": month_key,
                    "path": (
                        f"bootstrap-monthly/"
                        f"{game_id}/"
                        f"{month_key}.json.gz"
                    ),
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

            if historical_keys is None:
                print(
                    f"KEEP {game_id} {month_key}: "
                    f"histórico no verificable; "
                    f"se conserva por seguridad"
                )
            else:
                print(
                    f"KEEP {game_id} {month_key}: "
                    f"{missing_count} de {draw_count} sorteos "
                    f"aún no están en histórico"
                )

    base_historical_date_max = (
        manifest.get("overall", {}).get("dateMax")
    )

    if not base_historical_date_max:
        raise RuntimeError(
            "manifest.json no contiene overall.dateMax"
        )

    if monthly_entries:
        combined_date_max = max(
            [base_historical_date_max]
            + [
                entry["dateMax"]
                for entry in monthly_entries
            ]
        )
    else:
        combined_date_max = base_historical_date_max

    manifest["monthly"] = {
        "mode": "per-game-per-month",
        "baseHistoricalDateMax": base_historical_date_max,
        "combinedDateMax": combined_date_max,
        "drawsTotal": monthly_draws_total,
        "files": monthly_entries,
    }

    save_json(MANIFEST_PATH, manifest)

    print("")
    print("Monthly manifest OK")
    print(f"Base historical max: {base_historical_date_max}")
    print(f"Combined date max: {combined_date_max}")
    print(f"Monthly draws total: {monthly_draws_total}")
    print(f"Monthly files: {len(monthly_entries)}")


if __name__ == "__main__":
    main()