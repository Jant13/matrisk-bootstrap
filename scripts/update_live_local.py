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

DEBUG_EUROM_HTML = ROOT / "live" / "_euromillones_debug.html"
DEBUG_EUROM_TEXT = ROOT / "live" / "_euromillones_debug.txt"
DEBUG_EUROM_BLOCK = ROOT / "live" / "_euromillones_block_debug.txt"

DEBUG_GORDO_HTML = ROOT / "live" / "_gordo_debug.html"
DEBUG_GORDO_TEXT = ROOT / "live" / "_gordo_debug.txt"
DEBUG_GORDO_BLOCK = ROOT / "live" / "_gordo_block_debug.txt"

CHROME_PROFILE = ROOT / ".pw-chrome-profile"

EUROJACKPOT_URL = "https://www.juegosonce.es/resultados-eurojackpot"
PRIMITIVA_URL = "https://www.loteriasyapuestas.es/es/resultados/primitiva"
EUROMILLONES_URL = "https://www.loteriasyapuestas.es/es/resultados/euromillones"
GORDO_URL = "https://www.loteriasyapuestas.es/es/gordo-primitiva/resultados"
BONOLOTO_URL = "https://www.loteriasyapuestas.es/es/resultados/bonoloto"

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


def fetch_gordo_detail_text_with_real_chrome() -> str:
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
            page.goto(GORDO_URL, wait_until="domcontentloaded", timeout=90000)

            try:
                dismiss_cookie_banner(page)
            except Exception:
                pass

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(2500)

            # En esta URL aparece un listado de noticias.
            # Entramos en la primera noticia de resultados.
            first_link = page.locator("text=/El Gordo de la Primitiva: resultados del/i").first
            first_link.click(timeout=10000)

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(2500)

            print("\nSe ha abierto Chrome real en Gordo (detalle del último resultado).")
            print("Si aparece el banner de cookies, pulsa manualmente 'Solo usar cookies necesarias'.")
            print("Si ves los resultados cargados, vuelve a esta consola.")
            input("Cuando la página de Gordo esté visible y correcta, pulsa Enter aquí... ")

            html = page.content()
            DEBUG_GORDO_HTML.write_text(html, encoding="utf-8")

            visible_text = page.locator("body").inner_text()
            DEBUG_GORDO_TEXT.write_text(visible_text, encoding="utf-8")

            return visible_text
        finally:
            context.close()


def extract_first_selae_result_block(
    text: str,
    title: str,
    debug_block_path: Path,
    min_values: int = 8,
    max_chars: int = 2600,
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

        block = body[:max_chars]
        debug_block_path.write_text(
            f"DATE={date_es}\n\nBLOCK:\n{block}\n",
            encoding="utf-8",
        )

        values = [int(x) for x in re.findall(r"\b\d{1,2}\b", block)]
        if len(values) >= min_values:
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
        min_values=8,
        max_chars=2200,
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
        min_values=8,
        max_chars=2600,
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
    joker_match = re.search(r"Joker\s*([0-9 ]{5,})", block, flags=re.IGNORECASE)
    if joker_match:
        joker_digits = "".join(re.findall(r"\d", joker_match.group(1)))
        if joker_digits:
            joker = joker_digits

    if not joker:
        tail = block[-500:]
        joker_match2 = re.search(r"\bJoker\b.*?([0-9 ]{5,})", tail, flags=re.IGNORECASE | re.DOTALL)
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
# EUROMILLONES
# =========================================================
def parse_euromillones_text(rendered_text: str) -> Draw:
    normalized = normalize_text(rendered_text)
    DEBUG_EUROM_TEXT.write_text(normalized, encoding="utf-8")

    pattern = re.compile(
        rf"EUROMILLONES\s+{WEEKDAYS_RE}\s*-\s*(\d{{2}}/\d{{2}}/\d{{4}})(.*?)(?=EUROMILLONES\s+{WEEKDAYS_RE}\s*-\s*\d{{2}}/\d{{2}}/\d{{4}}|BUSCAR SORTEOS|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    matches = list(pattern.finditer(normalized))
    if not matches:
        raise ValueError("No pude localizar el primer bloque real de resultados de EUROMILLONES.")

    for m in matches:
        date_es = m.group(2)
        body = m.group(3)

        block = body[:1200]
        DEBUG_EUROM_BLOCK.write_text(
            f"DATE={date_es}\n\nBLOCK:\n{block}\n",
            encoding="utf-8",
        )

        top = re.split(r"EL MILL[ÓO]N", block, maxsplit=1, flags=re.IGNORECASE)[0]
        values = [int(x) for x in re.findall(r"\b\d{1,2}\b", top)]

        main = [v for v in values if 1 <= v <= 50][:5]
        if len(main) != 5:
            continue

        rest = values[5:]
        secondary = [v for v in rest if 1 <= v <= 12][:2]
        if len(secondary) != 2:
            continue

        day, month, year = date_es.split("/")
        date_str = f"{year}-{month}-{day}"

        return Draw(
            gameId="euromillones",
            date=date_str,
            main=main,
            secondary=secondary,
            source="selae-real-chrome",
        )

    raise ValueError(
        f"Encontré bloques de Euromillones, pero no pude extraer números válidos. Revisa: {DEBUG_EUROM_BLOCK}"
    )


# =========================================================
# EL GORDO DE LA PRIMITIVA
# =========================================================
def parse_gordo_text(rendered_text: str) -> Draw:
    normalized = normalize_text(rendered_text)
    DEBUG_GORDO_TEXT.write_text(normalized, encoding="utf-8")
    DEBUG_GORDO_BLOCK.write_text(normalized[:2000], encoding="utf-8")

    m_date = re.search(
        r"resultados del (\d{2}) de ([a-záéíóú]+) de (\d{4})",
        normalized,
        flags=re.IGNORECASE,
    )
    if not m_date:
        raise ValueError("No pude extraer la fecha del detalle de Gordo.")

    day = m_date.group(1)
    month_name = m_date.group(2).lower()
    year = m_date.group(3)

    month = MONTHS_ES.get(month_name)
    if not month:
        raise ValueError(f"Mes no reconocido en Gordo: {month_name}")

    date_str = f"{year}-{month}-{day}"

    m_nums = re.search(
        r"(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2}).*?R\((\d)\)",
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m_nums:
        raise ValueError("No pude extraer combinación y clave de Gordo.")

    main = [int(m_nums.group(i)) for i in range(1, 6)]
    reintegro = int(m_nums.group(6))

    return Draw(
        gameId="gordo",
        date=date_str,
        main=main,
        reintegro=reintegro,
        source="selae-real-chrome-detail",
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

    try:
        once_text = fetch_text(EUROJACKPOT_URL)
        euro = parse_eurojackpot_once(once_text)
        draws_by_game[euro.gameId] = draw_to_dict(euro)
        print(f"Eurojackpot OK: {euro.date} {euro.main} + {euro.secondary}")
    except Exception as e:
        errors.append(f"Eurojackpot: {e}")
        print(f"Eurojackpot ERROR: {e}")

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

    try:
        euromillones_text = fetch_selae_text_with_real_chrome(
            EUROMILLONES_URL,
            "Euromillones",
            DEBUG_EUROM_HTML,
            DEBUG_EUROM_TEXT,
        )
        euromillones = parse_euromillones_text(euromillones_text)
        draws_by_game[euromillones.gameId] = draw_to_dict(euromillones)
        print(
            f"Euromillones OK: {euromillones.date} {euromillones.main} "
            f"+ {euromillones.secondary}"
        )
    except Exception as e:
        errors.append(f"Euromillones: {e}")
        print(f"Euromillones ERROR: {e}")

    try:
        gordo_text = fetch_gordo_detail_text_with_real_chrome()
        gordo = parse_gordo_text(gordo_text)
        draws_by_game[gordo.gameId] = draw_to_dict(gordo)
        print(f"Gordo OK: {gordo.date} {gordo.main} R({gordo.reintegro})")
    except Exception as e:
        errors.append(f"Gordo: {e}")
        print(f"Gordo ERROR: {e}")

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