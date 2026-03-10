from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


ROOT = Path(__file__).resolve().parents[1]
LIVE_FILE = ROOT / "live" / "latest.json"
DEBUG_HTML = ROOT / "live" / "_bonoloto_debug.html"
DEBUG_TEXT = ROOT / "live" / "_bonoloto_debug.txt"
CHROME_PROFILE = ROOT / ".pw-chrome-profile"

ONCE_URL = "https://www.juegosonce.es/resultados-eurojackpot-"
BONOLOTO_URL = "https://www.loteriasyapuestas.es/es/resultados/bonoloto"

TIMEOUT = 30

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
    source: str = "local-test"


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def fetch_text(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
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
        source="once-html",
    )


def dismiss_cookie_banner(page) -> None:
    labels = [
        "Solo usar cookies necesarias",
        "Aceptar",
        "Aceptar y cerrar",
        "Aceptar todas",
        "Permitir todas las cookies",
    ]

    for label in labels:
        try:
            page.get_by_role("button", name=re.compile(label, re.IGNORECASE)).click(timeout=2500)
            page.wait_for_timeout(1200)
            return
        except Exception:
            pass

    for label in labels:
        try:
            page.locator(f"text={label}").first.click(timeout=2500)
            page.wait_for_timeout(1200)
            return
        except Exception:
            pass


def fetch_bonoloto_text_with_real_chrome() -> str:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(CHROME_PROFILE),
            channel="chrome",
            headless=False,
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1400, "height": 1100},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(BONOLOTO_URL, wait_until="domcontentloaded", timeout=90000)

            try:
                dismiss_cookie_banner(page)
            except Exception:
                pass

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass

            print("\nSe ha abierto Chrome real en Bonoloto.")
            print("Si aparece el banner de cookies, pulsa manualmente 'Solo usar cookies necesarias'.")
            print("Si ves los resultados cargados, vuelve a esta consola.")
            input("Cuando la página esté visible y correcta, pulsa Enter aquí... ")

            html = page.content()
            DEBUG_HTML.write_text(html, encoding="utf-8")

            visible_text = page.locator("body").inner_text()
            DEBUG_TEXT.write_text(visible_text, encoding="utf-8")

            return visible_text
        finally:
            context.close()


def normalize_lines(text: str) -> list[str]:
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    return [x for x in lines if x]


def parse_bonoloto_text(rendered_text: str) -> Draw:
    lines = normalize_lines(rendered_text)

    # Buscamos una línea con fecha dd/mm/yyyy cerca de Bonoloto
    header_idx = None
    date_es = None

    for idx, line in enumerate(lines):
        m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", line)
        if not m:
            continue

        nearby = " | ".join(lines[max(0, idx - 5): idx + 15]).lower()
        if "bonoloto" in nearby:
            header_idx = idx
            date_es = m.group(1)
            break

    if header_idx is None or date_es is None:
        raise ValueError(
            f"No pude localizar una fecha de sorteo dentro del bloque visible de Bonoloto. Revisa: {DEBUG_TEXT}"
        )

    block = " | ".join(lines[header_idx: header_idx + 40])

    # Quitamos las fechas para que no contaminen la extracción de números
    block = re.sub(r"\b\d{2}/\d{2}/\d{4}\b", " ", block)

    values = [int(x) for x in re.findall(r"\b\d{1,2}\b", block)]

    if len(values) < 8:
        raise ValueError(
            f"No pude extraer 8 valores de Bonoloto. Detectados: {values}. Revisa: {DEBUG_TEXT}"
        )

    day, month, year = date_es.split("/")
    date_str = f"{year}-{month}-{day}"

    main = values[:6]
    complementario = values[6]
    reintegro = values[7]

    return Draw(
        gameId="bonoloto",
        date=date_str,
        main=main,
        complementario=complementario,
        reintegro=reintegro,
        source="selae-real-chrome",
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

    try:
        once_text = fetch_text(ONCE_URL)
        euro = parse_eurojackpot_once(once_text)
        draws_by_game[euro.gameId] = draw_to_dict(euro)
        print(f"Eurojackpot OK: {euro.date} {euro.main} + {euro.secondary}")
    except Exception as e:
        errors.append(f"Eurojackpot: {e}")
        print(f"Eurojackpot ERROR: {e}")

    try:
        bonoloto_text = fetch_bonoloto_text_with_real_chrome()
        bonoloto = parse_bonoloto_text(bonoloto_text)
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
