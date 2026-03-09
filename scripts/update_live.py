from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
LIVE_FILE = ROOT / "live" / "latest.json"

ONCE_URL = "https://www.juegosonce.es/resultados-eurojackpot-"
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
    secondary: list[int]
    source: str = "remote-manifest"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_text(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MaTrisK-GitHub-Action/1.0)"
    }
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def parse_date_es(text: str) -> str:
    # Ejemplo:
    # "Último sorteo celebrado el martes, 24 de febrero de 2026"
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
    date_str = parse_date_es(text)

    # Línea típica:
    # "Números: 4, 5, 26, 38, 48. Soles: 2, 9."
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
        raise ValueError(f"Formato inesperado: main={main}, secondary={secondary}")

    return Draw(
        gameId="eurojackpot",
        date=date_str,
        main=main,
        secondary=secondary,
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
    return {
        "gameId": draw.gameId,
        "date": draw.date,
        "main": draw.main,
        "secondary": draw.secondary,
        "source": draw.source,
    }


def main() -> None:
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)

    text = fetch_text(ONCE_URL)
    draw = parse_eurojackpot_once(text)

    current = load_existing()
    current_draws = current.get("draws", [])

    new_draw = draw_to_dict(draw)

    # Si ya existe exactamente, solo refresca generatedAt sin reescribir innecesariamente
    if current_draws == [new_draw]:
        current["generatedAt"] = now_iso()
    else:
        current = {
            "schema": "matrisk-official-sync-payload",
            "generatedAt": now_iso(),
            "draws": [new_draw],
        }

    LIVE_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {LIVE_FILE} with Eurojackpot draw {draw.date}: {draw.main} + {draw.secondary}")


if __name__ == "__main__":
    main()
