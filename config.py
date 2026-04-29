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

# Publer (auto-publishing via Publer API — Phase 2)
PUBLER_API_KEY = _get_secret("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = _get_secret("PUBLER_WORKSPACE_ID")  # opcjonalny — auto-fetchowany jeśli pusty


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
        # Nano Banana Pro - najnowszy Gemini image model (Gemini 3 Pro Image, listopad 2025)
        # 4K output, najlepszy style transfer, advanced reasoning
        "name": "nano-banana-pro",
        "provider": "gemini",
        "model_id": "gemini-3-pro-image-preview",
        "supports_reference": True,
        "best_for": "styl + jakość",
        "cost_per_image": 0.00,  # free tier dostępny
        "daily_quota": 500,
    },
    {
        "name": "gpt-image-2",
        "provider": "openai",
        "model_id": "gpt-image-2",
        "supports_reference": True,
        "best_for": "tekst + jakość",
        "cost_per_image": 0.04,  # high quality estimate
        "daily_quota": 200,
    },
    {
        "name": "flux-schnell",
        "provider": "replicate",
        "model_id": "black-forest-labs/flux-schnell",
        "supports_reference": False,
        "best_for": "fallback",
        "cost_per_image": 0.003,
        "daily_quota": 1000,
    },
]

# Jakosc OpenAI: 'low' (~$0.011) | 'medium' (~$0.042) | 'high' (~$0.167)
# 'low' jest domyslne - dobra jakosc dla tla karuzeli, 7x tansze niz 'high'
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "low")


# ─────────────────────────────────────────────────────────────
# KAROZELE - PARAMETRY GENERACJI
# ─────────────────────────────────────────────────────────────
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350                # 4:5 - format Instagrama (lepiej dziala niz 1:1)
MIN_SLIDES = 5
MAX_SLIDES = 10
DEFAULT_SLIDES = 7

# Czcionka do nakladania polskiego tekstu (Pillow overlay)
# Cross-platform: probujemy bundled -> Streamlit Cloud (DejaVu) -> Linux/Mac/Windows fallback
ASSETS_FONTS_DIR = BASE_DIR / "assets" / "fonts"

_FONT_BOLD_CANDIDATES = [
    ASSETS_FONTS_DIR / "Montserrat-Black.ttf",                               # bundled, TikTok-style (preferred)
    ASSETS_FONTS_DIR / "Montserrat-Bold.ttf",                                # bundled fallback
    ASSETS_FONTS_DIR / "Inter-Variable.ttf",                                 # bundled fallback
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),            # Streamlit Cloud / Debian
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),    # Linux alt
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),             # Linux alt
    Path("/Library/Fonts/Arial Bold.ttf"),                                    # macOS
    Path("/System/Library/Fonts/Helvetica.ttc"),                              # macOS fallback
    Path("C:/Windows/Fonts/arialbd.ttf"),                                     # Windows
    Path("C:/Windows/Fonts/segoeuib.ttf"),                                    # Windows alt
]

_FONT_REGULAR_CANDIDATES = [
    ASSETS_FONTS_DIR / "Montserrat-Bold.ttf",                                # bundled, body in Bold (TikTok readability)
    ASSETS_FONTS_DIR / "Montserrat-Regular.ttf",                             # bundled fallback
    ASSETS_FONTS_DIR / "Inter-Variable.ttf",                                 # bundled fallback
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
]


def _find_first_existing(paths: list[Path]) -> str:
    """Zwraca pierwsza istniejaca sciezke albo pusty string (Pillow uzyje default)."""
    for p in paths:
        try:
            if Path(p).exists():
                return str(p)
        except (OSError, PermissionError):
            continue
    return ""


SLIDE_FONT_HEADLINE = _find_first_existing(_FONT_BOLD_CANDIDATES)
SLIDE_FONT_BODY = _find_first_existing(_FONT_REGULAR_CANDIDATES)
SLIDE_TEXT_COLOR = "#FFFFFF"
SLIDE_TEXT_STROKE = "#000000"
SLIDE_TEXT_STROKE_WIDTH = 8        # TikTok-style mocny czarny obrys (Montserrat Black + 8px)
SLIDE_TEXT_STROKE_WIDTH_BODY = 5   # body trochę cieńszy


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
def _get_secret_float(key: str, default: float) -> float:
    val = _get_secret(key, "")
    if not val:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


DAILY_COST_CAP_USD = _get_secret_float("DAILY_COST_CAP_USD", 5.0)


# ─────────────────────────────────────────────────────────────
# DETEKCJA STREAMLIT CLOUD (do warning'ow o ephemeral storage)
# ─────────────────────────────────────────────────────────────
IS_STREAMLIT_CLOUD = bool(
    os.getenv("STREAMLIT_RUNTIME_ENV") == "cloud"
    or "/mount/src" in str(BASE_DIR)
    or os.getenv("HOSTNAME", "").startswith("streamlit-")
)


# ─────────────────────────────────────────────────────────────
# JEZYKI
# ─────────────────────────────────────────────────────────────
SUPPORTED_LANGUAGES = ["pl", "en"]
DEFAULT_LANGUAGE = "pl"
