"""
Panel kontroli stylu tekstu na slajdach karuzeli.

Wywolanie:
    settings = render_text_settings_panel(brand_id, brief, key_prefix="generate")

Zwraca dict zgodny z core.text_renderer.DEFAULT_TEXT_SETTINGS.
Defaulty: brief.text_settings (jesli zapisany dla marki) -> session_state -> hardcoded.

Live preview obok suwakow: kazda zmiana parametru -> instant rerender placeholder slajdu.
"""
from __future__ import annotations
import io
from typing import Optional

import streamlit as st
from PIL import Image, ImageDraw

from config import SLIDE_WIDTH, SLIDE_HEIGHT
from db import upsert_brief
from core.text_renderer import DEFAULT_TEXT_SETTINGS, merge_text_settings, apply_text_to_image


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

# Przyklady tekstu do preview — krotki, sredni, dlugi
_PREVIEW_HEADLINES = {
    0: "TWOJ NAGLOWEK SLAJDU 1",
    1: "Drugi slajd — naglowek",
}
_PREVIEW_BODIES = {
    "short":  "Krotki przyklad body.",
    "medium": "Sredni body — pokazuje jak dlugi tekst sie zachowa.",
    "long":   "Dluzszy przyklad body ktory wypelnia wiecej miejsca na slajdzie zeby pokazac wrap i shrink.",
}


def _build_preview_image(settings: dict, slide_index: int) -> Image.Image:
    """
    Buduje placeholder slajd 1080x1350 z gradientem + naklada tekst wedlug settings.
    Dorzuca delikatne kropkowane linie pokazujace safe zones (TikTok/IG UI).
    """
    # 1) Tlo: diagonalny gradient w neutralnych tonach.
    #    Optymalizacja: tworzymy 2x2 pixel image z 4 narozami i resize'ujemy bicubic
    #    (~10ms zamiast 1s petli pixel-by-pixel).
    seed = Image.new("RGB", (2, 2))
    seed.putpixel((0, 0), (45, 55, 95))    # top-left   (ciemny)
    seed.putpixel((1, 0), (60, 60, 110))   # top-right
    seed.putpixel((0, 1), (75, 65, 125))   # bottom-left
    seed.putpixel((1, 1), (90, 70, 140))   # bottom-right (jasniejszy)
    img = seed.resize((SLIDE_WIDTH, SLIDE_HEIGHT), Image.BICUBIC)

    # 2) Naklada tekst zgodnie z aktualnymi settings
    headline = _PREVIEW_HEADLINES.get(slide_index, _PREVIEW_HEADLINES[0])
    body = _PREVIEW_BODIES.get(settings.get("text_length", "medium"), _PREVIEW_BODIES["medium"])
    img = apply_text_to_image(img, headline, body,
                                slide_index=slide_index,
                                text_settings=settings,
                                image_focus_hint="center")

    # 3) Delikatne linie safe zones (top 15%, bottom 28%) — kropkowane, 50% alpha
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    safe_top_y = int(SLIDE_HEIGHT * 0.15)
    safe_bottom_y = SLIDE_HEIGHT - int(SLIDE_HEIGHT * 0.28)

    # Kropkowana linia: rysujemy male segmenty
    dash = 14
    gap = 10
    for x in range(0, SLIDE_WIDTH, dash + gap):
        odraw.line([(x, safe_top_y), (min(x + dash, SLIDE_WIDTH), safe_top_y)],
                    fill=(255, 220, 100, 130), width=3)
        odraw.line([(x, safe_bottom_y), (min(x + dash, SLIDE_WIDTH), safe_bottom_y)],
                    fill=(255, 220, 100, 130), width=3)

    # Subtelne etykiety nad/pod linia
    try:
        from PIL import ImageFont as _ImageFont
        try:
            label_font = _ImageFont.load_default(size=22)
        except TypeError:
            label_font = _ImageFont.load_default()
        odraw.text((20, safe_top_y - 32), "TOP SAFE (TikTok header)",
                    font=label_font, fill=(255, 220, 100, 200))
        odraw.text((20, safe_bottom_y + 6), "BOTTOM SAFE (TT actions / IG caption)",
                    font=label_font, fill=(255, 220, 100, 200))
    except Exception:
        pass

    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")
    return img


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

    with st.expander("🎨 Styl tekstu — kontrolki + live podglad", expanded=default_expanded):
        st.caption(
            "Suwaj parametry po lewej, rezultat widzisz po prawej. "
            "Tekst przykladowy renderowany dokladnie tak jak na finalnym slajdzie (1080×1350)."
        )

        col_controls, col_preview = st.columns([3, 2])

        # ╔═════════════════ LEWA KOLUMNA: KONTROLKI ═════════════════╗
        with col_controls:
            # ─── Rozmiary ───
            st.markdown("**Rozmiary fontu**")
            headline_size_hero = st.slider(
                "Naglowek slajdu 1 (hero)",
                min_value=50, max_value=140,
                value=int(current["headline_size_hero"]),
                step=2,
                key=f"{key_prefix}_hero_size",
                help="Rozmiar tekstu na pierwszym slajdzie. Duza wartosc = wiekszy impact.",
            )
            headline_size_rest = st.slider(
                "Naglowek slajdy 2+",
                min_value=30, max_value=120,
                value=int(current["headline_size_rest"]),
                step=2,
                key=f"{key_prefix}_rest_size",
                help="Rozmiar tekstu na pozostalych slajdach. Mniej niz hero = efekt 'Hero+Whisper'.",
            )
            body_same_as_headline = st.checkbox(
                "Body tym samym rozmiarem co headline (TikTok Minimal feel)",
                value=bool(current["body_same_as_headline"]),
                key=f"{key_prefix}_body_same",
                help="Calosc tekstu jednolita, bez podzialu headline/body.",
            )
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

            # ─── Czcionka + UPPERCASE ───
            st.markdown("**Typografia**")
            col_a, col_b = st.columns(2)
            with col_a:
                font_keys = list(_FONT_OPTIONS.keys())
                default_font_idx = font_keys.index(current["font_key"]) if current["font_key"] in font_keys else 0
                font_key = st.selectbox(
                    "Font",
                    options=font_keys,
                    format_func=lambda k: _FONT_OPTIONS[k],
                    index=default_font_idx,
                    key=f"{key_prefix}_font",
                )
            with col_b:
                uppercase = st.checkbox(
                    "WSZYSTKO UPPERCASE",
                    value=bool(current["uppercase"]),
                    key=f"{key_prefix}_upper",
                    help="Cala karuzela wielkimi literami — typowo TikTok hook style.",
                )

            # ─── Kolory + obrys ───
            st.markdown("**Kolor i obrys**")
            col_c, col_d = st.columns(2)
            with col_c:
                text_color = st.color_picker(
                    "Kolor tekstu",
                    value=current["text_color"],
                    key=f"{key_prefix}_text_color",
                )
            with col_d:
                stroke_color = st.color_picker(
                    "Kolor obrysu",
                    value=current["stroke_color"],
                    key=f"{key_prefix}_stroke_color",
                )
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
            position_keys = list(_POSITION_OPTIONS.keys())
            pos_idx = position_keys.index(current["position"]) if current["position"] in position_keys else 0
            position = st.selectbox(
                "Pozycja tekstu na slajdzie",
                options=position_keys,
                format_func=lambda k: _POSITION_OPTIONS[k],
                index=pos_idx,
                key=f"{key_prefix}_position",
            )
            length_keys = list(_LENGTH_OPTIONS.keys())
            len_idx = length_keys.index(current["text_length"]) if current["text_length"] in length_keys else 1
            text_length = st.selectbox(
                "Dlugosc tekstu (instrukcja dla AI)",
                options=length_keys,
                format_func=lambda k: _LENGTH_OPTIONS[k],
                index=len_idx,
                key=f"{key_prefix}_length",
                help="Wstrzykiwane do prompta copywritera. Krotsze = bardziej impactowe.",
            )
            smart_fitting = st.checkbox(
                "Smart fitting (auto-overlay + auto-pozycja)",
                value=bool(current["smart_fitting"]),
                key=f"{key_prefix}_smart",
                help=(
                    "Po wygenerowaniu obrazu analizuje tlo i dodaje subtelny gradient pod "
                    "tekstem GDY tlo jest jasne lub niespokojne. Plus: gdy pozycja=auto, "
                    "wybiera najmniej zatluszczona strefe na bazie edge density."
                ),
            )

        # ─── Aktualizacja stanu (poza kolumnami zeby preview tez to widzial) ───
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

        # ╔═════════════════ PRAWA KOLUMNA: LIVE PREVIEW ═════════════════╗
        with col_preview:
            st.markdown("**Podglad slajdu**")

            # Toggle: slajd 1 (hero) vs slajdy 2+ (rest)
            preview_slide_key = f"{key_prefix}_preview_idx"
            if preview_slide_key not in st.session_state:
                st.session_state[preview_slide_key] = 0
            preview_slide = st.radio(
                "Ktory slajd?",
                options=[0, 1],
                format_func=lambda i: "Slajd 1 (hero)" if i == 0 else "Slajdy 2+",
                horizontal=True,
                key=preview_slide_key,
                label_visibility="collapsed",
            )

            # Generuj preview obraz live
            try:
                preview_img = _build_preview_image(new_settings, preview_slide)
                buf = io.BytesIO()
                preview_img.save(buf, "JPEG", quality=85)
                buf.seek(0)
                st.image(buf, use_container_width=True,
                         caption=f"Format slajdu: 1080×1350 (4:5)")
            except Exception as _e:
                st.warning(f"Preview niedostepny: {_e}")

            st.caption(
                "🟡 Zolte kropkowane linie = strefy bezpieczne (UI TikTok/IG zaslania tekst poza nimi). "
                "Tekst zawsze trzyma sie srodkowych ~57% wysokosci."
            )

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
