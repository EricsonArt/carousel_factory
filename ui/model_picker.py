"""
Wspólny picker modeli generacji obrazów.

Używany w:
  - ui/generate.py (Generator karuzel) — pełny picker
  - ui/generate.py (Viral Replicator) — pełny picker
  - ui/automation.py (Automat) — pełny picker

Zwraca tuple (use_ai, prefer_provider, model_override, image_quality)
gotowy do przekazania jako params do core.image_router.generate_image().
"""
from typing import Optional

from config import GEMINI_API_KEYS, OPENAI_API_KEY


def get_image_model_options() -> dict[str, str]:
    """
    Zwraca dict {model_key: label} dostępnych modeli na podstawie kluczy API.
    Klucze są takie same jak w generate.py żeby zachować spójność.
    """
    options: dict[str, str] = {}
    if GEMINI_API_KEYS:
        options["nano_banana_pro"]  = "🟢 Nano Banana Pro (Gemini 3 Pro Image)  —  TOP JAKOŚĆ, 4K, GRATIS"
        options["nano_banana_2"]    = "🟢 Nano Banana 2 (Gemini 3.1 Flash)  —  szybkie, GRATIS"
        options["nano_banana_v25"]  = "🟢 Nano Banana (Gemini 2.5 Flash Image)  —  klasyk, GRATIS"
    if OPENAI_API_KEY:
        options["openai_v2"]        = "🔴 GPT Image 2 (OpenAI 21.04.2026)  —  najnowszy, reasoning, czytelny tekst"
        options["openai_v1_high"]   = "🟠 gpt-image-1 high quality  —  starszy, ~$1.20/karuzela"
        options["openai_v1_low"]    = "💛 gpt-image-1 low quality  —  starszy, ~$0.08/karuzela"
    options["none"] = "⚠️ Gradient z palety (BEZ AI)"
    return options


def resolve_image_model(model_key: str) -> tuple[bool, Optional[str], Optional[str], str]:
    """
    Mapuje model_key z UI na parametry dla core.image_router.generate_image().

    Zwraca: (use_ai, prefer_provider, model_override, image_quality)
    """
    prefer_provider = {
        "nano_banana_pro": "gemini",
        "nano_banana_2":   "gemini",
        "nano_banana_v25": "gemini",
        "openai_v1_low":   "openai",
        "openai_v1_high":  "openai",
        "openai_v2":       "openai",
    }.get(model_key)

    image_quality = {
        "openai_v1_low":  "low",
        "openai_v1_high": "high",
        "openai_v2":      "high",
    }.get(model_key, "low")

    model_override = {
        "nano_banana_pro": "gemini-3-pro-image-preview",
        "nano_banana_2":   "gemini-3.1-flash-image-preview",
        "nano_banana_v25": "gemini-2.5-flash-image",
        "openai_v2":       "gpt-image-2",
    }.get(model_key)

    use_ai = model_key != "none"
    return use_ai, prefer_provider, model_override, image_quality
