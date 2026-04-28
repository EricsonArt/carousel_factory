"""
Narzedzia pomocnicze - port z viral_video_creator/modules/utils.py + dodatki dla schedulera.
"""
import re
import json
import uuid
import random
import hashlib
from datetime import datetime, time, timedelta, timezone
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# POLSKIE ZNAKI (port z viral_video_creator)
# ─────────────────────────────────────────────────────────────

_POLISH_MAP = str.maketrans(
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
    "acelnoszzACELNOSZZ"
)


def normalize_polish_to_ascii(text: str) -> str:
    """ą→a, ę→e, ó→o, itd."""
    return text.translate(_POLISH_MAP)


def normalize_keyword(text: str) -> str:
    """polskie znaki → ASCII, lowercase, tylko alfanumeryczne i _."""
    text = normalize_polish_to_ascii(text.lower())
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def sanitize_filename(name: str) -> str:
    """Bezpieczna nazwa pliku - max 64 znaki, ASCII."""
    name = normalize_polish_to_ascii(name)
    name = re.sub(r"[^\w\-_.]", "_", name)
    return name.strip("._")[:64]


# ─────────────────────────────────────────────────────────────
# IDENTYFIKATORY
# ─────────────────────────────────────────────────────────────

def generate_session_id() -> str:
    """12-znakowy hex."""
    return uuid.uuid4().hex[:12]


def generate_id(prefix: str) -> str:
    """np. 'brd_a3f2' lub 'sty_8c1e' - prefix + 8 hex."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def short_hash(text: str, length: int = 8) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


# ─────────────────────────────────────────────────────────────
# SCHEDULER - LOSOWE GODZINY W SLOTACH
# ─────────────────────────────────────────────────────────────

def slot_randomizer(slots: list[tuple[str, str]], num_posts: int,
                     min_gap_minutes: int = 90,
                     base_date: datetime = None,
                     seed: int = None) -> list[datetime]:
    """
    Generuje `num_posts` losowych UTC datetimes ulokowanych w `slots`.

    Sloty to lista (start_time, end_time) jako stringi 'HH:MM' w lokalnym czasie.
    Min `min_gap_minutes` przerwa miedzy postami.

    Algorytm:
      1) Dla kazdego slotu wybierz losowy moment.
      2) Sortuj rosnaco.
      3) Jesli ktorys post ma <min_gap od poprzedniego, przesun go na max(slot.start, prev+gap).
      4) Jesli num_posts > liczba slotow, dodaj kolejne dni.
    """
    if seed is not None:
        rnd = random.Random(seed)
    else:
        rnd = random.Random()

    if base_date is None:
        base_date = datetime.now(timezone.utc)

    base_date = base_date.replace(hour=0, minute=0, second=0, microsecond=0)
    results: list[datetime] = []

    day_offset = 0
    posts_left = num_posts

    while posts_left > 0:
        day_slots = []
        for start_str, end_str in slots:
            if posts_left <= 0:
                break
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))

            slot_start = base_date + timedelta(days=day_offset, hours=start_h, minutes=start_m)
            slot_end = base_date + timedelta(days=day_offset, hours=end_h, minutes=end_m)

            window_seconds = int((slot_end - slot_start).total_seconds())
            if window_seconds <= 0:
                continue
            offset_seconds = rnd.randint(0, window_seconds)
            chosen = slot_start + timedelta(seconds=offset_seconds)
            day_slots.append(chosen)
            posts_left -= 1

        day_slots.sort()
        # enforce min gap
        for i in range(1, len(day_slots)):
            min_next = day_slots[i - 1] + timedelta(minutes=min_gap_minutes)
            if day_slots[i] < min_next:
                day_slots[i] = min_next
        results.extend(day_slots)
        day_offset += 1

    return results[:num_posts]


# ─────────────────────────────────────────────────────────────
# JSON HELPERS
# ─────────────────────────────────────────────────────────────

def safe_json_loads(raw: str, default=None):
    """JSON loads z try/except - zwraca default jesli blad."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def extract_json_block(raw: str) -> str:
    """Wyciaga {...} z odpowiedzi LLM (czasami sa otoczone tekstem/markdownem)."""
    raw = raw.strip()
    # Usun markdown code blocks
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return match.group()
    return raw


# ─────────────────────────────────────────────────────────────
# IMAGE FILE HELPERS
# ─────────────────────────────────────────────────────────────

def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_image_bytes(image_bytes: bytes, path: Path) -> Path:
    ensure_dir(path.parent)
    path.write_bytes(image_bytes)
    return path


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ─────────────────────────────────────────────────────────────
# TEKST DO SLAJDOW
# ─────────────────────────────────────────────────────────────

def wrap_text_for_slide(text: str, max_chars_per_line: int = 18) -> list[str]:
    """
    Rozbija tekst headline na linie max_chars_per_line.
    Zachowuje slowa - nie tnie w srodku.
    """
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip() if current else word
        if len(candidate) > max_chars_per_line and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def truncate_with_ellipsis(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1].rstrip() + "…"
