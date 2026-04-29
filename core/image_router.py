"""
Image generation router z cascade fallback:
  1) GPT Image (OpenAI Images API)        - primary, czytelny tekst
  2) Gemini 2.5 Flash Image (Nano Banana) - secondary, najlepszy style transfer
  3) Replicate FLUX                        - tani fallback

Logika:
  - probujemy primary - jesli sukces, zwracamy bytes
  - jesli quota/error -> probujemy secondary
  - jesli wszystko siadlo -> raise QuotaExhausted

Phase 1: implementujemy tylko OpenAI (GPT Image). Reszta jest stub dla Phase 3.
"""
import io
import time
import base64
import requests
from pathlib import Path
from typing import Optional

from config import (
    OPENAI_API_KEY, GEMINI_API_KEY, REPLICATE_API_TOKEN,
    IMAGE_MODELS, SLIDE_WIDTH, SLIDE_HEIGHT,
    DAILY_COST_CAP_USD, IMAGE_QUALITY,
)
from db import get_today_usage, increment_usage, get_today_total_cost


class QuotaExhausted(Exception):
    """Wszystkie providery wyczerpaly dzienne limity."""
    pass


class ImageGenerationError(Exception):
    """Wszystkie providery zwrocily blad nie-quota."""
    pass


def generate_image(
    prompt: str,
    reference_images: Optional[list] = None,
    size: tuple[int, int] = None,
    style_hint: str = "",
    prefer_provider: Optional[str] = None,
    quality: str = "low",
    model_override: Optional[str] = None,
    inline_text: Optional[str] = None,
) -> dict:
    """
    Glowny entry point. Zwraca dict:
      {
        "image_bytes": bytes,
        "provider": "openai" | "gemini" | "replicate",
        "model": "<model_id>",
        "cost_usd": float,
      }

    Argumenty:
      prompt: angielski opis sceny dla obrazu
      reference_images: lista sciezek/URLi/bytes (do style transfer w gemini/openai-edits)
      size: (W, H), default config.SLIDE_WIDTH/SLIDE_HEIGHT
      style_hint: dodatkowy opis stylu z StyleProfile (image_style + composition_notes)
      prefer_provider: jesli ustawione, probuj najpierw tego providera
    """
    if size is None:
        size = (SLIDE_WIDTH, SLIDE_HEIGHT)

    # Hard cost cap
    if get_today_total_cost() > DAILY_COST_CAP_USD:
        raise QuotaExhausted(
            f"Dzienny limit kosztow ${DAILY_COST_CAP_USD} przekroczony "
            f"(${get_today_total_cost():.2f} dzis). Zwieksz w config.DAILY_COST_CAP_USD lub poczekaj do jutra."
        )

    # Buduj kolejnosc providerow
    providers = list(IMAGE_MODELS)
    if prefer_provider:
        providers.sort(key=lambda m: 0 if m["provider"] == prefer_provider else 1)

    # Jesli mamy reference images - preferuj providerow z supports_reference
    if reference_images:
        providers.sort(key=lambda m: 0 if m["supports_reference"] else 1)

    last_error = None
    for cfg in providers:
        if not _is_provider_available(cfg["provider"]):
            continue
        if _quota_exhausted(cfg):
            continue

        try:
            full_prompt = _augment_prompt(prompt, style_hint, inline_text=inline_text)
            image_bytes = _call_provider(cfg, full_prompt, reference_images, size,
                                          quality=quality, model_override=model_override)
            increment_usage(
                provider=cfg["provider"],
                model=cfg["model_id"],
                images=1,
                cost=cfg["cost_per_image"],
            )
            return {
                "image_bytes": image_bytes,
                "provider": cfg["provider"],
                "model": cfg["model_id"],
                "cost_usd": cfg["cost_per_image"],
            }
        except QuotaExhausted as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            continue

    if isinstance(last_error, QuotaExhausted) or last_error is None:
        raise QuotaExhausted("Wszystkie providery image-gen wyczerpane lub niedostepne.")
    raise ImageGenerationError(f"Wszystkie providery siednely. Ostatni blad: {last_error}")


# ─────────────────────────────────────────────────────────────
# DETEKCJA DOSTEPNOSCI
# ─────────────────────────────────────────────────────────────

def _is_provider_available(provider: str) -> bool:
    if provider == "openai":
        return bool(OPENAI_API_KEY)
    if provider == "gemini":
        return bool(GEMINI_API_KEY)
    if provider == "replicate":
        return bool(REPLICATE_API_TOKEN)
    return False


def _quota_exhausted(cfg: dict) -> bool:
    """Sprawdza dzienny limit obrazow per provider/model."""
    usage = get_today_usage(cfg["provider"], cfg["model_id"])
    return usage["images_generated"] >= cfg["daily_quota"]


# ─────────────────────────────────────────────────────────────
# AUGMENTACJA PROMPTU
# ─────────────────────────────────────────────────────────────

def _augment_prompt(prompt: str, style_hint: str, inline_text: Optional[str] = None) -> str:
    """
    Buduje finalny prompt dla generatora obrazow.
    Dwa tryby:
      - inline_text=None  -> ZAKAZ tekstu w obrazie (Pillow naklada potem)
      - inline_text="..."  -> model MA umiescic ten konkretny tekst w obrazie (TikTok/IG style)
    """
    parts = [prompt.strip()]
    if style_hint:
        parts.append(f"Visual style reference: {style_hint.strip()}")

    if inline_text:
        # AI generuje tekst razem z obrazem (Nano Banana Pro / GPT Image 2 sa w tym dobre)
        parts.append(
            f'IMPORTANT TEXT TO RENDER IN THE IMAGE (must appear exactly as written, large, '
            f'centered, highly readable): "{inline_text.strip()}"'
        )
        parts.append(
            "Render this text in the style of viral TikTok / Instagram Reels captions: "
            "very bold sans-serif typography (Montserrat Black or similar), pure white fill color, "
            "thick solid black outline/stroke around every letter, ALL CAPS for the headline, "
            "high contrast against the background, perfectly legible. "
            "The text is the focal point of the image — make it large and dominant."
        )
        parts.append(
            "Vertical 4:5 portrait aspect ratio. Spell every word EXACTLY as given — "
            "no typos, no extra words, no language drift."
        )
    else:
        # Pillow naklada tekst pozniej — model ma zostawic czyste tlo
        parts.append(
            "Pure background image only. Vertical 4:5 portrait aspect ratio. "
            "Clean composition with large empty area at the center or bottom where text will be added later. "
            "High quality, professional photography or illustration matching the reference style."
        )
        parts.append(
            "ABSOLUTELY NO TEXT. NO LETTERS. NO WORDS. NO NUMBERS. NO LOGOS. NO WATERMARKS. "
            "NO TYPOGRAPHY. NO CAPTIONS. NO SUBTITLES. NO SIGNAGE WITH READABLE TEXT. "
            "The image must be completely free of any written characters or symbols."
        )
    return ". ".join(parts)


# ─────────────────────────────────────────────────────────────
# OPENAI - GPT IMAGE
# ─────────────────────────────────────────────────────────────

def _call_provider(cfg: dict, prompt: str, refs: Optional[list], size: tuple,
                    quality: str = "low", model_override: Optional[str] = None) -> bytes:
    model_id = model_override or cfg["model_id"]
    if cfg["provider"] == "openai":
        return _call_openai(model_id, prompt, refs, size, quality=quality)
    if cfg["provider"] == "gemini":
        return _call_gemini(model_id, prompt, refs, size)
    if cfg["provider"] == "replicate":
        return _call_replicate(model_id, prompt, refs, size)
    raise ImageGenerationError(f"Nieznany provider: {cfg['provider']}")


def _call_openai(model_id: str, prompt: str, refs: Optional[list], size: tuple, quality: str = "low") -> bytes:
    """
    OpenAI Images API.
    quality: 'low' (~$0.011/img), 'medium' (~$0.042/img), 'high' (~$0.167/img)
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImageGenerationError("Brak pakietu openai. pip install openai")

    client = OpenAI(api_key=OPENAI_API_KEY)
    # Karuzele 4:5 — portrait dla high quality / gpt-image-2; square dla low (oszczędność)
    openai_size = "1024x1536" if (quality == "high" or model_id == "gpt-image-2") else "1024x1024"

    try:
        if refs:
            ref_files = [_to_file_object(r) for r in refs[:4]]
            resp = client.images.edit(
                model=model_id,
                image=ref_files if len(ref_files) > 1 else ref_files[0],
                prompt=prompt,
                size=openai_size,
                quality=quality,
                n=1,
            )
        else:
            resp = client.images.generate(
                model=model_id,
                prompt=prompt,
                size=openai_size,
                quality=quality,
                n=1,
            )
    except Exception as e:
        msg = str(e).lower()
        if "rate" in msg or "quota" in msg or "billing" in msg or "insufficient" in msg:
            raise QuotaExhausted(f"OpenAI quota: {e}")
        raise

    # OpenAI zwraca b64_json (gpt-image-1) lub url (dall-e-3)
    data = resp.data[0]
    if hasattr(data, "b64_json") and data.b64_json:
        return base64.b64decode(data.b64_json)
    if hasattr(data, "url") and data.url:
        r = requests.get(data.url, timeout=30)
        r.raise_for_status()
        return r.content
    raise ImageGenerationError("OpenAI nie zwrocil danych obrazu")


def _to_file_object(ref):
    """Konwertuj sciezke/URL/bytes na file-like obiekt dla OpenAI SDK."""
    if isinstance(ref, (str, Path)):
        s = str(ref)
        if s.startswith(("http://", "https://")):
            r = requests.get(s, timeout=30)
            r.raise_for_status()
            buf = io.BytesIO(r.content)
            buf.name = "ref.png"
            return buf
        path = Path(s)
        return open(path, "rb")
    if isinstance(ref, bytes):
        buf = io.BytesIO(ref)
        buf.name = "ref.png"
        return buf
    raise ValueError(f"Nieznany format reference image: {type(ref)}")


# ─────────────────────────────────────────────────────────────
# GEMINI - Phase 3 stub
# ─────────────────────────────────────────────────────────────

def _call_gemini(model_id: str, prompt: str, refs: Optional[list], size: tuple) -> bytes:
    """
    Gemini 2.0 Flash image generation (FREE tier: 15 req/min, 1500/dzień).
    Wymaga GEMINI_API_KEY w Streamlit Secrets.
    """
    if not GEMINI_API_KEY:
        raise QuotaExhausted("Brak GEMINI_API_KEY — dodaj do Streamlit Secrets.")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImageGenerationError("Brak pakietu google-genai. pip install google-genai")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Zbuduj prompt ze stylowymi wskazówkami
    parts = []
    if refs:
        for r in refs[:3]:
            try:
                parts.append(_ref_to_gemini_part(r))
            except Exception:
                pass
    parts.append(types.Part.from_text(text=prompt))

    try:
        resp = client.models.generate_content(
            model=model_id,
            contents=parts,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )
    except Exception as e:
        msg = str(e).lower()
        if "rate" in msg or "quota" in msg or "429" in msg:
            raise QuotaExhausted(f"Gemini quota: {e}")
        raise ImageGenerationError(f"Gemini error: {e}")

    for candidate in resp.candidates:
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                return part.inline_data.data
    raise ImageGenerationError("Gemini nie zwrocil obrazu — sprobuj ponownie")


def _ref_to_gemini_part(ref):
    """Konwertuj na Gemini Part (image bytes)."""
    from google.genai import types
    if isinstance(ref, (str, Path)):
        s = str(ref)
        if s.startswith(("http://", "https://")):
            r = requests.get(s, timeout=30)
            r.raise_for_status()
            data = r.content
        else:
            data = Path(s).read_bytes()
    elif isinstance(ref, bytes):
        data = ref
    else:
        raise ValueError(f"Nieznany format ref: {type(ref)}")
    return types.Part.from_bytes(data=data, mime_type="image/png")


# ─────────────────────────────────────────────────────────────
# REPLICATE - Phase 3 stub
# ─────────────────────────────────────────────────────────────

def _call_replicate(model_id: str, prompt: str, refs: Optional[list], size: tuple) -> bytes:
    if not REPLICATE_API_TOKEN:
        raise QuotaExhausted("Replicate niedostepny.")

    try:
        import replicate
    except ImportError:
        raise ImageGenerationError("Brak pakietu replicate. pip install replicate")

    client = replicate.Client(api_token=REPLICATE_API_TOKEN)

    try:
        output = client.run(
            model_id,
            input={
                "prompt": prompt,
                "aspect_ratio": "4:5",
                "output_format": "png",
            }
        )
    except Exception as e:
        msg = str(e).lower()
        if "rate" in msg or "quota" in msg or "402" in msg:
            raise QuotaExhausted(f"Replicate quota: {e}")
        raise

    # output to URL lub lista URL
    if isinstance(output, list):
        url = output[0]
    else:
        url = output
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content
