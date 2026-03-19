from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
LIVE_FILE = ROOT / "live" / "latest.json"

ONCE_URL = "https://www.juegosonce.es/historico-resultados-eurojackpot"
SELAE_RESULTS_URL = "https://www.loteriasyapuestas.es/es/resultados"
BONOLOTO_RESULTS_URL = "https://www.loteriasyapuestas.es/es/resultados/bonoloto"
TIMEOUT = 25

MONTHS_ES = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "setiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12",
}


@dataclass
class Draw:
    gameId: str
    date: str
    main: list[int]
    secondary: list[int] | None = None
    complementario: int | None = None
    reintegro: int | None = None
    source: str = "remote-manifest"


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def fetch_text(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MaTrisK-GitHub-Action/1.0)"
    }
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def parse_date_es_once(text: str) -> str:
    m = re.search(
        r"Último sorteo celebrado el [^,]+,\s*(\d{1,2}) de ([a-záéíóú]+) de (\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError("No pude extraer la fecha del último sorteo de Eurojackpot.")

    day = f"{int(m.group(1)):02d}"
    month_name = m.group(2).lower()
    year = m.group(3)

    month = MONTHS_ES.get(month_name)
    if not month:
        raise ValueError(f"Mes no reconocido: {month_name}")

    return f"{year}-{month}-{day}"


def parse_eurojackpot_once(text: str) -> Draw:
    date_str = parse_date_es_once(text)

    m = re.search(
        r"Números:\s*([0-9,\s]+)\.\s*Soles:\s*([0-9,\s]+)\.",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError("No pude extraer números y soles de Eurojackpot.")

    main = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
    secondary = [int(x.strip()) for x in m.group(2).split(",") if x.strip()]

    if len(main) != 5 or len(secondary) != 2:
        raise ValueError(f"Formato inesperado Eurojackpot: main={main}, secondary={secondary}")

    return Draw(
        gameId="eurojackpot",
        date=date_str,
        main=main,
        secondary=secondary,
    )


def parse_bonoloto_selae(html: str) -> Draw:
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    try:
        idx = next(
            i for i, line in enumerate(lines)
            if "Ver por orden de aparición" in line
        )
    except StopIteration:
        raise ValueError("No encontré 'Ver por orden de aparición' en la página de Bonoloto.")

    date_es = None
    for line in reversed(lines[max(0, idx - 15):idx]):
        m = re.search(r"(\d{2}/\d{2}/\d{4})", line)
        if m:
            date_es = m.group(1)
            break

    if not date_es:
        raise ValueError("No pude extraer la fecha del último sorteo de Bonoloto.")

    day, month, year = date_es.split("/")
    date_str = f"{year}-{month}-{day}"

    main = []
    j = idx + 1
    while j < len(lines) and len(main) < 6:
        if re.fullmatch(r"\d{1,2}", lines[j]):
            main.append(int(lines[j]))
        j += 1

    if len(main) != 6:
        raise ValueError(f"No pude extraer los 6 números principales. Detectados: {main}")

    complementario = None
    reintegro = None

    for k in range(j, min(j + 10, len(lines) - 1)):
        if lines[k] == "C" and re.fullmatch(r"\d{1,2}", lines[k + 1]):
            complementario = int(lines[k + 1])
        if lines[k] == "R" and re.fullmatch(r"\d{1,2}", lines[k + 1]):
            reintegro = int(lines[k + 1])

    if complementario is None or reintegro is None:
        raise ValueError(
            f"No pude extraer C/R correctamente. C={complementario}, R={reintegro}"
        )

    return Draw(
        gameId="bonoloto",
        date=date_str,
        main=main,
        complementario=complementario,
        reintegro=reintegro,
    )


def load_existing() -> dict:
    if LIVE_FILE.exists():
        return json.loads(LIVE_FILE.read_text(encoding="utf-8"))
    return {
        "schema": "matrisk-official-sync-payload",
        "generatedAt": now_iso(),
        "draws": [],
    }


def draw_to_dict(draw: Draw) -> dict:
    data = asdict(draw)
    return {k: v for k, v in data.items() if v is not None}


def main() -> None:
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing = load_existing()
    draws_by_game: dict[str, dict] = {
        d["gameId"]: d for d in existing.get("draws", []) if "gameId" in d
    }

    errors: list[str] = []

    # Eurojackpot / ONCE
    try:
        once_text = fetch_text(ONCE_URL)
        euro = parse_eurojackpot_once(once_text)
        draws_by_game[euro.gameId] = draw_to_dict(euro)
        print(f"Eurojackpot OK: {euro.date} {euro.main} + {euro.secondary}")
    except Exception as e:
        errors.append(f"Eurojackpot: {e}")
        print(f"Eurojackpot ERROR: {e}")

    # Bonoloto / SELAE
    try:
        bonoloto_html = fetch_text(BONOLOTO_RESULTS_URL)
        bonoloto = parse_bonoloto_selae(bonoloto_html)
        draws_by_game[bonoloto.gameId] = draw_to_dict(bonoloto)
        print(
            f"Bonoloto OK: {bonoloto.date} {bonoloto.main} "
            f"C({bonoloto.complementario}) R({bonoloto.reintegro})"
        )
    except Exception as e:
        errors.append(f"Bonoloto: {e}")
        print(f"Bonoloto ERROR: {e}")

    if not draws_by_game:
        raise RuntimeError("No se pudo actualizar ningún juego. " + " | ".join(errors))

    payload = {
        "schema": "matrisk-official-sync-payload",
        "generatedAt": now_iso(),
        "draws": sorted(draws_by_game.values(), key=lambda d: d["gameId"]),
    }

    LIVE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Updated {LIVE_FILE} with {len(payload['draws'])} draws")
    if errors:
        print("WARNINGS: " + " | ".join(errors))


if __name__ == "__main__":
    main()
