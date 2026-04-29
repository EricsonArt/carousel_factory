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
                     seed: int = None,
                     min_lead_minutes: int = 10) -> list[datetime]:
    """
    Generuje `num_posts` losowych UTC datetimes ulokowanych w `slots`.

    Sloty to lista (start_time, end_time) jako stringi 'HH:MM' UTC.
    - min_gap_minutes: minimalna przerwa miedzy postami
    - min_lead_minutes: minimalny zapas od `now()` (Publer potrzebuje czasu na przetworzenie)

    Algorytm:
      1) Pomijamy sloty ktore juz sie skonczyly dzis (slot_end < now+lead).
      2) Dla pozostalych slotow losujemy moment, clampujac dolnie do `now+lead`.
      3) Jesli num_posts > liczba slotow, dodajemy kolejne dni.
      4) Wymuszamy min_gap_minutes miedzy kolejnymi postami.
    """
    if seed is not None:
        rnd = random.Random(seed)
    else:
        rnd = random.Random()

    now_utc = datetime.now(timezone.utc)
    earliest_allowed = now_utc + timedelta(minutes=min_lead_minutes)

    if base_date is None:
        base_date = now_utc

    base_date = base_date.replace(hour=0, minute=0, second=0, microsecond=0)
    results: list[datetime] = []

    day_offset = 0
    posts_left = num_posts
    safety_loops = 0

    while posts_left > 0 and safety_loops < 60:
        safety_loops += 1
        day_slots = []
        for start_str, end_str in slots:
            if posts_left <= 0:
                break
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))

            slot_start = base_date + timedelta(days=day_offset, hours=start_h, minutes=start_m)
            slot_end = base_date + timedelta(days=day_offset, hours=end_h, minutes=end_m)

            # Pomin slot ktory juz minal (zostaly < lead minut)
            if slot_end <= earliest_allowed:
                continue

            # Clampuj dolnie do earliest_allowed (zeby nie wybrac przeszlosci)
            effective_start = max(slot_start, earliest_allowed)
            window_seconds = int((slot_end - effective_start).total_seconds())
            if window_seconds <= 0:
                continue

            offset_seconds = rnd.randint(0, window_seconds)
            chosen = effective_start + timedelta(seconds=offset_seconds)
            day_slots.append(chosen)
            posts_left -= 1

        day_slots.sort()
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
    """
    Wyciaga {...} z odpowiedzi LLM (czasami sa otoczone tekstem/markdownem).
    Jezeli JSON zostal przyciety (np. max_tokens hit), probuje go domknac
    dopisujac brakujace `]` i `}`.
    """
    raw = raw.strip()
    # Usun markdown code blocks
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Wyciagnij od pierwszego `{` do konca (zachlannie)
    start = raw.find("{")
    if start == -1:
        return raw
    candidate = raw[start:]

    # Jezeli sie udaje sparsowac od razu — zwroc.
    try:
        json.loads(candidate)
        return candidate
    except (json.JSONDecodeError, TypeError):
        pass

    # Self-heal: policz nawiasy w `candidate`, ale tylko poza stringami
    return _try_heal_truncated_json(candidate)


def _try_heal_truncated_json(s: str) -> str:
    """
    Naprawia obciety JSON. Strategia: iteracyjnie ucinaj od konca po przecinku
    i domykaj brakujace ]/}, az do skutku.
    """
    # 1) Spróbuj zamknac obecna treść dopisujac brakujace ]/}
    for trim_to in _candidate_lengths(s):
        candidate = s[:trim_to].rstrip()
        # usun zwisajace przecinki przed nawiasami zamykajacymi
        candidate = re.sub(r",\s*$", "", candidate)
        if not candidate:
            continue

        # Counting nawiasów (przybliżone — nie odsiewa cudzyslowów,
        # ale w praktyce LLM rzadko ma `{` w stringu)
        ob = candidate.count("{") - candidate.count("}")
        obb = candidate.count("[") - candidate.count("]")
        if ob < 0 or obb < 0:
            continue

        # Jezeli ostatnim non-ws char jest `:` to znaczy ze klucz nie ma wartosci — pomin
        if candidate.rstrip().endswith(":"):
            continue
        # Jezeli ostatnim jest `"` w pozycji klucza — tez pomin
        # (proba parse i tak rzuci, mozemy ufac fallback)

        attempt = candidate + ("]" * obb) + ("}" * ob)
        try:
            json.loads(attempt)
            return attempt
        except (json.JSONDecodeError, ValueError):
            continue

    return s  # fallback — niech `safe_json_loads` zwroci None


def _candidate_lengths(s: str):
    """Generator pozycji do prob ucinania — od pelnej dlugosci do ostatnich N przecinków."""
    yield len(s)
    # Spróbuj kolejne pozycje przecinkow od konca
    positions = [i for i, ch in enumerate(s) if ch == ","]
    for p in reversed(positions[-50:]):
        yield p
    # Spróbuj pozycje zamkniec nawiasow
    for ch_target in "}]":
        positions = [i + 1 for i, ch in enumerate(s) if ch == ch_target]
        for p in reversed(positions[-30:]):
            yield p


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
