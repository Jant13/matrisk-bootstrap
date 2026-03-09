from __future__ import annotations

import html
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
SELAE_HOME_URL = "https://www.loteriasyapuestas.es/"
BONOLOTO_PAGE_URL = "https://www.loteriasyapuestas.es/es/bonoloto/resultados"
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

HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

RSS_HEADERS = {
    **HTML_HEADERS,
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Referer": BONOLOTO_PAGE_URL,
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


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    r = requests.get(url, headers=headers or HTML_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def fetch_bonoloto_rss() -> str:
    session = requests.Session()

    # Calentar sesión/cookies antes del RSS
    warmup_urls = [
        SELAE_HOME_URL,
        BONOLOTO_PAGE_URL,
    ]
    for url in warmup_urls:
        try:
            session.get(url, headers=HTML_HEADERS, timeout=TIMEOUT)
        except Exception:
            pass

    r = session.get(BONOLOTO_RSS_URL, headers=RSS_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def parse_date_long_es(text: str) -> str:
    m = re.search(
        r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"No pude extraer fecha española larga desde: {text[:160]}")

    day = f"{int(m.group(1)):02d}"
    month_name = m.group(2).lower()
    year = m.group(3)

    month = MONTHS_ES.get(month_name)
    if not month:
        raise ValueError(f"Mes no reconocido: {month_name}")

    return f"{year}-{month}-{day}"


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
    soup = BeautifulSoup(xml_text, "xml")
    item = soup.find("item")
    if not item:
        raise ValueError("No encontré ningún <item> en el RSS de Bonoloto.")

    title = item.title.get_text(" ", strip=True) if item.title else ""
    desc_raw = item.description.get_text(" ", strip=False) if item.description else ""
    desc_html = html.unescape(desc_raw)
    desc_text = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)

    date_str = parse_date_long_es(title + " " + desc_text)

    m_nums = re.search(
        r"n[úu]meros:\s*([0-9]{1,2}(?:\s*-\s*[0-9]{1,2}){5})",
        desc_text,
        flags=re.IGNORECASE,
    )
    if not m_nums:
        raise ValueError(
            f"No pude extraer la combinación principal de Bonoloto desde: {desc_text[:250]}"
        )

    main = [int(x.strip()) for x in m_nums.group(1).split("-")]

    m_comp = re.search(
        r"Complementario:\s*\(?\s*(\d{1,2})\s*\)?",
        desc_text,
        flags=re.IGNORECASE,
    )
    if not m_comp:
        raise ValueError(f"No pude extraer el complementario desde: {desc_text[:250]}")
    complementario = int(m_comp.group(1))

    m_reint = re.search(
        r"Reintegro:\s*(\d{1,2})",
        desc_text,
        flags=re.IGNORECASE,
    )
    if not m_reint:
        raise ValueError(f"No pude extraer el reintegro desde: {desc_text[:250]}")
    reintegro = int(m_reint.group(1))

    if len(main) != 6:
        raise ValueError(f"Bonoloto principal inválida: {main}")

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
        once_text = fetch_text(ONCE_URL, headers=HTML_HEADERS)
        euro = parse_eurojackpot_once(once_text)
        draws_by_game[euro.gameId] = draw_to_dict(euro)
        print(f"Eurojackpot OK: {euro.date} {euro.main} + {euro.secondary}")
    except Exception as e:
        errors.append(f"Eurojackpot: {e}")
        print(f"Eurojackpot ERROR: {e}")

    # Bonoloto / SELAE RSS
    try:
        bonoloto_rss = fetch_bonoloto_rss()
        bonoloto = parse_bonoloto_rss(bonoloto_rss)
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
