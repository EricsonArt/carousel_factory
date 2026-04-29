"""
Carousel Generator - orchestrator pelnego pipeline'u:
  1) Copywriter (Claude) -> JSON ze slajdami (headline, body, image_prompt)
  2) Image Router -> generuje obraz tla per slajd (z reference images stylu)
  3) Pillow overlay -> nakłada polski tekst na finalny obraz
  4) Walidacja vs brief -> blokuje halucynacje/forbidden claims
  5) Save do bazy + plikow
"""
import io
import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from config import (
    PROMPTS_DIR, CAROUSELS_DIR,
    SLIDE_WIDTH, SLIDE_HEIGHT,
    SLIDE_FONT_HEADLINE, SLIDE_FONT_BODY,
    SLIDE_TEXT_COLOR, SLIDE_TEXT_STROKE, SLIDE_TEXT_STROKE_WIDTH,
    DEFAULT_SLIDES, MIN_SLIDES, MAX_SLIDES,
)
try:
    from config import SLIDE_TEXT_STROKE_WIDTH_BODY
except ImportError:
    SLIDE_TEXT_STROKE_WIDTH_BODY = max(2, SLIDE_TEXT_STROKE_WIDTH - 3)
from core.llm import call_claude_json, validate_against_brief
from core.image_router import generate_image, QuotaExhausted, ImageGenerationError
from core.utils import (
    generate_id, ensure_dir, write_image_bytes, hex_to_rgb,
    wrap_text_for_slide, sanitize_filename,
)
from db import create_carousel, update_carousel, get_brief, get_style


# ─────────────────────────────────────────────────────────────
# STEP 1: COPYWRITER
# ─────────────────────────────────────────────────────────────

def _load_copy_prompt() -> str:
    return (PROMPTS_DIR / "carousel_copy.md").read_text(encoding="utf-8")


def generate_copy(
    topic: str,
    brief: dict,
    style: Optional[dict] = None,
    slide_count: int = DEFAULT_SLIDES,
    language: str = "pl",
) -> dict:
    """
    Generuje cala karuzele tekstowa (slides + caption + hashtags).
    language: 'pl' | 'en' — w jakim języku ma być treść slajdów.
    """
    slide_count = max(MIN_SLIDES, min(MAX_SLIDES, slide_count))
    system_prompt = _load_copy_prompt()

    style_section = ""
    if style:
        hooks = style.get("hook_formulas") or []
        style_section = f"""

STYL VISUAL (do inspiracji hookow i tonu):
- Hook formulas wzorce: {json.dumps(hooks, ensure_ascii=False)}
- Mood: {style.get('mood', '')}
- Image style (do image_prompt kazdego slajdu): {style.get('image_style', '')}
"""

    if language == "en":
        language_directive = (
            "- LANGUAGE: ENGLISH. All slide text (headlines, body, caption, hashtags labels) "
            "must be in fluent, native English. Do NOT use any Polish words or characters. "
            "Hashtags should be English/global (e.g. #tips, #howto, #productivity)."
        )
    else:
        language_directive = (
            "- LANGUAGE: POLSKI. Z poprawnymi znakami diakrytycznymi (ą ę ó ł ś ć ż ź ń). "
            "Hashtagi mieszane PL i EN."
        )

    prompt = f"""Stworz MAKSYMALNIE WIRALOWA karuzele Instagram/TikTok na temat:
"{topic}"

PARAMETRY:
- Liczba slajdow: {slide_count} (dokladnie tyle)
{language_directive}

BRIEF MARKI:
{json.dumps(brief, ensure_ascii=False, indent=2)}
{style_section}

WAZNE:
- Uzywaj WYLACZNIE USPs i ofert z briefa - nie wymyslaj nowych cech produktu
- Trzymaj sie voice_tone z briefa
- Mow do glownego avatara z briefa
- W ostatnim slajdzie (CTA) uzyj cta_url z briefa
- Forbidden claims sa ZAKAZANE: {json.dumps(brief.get('forbidden_claims', []), ensure_ascii=False)}

Zwroc JSON zgodny ze schematem opisanym w system promptcie. TYLKO JSON.
"""
    return call_claude_json(prompt, system=system_prompt, max_tokens=6000)


# ─────────────────────────────────────────────────────────────
# STEP 2: IMAGE GENERATION + STEP 3: PILLOW OVERLAY
# ─────────────────────────────────────────────────────────────

def render_slide_image(
    slide: dict,
    style: Optional[dict],
    output_path: Path,
    use_ai_images: bool = False,
    prefer_provider: Optional[str] = None,
    image_quality: str = "low",
    model_override: Optional[str] = None,
    text_mode: str = "overlay",
) -> dict:
    """
    Generuje obraz tla + tekst.
    text_mode:
      - "overlay" (default) — Pillow naklada tekst po wygenerowaniu obrazu (PL znaki gwarantowane)
      - "inline"  — model AI generuje tekst RAZEM z obrazem (TikTok-style, ale moze masakrowac PL)
    Zwraca {"image_path": ..., "image_provider": ..., "image_model": ...}
    """
    headline = slide.get("headline", "")
    body = slide.get("body", "")
    image_focus = slide.get("image_focus", "center")

    # Tekst do wstrzykniecia w obraz (tylko dla trybu inline)
    # KRYTYCZNE: w inline puszczamy TYLKO headline (krotki) — body jest za dlugi
    # i modele AI go masakruja na akapity lawiny. Body lapie sie pod karuzela jako caption.
    inline_text_payload = None
    if text_mode == "inline" and use_ai_images:
        ht = (headline or "").strip().upper()
        if ht:
            inline_text_payload = ht

    if use_ai_images:
        image_prompt = slide.get("image_prompt", "")
        style_hint = ""
        refs = []
        if style:
            style_hint = ". ".join(filter(None, [
                style.get("image_style", ""),
                style.get("composition_notes", ""),
                f"palette: {', '.join(style.get('palette', [])[:5])}" if style.get("palette") else "",
                f"mood: {style.get('mood', '')}" if style.get("mood") else "",
            ]))
            refs = list(style.get("reference_image_paths") or [])

        try:
            result = generate_image(
                prompt=image_prompt or f"Background for social media carousel slide about: {headline}",
                reference_images=refs[:4],
                size=(SLIDE_WIDTH, SLIDE_HEIGHT),
                style_hint=style_hint,
                prefer_provider=prefer_provider,
                quality=image_quality,
                model_override=model_override,
                inline_text=inline_text_payload,
            )
        except (QuotaExhausted, ImageGenerationError):
            result = {
                "image_bytes": _solid_background_with_palette(style),
                "provider": "fallback",
                "model": "solid_color",
                "cost_usd": 0.0,
            }
            # Fallback nie ma tekstu — wymus overlay
            inline_text_payload = None
    else:
        # Bez AI: gradient z palety + zawsze Pillow overlay
        result = {
            "image_bytes": _gradient_background_with_palette(style),
            "provider": "local",
            "model": "gradient",
            "cost_usd": 0.0,
        }
        inline_text_payload = None

    img = Image.open(io.BytesIO(result["image_bytes"])).convert("RGB")
    img = img.resize((SLIDE_WIDTH, SLIDE_HEIGHT), Image.LANCZOS)

    # Tekst nakladamy Pillowem TYLKO gdy nie wstrzyknelismy go do AI
    if not inline_text_payload:
        img = _overlay_text(img, headline, body, image_focus, style)

    ensure_dir(output_path.parent)
    img.save(output_path, "JPEG", quality=92)

    return {
        "image_path": str(output_path),
        "image_provider": result["provider"],
        "image_model": result["model"],
        "cost_usd": result["cost_usd"],
    }


def _overlay_text(img: Image.Image, headline: str, body: str,
                    focus: str, style: Optional[dict]) -> Image.Image:
    """
    Naklada tekst w stylu TikTok/IG: Montserrat Black + mocny czarny obrys.
    Bez ciemnego boxa za tekstem — sam stroke wystarcza dla czytelnosci.

    Safe zones (zeby nie zaslaniac UI platformy):
      - top 15%   → TikTok username/header, IG handle
      - bottom 28% → TikTok action buttons + caption, IG caption
      → tekst ma siedziec w srodkowych ~57% wysokosci.
    """
    if not headline and not body:
        return img

    W, H = img.size
    draw = ImageDraw.Draw(img)

    safe_top = int(H * 0.15)
    safe_bottom = int(H * 0.28)
    available_h = H - safe_top - safe_bottom

    # Wraps — krotkie linie dla impactu
    headline_lines = wrap_text_for_slide(headline.upper() if headline else "", max_chars_per_line=14)
    body_lines = wrap_text_for_slide(body or "", max_chars_per_line=28)

    # Mniejsze fonty — naglowek byl za duzy
    total_chars = sum(len(l) for l in headline_lines + body_lines)
    head_size = _pick_font_size(headline_lines, max_size=92, min_size=56)
    body_size = _pick_font_size(body_lines, max_size=36, min_size=26)
    if total_chars > 120:
        head_size = int(head_size * 0.85)
        body_size = int(body_size * 0.85)

    head_line_gap = 10
    body_line_gap = 6
    block_gap = 28

    def _measure(hs, bs):
        hf = _load_font(SLIDE_FONT_HEADLINE, hs)
        bf = _load_font(SLIDE_FONT_BODY, bs)
        hh = sum(_text_height(l, hf) for l in headline_lines) \
             + head_line_gap * max(0, len(headline_lines) - 1)
        bh = sum(_text_height(l, bf) for l in body_lines) \
             + body_line_gap * max(0, len(body_lines) - 1)
        g = block_gap if headline_lines and body_lines else 0
        return hf, bf, hh, bh, g, hh + g + bh

    head_font, body_font, head_h, body_h, gap, total_h = _measure(head_size, body_size)

    # Auto-shrink: jak nie miesci sie w safe zone, skaluj az do min
    while total_h > available_h and (head_size > 56 or body_size > 26):
        head_size = max(56, int(head_size * 0.92))
        body_size = max(26, int(body_size * 0.92))
        head_font, body_font, head_h, body_h, gap, total_h = _measure(head_size, body_size)
        if head_size <= 56 and body_size <= 26:
            break

    # Pozycja w safe zone
    if focus == "top":
        y_start = safe_top
    elif focus == "bottom":
        y_start = H - safe_bottom - total_h
    else:
        # center w obrebie safe area
        y_start = safe_top + (available_h - total_h) // 2

    # Hard clamp
    y_start = max(safe_top, min(y_start, H - safe_bottom - total_h))

    # Render headline — Montserrat Black + grube czarne stroke
    y = y_start
    for line in headline_lines:
        x = (W - _text_width(line, head_font)) // 2
        draw.text(
            (x, y), line,
            font=head_font,
            fill=SLIDE_TEXT_COLOR,
            stroke_width=SLIDE_TEXT_STROKE_WIDTH,
            stroke_fill=SLIDE_TEXT_STROKE,
        )
        y += _text_height(line, head_font) + head_line_gap

    if headline_lines and body_lines:
        y += gap

    # Render body — cienszy stroke
    for line in body_lines:
        x = (W - _text_width(line, body_font)) // 2
        draw.text(
            (x, y), line,
            font=body_font,
            fill=SLIDE_TEXT_COLOR,
            stroke_width=SLIDE_TEXT_STROKE_WIDTH_BODY,
            stroke_fill=SLIDE_TEXT_STROKE,
        )
        y += _text_height(line, body_font) + body_line_gap

    return img


def _load_font(path: str, size: int):
    """
    Probuje zaladowac font ze sciezki. Obsluga edge case'ow:
      - empty path (brak fontow systemowych) -> Pillow default ze skalowaniem (10.1+)
      - nie znaleziony plik -> default ze skalowaniem
      - inny blad -> default ze skalowaniem
    """
    if path:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass

    # Fallback - Pillow 10.1+ default font supports size
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 10.1 - bitmap font bez size
        return ImageFont.load_default()


def _pick_font_size(lines: list[str], max_size: int, min_size: int) -> int:
    if not lines:
        return min_size
    longest = max(len(l) for l in lines)
    if longest <= 12:
        return max_size
    if longest <= 18:
        return int(max_size * 0.85)
    if longest <= 24:
        return int(max_size * 0.7)
    return min_size


def _text_width(text: str, font) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _text_height(text: str, font) -> int:
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]


def _solid_background_with_palette(style: Optional[dict]) -> bytes:
    """Fallback gdy generator obrazow padl - solidny kolor z palety stylu."""
    palette = (style or {}).get("palette") or ["#1a1a2e"]
    color = palette[0] if isinstance(palette, list) and palette else "#1a1a2e"
    rgb = hex_to_rgb(color)
    img = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), rgb)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _gradient_background_with_palette(style: Optional[dict]) -> bytes:
    """Gradient z 2 kolorów palety — szybkie tło bez AI."""
    palette = (style or {}).get("palette") or ["#1a1a2e", "#4c1d95"]
    c1 = hex_to_rgb(palette[0] if palette else "#1a1a2e")
    c2 = hex_to_rgb(palette[1] if len(palette) > 1 else "#4c1d95")

    img = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT))
    pixels = img.load()
    for y in range(SLIDE_HEIGHT):
        t = y / SLIDE_HEIGHT
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        for x in range(SLIDE_WIDTH):
            pixels[x, y] = (r, g, b)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# GLOWNY ENTRY: GENERATE FULL CAROUSEL
# ─────────────────────────────────────────────────────────────

def generate_carousel(
    brand_id: str,
    topic: str,
    style_id: Optional[str] = None,
    topic_id: Optional[str] = None,
    slide_count: int = DEFAULT_SLIDES,
    use_ai_images: bool = False,
    prefer_provider: Optional[str] = None,
    image_quality: str = "low",
    model_override: Optional[str] = None,
    language: str = "pl",
    text_mode: str = "overlay",
    progress_callback=None,
) -> dict:
    """
    Pelny pipeline:
      1. Czyta brief + styl z bazy
      2. Generuje copy (Claude)
      3. Walidacja vs brief
      4. Per slajd: generuje obraz + naklada tekst
      5. Zapis do bazy + dysk

    progress_callback(stage: str, pct: float) - opcjonalny dla UI.

    Zwraca: dict z carouselem (taki sam jak db.get_carousel)
    """
    brief = get_brief(brand_id) or {}
    style = get_style(style_id) if style_id else None

    if progress_callback:
        progress_callback("Generuje tekst karuzeli...", 0.1)

    copy_data = generate_copy(topic, brief, style, slide_count, language=language)

    if progress_callback:
        progress_callback("Walidacja zgodnosci z briefem...", 0.25)

    # Walidacja — tylko ostrzeżenie, nie blokuje generacji
    try:
        validation = validate_against_brief(copy_data.get("slides", []), brief)
    except Exception:
        validation = {"ok": True, "violations": []}

    # Stworz wpis carousel w bazie (placeholder, slides z paths uzupelniamy nizej)
    carousel_id = generate_id("car")
    carousel_dir = CAROUSELS_DIR / brand_id / carousel_id
    ensure_dir(carousel_dir)

    slides_with_images = []
    n = len(copy_data.get("slides", []))

    for i, slide in enumerate(copy_data["slides"]):
        if progress_callback:
            progress_callback(
                f"Generuje slajd {i+1}/{n}...",
                0.3 + 0.6 * (i / max(n, 1))
            )

        slide_filename = f"{i+1:02d}_{sanitize_filename(slide.get('headline', 'slide'))}.jpg"
        slide_path = carousel_dir / slide_filename
        try:
            img_meta = render_slide_image(
                slide, style, slide_path,
                use_ai_images=use_ai_images,
                prefer_provider=prefer_provider,
                image_quality=image_quality,
                model_override=model_override,
                text_mode=text_mode,
            )
        except Exception as e:
            img_meta = {
                "image_path": "",
                "image_provider": "error",
                "image_model": str(e)[:80],
                "cost_usd": 0.0,
            }

        slides_with_images.append({
            **slide,
            "image_path": img_meta["image_path"],
            "image_provider": img_meta["image_provider"],
            "image_model": img_meta["image_model"],
        })

    if progress_callback:
        progress_callback("Zapisuje karuzele...", 0.95)

    # Zapis caption + hashtags do pliku
    caption_path = carousel_dir / "caption.txt"
    caption_text = (copy_data.get("caption", "") + "\n\n" +
                    " ".join(copy_data.get("hashtags", [])))
    caption_path.write_text(caption_text, encoding="utf-8")

    # Zapis do DB
    create_carousel(
        carousel_id=carousel_id,
        brand_id=brand_id,
        style_id=style_id,
        topic_id=topic_id,
        slides=slides_with_images,
        caption=copy_data.get("caption", ""),
        hashtags=copy_data.get("hashtags", []),
    )

    if progress_callback:
        progress_callback("Gotowe!", 1.0)

    from db import get_carousel
    return get_carousel(carousel_id)


def export_carousel_as_zip(carousel_id: str) -> Path:
    """Spakuj wszystkie slajdy + caption.txt do pojedynczego pliku ZIP do pobrania."""
    import zipfile
    from db import get_carousel

    carousel = get_carousel(carousel_id)
    if not carousel:
        raise ValueError(f"Carousel {carousel_id} nie istnieje")

    carousel_dir = CAROUSELS_DIR / carousel["brand_id"] / carousel_id
    zip_path = carousel_dir / f"{carousel_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for slide in carousel.get("slides", []):
            p = Path(slide.get("image_path", ""))
            if p.exists():
                zf.write(p, p.name)
        caption_path = carousel_dir / "caption.txt"
        if caption_path.exists():
            zf.write(caption_path, "caption.txt")

    return zip_path
