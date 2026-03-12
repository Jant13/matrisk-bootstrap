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

DEBUG_BONO_HTML = ROOT / "live" / "_bonoloto_debug.html"
DEBUG_BONO_TEXT = ROOT / "live" / "_bonoloto_debug.txt"
DEBUG_BONO_BLOCK = ROOT / "live" / "_bonoloto_block_debug.txt"

DEBUG_PRIMI_HTML = ROOT / "live" / "_primitiva_debug.html"
DEBUG_PRIMI_TEXT = ROOT / "live" / "_primitiva_debug.txt"
DEBUG_PRIMI_BLOCK = ROOT / "live" / "_primitiva_block_debug.txt"

CHROME_PROFILE = ROOT / ".pw-chrome-profile"

# Fuentes
EUROJACKPOT_URL = "https://www.juegosonce.es/resultados-eurojackpot"
BONOLOTO_URL = "https://www.loteriasyapuestas.es/es/resultados/bonoloto"
PRIMITIVA_URL = "https://www.loteriasyapuestas.es/es/resultados/primitiva"

TIMEOUT = 30
WEEKDAYS_RE = r"(lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)"

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
    joker: str | None = None
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


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\r\n?", "\n", text)
    return text


# =========================================================
# EUROJACKPOT (ONCE, por requests)
# =========================================================
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
        source="once-html-current",
    )


# =========================================================
# SELAE con Chrome real
# =========================================================
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


def fetch_selae_text_with_real_chrome(
    url: str,
    game_name: str,
    debug_html_path: Path,
    debug_text_path: Path,
) -> str:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(CHROME_PROFILE),
            channel="chrome",
            headless=False,
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1400, "height": 1100},
            args=["--disable-blink-features=AutomationControlled"],
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=90000)

            try:
                dismiss_cookie_banner(page)
            except Exception:
                pass

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(2500)

            print(f"\nSe ha abierto Chrome real en {game_name}.")
            print("Si aparece el banner de cookies, pulsa manualmente 'Solo usar cookies necesarias'.")
            print("Si ves los resultados cargados, vuelve a esta consola.")
            input(f"Cuando la página de {game_name} esté visible y correcta, pulsa Enter aquí... ")

            html = page.content()
            debug_html_path.write_text(html, encoding="utf-8")

            visible_text = page.locator("body").inner_text()
            debug_text_path.write_text(visible_text, encoding="utf-8")

            return visible_text
        finally:
            context.close()


def extract_first_selae_result_block(
    text: str,
    title: str,
    debug_block_path: Path,
) -> tuple[str, str]:
    normalized = normalize_text(text)
    escaped_title = re.escape(title)

    pattern = re.compile(
        rf"{escaped_title}\s+{WEEKDAYS_RE}\s*-\s*(\d{{2}}/\d{{2}}/\d{{4}})(.*?)(?={escaped_title}\s+{WEEKDAYS_RE}\s*-\s*\d{{2}}/\d{{2}}/\d{{4}}|BUSCAR SORTEOS|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    matches = list(pattern.finditer(normalized))
    if not matches:
        raise ValueError(f"No pude localizar el primer bloque real de resultados de {title}.")

    for m in matches:
        date_es = m.group(2)
        body = m.group(3)

        block = body[:2200]
        debug_block_path.write_text(
            f"DATE={date_es}\n\nBLOCK:\n{block}\n",
            encoding="utf-8",
        )

        values = [int(x) for x in re.findall(r"\b\d{1,2}\b", block)]

        if len(values) >= 8:
            return date_es, block

    raise ValueError(f"Encontré bloques de {title}, pero no pude extraer valores válidos.")


# =========================================================
# BONOLOTO
# =========================================================
def parse_bonoloto_text(rendered_text: str) -> Draw:
    date_es, block = extract_first_selae_result_block(
        rendered_text,
        "BONOLOTO",
        DEBUG_BONO_BLOCK,
    )

    values = [int(x) for x in re.findall(r"\b\d{1,2}\b", block)]

    if len(values) < 8:
        raise ValueError(
            f"No pude extraer 8 valores (6 principales + C + R) de Bonoloto. Detectados: {values}"
        )

    main = values[:6]
    complementario = values[6]
    reintegro = values[7]

    day, month, year = date_es.split("/")
    date_str = f"{year}-{month}-{day}"

    return Draw(
        gameId="bonoloto",
        date=date_str,
        main=main,
        complementario=complementario,
        reintegro=reintegro,
        source="selae-real-chrome",
    )


# =========================================================
# PRIMITIVA
# =========================================================
def parse_primitiva_text(rendered_text: str) -> Draw:
    normalized = normalize_text(rendered_text)
    DEBUG_PRIMI_TEXT.write_text(normalized, encoding="utf-8")

    date_es, block = extract_first_selae_result_block(
        normalized,
        "LA PRIMITIVA",
        DEBUG_PRIMI_BLOCK,
    )

    values = [int(x) for x in re.findall(r"\b\d{1,2}\b", block)]

    if len(values) < 8:
        raise ValueError(
            f"No pude extraer 8 valores (6 principales + C + R) de Primitiva. Detectados: {values}"
        )

    main = values[:6]
    complementario = values[6]
    reintegro = values[7]

    joker = None

    # Intento 1: "Joker 1234567" o "JOKER 1234567"
    joker_match = re.search(r"Joker\s*([0-9 ]{5,})", block, flags=re.IGNORECASE)
    if joker_match:
        joker_digits = "".join(re.findall(r"\d", joker_match.group(1)))
        if joker_digits:
            joker = joker_digits

    # Intento 2: si no salió, mirar "J" aislada cerca del final
    if not joker:
        tail = block[-400:]
        joker_match2 = re.search(r"\bJ\b\s*([0-9 ]{5,})", tail, flags=re.IGNORECASE)
        if joker_match2:
            joker_digits = "".join(re.findall(r"\d", joker_match2.group(1)))
            if joker_digits:
                joker = joker_digits

    day, month, year = date_es.split("/")
    date_str = f"{year}-{month}-{day}"

    return Draw(
        gameId="primitiva",
        date=date_str,
        main=main,
        complementario=complementario,
        reintegro=reintegro,
        joker=joker,
        source="selae-real-chrome",
    )


# =========================================================
# JSON
# =========================================================
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

    # 1) Eurojackpot
    try:
        once_text = fetch_text(EUROJACKPOT_URL)
        euro = parse_eurojackpot_once(once_text)
        draws_by_game[euro.gameId] = draw_to_dict(euro)
        print(f"Eurojackpot OK: {euro.date} {euro.main} + {euro.secondary}")
    except Exception as e:
        errors.append(f"Eurojackpot: {e}")
        print(f"Eurojackpot ERROR: {e}")

    # 2) Primitiva
    try:
        primitiva_text = fetch_selae_text_with_real_chrome(
            PRIMITIVA_URL,
            "Primitiva",
            DEBUG_PRIMI_HTML,
            DEBUG_PRIMI_TEXT,
        )
        primitiva = parse_primitiva_text(primitiva_text)
        draws_by_game[primitiva.gameId] = draw_to_dict(primitiva)
        joker_txt = f" J({primitiva.joker})" if primitiva.joker else ""
        print(
            f"Primitiva OK: {primitiva.date} {primitiva.main} "
            f"C({primitiva.complementario}) R({primitiva.reintegro}){joker_txt}"
        )
    except Exception as e:
        errors.append(f"Primitiva: {e}")
        print(f"Primitiva ERROR: {e}")

    # 3) Bonoloto
    try:
        bonoloto_text = fetch_selae_text_with_real_chrome(
            BONOLOTO_URL,
            "Bonoloto",
            DEBUG_BONO_HTML,
            DEBUG_BONO_TEXT,
        )
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
