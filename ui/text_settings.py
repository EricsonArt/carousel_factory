"""
Panel kontroli stylu tekstu na slajdach karuzeli.

Wywolanie:
    settings = render_text_settings_panel(brand_id, brief, key_prefix="generate")

Zwraca dict zgodny z core.text_renderer.DEFAULT_TEXT_SETTINGS.
Defaulty: brief.text_settings (jesli zapisany dla marki) -> session_state -> hardcoded.

Checkbox "Zapisz jako domyslny styl marki" pod panelem -> upsert_brief.
"""
from __future__ import annotations
from typing import Optional

import streamlit as st

from db import upsert_brief
from core.text_renderer import DEFAULT_TEXT_SETTINGS, merge_text_settings


_FONT_OPTIONS = {
    "montserrat_black": "Montserrat Black (TikTok-style, gruby)",
    "montserrat_bold":  "Montserrat Bold (mocny, czytelny)",
    "inter":            "Inter (nowoczesny, czysty)",
    "system":           "Domyslny systemowy",
}

_POSITION_OPTIONS = {
    "auto":    "Auto (AI dopasuje do tla — smart positioning)",
    "top":     "Gora",
    "center":  "Srodek",
    "bottom":  "Dol",
}

_LENGTH_OPTIONS = {
    "short":  "Krotka (max 8 slow body)",
    "medium": "Srednia (max 14 slow body)",
    "long":   "Dluga (max 22 slow body)",
}


def render_text_settings_panel(brand_id: str, brief: dict,
                                 key_prefix: str = "ts",
                                 default_expanded: bool = False) -> dict:
    """
    Renderuje expander z 11 kontrolkami stylu tekstu i zwraca aktualne ustawienia.
    Zmiana -> wartosc w session_state[key_prefix + "_settings"].
    Checkbox "Zapisz jako domyslny" -> upsert_brief(text_settings).
    """
    # Resolve initial state: session > brief > defaults
    state_key = f"{key_prefix}_text_settings"
    if state_key not in st.session_state:
        st.session_state[state_key] = merge_text_settings(brief.get("text_settings"))

    current = st.session_state[state_key]

    with st.expander("🎨 Styl tekstu (rozmiar, font, kolor, pozycja)", expanded=default_expanded):
        st.caption(
            "Te parametry wplywaja na to jak Pillow naklada tekst na obraz. "
            "AI nadal dopasowuje sie do dlugosci tekstu i smart-positioning na bazie tla."
        )

        # ─── Rozmiary ───
        st.markdown("**Rozmiary fontu**")
        col1, col2 = st.columns(2)
        with col1:
            headline_size_hero = st.slider(
                "Naglowek slajdu 1 (hero)",
                min_value=50, max_value=140,
                value=int(current["headline_size_hero"]),
                step=2,
                key=f"{key_prefix}_hero_size",
                help="Rozmiar tekstu na pierwszym slajdzie. Duza wartosc = wiekszy impact.",
            )
        with col2:
            headline_size_rest = st.slider(
                "Naglowek slajdy 2+",
                min_value=30, max_value=120,
                value=int(current["headline_size_rest"]),
                step=2,
                key=f"{key_prefix}_rest_size",
                help="Rozmiar tekstu na pozostalych slajdach. Mniej niz hero = efekt 'Hero+Whisper'.",
            )

        col3, col4 = st.columns(2)
        with col3:
            body_same_as_headline = st.checkbox(
                "Body tym samym fontem/rozmiarem co headline",
                value=bool(current["body_same_as_headline"]),
                key=f"{key_prefix}_body_same",
                help="TikTok Minimal feel — calosc tekstu jednolita, bez podzialu headline/body.",
            )
        with col4:
            if not body_same_as_headline:
                body_size = st.slider(
                    "Rozmiar body",
                    min_value=18, max_value=70,
                    value=int(current["body_size"]),
                    step=2,
                    key=f"{key_prefix}_body_size",
                )
            else:
                body_size = current["body_size"]
                st.caption("Body uzyje rozmiaru naglowka.")

        # ─── Czcionka + UPPERCASE ───
        st.markdown("**Typografia**")
        col5, col6 = st.columns(2)
        with col5:
            font_keys = list(_FONT_OPTIONS.keys())
            default_font_idx = font_keys.index(current["font_key"]) if current["font_key"] in font_keys else 0
            font_key = st.selectbox(
                "Font",
                options=font_keys,
                format_func=lambda k: _FONT_OPTIONS[k],
                index=default_font_idx,
                key=f"{key_prefix}_font",
            )
        with col6:
            uppercase = st.checkbox(
                "WSZYSTKO UPPERCASE",
                value=bool(current["uppercase"]),
                key=f"{key_prefix}_upper",
                help="Cala karuzela wielkimi literami — typowo TikTok hook style.",
            )

        # ─── Kolory + obrys ───
        st.markdown("**Kolor i obrys**")
        col7, col8, col9 = st.columns(3)
        with col7:
            text_color = st.color_picker(
                "Kolor tekstu",
                value=current["text_color"],
                key=f"{key_prefix}_text_color",
            )
        with col8:
            stroke_color = st.color_picker(
                "Kolor obrysu",
                value=current["stroke_color"],
                key=f"{key_prefix}_stroke_color",
            )
        with col9:
            stroke_width = st.slider(
                "Grubosc obrysu",
                min_value=0, max_value=12,
                value=int(current["stroke_width"]),
                step=1,
                key=f"{key_prefix}_stroke_w",
                help="0 = brak obrysu (Editorial style). 6+ = TikTok bold.",
            )

        # ─── Pozycja + dlugosc + smart fitting ───
        st.markdown("**Pozycja i dlugosc tekstu**")
        col10, col11, col12 = st.columns(3)
        with col10:
            position_keys = list(_POSITION_OPTIONS.keys())
            pos_idx = position_keys.index(current["position"]) if current["position"] in position_keys else 0
            position = st.selectbox(
                "Pozycja tekstu na slajdzie",
                options=position_keys,
                format_func=lambda k: _POSITION_OPTIONS[k],
                index=pos_idx,
                key=f"{key_prefix}_position",
            )
        with col11:
            length_keys = list(_LENGTH_OPTIONS.keys())
            len_idx = length_keys.index(current["text_length"]) if current["text_length"] in length_keys else 1
            text_length = st.selectbox(
                "Dlugosc tekstu (instrukcja dla AI)",
                options=length_keys,
                format_func=lambda k: _LENGTH_OPTIONS[k],
                index=len_idx,
                key=f"{key_prefix}_length",
                help="Wstrzykiwane do prompta copywritera. Krotsze = bardziej impactowe, mniej slow.",
            )
        with col12:
            smart_fitting = st.checkbox(
                "Smart fitting (auto-overlay + auto-pozycja)",
                value=bool(current["smart_fitting"]),
                key=f"{key_prefix}_smart",
                help=(
                    "Po wygenerowaniu obrazu analizuje tlo i dodaje subtelny gradient pod tekstem "
                    "GDY tlo jest jasne lub niespokojne. Plus: gdy pozycja=auto, wybiera "
                    "najmniej zatluszczona strefe (top/center/bottom) na bazie edge density."
                ),
            )

        # ─── Aktualizacja stanu ───
        new_settings = {
            "headline_size_hero": int(headline_size_hero),
            "headline_size_rest": int(headline_size_rest),
            "body_size": int(body_size),
            "body_same_as_headline": bool(body_same_as_headline),
            "font_key": font_key,
            "text_color": text_color,
            "stroke_color": stroke_color,
            "stroke_width": int(stroke_width),
            "position": position,
            "uppercase": bool(uppercase),
            "text_length": text_length,
            "smart_fitting": bool(smart_fitting),
        }
        st.session_state[state_key] = new_settings

        # ─── Save as default ───
        st.markdown("---")
        col_save, col_reset = st.columns([2, 1])
        with col_save:
            if st.button(
                "💾 Zapisz jako domyslny styl tej marki",
                key=f"{key_prefix}_save_default",
                use_container_width=True,
                help="Zapisuje obecne ustawienia w briefie marki. "
                     "Automat tygodniowy uzyje ich przy kazdej generacji.",
            ):
                upsert_brief(brand_id, {"text_settings": new_settings})
                st.success("✓ Zapisano jako domyslny styl tej marki. Automat tez bedzie z tego korzystac.")
        with col_reset:
            if st.button(
                "↺ Reset",
                key=f"{key_prefix}_reset",
                use_container_width=True,
                help="Przywroc fabryczne ustawienia (TikTok bold).",
            ):
                st.session_state[state_key] = dict(DEFAULT_TEXT_SETTINGS)
                st.rerun()

    return new_settings
