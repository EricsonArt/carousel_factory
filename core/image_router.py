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
import threading
import requests
from pathlib import Path
from typing import Optional

from config import (
    OPENAI_API_KEY, GEMINI_API_KEY, GEMINI_API_KEYS, REPLICATE_API_TOKEN,
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


# Rate limiter dla Gemini per-klucz — free tier 15 RPM, dajemy 4.5s odstep
# Wspoldzielony miedzy watkami (automat moze generowac rownolegle)
_GEMINI_MIN_INTERVAL_SEC = 4.5
_gemini_state_lock = threading.Lock()
_gemini_last_call_at: dict[str, float] = {}  # key_prefix -> timestamp
_gemini_dead_keys: set[str] = set()           # klucze ktore zwrocily daily quota / billing
_gemini_round_robin_idx = 0                    # licznik rotacji


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
        # Dostepny gdy mamy chociaz jeden zywy klucz (nie wykluczony)
        return bool(_alive_gemini_keys())
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


# quality → sufiks promptu (gpt-image-2 NIE OBSŁUGUJE param quality w API!)
# Reuse z gpt_image_studio/modules/image_generator.py — przetestowane, działa
_GPT_IMAGE_2_QUALITY_SUFFIX = {
    "low":    "",
    "medium": "high quality",
    "high":   "ultra high quality, intricate details, 8k, masterpiece",
}


def _call_openai(model_id: str, prompt: str, refs: Optional[list], size: tuple, quality: str = "low") -> bytes:
    """
    OpenAI Images API.

    UWAGA: gpt-image-2 NIE OBSŁUGUJE param `quality` w API. Studio gpt_image_studio
    używa quality jako sufiksu promptu zamiast param API. Wcześniej karuzele wysyłały
    `quality=` do gpt-image-2 co powodowało albo silent ignore albo błędy → kiepskie obrazy.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImageGenerationError("Brak pakietu openai. pip install openai")

    client = OpenAI(api_key=OPENAI_API_KEY)
    is_gpt_image_2 = model_id == "gpt-image-2"

    # Karuzele 4:5 — portrait dla high quality / gpt-image-2; square dla low (oszczędność)
    openai_size = "1024x1536" if (quality == "high" or is_gpt_image_2) else "1024x1024"

    # Przygotuj prompt — dla gpt-image-2 doklej sufiks quality, NIE używaj param quality
    final_prompt = prompt
    if is_gpt_image_2:
        suffix = _GPT_IMAGE_2_QUALITY_SUFFIX.get(quality, "")
        if suffix:
            final_prompt = f"{prompt}, {suffix}"

    # Buduj kwargs — quality TYLKO dla starszych modeli (gpt-image-1)
    base_kwargs = {
        "model": model_id,
        "prompt": final_prompt,
        "size": openai_size,
        "n": 1,
    }
    if not is_gpt_image_2:
        base_kwargs["quality"] = quality

    try:
        if refs:
            ref_files = [_to_file_object(r) for r in refs[:4]]
            resp = client.images.edit(
                image=ref_files if len(ref_files) > 1 else ref_files[0],
                **base_kwargs,
            )
        else:
            resp = client.images.generate(**base_kwargs)
    except Exception as e:
        msg = str(e).lower()
        if "must be verified" in msg or ("403" in msg and "verif" in msg):
            raise ImageGenerationError(
                "OpenAI: organizacja niezweryfikowana. gpt-image-2 wymaga weryfikacji "
                "tożsamości. Wejdź na platform.openai.com/settings/organization/general "
                "i kliknij Start przy 'Individual'. Po ~15 min spróbuj ponownie."
            )
        if "rate" in msg or "quota" in msg or "billing" in msg or "insufficient" in msg:
            raise QuotaExhausted(f"OpenAI quota: {e}")
        raise

    # OpenAI zwraca b64_json (gpt-image-1, gpt-image-2) lub url (dall-e-3)
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

def _key_id(key: str) -> str:
    """Krotki identyfikator klucza do logow (NIE caly klucz)."""
    if not key:
        return "?"
    return f"{key[:6]}…{key[-3:]}"


def _alive_gemini_keys() -> list[str]:
    """Zwraca klucze nie oznaczone jako 'dead' (daily quota wyczerpany)."""
    with _gemini_state_lock:
        return [k for k in GEMINI_API_KEYS if k not in _gemini_dead_keys]


def _next_gemini_key() -> Optional[str]:
    """Round-robin po zywych kluczach z respektowaniem rate-limitu per-klucz."""
    global _gemini_round_robin_idx
    alive = _alive_gemini_keys()
    if not alive:
        return None

    # Wybierz klucz ktory najdluzej nie byl uzyty (zeby rownolegle rozkladac obciazenie)
    with _gemini_state_lock:
        oldest = min(alive, key=lambda k: _gemini_last_call_at.get(k, 0.0))
        return oldest


def _gemini_wait_for_key(key: str):
    """Sleep az klucz bedzie gotowy (4.5s od ostatniego uzycia)."""
    global _gemini_last_call_at
    with _gemini_state_lock:
        last = _gemini_last_call_at.get(key, 0.0)
        elapsed = time.time() - last
        if elapsed < _GEMINI_MIN_INTERVAL_SEC:
            sleep_for = _GEMINI_MIN_INTERVAL_SEC - elapsed
        else:
            sleep_for = 0
    if sleep_for > 0:
        time.sleep(sleep_for)
    with _gemini_state_lock:
        _gemini_last_call_at[key] = time.time()


def _mark_gemini_dead(key: str, reason: str):
    """Oznacza klucz jako wyczerpany — nie probujemy go juz w tej sesji."""
    with _gemini_state_lock:
        _gemini_dead_keys.add(key)


def _call_gemini(model_id: str, prompt: str, refs: Optional[list], size: tuple) -> bytes:
    """
    Gemini image generation z PULA kluczy.
    - Per-klucz rate limit (4.5s = ~13 RPM, pod 15 free tier)
    - Auto-rotacja: gdy klucz padnie na 429 → sprobuj kolejnym
    - Daily quota klucza → mark jako dead, nie wracamy
    """
    if not GEMINI_API_KEYS:
        raise QuotaExhausted("Brak kluczy GEMINI — dodaj GEMINI_API_KEY (lub _1, _2...) do Secrets.")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImageGenerationError("Brak pakietu google-genai. pip install google-genai")

    parts = []
    if refs:
        for r in refs[:3]:
            try:
                parts.append(_ref_to_gemini_part(r))
            except Exception:
                pass
    parts.append(types.Part.from_text(text=prompt))

    keys_tried_this_request: list[str] = []
    last_error: Optional[Exception] = None

    # Petla rotacji: probujemy kolejne klucze az ktorys zadziala
    while True:
        key = _next_gemini_key()
        if not key or key in keys_tried_this_request:
            # Wszystkie zywe klucze sprobowane → koniec
            break
        keys_tried_this_request.append(key)

        # Per-klucz: max 3 proby z backoffem na rate limit (transient)
        for attempt in range(3):
            _gemini_wait_for_key(key)
            try:
                client = genai.Client(api_key=key)
                resp = client.models.generate_content(
                    model=model_id,
                    contents=parts,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    ),
                )
                for candidate in resp.candidates:
                    for part in candidate.content.parts:
                        if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                            return part.inline_data.data
                # Brak obrazu — to dziwne, traktujemy jako transient
                last_error = ImageGenerationError("Gemini zwrocil odpowiedz bez obrazu")
                time.sleep(2)
                continue

            except Exception as e:
                msg = str(e).lower()
                last_error = e

                # Daily quota / billing wyczerpane → klucz jest martwy, przeskocz na kolejny
                is_daily = (
                    ("quota" in msg and "daily" in msg)
                    or "billing" in msg
                    or "permission" in msg
                    or "api key not valid" in msg
                    or "invalid" in msg and "key" in msg
                )
                if is_daily:
                    _mark_gemini_dead(key, str(e)[:80])
                    break  # break z attempt loop → bierzemy kolejny klucz

                # 429 / rate limit / resource_exhausted → backoff
                is_rate = (
                    "429" in msg or "rate" in msg
                    or "resource_exhausted" in msg or "too many" in msg
                )
                if is_rate:
                    if attempt < 2:
                        time.sleep(8 * (attempt + 1))  # 8, 16 sek
                        continue
                    # Po 3 probach na tym kluczu — moze tu jest dzienny limit ukryty pod 429.
                    # Mark jako dead i probuj kolejnego klucza
                    _mark_gemini_dead(key, "rate limit po 3 probach")
                    break

                # Inny blad — sprobuj raz jeszcze na tym samym kluczu
                if attempt < 1:
                    time.sleep(3)
                    continue
                # Po 2 probach z innym bledem → przejdz na kolejny klucz
                break

    # Wyczerpano wszystkie zywe klucze
    alive = _alive_gemini_keys()
    if not alive:
        raise QuotaExhausted(
            f"Wszystkie {len(GEMINI_API_KEYS)} kluczy Gemini wyczerpane. "
            f"Ostatni blad: {last_error}"
        )
    raise ImageGenerationError(
        f"Gemini nie zwrocil obrazu mimo {len(keys_tried_this_request)} kluczy: {last_error}"
    )


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
