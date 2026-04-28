"""
Style Extractor - analiza zdjec referencyjnych przez Claude Vision
i wyciagniecie StyleProfile JSON.
"""
from pathlib import Path
from typing import Union

from config import PROMPTS_DIR
from core.llm import call_claude_vision_json


def _load_prompt() -> str:
    return (PROMPTS_DIR / "style_extract.md").read_text(encoding="utf-8")


def extract_style_profile(
    images: list[Union[str, Path, bytes]],
    extra_context: str = "",
) -> dict:
    """
    Analizuje 5-10 zdjec i zwraca pelny StyleProfile JSON.

    Argumenty:
      images: lista sciezek do plikow lokalnych, URLi lub raw bytes
      extra_context: opcjonalny opis kontekstu (np. "to jest profil Pawla Tkaczyka")

    Zwraca: dict zgodny z prompts/style_extract.md schema
    """
    if not images:
        raise ValueError("Brak zdjec do analizy stylu.")

    if len(images) > 10:
        # Limituj zeby nie przekroczyc context window i zaoszczedzic na tokenach
        images = images[:10]

    system_prompt = _load_prompt()

    user_prompt = "Przeanalizuj te zdjecia i wyciagnij pelny Style Profile zgodnie ze schematem."
    if extra_context:
        user_prompt += f"\n\nDodatkowy kontekst od uzytkownika: {extra_context}"
    user_prompt += "\n\nZwroc TYLKO JSON, zero komentarzy."

    profile = call_claude_vision_json(
        prompt=user_prompt,
        images=images,
        system=system_prompt,
        max_tokens=4096,
    )

    # Walidacja minimalna
    required_keys = ["palette", "typography", "layout_patterns", "image_style", "extracted_summary"]
    for k in required_keys:
        if k not in profile:
            profile[k] = "" if k == "extracted_summary" or k == "image_style" else []

    return profile


def re_extract_with_more_refs(
    existing_profile: dict,
    new_images: list,
) -> dict:
    """
    Gdy user dodaje wiecej zdjec do istniejacego stylu - aktualizuje profile.
    Po prostu robi nowa analize wszystkich zdjec lacznie.
    """
    # ProstaImplementacja: re-extract z nowymi zdjeciami (caller przekazuje wszystkie)
    return extract_style_profile(new_images,
                                   extra_context=f"Aktualizacja istniejacego stylu '{existing_profile.get('name', '')}'.")
