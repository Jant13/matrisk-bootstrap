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

ONCE_URL = "https://www.juegosonce.es/resultados-eurojackpot-"
BONOLOTO_RSS_URL = "https://www.loteriasyapuestas.es/es/bonoloto/resultados/.formatoRSS"
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
        "User-Agent": "Mozilla/5.0 (compatible; MaTrisK-GitHub-Action/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7",
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
        raise ValueError(
            f"Formato inesperado Eurojackpot: main={main}, secondary={secondary}"
        )

    return Draw(
        gameId="eurojackpot",
        date=date_str,
        main=main,
        secondary=secondary,
    )


def parse_bonoloto_rss(xml_text: str) -> Draw:
    soup = BeautifulSoup(xml_text, "html.parser")
    item = soup.find("item")
    if not item:
        raise ValueError("No encontré ningún <item> en el RSS de Bonoloto.")

    title_tag = item.find("title")
    desc_tag = item.find("description")

    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    description_html = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    if not title:
        raise ValueError("El RSS de Bonoloto no contiene título en el primer item.")

    m_date = re.search(
        r"del\s+(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})",
        title,
        flags=re.IGNORECASE,
    )
    if not m_date:
        raise ValueError(f"No pude extraer la fecha del título RSS: {title}")

    day = f"{int(m_date.group(1)):02d}"
    month_name = m_date.group(2).lower()
    year = m_date.group(3)

    month = MONTHS_ES.get(month_name)
    if not month:
        raise ValueError(f"Mes no reconocido en Bonoloto RSS: {month_name}")

    date_str = f"{year}-{month}-{day}"

    description_text = BeautifulSoup(description_html, "html.parser").get_text(
        " ", strip=True
    )
    description_text = re.sub(r"\s+", " ", description_text)

    m_nums = re.search(
        r"n[uú]meros:\s*([0-9\s\-]+)\s+Complementario:\s*\(?(\d{1,2})\)?\s+Reintegro:\s*\(?(\d{1,2})\)?",
        description_text,
        flags=re.IGNORECASE,
    )
    if not m_nums:
        raise ValueError(
            f"No pude extraer números/C/R del RSS de Bonoloto: {description_text}"
        )

    main = [int(x.strip()) for x in m_nums.group(1).split("-") if x.strip()]
    complementario = int(m_nums.group(2))
    reintegro = int(m_nums.group(3))

    if len(main) != 6:
        raise ValueError(f"Bonoloto RSS devolvió {len(main)} números en lugar de 6: {main}")

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

    # Bonoloto / SELAE RSS
    try:
        bonoloto_xml = fetch_text(BONOLOTO_RSS_URL)
        bonoloto = parse_bonoloto_rss(bonoloto_xml)
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
            
