"""
Viral Replicator — wkleja link viralu (TikTok / Instagram), AI analizuje
strukture przez Claude Vision i generuje swoja karuzele "ten sam DNA, ten sam
hook pattern", ale dla brand briefa usera + CTA na flipzone.pl (cta_url z briefa).

Pipeline:
  1) fetch_viral_post(url)             — yt-dlp scrape (DARMOWY!) → metadata + obrazy
  2) analyze_and_replicate(...)        — Claude Vision z prompts/viral_replicator.md
                                         → JSON identyczny formatu jak generate_copy()
  3) replicate_viral_carousel(...)     — orchestrator: scrape → vision → image gen → Pillow → DB
"""
from __future__ import annotations
import io
import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

from config import PROMPTS_DIR, CAROUSELS_DIR, SLIDE_WIDTH, SLIDE_HEIGHT
from core.llm import call_claude_vision_json
from core.image_router import generate_image, QuotaExhausted, ImageGenerationError
from core.text_renderer import apply_text_to_image, merge_text_settings
from core.carousel_generator import _normalize_copy_text  # post-processing dashes/PLN
from core.utils import generate_id, ensure_dir, sanitize_filename
from db import create_carousel, update_carousel, get_brief, get_style


SUPPORTED_DOMAINS = ("tiktok.com", "instagram.com")


class ViralFetchError(Exception):
    """Nie udalo sie pobrac danych viralu (bad URL, prywatny, geo-blocked, rate limit)."""
    pass


# ─────────────────────────────────────────────────────────────
# STEP 1: SCRAPE (yt-dlp — DARMOWY)
# ─────────────────────────────────────────────────────────────

def _detect_platform(url: str) -> str:
    u = url.lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    return "unknown"


def _sanitize_url(url: str) -> str:
    """
    Czysci URL: usuwa query string i fragment (TikTok i IG dorzucaja tony tracking
    parametrow ktore mylą yt-dlp).

    Przyklad:
      https://www.tiktok.com/@kit/photo/123?is_from_webapp=1&sender_device=pc...
      → https://www.tiktok.com/@kit/photo/123

    Dodatkowo: vt.tiktok.com / vm.tiktok.com shortlinks zostaja jak sa — yt-dlp
    sam je rezolwuje. Trailing slash zostaje (yt-dlp toleruje).
    """
    s = url.strip()
    if not s:
        return s
    # Usun white spaces wewnatrz (np. z kopiowania ze Slacka)
    s = s.replace(" ", "")
    parsed = urllib.parse.urlparse(s)
    if not parsed.scheme:
        # User wkleil bez https:// — dorzuc
        s = "https://" + s
        parsed = urllib.parse.urlparse(s)
    clean = urllib.parse.urlunparse((
        parsed.scheme, parsed.netloc, parsed.path, "", "", ""
    ))
    return clean


def fetch_viral_post(url: str) -> dict:
    """
    Pobiera metadane + obrazy viralu przez yt-dlp.

    Zwraca:
      {
        "platform": "tiktok" | "instagram",
        "caption": str,
        "hashtags": list[str],
        "images_bytes": list[bytes],   # slajdy karuzeli LUB cover frame wideo
        "is_carousel": bool,            # True = wieloobrazowa karuzela, False = single (wideo cover)
        "original_url": str,
        "raw_meta": dict,                # surowe info dla debugu
      }
    """
    if not url or not any(d in url.lower() for d in SUPPORTED_DOMAINS):
        raise ViralFetchError(f"URL musi byc z TikToka lub Instagrama. Otrzymano: {url}")

    # Sanitize URL — strip query string i tracking parametry, ktore mylą yt-dlp
    clean_url = _sanitize_url(url)

    try:
        import yt_dlp
    except ImportError:
        raise ViralFetchError("Brak yt-dlp — zainstaluj: pip install yt-dlp")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }

    platform = _detect_platform(clean_url)
    info = None
    yt_dlp_error: Optional[str] = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
    except Exception as e:
        yt_dlp_error = str(e)
        msg_lower = yt_dlp_error.lower()

        # Fatalne bledy — nie ma sensu probowac fallbacku
        if "private" in msg_lower or "login required" in msg_lower:
            raise ViralFetchError("Post jest prywatny / wymaga logowania.")
        if "not found" in msg_lower or "404" in msg_lower or "removed" in msg_lower:
            raise ViralFetchError("Post nie istnieje lub zostal usuniety.")
        if "geo" in msg_lower or "country" in msg_lower:
            raise ViralFetchError("Post jest zablokowany w tym regionie (geo-block).")
        if "rate" in msg_lower or "429" in msg_lower or "too many" in msg_lower:
            # Yt-dlp moze byc rate-limited, ale TikWM ma osobny limit — sprobujmy
            pass

        # Dla bledow typu "Unsupported URL" lub innych nie-fatalnych —
        # spadamy nizej do TikWM fallback (dla TikTok)

    # ── TIKWM FALLBACK dla TikTok ──
    # Wlacza sie gdy yt-dlp padl LUB nie zwrocil obrazow,
    # ale tylko dla URLi tiktok.com (TikWM nie obsluguje IG)
    use_tikwm_fallback = (
        platform == "tiktok"
        and (info is None or not (info.get("entries") or info.get("formats") or info.get("thumbnails")))
    )

    if use_tikwm_fallback:
        try:
            tikwm_data = _fetch_via_tikwm(clean_url)
            return {
                "platform": "tiktok",
                "caption": tikwm_data["caption"],
                "hashtags": tikwm_data["hashtags"],
                "images_bytes": tikwm_data["images_bytes"],
                "is_carousel": tikwm_data["is_carousel"],
                "original_url": clean_url,
                "raw_meta": {
                    **tikwm_data["raw_meta"],
                    "_source": "tikwm_fallback",
                    "_yt_dlp_error": (yt_dlp_error or "")[:200],
                },
            }
        except ViralFetchError as tikwm_err:
            # Oba zawiodly — zwroc lepszy z bledow
            primary = yt_dlp_error or "yt-dlp nie zwrocil obrazow"
            raise ViralFetchError(
                f"Oba scrapery padly. yt-dlp: {primary[:200]}. TikWM: {tikwm_err}"
            )

    # Yt-dlp padl bez fallbacku (Instagram lub jakis inny case)
    if info is None:
        msg_lower = (yt_dlp_error or "").lower()
        if "unsupported url" in msg_lower:
            raise ViralFetchError(
                f"yt-dlp nie obsluguje tego URL ({clean_url}). "
                "Sprobuj wkleic 'czysty' link bez parametrow."
            )
        raise ViralFetchError(f"yt-dlp blad: {(yt_dlp_error or 'nieznany')[:300]}")
    caption = info.get("description") or info.get("title") or ""
    hashtags = re.findall(r"#\w+", caption)

    # Detekcja: karuzela wieloobrazowa vs pojedyncze wideo
    images_bytes: list[bytes] = []
    is_carousel = False

    # TikTok image carousel — yt-dlp zwraca 'entries' lub 'thumbnails' z wieloma obrazami
    entries = info.get("entries")
    if entries and len(entries) > 1:
        is_carousel = True
        for entry in entries[:10]:  # max 10 slajdow
            img_url = (
                entry.get("url")
                or entry.get("thumbnail")
                or (entry.get("thumbnails") or [{}])[-1].get("url")
            )
            if img_url:
                content = _download_image(img_url)
                if content:
                    images_bytes.append(content)
    else:
        # IG carousel zwraca info.formats z multiple images, sprawdzmy
        formats = info.get("formats") or []
        image_formats = [f for f in formats if f.get("vcodec") == "none" and f.get("ext") in ("jpg", "jpeg", "png", "webp")]
        if len(image_formats) > 1:
            # IG carousel images
            is_carousel = True
            for fmt in image_formats[:10]:
                img_url = fmt.get("url")
                if img_url:
                    content = _download_image(img_url)
                    if content:
                        images_bytes.append(content)
        else:
            # Single video — bierzemy cover thumbnail
            thumbs = info.get("thumbnails") or []
            # Najwiekszy dostepny thumbnail
            thumbs_sorted = sorted(
                [t for t in thumbs if t.get("url")],
                key=lambda t: (t.get("width") or 0) * (t.get("height") or 0),
                reverse=True,
            )
            if thumbs_sorted:
                content = _download_image(thumbs_sorted[0]["url"])
                if content:
                    images_bytes.append(content)
            elif info.get("thumbnail"):
                content = _download_image(info["thumbnail"])
                if content:
                    images_bytes.append(content)

    if not images_bytes:
        raise ViralFetchError(
            "Nie udalo sie pobrac zadnych obrazow z viralu. "
            "yt-dlp zwrocil metadata ale bez URL obrazow — moze post byc tylko-tekst, "
            "lub ekstraktor nie obsluguje tej wersji TikTok/IG. Sprobuj inny link."
        )

    return {
        "platform": platform,
        "caption": caption,
        "hashtags": hashtags,
        "images_bytes": images_bytes,
        "is_carousel": is_carousel,
        "original_url": clean_url,
        "raw_meta": {
            "title": info.get("title", "")[:200],
            "uploader": info.get("uploader", ""),
            "duration": info.get("duration"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
        },
    }


def _download_image(url: str, timeout: int = 15) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if r.ok and r.content:
            return r.content
    except Exception:
        return None
    return None


# ─────────────────────────────────────────────────────────────
# TIKWM FALLBACK — darmowy publiczny API dla TikTok photo+video
# ─────────────────────────────────────────────────────────────
# Uzywamy gdy yt-dlp pada na 'Unsupported URL' (zwykle TikTok /photo/)
# lub na innym ekstraktor-spec'ficznym bledzie.

def _fetch_via_tikwm(url: str) -> dict:
    """
    Pobiera dane TikToka przez darmowe TikWM API (bez auth).
    Obsluguje zarowno photo carousele jak i wideo (cover frame).

    Zwraca: {caption, hashtags, images_bytes, is_carousel, raw_meta}
    Rzuca ViralFetchError przy bledach.
    """
    api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url, safe='')}"
    try:
        r = requests.get(api_url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    except requests.RequestException as e:
        raise ViralFetchError(f"TikWM API niedostepne: {e}")

    if r.status_code == 429:
        raise ViralFetchError("TikWM rate limit (zbyt wiele zapytan). Sprobuj za 2-3 min.")
    if not r.ok:
        raise ViralFetchError(f"TikWM HTTP {r.status_code}: {r.text[:200]}")

    try:
        data = r.json()
    except Exception:
        raise ViralFetchError(f"TikWM zwrocil nie-JSON: {r.text[:200]}")

    if data.get("code") != 0:
        msg = data.get("msg") or "unknown"
        raise ViralFetchError(f"TikWM odrzucil URL: {msg}")

    info = data.get("data") or {}
    caption = info.get("title") or ""
    hashtags = re.findall(r"#\w+", caption)

    images_bytes: list[bytes] = []
    is_carousel = False

    images = info.get("images")
    if images and isinstance(images, list):
        is_carousel = True
        for img_url in images[:10]:
            content = _download_image(img_url)
            if content:
                images_bytes.append(content)
    else:
        # Wideo — cover frame
        cover_url = (
            info.get("cover")
            or info.get("origin_cover")
            or info.get("ai_dynamic_cover")
        )
        if cover_url:
            content = _download_image(cover_url)
            if content:
                images_bytes.append(content)

    if not images_bytes:
        raise ViralFetchError("TikWM zwrocil metadata ale bez URL obrazow.")

    author = (info.get("author") or {})
    return {
        "caption": caption,
        "hashtags": hashtags,
        "images_bytes": images_bytes,
        "is_carousel": is_carousel,
        "raw_meta": {
            "title": (info.get("title") or "")[:200],
            "uploader": author.get("unique_id") or author.get("nickname") or "",
            "duration": info.get("duration"),
            "view_count": info.get("play_count"),
            "like_count": info.get("digg_count"),
        },
    }


# ─────────────────────────────────────────────────────────────
# STEP 2: VISION ANALYSIS + REPLICATION
# ─────────────────────────────────────────────────────────────

def _load_replicator_prompt() -> str:
    return (PROMPTS_DIR / "viral_replicator.md").read_text(encoding="utf-8")


def _viral_visual_to_text_settings(v: Optional[dict]) -> dict:
    """
    Mapuje analize wizualna z viralu (Vision output) na nasz schemat text_settings.
    Tylko klucze ktore sa pewne — reszta bierze wartosci marki (merge w renderze).
    """
    if not isinstance(v, dict) or not v:
        return {}
    out: dict = {}

    pos = (v.get("text_position") or "").strip().lower()
    if pos in ("top", "center", "bottom"):
        out["position"] = pos

    color = (v.get("text_color_hex") or "").strip()
    if color.startswith("#") and len(color) in (4, 7):
        out["text_color"] = color

    weight = (v.get("weight") or "").strip().lower()
    if weight in ("black", "extra_bold", "extrabold", "heavy"):
        out["font_key"] = "montserrat_black"
    elif weight == "bold":
        out["font_key"] = "montserrat_bold"
    elif weight in ("regular", "medium", "light", "thin"):
        out["font_key"] = "inter"

    size = (v.get("size_hint") or "").strip().lower()
    if size == "huge":
        out["headline_size_hero"] = 140
        out["headline_size_rest"] = 110
        out["body_size"] = 48
    elif size == "large":
        out["headline_size_hero"] = 110
        out["headline_size_rest"] = 88
        out["body_size"] = 42
    elif size == "medium":
        out["headline_size_hero"] = 88
        out["headline_size_rest"] = 68
        out["body_size"] = 36
    elif size == "small":
        out["headline_size_hero"] = 64
        out["headline_size_rest"] = 50
        out["body_size"] = 30

    if isinstance(v.get("uppercase"), bool):
        out["uppercase"] = v["uppercase"]

    has_stroke = v.get("has_stroke")
    if has_stroke is False:
        out["stroke_width"] = 0
    elif has_stroke is True:
        out["stroke_width"] = 6

    sc = (v.get("stroke_color_hex") or "").strip()
    if sc.startswith("#") and len(sc) in (4, 7):
        out["stroke_color"] = sc

    return out


def analyze_and_replicate(viral_data: dict, brief: dict, style: Optional[dict] = None,
                            language: str = "pl", clone_visual: bool = False) -> dict:
    """
    Wywoluje Claude Vision z slajdami viralu + briefem usera, dostaje JSON
    z 'replicated_carousel' o tej samej strukturze co generate_copy.
    """
    system_prompt = _load_replicator_prompt()

    # Kontekst dla LLM
    images_count = len(viral_data["images_bytes"])
    is_carousel = viral_data["is_carousel"]
    platform = viral_data["platform"]
    caption = viral_data["caption"][:1500]  # cap dla token budget
    hashtags_str = " ".join(viral_data["hashtags"][:20])

    cta_url = brief.get("cta_url", "").strip()
    cta_text = brief.get("cta_text", "").strip()

    if language == "en":
        lang_block = (
            "- LANGUAGE: ENGLISH. Native English in slides + caption.\n"
            "- CURRENCY: convert any PLN amounts to USD (~4 PLN ≈ $1, round prices to $5, "
            "revenue to $50/$100). Display as '$X', never PLN/zł.\n"
            "- DASHES: only plain hyphen-minus '-'. NEVER em-dash '—' or en-dash '–'."
        )
        # CTA: jezeli brief.cta_text jest po polsku, przetlumacz go na naturalny EN
        if cta_text:
            cta_text_instruction = (
                f"- cta_text z briefa: \"{cta_text}\" (PO POLSKU). "
                f"PRZETLUMACZ go na naturalny angielski zachowujac intencje "
                f"(np. 'Klik link w bio' → 'Link in bio', 'Sprawdz oferte' → 'Check the offer', "
                f"'Sprawdz w bio' → 'Check bio'). NIE zostawiaj polskiego tekstu w EN karuzeli."
            )
        else:
            cta_text_instruction = "- cta_text: brak w briefie — uzyj generycznego EN, np. 'Link in bio' / 'Check it out'"
    else:
        lang_block = (
            "- LANGUAGE: POLSKI z poprawnymi diakrytykami (ą ę ó ł ś ć ż ź ń).\n"
            "- WALUTA: kwoty zostaja w PLN.\n"
            "- MYSLNIKI: tylko zwykly dywiz '-', nigdy '—' ani '–'."
        )
        if cta_text:
            cta_text_instruction = f"- cta_text: \"{cta_text}\" (uzyj 1:1 lub naturalnie zaadaptuj do kontekstu)"
        else:
            cta_text_instruction = "- cta_text: brak w briefie — uzyj generycznego po polsku, np. 'Klik link w bio'"

    brief_name = (brief.get("brand_name") or brief.get("name") or "").strip()
    brief_product = (brief.get("product") or "").strip()[:200]

    if clone_visual:
        visual_block = (
            "🔴 clone_visual_style: TRUE — TRYB KLONOWANIA WIZUALNEGO AKTYWNY 🔴\n\n"
            "TO JEST NAJWAŻNIEJSZE ZADANIE TEJ ANALIZY. Bez `viral_visual` na każdym slajdzie\n"
            "wynik jest BEZUŻYTECZNY — dlatego ABSOLUTNIE WYMAGANE jest wypełnienie tego pola.\n\n"
            "DLA KAŻDEGO SLAJDU (włącznie z CTA) MUSISZ dodać pole `viral_visual` o strukturze:\n\n"
            "```json\n"
            "\"viral_visual\": {\n"
            "  \"text_position\": \"top\" | \"center\" | \"bottom\",\n"
            "  \"text_color_hex\": \"#FFFFFF\",\n"
            "  \"text_alignment\": \"left\" | \"center\" | \"right\",\n"
            "  \"weight\": \"black\" | \"bold\" | \"regular\" | \"light\",\n"
            "  \"size_hint\": \"huge\" | \"large\" | \"medium\" | \"small\",\n"
            "  \"uppercase\": true | false,\n"
            "  \"has_stroke\": true | false,\n"
            "  \"stroke_color_hex\": \"#000000\",\n"
            "  \"background_aesthetic\": \"short ENG description of bg colors/mood for AI image gen\"\n"
            "}\n"
            "```\n\n"
            "PRZYKŁAD wypełnionego viral_visual ze slajdu z wielkim białym tekstem CAPS na środku\n"
            "z czarnym obrysem na czarnym gradient tle:\n"
            "```json\n"
            "\"viral_visual\": {\n"
            "  \"text_position\": \"center\",\n"
            "  \"text_color_hex\": \"#FFFFFF\",\n"
            "  \"text_alignment\": \"center\",\n"
            "  \"weight\": \"black\",\n"
            "  \"size_hint\": \"huge\",\n"
            "  \"uppercase\": true,\n"
            "  \"has_stroke\": true,\n"
            "  \"stroke_color_hex\": \"#000000\",\n"
            "  \"background_aesthetic\": \"dark moody gradient, deep navy to black\"\n"
            "}\n"
            "```\n\n"
            "PATRZ DOKŁADNIE NA KAŻDY SLAJD i analizuj:\n"
            "- Gdzie fizycznie znajduje się tekst (góra/środek/dół)?\n"
            "- Jaki dokładnie ma kolor (oszacuj hex jak najbliżej)?\n"
            "- Czy jest gruby (black), pogrubiony (bold), zwykły (regular), cienki (light)?\n"
            "- Jak duży względem slajdu (huge=ponad 30% wysokości, large=20-30%, medium=10-20%, small=poniżej 10%)?\n"
            "- Czy jest CAPS LOCK?\n"
            "- Czy ma czarny/biały obrys (kontur litery)?\n\n"
            "Slajd CTA dziedziczy ten sam viral_visual styl co reszta slajdów — żeby wyglądało spójnie."
        )
    else:
        visual_block = (
            "clone_visual_style: FALSE\n"
            "→ NIE dodawaj pola viral_visual. Tekst dostanie styl marki."
        )

    user_prompt = f"""Otrzymujesz {images_count} {'slajdów karuzeli' if is_carousel else 'kadr (cover frame wideo)'} wiralu z {platform.upper()}.

═══════════════════════════════════════════════════════════════
{visual_block}
═══════════════════════════════════════════════════════════════

ORIGINAL CAPTION:
{caption or '(brak)'}

ORIGINAL HASHTAGS:
{hashtags_str or '(brak)'}

TARGET LANGUAGE: {language.upper()}

---

ZADANIE:
1. Odczytaj DOKŁADNY tekst z każdego slajdu (headline + body).
   Zapisz w `text_density_per_slide` liczbę słów per slajd.

2. Skopiuj tekst 1:1 do nowych slajdów — NIE przerabiaj, NIE rebranduj, NIE ulepszaj.
   Jeśli target_language różni się od języka wiralu → przetłumacz zachowując rytm/CAPS/interpunkcję.

3. Sprawdź czy skopiowany tekst jest spójny z CTA które dodasz na końcu.
   Jeśli nie — zmień MINIMALNIE (max 1-2 słowa na slajd, tylko absolutnie konieczne).

4. Dodaj JEDEN DODATKOWY slajd CTA na końcu (poza liczbą oryginalnych slajdów):
   {cta_text_instruction}
   - cta_url (link, 1:1 bez zmian): "{cta_url or '(brak)'}"
   - CTA musi naturalnie wynikać z tematyki poprzednich slajdów

5. Liczba slajdów = {images_count if is_carousel else 'dobierz 7-9 (wideo → zaprojektuj strukturę)'} oryginalnych + 1 CTA.

{("6. ⚠️ PRZYPOMNIENIE: clone_visual_style jest WŁĄCZONE — KAŻDY slajd musi mieć pole viral_visual ze WSZYSTKIMI 9 polami wypełnionymi (patrz instrukcja na górze)." if clone_visual else "")}

WYMAGANIA TECHNICZNE:
{lang_block}

KONTEKST MARKI (TYLKO dla slajdu CTA — nie przerabiaj reszty pod tę markę):
- Nazwa marki: {brief_name or '(brak)'}
- Produkt/usługa: {brief_product or '(brak)'}

Zwróć JSON według schematu z system promptu. TYLKO JSON.
"""

    # Vision call — wysylamy wszystkie slajdy (potrzebne do dokladnego odczytu tekstu)
    images_payload = viral_data["images_bytes"][:10]

    result = call_claude_vision_json(
        prompt=user_prompt,
        images=images_payload,
        system=system_prompt,
        max_tokens=10000,
    )

    return _normalize_copy_text(result, language=language)


# ─────────────────────────────────────────────────────────────
# STEP 3: ORCHESTRATOR
# ─────────────────────────────────────────────────────────────

def replicate_viral_carousel(
    url: str,
    brand_id: str,
    style_id: Optional[str] = None,
    use_ai_images: bool = True,
    prefer_provider: Optional[str] = None,
    image_quality: str = "low",
    model_override: Optional[str] = None,
    language: str = "pl",
    text_settings: Optional[dict] = None,
    progress_callback=None,
    clone_visual: bool = False,
) -> dict:
    """
    Pelny pipeline replikacji viralu.
    Wywoluje fetch -> Vision analysis -> generuje obrazy -> Pillow overlay -> DB.
    Zwraca slownik karuzeli (jak get_carousel).
    """
    brief = get_brief(brand_id) or {}
    style = get_style(style_id) if style_id else None
    effective_text_settings = merge_text_settings(text_settings or brief.get("text_settings"))

    # 1) Scrape
    if progress_callback:
        progress_callback("Pobieram viralu z " + _detect_platform(url) + "...", 0.05)
    viral_data = fetch_viral_post(url)

    # 2) Vision analysis + replication
    if progress_callback:
        stage = "Claude Vision: analiza tekstu + stylu wizualnego..." if clone_visual else "Claude Vision analizuje strukture viralu..."
        progress_callback(stage, 0.20)
    replicated = analyze_and_replicate(viral_data, brief, style, language=language, clone_visual=clone_visual)

    # JSON mapping: replicated_carousel jest zagniezdzony, splaszczamy
    carousel_payload = replicated.get("replicated_carousel") or replicated
    slides_data = carousel_payload.get("slides", [])
    caption = carousel_payload.get("caption", "")
    hashtags = carousel_payload.get("hashtags") or []
    viral_analysis = replicated.get("viral_analysis", {})
    translation = replicated.get("translation_strategy", {})

    if not slides_data:
        raise ViralFetchError("Vision nie zwrocil slajdow do zreplikowania.")

    # 3) Image generation per slide + Pillow overlay
    carousel_id = generate_id("car")
    carousel_dir = CAROUSELS_DIR / brand_id / carousel_id
    ensure_dir(carousel_dir)

    slides_with_images = []
    n = len(slides_data)

    for i, slide in enumerate(slides_data):
        if progress_callback:
            progress_callback(f"Generuje slajd {i+1}/{n}...", 0.30 + 0.6 * (i / max(n, 1)))

        slide_filename = f"{i+1:02d}_{sanitize_filename(slide.get('headline', 'slide'))}.jpg"
        slide_path = carousel_dir / slide_filename

        # Per-slajd override stylu tekstu — tylko gdy clone_visual i AI zwrocilo viral_visual
        visual_applied = False
        visual_override: dict = {}
        if clone_visual:
            raw_vv = slide.get("viral_visual")
            visual_override = _viral_visual_to_text_settings(raw_vv)
            if visual_override:
                slide_text_settings = {**effective_text_settings, **visual_override}
                visual_applied = True
                print(f"[viral_replicator] slide {i+1}: viral_visual applied → {visual_override}")
            else:
                slide_text_settings = effective_text_settings
                print(f"[viral_replicator] slide {i+1}: clone_visual=True ale AI nie zwrocil viral_visual (raw={raw_vv})")
        else:
            slide_text_settings = effective_text_settings

        try:
            img_meta = _render_replicated_slide(
                slide, style, slide_path, i,
                use_ai_images=use_ai_images,
                prefer_provider=prefer_provider,
                image_quality=image_quality,
                model_override=model_override,
                text_settings=slide_text_settings,
            )
        except Exception as e:
            img_meta = {
                "image_path": "",
                "image_provider": "error",
                "image_model": str(e)[:80],
            }

        slides_with_images.append({
            **slide,
            "image_path": img_meta["image_path"],
            "image_provider": img_meta["image_provider"],
            "image_model": img_meta["image_model"],
            "_visual_applied": visual_applied,
            "_visual_override": visual_override,
        })

    # 4) Save caption + hashtags
    caption_path = carousel_dir / "caption.txt"
    caption_path.write_text(caption + "\n\n" + " ".join(hashtags), encoding="utf-8")

    # Statystyki clone_visual — ile slajdów dostało faktyczny override z AI
    visual_stats = {
        "clone_visual_requested": clone_visual,
        "slides_with_visual_applied": sum(1 for s in slides_with_images if s.get("_visual_applied")),
        "slides_total": len(slides_with_images),
        "per_slide_overrides": [
            {"slide": idx+1, "applied": s.get("_visual_applied"), "override": s.get("_visual_override", {})}
            for idx, s in enumerate(slides_with_images)
        ],
    }

    if clone_visual and visual_stats["slides_with_visual_applied"] == 0:
        print("[viral_replicator] OSTRZEZENIE: clone_visual=True ale AI nie zwrocil viral_visual ANI razu. "
              "Slajdy uzyja stylu marki (tak jak by clone_visual=False).")

    # Append viral analysis as separate file (do debugu / nauki)
    analysis_path = carousel_dir / "viral_analysis.json"
    analysis_path.write_text(
        json.dumps({
            "viral_analysis": viral_analysis,
            "translation_strategy": translation,
            "original_url": url,
            "platform": viral_data["platform"],
            "viral_meta": viral_data.get("raw_meta", {}),
            "clone_visual_stats": visual_stats,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5) DB save z source='viral_replicator'
    create_carousel(
        carousel_id=carousel_id,
        brand_id=brand_id,
        style_id=style_id,
        topic_id=None,
        slides=slides_with_images,
        caption=caption,
        hashtags=hashtags,
    )
    update_carousel(carousel_id, source="viral_replicator", source_url=url)

    if progress_callback:
        progress_callback("Gotowe!", 1.0)

    from db import get_carousel
    return get_carousel(carousel_id)


def _render_replicated_slide(slide: dict, style: Optional[dict], output_path: Path,
                              slide_index: int, use_ai_images: bool,
                              prefer_provider: Optional[str], image_quality: str,
                              model_override: Optional[str],
                              text_settings: dict) -> dict:
    """Reuse logiki carousel_generator: image gen + Pillow overlay."""
    from PIL import Image
    from core.carousel_generator import _gradient_background_with_palette

    headline = slide.get("headline", "")
    body = slide.get("body", "")
    image_focus = slide.get("image_focus", "center")
    image_prompt = slide.get("image_prompt", "")

    if use_ai_images:
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
            )
        except (QuotaExhausted, ImageGenerationError) as e:
            result = {
                "image_bytes": _gradient_background_with_palette(style),
                "provider": "fallback_quota" if isinstance(e, QuotaExhausted) else "fallback_error",
                "model": str(e)[:80],
            }
    else:
        result = {
            "image_bytes": _gradient_background_with_palette(style),
            "provider": "local",
            "model": "gradient",
        }

    img = Image.open(io.BytesIO(result["image_bytes"])).convert("RGB")
    img = img.resize((SLIDE_WIDTH, SLIDE_HEIGHT), Image.LANCZOS)
    img = apply_text_to_image(img, headline, body,
                                slide_index=slide_index,
                                text_settings=text_settings,
                                image_focus_hint=image_focus)

    ensure_dir(output_path.parent)
    img.save(output_path, "JPEG", quality=92)

    return {
        "image_path": str(output_path),
        "image_provider": result["provider"],
        "image_model": result["model"],
    }
