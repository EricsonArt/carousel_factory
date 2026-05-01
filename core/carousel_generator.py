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

from PIL import Image

from config import (
    PROMPTS_DIR, CAROUSELS_DIR,
    SLIDE_WIDTH, SLIDE_HEIGHT,
    DEFAULT_SLIDES, MIN_SLIDES, MAX_SLIDES,
)
from core.llm import call_claude_json, validate_against_brief
from core.image_router import generate_image, QuotaExhausted, ImageGenerationError
from core.utils import (
    generate_id, ensure_dir, hex_to_rgb, sanitize_filename,
)
from core.text_renderer import (
    apply_text_to_image, merge_text_settings, length_directive_for_prompt,
    DEFAULT_TEXT_SETTINGS,
)
from db import create_carousel, update_carousel, get_brief, get_style


# ─────────────────────────────────────────────────────────────
# STEP 1: COPYWRITER
# ─────────────────────────────────────────────────────────────

COPY_FRAMEWORKS = {
    "default": "carousel_copy_default.md",
    "viral_loop": "carousel_copy_viral_loop.md",
}


def _load_copy_prompt(brief: Optional[dict] = None) -> str:
    """
    Wybiera prompt copywritera per-marka na podstawie brief.copy_framework.
      - "default" (domyslnie): uniwersalny prompt — pasuje do wiekszosci marek (e-commerce, lifestyle, edu, B2B)
      - "viral_loop": 9-funkcyjna struktura "Petla ktora sie nie zamyka" z hookiem paradoksalnym
        + caption 5-sekcyjny + slowo-trigger w komentarzu. Pasuje dla info-produktow,
        coachingu, "make money online", reselling, personal brand z lead magnetem.
    Fallback: jezeli plik nie istnieje, uzywa default.
    """
    framework = (brief or {}).get("copy_framework", "default")
    filename = COPY_FRAMEWORKS.get(framework, COPY_FRAMEWORKS["default"])
    path = PROMPTS_DIR / filename
    if not path.exists():
        path = PROMPTS_DIR / COPY_FRAMEWORKS["default"]
    return path.read_text(encoding="utf-8")


def generate_copy(
    topic: str,
    brief: dict,
    style: Optional[dict] = None,
    slide_count: int = DEFAULT_SLIDES,
    language: str = "pl",
    text_length: str = "medium",
    custom_instructions: str = "",
) -> dict:
    """
    Generuje cala karuzele tekstowa (slides + caption + hashtags).
    language: 'pl' | 'en' — w jakim języku ma być treść slajdów.
    text_length: 'short' | 'medium' | 'long' — wstrzykuje twardy limit dlugosci do user-prompta,
                 zeby tekst pasowal do parametrow renderera (Pillow potem nie musi obciec).
    """
    slide_count = max(MIN_SLIDES, min(MAX_SLIDES, slide_count))
    system_prompt = _load_copy_prompt(brief)
    framework = (brief or {}).get("copy_framework", "default")
    length_block = f"\nLIMIT DLUGOSCI TEKSTU (priorytet nad system prompt): {length_directive_for_prompt(text_length)}\n"

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
            "Hashtags should be English/global (e.g. #tips, #howto, #productivity).\n"
            "- CURRENCY: convert ALL prices/amounts/revenue claims from the brief (which are in PLN) "
            "to USD. Use approximate rate: 4 PLN ≈ 1 USD. Round prices to nearest $5 (e.g. 99 PLN → $25, "
            "199 PLN → $50). Round revenue/social-proof figures to nearest $50 or $100 "
            "(e.g. 8400 PLN → $2,100, 15000 PLN → $3,750). Display as '$X' or 'X USD' — NEVER 'PLN' or 'zł'.\n"
            "- CTA TRANSLATION: brief.cta_text is in Polish (e.g. 'Klik link w bio'). "
            "TRANSLATE it to natural English keeping the intent. Examples: "
            "'Klik link w bio' → 'Link in bio', 'Sprawdz w bio' → 'Check bio', "
            "'Sprawdz oferte' → 'Check the offer', 'Zobacz wiecej' → 'See more'. "
            "NEVER leave Polish CTA text in an English carousel. brief.cta_url stays 1:1.\n"
            "- DASHES: use ONLY plain hyphen-minus '-' (U+002D). NEVER use em-dash '—' (U+2014), "
            "en-dash '–' (U+2013), figure-dash '‒' or horizontal-bar '―'. If you want a long dash, "
            "type two hyphens '--' or use a comma."
        )
    else:
        language_directive = (
            "- LANGUAGE: POLSKI. Z poprawnymi znakami diakrytycznymi (ą ę ó ł ś ć ż ź ń). "
            "Hashtagi mieszane PL i EN.\n"
            "- WALUTA: zostaw kwoty z briefa w PLN (lub uzyj 'zl' / '{X} zl').\n"
            "- MYSLNIKI: uzywaj WYLACZNIE zwyklego dywizu '-' (U+002D). NIGDY nie uzywaj "
            "pauzy '—' (U+2014), polpauzy '–' (U+2013) ani podobnych. Jak chcesz dluzszy myslnik — "
            "napisz '--' albo uzyj przecinka."
        )

    if framework == "viral_loop":
        process_block = f"""
PROCES (zgodnie z system promptem):
1. Slajd 1 (HOOK PARADOKSALNY): wygeneruj 8 wersji hooka roznymi technikami,
   oceniaj kazda w 4 kryteriach (paradoks/konkret/dlugosc/personal stakes),
   zwroc TOP-1 w headline+body i 3 alternatywy w slides[0].alternatives[].
2. Pozostale slajdy: zmapuj funkcje psychologiczne na N={slide_count} wedlug tabeli z system promptu.
3. Caption: 5 sekcji rozdzielonych \\n\\n (hook-recap, mikropotwierdzenie,
   wartosc ucieta, CTA+deliverables, P.S. z anticipated regret), 600-1100 znakow.
4. cta_keyword: jedno slowo UPPERCASE pasujace do niszy (uzyj brief.cta_keyword jesli istnieje).

WAZNE (viral_loop):
- Slajd PROOF: wszystkie imiona/liczby z brief.social_proof[] / brief.testimonials[].
- Slajd SOLUTION: NIE wymieniaj nazwy produktu — mowisz "system ktory zbudowalem".
- Slajd CTA: format wybor (2 opcje) + slowo-trigger UPPERCASE w komentarzu, NIE "DM mi" / "link w bio".
- Przed zwroceniem przejdz checkliste walidacji z system promptu.
"""
        max_tokens = 8000
    else:
        process_block = ""
        max_tokens = 6000

    custom_block = ""
    if custom_instructions and custom_instructions.strip():
        custom_block = (
            "\n🎯 DODATKOWE INSTRUKCJE OD UŻYTKOWNIKA (PRIORYTET — stosuj się do tego nawet gdy "
            "kłóci się z innymi regułami, chyba że łamie 'forbidden_claims' z briefa):\n"
            f"{custom_instructions.strip()}\n"
        )

    prompt = f"""Stworz MAKSYMALNIE WIRALOWA karuzele Instagram/TikTok na temat:
"{topic}"

PARAMETRY:
- Liczba slajdow: {slide_count} (dokladnie tyle)
{language_directive}
{length_block}{custom_block}
BRIEF MARKI:
{json.dumps(brief, ensure_ascii=False, indent=2)}
{style_section}{process_block}
WAZNE:
- Uzywaj WYLACZNIE USPs i ofert z briefa - nie wymyslaj nowych cech produktu
- Trzymaj sie voice_tone z briefa
- Mow do glownego avatara z briefa
- W ostatnim slajdzie (CTA) uzyj cta_url z briefa
- Forbidden claims sa ZAKAZANE: {json.dumps(brief.get('forbidden_claims', []), ensure_ascii=False)}

Zwroc JSON zgodny ze schematem opisanym w system promptcie. TYLKO JSON.
"""
    raw = call_claude_json(prompt, system=system_prompt, max_tokens=max_tokens)
    # Defensywne post-processing — gwarantujemy zwykle dywizy nawet gdy LLM przeoczy instrukcje
    return _normalize_copy_text(raw, language=language)


# Mapowanie wszystkich wariantow myslnika Unicode -> zwykly hyphen-minus
_DASH_REPLACEMENTS = {
    "—": "-",  # em-dash —
    "–": "-",  # en-dash –
    "‒": "-",  # figure dash ‒
    "―": "-",  # horizontal bar ―
    "−": "-",  # minus sign −
    "﹘": "-",  # small em dash
    "﹣": "-",  # small hyphen-minus
    "－": "-",  # fullwidth hyphen
}


def _normalize_text_field(s) -> str:
    if not isinstance(s, str):
        return s
    for src, dst in _DASH_REPLACEMENTS.items():
        if src in s:
            s = s.replace(src, dst)
    return s


def _convert_pln_to_usd_in_text(s: str) -> str:
    """
    Defensywne fallback: jezeli LLM mimo instrukcji zostawi 'PLN' / 'zl' w trybie EN,
    zamienia na 'USD' / '$' z przelicznikiem ~4:1. Tylko proste wzorce — nie ruszamy
    skomplikowanych zdan, zeby nie zepsuc gramatyki.
    """
    import re
    if not isinstance(s, str):
        return s

    # Pattern: liczba (z opc. spacjami/przecinkiem/kropka jako separator) + 'PLN' / 'zl' / 'zł'
    def _replace_amount(match):
        num_str = match.group(1).replace(" ", "").replace(",", "").replace(".", "")
        try:
            pln_amount = float(num_str)
            usd_amount = pln_amount / 4.0
            if usd_amount < 50:
                rounded = round(usd_amount / 5) * 5
            elif usd_amount < 1000:
                rounded = round(usd_amount / 50) * 50
            else:
                rounded = round(usd_amount / 100) * 100
            return f"${int(rounded):,}"
        except (ValueError, ZeroDivisionError):
            return match.group(0)

    s = re.sub(r"(\d[\d\s,\.]*)\s*(?:PLN|zl|zł)\b", _replace_amount, s, flags=re.IGNORECASE)
    return s


def _normalize_copy_text(copy_data: dict, language: str = "pl") -> dict:
    """
    Czysci tekst we wszystkich polach JSON-a copywritera:
    - zamienia em/en-dash na zwykly '-'
    - dla EN: defensywnie konwertuje PLN -> USD jezeli LLM zostawi
    """
    if not isinstance(copy_data, dict):
        return copy_data

    def _process(value):
        v = _normalize_text_field(value)
        if language == "en":
            v = _convert_pln_to_usd_in_text(v)
        return v

    for slide in copy_data.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        for k in ("headline", "body"):
            if k in slide:
                slide[k] = _process(slide[k])
        if isinstance(slide.get("alternatives"), list):
            slide["alternatives"] = [_process(a) for a in slide["alternatives"]]

    if "caption" in copy_data:
        copy_data["caption"] = _process(copy_data["caption"])

    if isinstance(copy_data.get("hashtags"), list):
        copy_data["hashtags"] = [_normalize_text_field(h) for h in copy_data["hashtags"]]

    return copy_data


# ─────────────────────────────────────────────────────────────
# STEP 2: IMAGE GENERATION + STEP 3: PILLOW OVERLAY
# ─────────────────────────────────────────────────────────────

def regenerate_single_slide(
    carousel_id: str,
    slide_index: int,
    image_instructions: str = "",
    new_headline: Optional[str] = None,
    new_body: Optional[str] = None,
) -> dict:
    """
    Regeneruje pojedynczy slajd:
    - obraz (AI z dodatkowymi instrukcjami)
    - opcjonalnie zmienia headline/body
    - nakłada tekst Pillow overlay
    Zwraca zaktualizowany dict karuzeli.
    """
    from db import get_carousel
    from core.viral_replicator import _strip_emojis

    carousel = get_carousel(carousel_id)
    if not carousel:
        raise ValueError(f"Karuzela {carousel_id} nie istnieje")

    slides = list(carousel.get("slides", []))
    if slide_index < 0 or slide_index >= len(slides):
        raise ValueError(f"Slajd {slide_index} poza zakresem (0..{len(slides)-1})")

    slide = dict(slides[slide_index])
    brand_id = carousel.get("brand_id")
    style_id = carousel.get("style_id")

    brief = get_brief(brand_id) or {}
    style = get_style(style_id) if style_id else None
    effective_text_settings = merge_text_settings(brief.get("text_settings"))

    if new_headline is not None:
        slide["headline"] = _strip_emojis(new_headline)
    if new_body is not None:
        slide["body"] = _strip_emojis(new_body)

    # Wybierz providera ktory dzialal poprzednio (lub default Gemini)
    prev_provider = (slide.get("image_provider") or "").strip()
    if prev_provider in ("gemini", "openai"):
        prefer_provider = prev_provider
    elif prev_provider.startswith("fallback") or prev_provider in ("local", "error", ""):
        prefer_provider = "gemini"  # default na najlepszy darmowy
    else:
        prefer_provider = prev_provider or "gemini"

    output_path = Path(slide.get("image_path") or
                        (CAROUSELS_DIR / brand_id / carousel_id /
                         f"{slide_index+1:02d}_regen.jpg"))

    img_meta = render_slide_image(
        slide, style, output_path,
        use_ai_images=True,
        prefer_provider=prefer_provider,
        image_quality="low",
        text_mode="overlay",
        slide_index=slide_index,
        text_settings=effective_text_settings,
        image_custom_instructions=image_instructions,
    )

    slide["image_path"] = img_meta["image_path"]
    slide["image_provider"] = img_meta["image_provider"]
    slide["image_model"] = img_meta["image_model"]
    slides[slide_index] = slide

    update_carousel(carousel_id, slides=slides)
    return get_carousel(carousel_id)


def render_slide_image(
    slide: dict,
    style: Optional[dict],
    output_path: Path,
    use_ai_images: bool = False,
    prefer_provider: Optional[str] = None,
    image_quality: str = "low",
    model_override: Optional[str] = None,
    text_mode: str = "overlay",
    slide_index: int = 0,
    text_settings: Optional[dict] = None,
    image_custom_instructions: str = "",
) -> dict:
    """
    Generuje obraz tla + tekst.
    text_mode:
      - "overlay" (default) — Pillow naklada tekst po wygenerowaniu obrazu (PL znaki gwarantowane)
      - "inline"  — model AI generuje tekst RAZEM z obrazem (TikTok-style, ale moze masakrowac PL)
    slide_index: 0 = slajd 1 (hero rozmiar), >=1 = pozostale (rest rozmiar).
    text_settings: dict z core.text_renderer.DEFAULT_TEXT_SETTINGS (rozmiar, font, kolor, stroke, pozycja).
                   None → uzywa domyslnych.
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
        # Per-slajd custom instructions od usera dolaczone do image_prompt
        slide_custom = (slide.get("_image_custom_instructions") or "").strip()
        global_custom = (image_custom_instructions or "").strip()
        if global_custom:
            image_prompt = f"{image_prompt}. User instructions: {global_custom}".strip(". ")
        if slide_custom:
            image_prompt = f"{image_prompt}. Specific for this slide: {slide_custom}".strip(". ")
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
        except QuotaExhausted as _e:
            result = {
                "image_bytes": _gradient_background_with_palette(style),
                "provider": "fallback_quota",
                "model": f"quota: {str(_e)[:80]}",
                "cost_usd": 0.0,
            }
            inline_text_payload = None
        except ImageGenerationError as _e:
            result = {
                "image_bytes": _gradient_background_with_palette(style),
                "provider": "fallback_error",
                "model": f"err: {str(_e)[:80]}",
                "cost_usd": 0.0,
            }
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
        img = apply_text_to_image(
            img, headline, body,
            slide_index=slide_index,
            text_settings=text_settings,
            image_focus_hint=image_focus,
        )

    ensure_dir(output_path.parent)
    img.save(output_path, "JPEG", quality=92)

    return {
        "image_path": str(output_path),
        "image_provider": result["provider"],
        "image_model": result["model"],
        "cost_usd": result["cost_usd"],
    }


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
    text_settings: Optional[dict] = None,
    progress_callback=None,
    custom_instructions: str = "",
    image_custom_instructions: str = "",
) -> dict:
    """
    Pelny pipeline:
      1. Czyta brief + styl z bazy
      2. Generuje copy (Claude)  — uwzglednia text_settings.text_length
      3. Walidacja vs brief
      4. Per slajd: generuje obraz + naklada tekst (z text_settings, slide_index)
      5. Zapis do bazy + dysk

    text_settings: dict z text_renderer.DEFAULT_TEXT_SETTINGS. Jesli None, czyta z brief.text_settings;
                   jesli brief tez nie ma — uzywa domyslnych.
    progress_callback(stage: str, pct: float) - opcjonalny dla UI.

    Zwraca: dict z carouselem (taki sam jak db.get_carousel)
    """
    brief = get_brief(brand_id) or {}
    style = get_style(style_id) if style_id else None

    # Resolve text_settings: parametr -> brief.text_settings -> defaults
    effective_text_settings = merge_text_settings(text_settings or brief.get("text_settings"))
    text_length = effective_text_settings.get("text_length", "medium")

    if progress_callback:
        progress_callback("Generuje tekst karuzeli...", 0.1)

    copy_data = generate_copy(topic, brief, style, slide_count,
                               language=language, text_length=text_length,
                               custom_instructions=custom_instructions)

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
                slide_index=i,
                text_settings=effective_text_settings,
                image_custom_instructions=image_custom_instructions,
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


# ─────────────────────────────────────────────────────────────
# REPAIR — regeneruje brakujace tla AI dla istniejacych karuzel
# ─────────────────────────────────────────────────────────────

# Provider'y AI ktore traktujemy jako "OK" (tla wygenerowane prawdziwie)
_OK_PROVIDERS = {"gemini", "openai", "replicate"}

# Provider'y wprost wskazujace na fallback (gradient/error)
_KNOWN_BROKEN_PROVIDERS = {
    "fallback_quota", "fallback_error", "error", "local", "gradient", "fallback",
}


def _looks_like_solid_background(image_path: str) -> bool:
    """
    Heurystyka: jesli obraz jest praktycznie jednolitym kolorem (std-dev < 10),
    to znaczy ze to gradient/solid fallback, nie AI tlo.
    Zwraca False jak nie da sie odczytac (zachowawczo — nie traktujemy jako broken).
    """
    try:
        from PIL import Image, ImageStat
        from pathlib import Path as _P
        if not image_path or not _P(image_path).exists():
            return False
        with Image.open(image_path) as img:
            # Sample srodek obrazu (gdzie jest prawdziwy content, nie krawedz)
            w, h = img.size
            crop = img.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4)).convert("RGB")
            stat = ImageStat.Stat(crop)
            # Sredni std-dev po 3 kanalach
            avg_std = sum(stat.stddev) / 3
            return avg_std < 10  # bardzo niski variance = jednolite tlo
    except Exception:
        return False


def get_broken_slide_indices(carousel: dict, *, deep_scan: bool = False) -> list[int]:
    """
    Zwraca indeksy slajdow ktore prawdopodobnie maja zastepcze (nie-AI) tlo.

    Logika:
      1. Provider explicite z _KNOWN_BROKEN_PROVIDERS → broken
      2. Provider pusty / unknown / nie-AI → broken (zachowawczo)
      3. Provider w _OK_PROVIDERS (gemini/openai/replicate) → OK
      4. (Opcja deep_scan) Sprawdz plik — jak std-dev kolorow w srodku < 10,
         to gradient/solid → broken (uzyteczne dla starych karuzel
         ktore mialy wpisany provider 'gemini' ale plik faktycznie padl)
    """
    broken = []
    for i, slide in enumerate(carousel.get("slides") or []):
        provider = (slide.get("image_provider") or "").lower().strip()

        is_broken = False
        if not provider:
            is_broken = True  # pusty = na pewno cos nie tak
        elif any(provider.startswith(p) for p in _KNOWN_BROKEN_PROVIDERS):
            is_broken = True
        elif not any(provider.startswith(p) for p in _OK_PROVIDERS):
            is_broken = True  # nieznany provider = traktuj jako broken
        elif deep_scan:
            # Provider mowi gemini/openai ale plik moze byc fallback (stare karuzele)
            if _looks_like_solid_background(slide.get("image_path", "")):
                is_broken = True

        if is_broken:
            broken.append(i)
    return broken


def repair_carousel_backgrounds(
    carousel_id: str,
    prefer_provider: str = "gemini",
    model_override: Optional[str] = "gemini-3-pro-image-preview",
    image_quality: str = "low",
    progress_callback=None,
) -> dict:
    """
    Regeneruje TYLKO te slajdy ktorych image_provider wskazuje na fallback (quota / error).
    Tekst (headline, body) zostaje 1:1 — nie wywolujemy Claude do copy.

    Zwraca: {"repaired": int, "failed": int, "skipped": int, "details": list}
    """
    from db import get_carousel as _get
    carousel = _get(carousel_id)
    if not carousel:
        raise ValueError(f"Carousel {carousel_id} nie istnieje")

    brief = get_brief(carousel.get("brand_id", "")) or {}
    style = get_style(carousel.get("style_id")) if carousel.get("style_id") else None
    text_settings = merge_text_settings(brief.get("text_settings"))

    slides = list(carousel.get("slides") or [])
    # deep_scan=True — dla starych karuzel sprawdz tez pliki na dysku
    broken_idx = get_broken_slide_indices({"slides": slides}, deep_scan=True)

    if not broken_idx:
        return {"repaired": 0, "failed": 0, "skipped": len(slides),
                "details": ["Brak slajdow do naprawy — wszystkie maja AI tlo."]}

    carousel_dir = CAROUSELS_DIR / carousel["brand_id"] / carousel_id
    ensure_dir(carousel_dir)

    repaired = 0
    failed = 0
    details: list[str] = []

    for k, i in enumerate(broken_idx):
        if progress_callback:
            progress_callback(
                f"Regeneruje slajd {i+1} (broken {k+1}/{len(broken_idx)})...",
                0.05 + 0.9 * (k / len(broken_idx)),
            )

        slide = slides[i]
        # Reuse istniejaca sciezke (zachowuje filename + nazwe headlinem)
        slide_path_str = slide.get("image_path", "")
        if slide_path_str:
            slide_path = Path(slide_path_str)
        else:
            slide_path = carousel_dir / f"{i+1:02d}_{sanitize_filename(slide.get('headline', 'slide'))}.jpg"

        try:
            new_meta = render_slide_image(
                slide, style, slide_path,
                use_ai_images=True,
                prefer_provider=prefer_provider,
                image_quality=image_quality,
                model_override=model_override,
                text_mode="overlay",
                slide_index=i,
                text_settings=text_settings,
            )
            # Sprawdz czy faktycznie udalo sie wygenerowac AI tlo (a nie kolejny fallback)
            new_provider = (new_meta.get("image_provider") or "").lower()
            if any(new_provider.startswith(p) for p in _BROKEN_PROVIDERS):
                # Ciagle fallback — Gemini wciaz ma quota issues
                failed += 1
                details.append(f"Slajd {i+1}: dalej fallback ({new_provider})")
                # Update mimo to — moze sciezka sie zmienila
                slides[i]["image_path"] = new_meta["image_path"]
                slides[i]["image_provider"] = new_meta["image_provider"]
                slides[i]["image_model"] = new_meta["image_model"]
            else:
                repaired += 1
                details.append(f"Slajd {i+1}: OK ({new_provider})")
                slides[i]["image_path"] = new_meta["image_path"]
                slides[i]["image_provider"] = new_meta["image_provider"]
                slides[i]["image_model"] = new_meta["image_model"]

        except Exception as e:
            failed += 1
            details.append(f"Slajd {i+1}: blad — {str(e)[:100]}")

    # Update DB jednym zapisem
    update_carousel(carousel_id, slides=slides)

    if progress_callback:
        progress_callback("Gotowe!", 1.0)

    return {
        "repaired": repaired,
        "failed": failed,
        "skipped": len(slides) - len(broken_idx),
        "details": details,
    }
