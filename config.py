"""
Konfiguracja carousel_factory.

Wszystkie sekrety (klucze API) czytamy przez `_get_secret()`:
1) Streamlit Secrets (`.streamlit/secrets.toml`)
2) Zmienne srodowiskowe (`.env`)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get_secret(key: str, default: str = "") -> str:
    """Czyta sekret z Streamlit Secrets lub .env. Port z viral_video_creator."""
    try:
        import streamlit as st
        val = st.secrets.get(key, "")
        if val:
            return str(val)
    except Exception:
        pass
    return os.getenv(key, default)


# ─────────────────────────────────────────────────────────────
# SCIEZKI
# ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CAROUSELS_DIR = DATA_DIR / "carousels"
STYLES_DIR = DATA_DIR / "styles"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
PROMPTS_DIR = BASE_DIR / "prompts"
DB_PATH = DATA_DIR / "carousel_factory.db"

for _d in (DATA_DIR, CAROUSELS_DIR, STYLES_DIR, SESSIONS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────
# KLUCZE API
# ─────────────────────────────────────────────────────────────
OPENAI_API_KEY = _get_secret("OPENAI_API_KEY")
GEMINI_API_KEY = _get_secret("GEMINI_API_KEY")
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
APIFY_API_TOKEN = _get_secret("APIFY_API_TOKEN")
REPLICATE_API_TOKEN = _get_secret("REPLICATE_API_TOKEN")

# Instagram (Phase 2 - instagrapi MVP)
INSTAGRAM_USERNAME = _get_secret("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = _get_secret("INSTAGRAM_PASSWORD")

# Instagram Graph API (Phase 3 - oficjalne API)
IG_USER_ID = _get_secret("IG_USER_ID")
IG_ACCESS_TOKEN = _get_secret("IG_ACCESS_TOKEN")

# TikTok Content Posting API (Phase 3)
TT_CLIENT_KEY = _get_secret("TT_CLIENT_KEY")
TT_CLIENT_SECRET = _get_secret("TT_CLIENT_SECRET")
TT_ACCESS_TOKEN = _get_secret("TT_ACCESS_TOKEN")

# Haslo dostepu do aplikacji (gdy wystawiona publicznie). Pusty = brak gate.
APP_PASSWORD = _get_secret("APP_PASSWORD")


# ─────────────────────────────────────────────────────────────
# MODELE LLM
# ─────────────────────────────────────────────────────────────
CLAUDE_TEXT_MODEL = "claude-sonnet-4-6"          # copywriting, brief wizard
CLAUDE_VISION_MODEL = "claude-sonnet-4-6"        # vision: style extraction, viral replicator
CLAUDE_FAST_MODEL = "claude-haiku-4-5-20251001"  # walidacja, krotkie taski


# ─────────────────────────────────────────────────────────────
# IMAGE GENERATION CASCADE
# ─────────────────────────────────────────────────────────────
# Kaskada: probujemy primary -> jesli quota wyczerpana -> secondary -> fallback
IMAGE_MODELS = [
    {
        "name": "gpt-image-1",
        "provider": "openai",
        "model_id": "gpt-image-1",
        "supports_reference": True,        # /images/edits przyjmuje refs
        "best_for": "tekst",                # czytelny tekst polski
        "cost_per_image": 0.04,             # USD przy quality=high
        "daily_quota": 200,                 # mozliwe do override per user
    },
    {
        "name": "gemini-2.5-flash-image",
        "provider": "gemini",
        "model_id": "gemini-2.5-flash-image",
        "supports_reference": True,        # multi-image blending
        "best_for": "styl",                 # idealny do replikacji stylu
        "cost_per_image": 0.039,
        "daily_quota": 500,
    },
    {
        "name": "flux-pro",
        "provider": "replicate",
        "model_id": "black-forest-labs/flux-1.1-pro",
        "supports_reference": False,
        "best_for": "fallback",
        "cost_per_image": 0.04,
        "daily_quota": 1000,
    },
]


# ─────────────────────────────────────────────────────────────
# KAROZELE - PARAMETRY GENERACJI
# ─────────────────────────────────────────────────────────────
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350                # 4:5 - format Instagrama (lepiej dziala niz 1:1)
MIN_SLIDES = 5
MAX_SLIDES = 10
DEFAULT_SLIDES = 7

# Czcionka do nakladania polskiego tekstu (Pillow overlay)
_FONTS_WIN = Path("C:/Windows/Fonts")
SLIDE_FONT_HEADLINE = str(_FONTS_WIN / "arialbd.ttf")  # bold dla naglowkow
SLIDE_FONT_BODY = str(_FONTS_WIN / "arial.ttf")        # regular
SLIDE_TEXT_COLOR = "#FFFFFF"
SLIDE_TEXT_STROKE = "#000000"
SLIDE_TEXT_STROKE_WIDTH = 4


# ─────────────────────────────────────────────────────────────
# PUBLISHING
# ─────────────────────────────────────────────────────────────
PUBLISHER_MODE = os.getenv("PUBLISHER_MODE", "none")  # 'none' | 'instagrapi' | 'graph_api' | 'tiktok'
MAX_POSTS_PER_DAY_PER_BRAND = 10
MIN_GAP_MINUTES = 90
SLOT_HOURS = [
    ("07:30", "09:30"),
    ("11:30", "13:30"),
    ("17:00", "19:00"),
    ("20:00", "22:30"),
]


# ─────────────────────────────────────────────────────────────
# COST CONTROL
# ─────────────────────────────────────────────────────────────
DAILY_COST_CAP_USD = float(os.getenv("DAILY_COST_CAP_USD", "5.0"))


# ─────────────────────────────────────────────────────────────
# JEZYKI
# ─────────────────────────────────────────────────────────────
SUPPORTED_LANGUAGES = ["pl", "en"]
DEFAULT_LANGUAGE = "pl"
