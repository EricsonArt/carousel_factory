"""
Text renderer dla slajdow karuzeli.

Funkcje:
  - apply_text_to_image(img, headline, body, slide_index, settings) -> Image
  - DEFAULT_TEXT_SETTINGS / merge_text_settings()
  - smart_position()        — wybiera najlepsze miejsce gdy settings.position == "auto"
  - adaptive_overlay()      — subtelny gradient pod tekstem gdy tlo jasne / niespokojne

Settings dict (canonical keys):
  - headline_size_hero   int   pt nag rozmiaru slajdu 1
  - headline_size_rest   int   pt slajdy 2+
  - body_size            int   pt body
  - body_same_as_headline bool jesli True, body uzywa tych samych rozmiarow co headline
  - font_key             str   "montserrat_black" | "montserrat_bold" | "inter" | "system"
  - text_color           str   "#FFFFFF"
  - stroke_color         str   "#000000"
  - stroke_width         int   0..12
  - position             str   "auto" | "top" | "center" | "bottom"
  - uppercase            bool
  - text_length          str   "short" | "medium" | "long"   (uzywane przez generate_copy)
  - smart_fitting        bool  auto-overlay + smart-position
"""
from __future__ import annotations
import io
import statistics
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat

from config import (
    SLIDE_WIDTH, SLIDE_HEIGHT,
    SLIDE_FONT_HEADLINE, SLIDE_FONT_BODY,
    ASSETS_FONTS_DIR,
)
from core.utils import wrap_text_for_slide, hex_to_rgb


DEFAULT_TEXT_SETTINGS: dict = {
    "headline_size_hero": 92,
    "headline_size_rest": 70,
    "body_size": 36,
    "body_same_as_headline": False,
    "flat_text_style": False,            # NOWE: headline = ten sam font/rozmiar co body (naturalny look)
    "hide_headline_first_two": False,    # NOWE: slajdy 1 i 2 bez naglowka, tylko body
    "font_key": "montserrat_black",
    "text_color": "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 6,
    "position": "auto",
    "uppercase": True,
    "text_length": "medium",
    "smart_fitting": True,
}


def merge_text_settings(user_settings: Optional[dict]) -> dict:
    """Merge user settings z defaultami — brakujace klucze wypelnia DEFAULT_TEXT_SETTINGS."""
    out = dict(DEFAULT_TEXT_SETTINGS)
    if user_settings:
        for k, v in user_settings.items():
            if v is not None and k in DEFAULT_TEXT_SETTINGS:
                out[k] = v
    return out


# ─────────────────────────────────────────────────────────────
# FONT LOADING
# ─────────────────────────────────────────────────────────────

_FONT_PATH_CACHE: dict[str, str] = {}


def _resolve_font_path(font_key: str, role: str) -> str:
    """
    Mapuje font_key + role (headline/body) na konkretna sciezke pliku TTF.
    Cache w pamieci procesu — system file lookup tylko raz.
    """
    cache_key = f"{font_key}:{role}"
    if cache_key in _FONT_PATH_CACHE:
        return _FONT_PATH_CACHE[cache_key]

    candidates: list = []
    if font_key == "montserrat_black":
        candidates = [ASSETS_FONTS_DIR / "Montserrat-Black.ttf",
                       ASSETS_FONTS_DIR / "Montserrat-Bold.ttf"]
    elif font_key == "montserrat_bold":
        candidates = [ASSETS_FONTS_DIR / "Montserrat-Bold.ttf",
                       ASSETS_FONTS_DIR / "Montserrat-Black.ttf"]
    elif font_key == "inter":
        candidates = [ASSETS_FONTS_DIR / "Inter-Variable.ttf",
                       ASSETS_FONTS_DIR / "Montserrat-Bold.ttf"]
    else:  # "system" / fallback
        path = SLIDE_FONT_HEADLINE if role == "headline" else SLIDE_FONT_BODY
        _FONT_PATH_CACHE[cache_key] = path or ""
        return path or ""

    for p in candidates:
        try:
            if p.exists():
                _FONT_PATH_CACHE[cache_key] = str(p)
                return str(p)
        except (OSError, PermissionError):
            continue

    fallback = SLIDE_FONT_HEADLINE if role == "headline" else SLIDE_FONT_BODY
    _FONT_PATH_CACHE[cache_key] = fallback or ""
    return fallback or ""


def _load_font(path: str, size: int):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _text_width(text: str, font) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _text_height(text: str, font) -> int:
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]


# ─────────────────────────────────────────────────────────────
# SMART POSITION (analiza obrazu)
# ─────────────────────────────────────────────────────────────

def _region_busyness(img: Image.Image, top: int, bottom: int) -> float:
    """
    Zwraca 'busyness score' regionu (top..bottom px na osi Y).
    Niski wynik = spokojny region (dobry na tekst). Wysoki = ruch/szczegoly.

    Mierzymy: (a) edge density po Sobel/FIND_EDGES, (b) std-dev jasnosci.
    """
    if bottom <= top:
        return 0.0
    region = img.crop((0, top, img.width, bottom)).convert("L")
    edges = region.filter(ImageFilter.FIND_EDGES)
    edge_mean = ImageStat.Stat(edges).mean[0]
    luma_std = ImageStat.Stat(region).stddev[0]
    return float(edge_mean * 1.2 + luma_std * 0.8)


def smart_position(img: Image.Image, text_height: int, safe_top: int, safe_bottom: int) -> int:
    """
    Wybiera y_start dla tekstu na bazie analizy 3 stref (top/center/bottom).
    Zwraca y_start w pikselach.
    """
    H = img.height
    available_h = H - safe_top - safe_bottom

    # Trzy kandydatury Y
    candidates = {
        "top":    safe_top,
        "center": safe_top + (available_h - text_height) // 2,
        "bottom": H - safe_bottom - text_height,
    }

    scores = {}
    for name, y in candidates.items():
        y_clamped = max(safe_top, min(y, H - safe_bottom - text_height))
        scores[name] = _region_busyness(img, y_clamped, y_clamped + text_height)

    # Najmniejsza busyness wygrywa
    best = min(scores, key=scores.get)
    y = candidates[best]
    return max(safe_top, min(y, H - safe_bottom - text_height))


# ─────────────────────────────────────────────────────────────
# ADAPTIVE OVERLAY (gradient pod tekstem)
# ─────────────────────────────────────────────────────────────

def _region_brightness(img: Image.Image, top: int, bottom: int) -> float:
    """Srednia jasnosc regionu 0-255."""
    if bottom <= top:
        return 128.0
    region = img.crop((0, top, img.width, bottom)).convert("L")
    return float(ImageStat.Stat(region).mean[0])


def _region_busyness_simple(img: Image.Image, top: int, bottom: int) -> float:
    if bottom <= top:
        return 0.0
    region = img.crop((0, top, img.width, bottom)).convert("L")
    return float(ImageStat.Stat(region).stddev[0])


def adaptive_overlay(img: Image.Image, y_top: int, y_bottom: int,
                      text_color_hex: str, has_strong_stroke: bool = False) -> Image.Image:
    """
    Dodaje BARDZO SUBTELNY gradient za tekstem TYLKO gdy:
      - tekst nie ma mocnego obrysu (has_strong_stroke=False)
      - tlo wyraznie kontrastuje slabo z tekstem (high luma diff vs ekstremalna)
      - lub tlo bardzo niespokojne (std-dev > 75)
    Gradient: smooth fade, peak alpha tylko 60/255 (24%) — nie zaslania tla.
    """
    H = img.height
    y_top = max(0, y_top)
    y_bottom = min(H, y_bottom)
    if y_bottom - y_top < 20:
        return img

    # Jezeli mamy mocny stroke (3+), tekst sam jest czytelny — zaden overlay nie potrzebny
    if has_strong_stroke:
        return img

    text_is_light = _is_color_light(text_color_hex)
    bg_brightness = _region_brightness(img, y_top, y_bottom)
    bg_busyness = _region_busyness_simple(img, y_top, y_bottom)

    # Zmiekczone progi: overlay tylko gdy naprawde trzeba
    needs_overlay = False
    if text_is_light and bg_brightness > 180:  # bylo 140 — teraz tylko bardzo jasne tla
        needs_overlay = True
    if not text_is_light and bg_brightness < 70:  # bylo 110 — teraz tylko bardzo ciemne tla
        needs_overlay = True
    if bg_busyness > 75:  # bylo 55 — teraz tylko bardzo niespokojne tla
        needs_overlay = True

    if not needs_overlay:
        return img

    # Buduj gradient layer (RGBA), full image rozmiar, alpha = 0 wszedzie poza strefa tekstu
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    base_rgb = (0, 0, 0) if text_is_light else (255, 255, 255)

    # Padding gradientu - smooth fade in/out
    pad = 80
    region_top = max(0, y_top - pad)
    region_bottom = min(H, y_bottom + pad)
    peak_alpha = 60  # bylo 140 — znacznie subtelniejsze (24% nieprzezroczystosci)

    pixels = overlay.load()
    width = img.width
    for y in range(region_top, region_bottom):
        # 0 na krawedziach, peak w srodku strefy tekstu
        if y < y_top:
            t = (y - region_top) / max(pad, 1)
            alpha = int(peak_alpha * t)
        elif y > y_bottom:
            t = (region_bottom - y) / max(pad, 1)
            alpha = int(peak_alpha * t)
        else:
            alpha = peak_alpha
        for x in range(width):
            pixels[x, y] = (base_rgb[0], base_rgb[1], base_rgb[2], alpha)

    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")
    return img


def _is_color_light(hex_color: str) -> bool:
    """Czy kolor jest 'jasny' (luminance > 140)?"""
    try:
        r, g, b = hex_to_rgb(hex_color)
    except Exception:
        return True
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    return luma > 140


# ─────────────────────────────────────────────────────────────
# GLOWNY ENTRY: APPLY TEXT TO IMAGE
# ─────────────────────────────────────────────────────────────

def _pick_font_size_for_lines(lines: list[str], requested_size: int, min_size: int) -> int:
    """Skaluje font na bazie najdluzszej linii — krotka linia dostaje pelny rozmiar."""
    if not lines:
        return min_size
    longest = max(len(l) for l in lines)
    if longest <= 12:
        return requested_size
    if longest <= 18:
        return max(min_size, int(requested_size * 0.85))
    if longest <= 24:
        return max(min_size, int(requested_size * 0.72))
    return max(min_size, int(requested_size * 0.6))


def apply_text_to_image(
    img: Image.Image,
    headline: str,
    body: str,
    slide_index: int,
    text_settings: Optional[dict] = None,
    image_focus_hint: str = "center",
) -> Image.Image:
    """
    Naklada tekst na obraz wedlug text_settings.

    slide_index: 0 = slajd 1 (hero rozmiar), >=1 = pozostale (rest rozmiar).
    image_focus_hint: 'top'|'center'|'bottom'|'auto' z copywritera per-slajd.
                       Uzywany gdy settings.position == 'auto'.

    Zwraca nowy Image (RGB).
    """
    s = merge_text_settings(text_settings)

    # OPCJA: ukryj naglowek na slajdach 1-2 (slide_index 0 i 1).
    # Headline znika; body zostaje normalnie, daje "ludzki" feel zamiast "reklamy".
    if s.get("hide_headline_first_two") and slide_index < 2:
        headline = ""

    if not headline and not body:
        return img

    if s["uppercase"]:
        headline = (headline or "").upper()
        body = (body or "").upper()

    # Rozmiary fontu zgodnie z slide_index (hero vs rest)
    is_hero = (slide_index == 0)
    head_target_size = s["headline_size_hero"] if is_hero else s["headline_size_rest"]

    if s["body_same_as_headline"]:
        body_target_size = head_target_size
    else:
        body_target_size = s["body_size"]

    head_font_path = _resolve_font_path(s["font_key"], "headline")
    body_font_path = _resolve_font_path(s["font_key"], "body")

    # OPCJA: flat_text_style — naglowek dostaje TEN SAM rozmiar i font co body.
    # Eliminuje "wielki bold headline + maly body" reklame-look,
    # daje jednolity "ludzki" tekst.
    if s.get("flat_text_style"):
        head_target_size = body_target_size
        head_font_path = body_font_path

    W, H = img.size

    # Safe zones: top 15% (TT username), bottom 28% (TT actions + IG caption)
    # → tekst w srodkowych ~57%
    safe_top = int(H * 0.15)
    safe_bottom = int(H * 0.28)
    available_h = H - safe_top - safe_bottom

    # Wraps
    headline_lines = wrap_text_for_slide(headline or "", max_chars_per_line=14)
    body_lines = wrap_text_for_slide(body or "", max_chars_per_line=28)

    # Auto-shrink: zaczynamy od targetow, schodzimy dol jesli nie miesci
    head_size = _pick_font_size_for_lines(headline_lines,
                                           requested_size=head_target_size,
                                           min_size=max(40, int(head_target_size * 0.55)))
    body_size = _pick_font_size_for_lines(body_lines,
                                           requested_size=body_target_size,
                                           min_size=max(20, int(body_target_size * 0.6)))

    head_line_gap = 10
    body_line_gap = 6
    block_gap = 28

    def _measure(hs, bs):
        hf = _load_font(head_font_path, hs)
        bf = _load_font(body_font_path, bs)
        hh = sum(_text_height(l, hf) for l in headline_lines) \
             + head_line_gap * max(0, len(headline_lines) - 1)
        bh = sum(_text_height(l, bf) for l in body_lines) \
             + body_line_gap * max(0, len(body_lines) - 1)
        g = block_gap if headline_lines and body_lines else 0
        return hf, bf, hh, bh, g, hh + g + bh

    head_font, body_font, head_h, body_h, gap, total_h = _measure(head_size, body_size)

    # Auto-shrink loop — zwezamy obie wartosci proporcjonalnie az sie zmiesci
    min_head = max(40, int(head_target_size * 0.55))
    min_body = max(20, int(body_target_size * 0.6))
    while total_h > available_h and (head_size > min_head or body_size > min_body):
        head_size = max(min_head, int(head_size * 0.92))
        body_size = max(min_body, int(body_size * 0.92))
        head_font, body_font, head_h, body_h, gap, total_h = _measure(head_size, body_size)
        if head_size <= min_head and body_size <= min_body:
            break

    # POZYCJA: smart_fitting + position == 'auto' → analizuj obraz; inaczej hint
    position_setting = s["position"]
    if position_setting == "auto":
        if s["smart_fitting"]:
            y_start = smart_position(img, total_h, safe_top, safe_bottom)
        else:
            # Fallback: uzyj image_focus_hint z copywritera per-slajd
            y_start = _y_from_hint(image_focus_hint, H, total_h, safe_top, safe_bottom)
    else:
        y_start = _y_from_hint(position_setting, H, total_h, safe_top, safe_bottom)

    # Hard clamp
    y_start = max(safe_top, min(y_start, H - safe_bottom - total_h))

    # ADAPTIVE OVERLAY — subtelny gradient pod tekstem dla czytelnosci.
    # Przy mocnym stroke (3+ pikseli) tekst sam jest czytelny — gradient nie potrzebny.
    if s["smart_fitting"]:
        has_strong_stroke = int(s.get("stroke_width", 0)) >= 3
        img = adaptive_overlay(
            img, y_start - 20, y_start + total_h + 20, s["text_color"],
            has_strong_stroke=has_strong_stroke,
        )

    draw = ImageDraw.Draw(img)
    text_color = s["text_color"]
    stroke_color = s["stroke_color"]
    stroke_width = max(0, int(s["stroke_width"]))
    body_stroke = max(0, stroke_width - 3) if stroke_width > 0 else 0

    # Render headline
    y = y_start
    for line in headline_lines:
        x = (W - _text_width(line, head_font)) // 2
        draw.text(
            (x, y), line,
            font=head_font,
            fill=text_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color if stroke_width > 0 else text_color,
        )
        y += _text_height(line, head_font) + head_line_gap

    if headline_lines and body_lines:
        y += gap

    for line in body_lines:
        x = (W - _text_width(line, body_font)) // 2
        draw.text(
            (x, y), line,
            font=body_font,
            fill=text_color,
            stroke_width=body_stroke,
            stroke_fill=stroke_color if body_stroke > 0 else text_color,
        )
        y += _text_height(line, body_font) + body_line_gap

    return img


def _y_from_hint(hint: str, H: int, total_h: int, safe_top: int, safe_bottom: int) -> int:
    available_h = H - safe_top - safe_bottom
    if hint == "top":
        return safe_top
    if hint == "bottom":
        return H - safe_bottom - total_h
    return safe_top + (available_h - total_h) // 2  # center / inne


# ─────────────────────────────────────────────────────────────
# LENGTH DIRECTIVE dla copywritera
# ─────────────────────────────────────────────────────────────

LENGTH_DIRECTIVES = {
    "short":  "BARDZO KROTKO: headline max 5 slow, body max 8 slow. Jedno krotkie zdanie.",
    "medium": "Standardowo: headline 2-7 slow, body 8-14 slow. Jedno krotkie zdanie.",
    "long":   "Pelne: headline 4-8 slow, body 14-22 slow. Mozna 1-2 zdania.",
}


def length_directive_for_prompt(text_length: str) -> str:
    return LENGTH_DIRECTIVES.get(text_length, LENGTH_DIRECTIVES["medium"])
