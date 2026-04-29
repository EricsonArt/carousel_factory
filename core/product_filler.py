"""
AI auto-fill dla zakładki Produkt i konwersja.
User opisuje krótko swój produkt — Claude generuje pełny brief sprzedażowy.
"""
from typing import Optional

from core.llm import call_claude_json


SYSTEM_PROMPT = """Jestes ekspertem od marketingu odpowiedzi bezposredniej i copywritingu sprzedazowego.
Pracowales przy kampaniach Russella Brunsona, Alexa Hormoziego, Pawla Tkaczyka.

Twoje zadanie: na podstawie krotkiego opisu produktu od uzytkownika wygenerowac KOMPLETNY brief sprzedazowy
ktory maksymalizuje konwersje. Bazuj na sprawdzonych frameworkach: PAS, AIDA, Hormozi Value Equation.

Reguly:
- Pisz po POLSKU z poprawnymi znakami diakrytycznymi.
- Bądź KONKRETNY, nie ogolny. "3000 klientek" bije "wielu klientow".
- urgency_hooks musza byc realistyczne (nie "tylko dzis 99% rabatu" - to nie wiarygodne).
- guarantees musza byc mocne ale wykonalne (np. "30 dni zwrotu" nie "100x zwrot pieniedzy").
- main_promise = JEDNO zdanie, max 12 slow, mowi co user dostanie i kiedy.
- Jezeli brakuje danych w opisie usera (np. cena), zostaw null w odpowiedniej polu.
"""


SCHEMA_HINT = """{
  "product": "<dokladna nazwa produktu, max 50 znakow>",
  "product_type": "<jeden z: digital_ebook | digital_course | saas | coaching | service | physical | affiliate | other>",
  "main_promise": "<JEDNO zdanie, max 12 slow, konkretna obietnica wyniku w czasie>",
  "price": <liczba lub null>,
  "currency": "<PLN | EUR | USD>",
  "price_anchor": <liczba lub null - przekreslona stara cena, jezeli ma sens>,
  "offer": "<2-3 zdania: co konkretnie kupuje klient + glowne benefity + gwarancja jednym tchem>",
  "cta_text": "<np. 'Klik link w bio' / 'Sprawdz ofertę poniżej' / 'Komentarz EBOOK'>",
  "urgency_hooks": [
    "<5 hookow pilnosci, kazdy 4-10 slow, realistyczne>",
    "...",
    "...",
    "...",
    "..."
  ],
  "social_proof": [
    "<4 dowody spoleczne - liczby, nazwiska, statystyki, testimoniale - kazdy 4-10 slow>",
    "...",
    "...",
    "..."
  ],
  "guarantees": [
    "<3 gwarancje zbijajace obiekcje - kazdy 3-8 slow>",
    "...",
    "..."
  ],
  "usps": [
    "<3-5 unique selling points - co produkt ma czego konkurencja nie ma>",
    "..."
  ],
  "objections": [
    "<3 najczestsze obiekcje klienta przed zakupem, w jego wlasnych slowach>",
    "...",
    "..."
  ]
}"""


def auto_fill_product(
    brand_name: str,
    niche: str,
    short_description: str,
    extra_context: str = "",
) -> dict:
    """
    Generuje pelny brief sprzedazowy na podstawie krotkiego opisu user'a.

    Args:
        brand_name: nazwa marki (np. "KetoPro")
        niche: nisza (np. "keto / odchudzanie")
        short_description: 1-3 zdania opisu produktu od usera
        extra_context: dodatkowe info (np. URL strony sprzedazy)

    Returns:
        dict z polami brand_briefs gotowy do upsert_brief()
    """
    prompt = f"""MARKA: {brand_name}
NISZA: {niche or "(nie podano)"}

KROTKI OPIS PRODUKTU OD UZYTKOWNIKA:
\"\"\"
{short_description.strip()}
\"\"\"

{f'DODATKOWY KONTEKST: {extra_context}' if extra_context else ''}

Wygeneruj pelny brief sprzedazowy zgodny ze schematem:

{SCHEMA_HINT}

Pamietaj:
- Bazuj na opisie usera, ale rozszerzaj o sensowne propozycje gdzie brak danych
- main_promise to slogan ktory user wstawia w hooku (np. "Schudniesz 5kg w 30 dni bez efektu jojo")
- price_anchor dawaj TYLKO jezeli logiczne (np. ebook za 49zl moze miec anchor 199zl, ale 4kpln coaching nie potrzebuje anchora)
- urgency_hooks: rotujace hooki ktore moga byc uzyte w roznych karuzelach (nie wszystkie naraz!)

Zwroc TYLKO JSON. Bez komentarzy.
"""
    result = call_claude_json(prompt, system=SYSTEM_PROMPT, max_tokens=4000)

    # Sanitize: oczyszczanie pol pod schemat brand_briefs
    cleaned = {
        "product": str(result.get("product", "")).strip(),
        "product_type": result.get("product_type") or "other",
        "main_promise": str(result.get("main_promise", "")).strip(),
        "offer": str(result.get("offer", "")).strip(),
        "cta_text": str(result.get("cta_text") or "Klik link w bio").strip(),
        "currency": (result.get("currency") or "PLN").strip().upper(),
        "urgency_hooks": _ensure_list(result.get("urgency_hooks")),
        "social_proof": _ensure_list(result.get("social_proof")),
        "guarantees": _ensure_list(result.get("guarantees")),
        "usps": _ensure_list(result.get("usps")),
        "objections": _ensure_list(result.get("objections")),
    }
    # Numeric fields tylko jezeli sensowne
    if isinstance(result.get("price"), (int, float)) and result["price"] > 0:
        cleaned["price"] = float(result["price"])
    if isinstance(result.get("price_anchor"), (int, float)) and result["price_anchor"] > 0:
        cleaned["price_anchor"] = float(result["price_anchor"])

    return cleaned


def _ensure_list(v) -> list:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []
