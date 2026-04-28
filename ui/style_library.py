"""
Style Library — upload zdjęć referencyjnych + linków IG/TT, ekstrakcja stylu przez AI Vision.
Phase 1: tylko upload plików (URL scraping w Phase 2 z Apify).
"""
import json
from pathlib import Path

import streamlit as st

from config import STYLES_DIR
from core.style_extractor import extract_style_profile
from core.utils import generate_id, ensure_dir
from db import create_style, list_styles, get_style, update_style, delete_style
from ui.theme import page_header, section_title, empty_state


def render_style_library(brand_id: str):
    page_header(
        "Biblioteka stylów",
        "Wgraj zdjęcia z viralowych karuzel — AI wyciąga paletę, typografię i hook patterns.",
        icon="🎨",
    )

    styles = list_styles(brand_id)

    if styles:
        section_title(f"Twoje style ({len(styles)})", icon="🖼️")

        for style in styles:
            _render_style_card(style)

        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
    else:
        empty_state(
            "🎨",
            "Brak stylów",
            "Dodaj pierwszy styl poniżej — wgraj 5-10 zdjęć z karuzel które Ci się podobają.",
        )
        st.markdown('<div style="margin-top:1.5rem;"></div>', unsafe_allow_html=True)

    st.markdown('<hr>', unsafe_allow_html=True)
    _render_add_style_form(brand_id)


def _render_style_card(style: dict):
    is_preferred = style.get("is_preferred")
    star = "⭐ " if is_preferred else ""

    with st.expander(f"{star}{style['name']}", expanded=False):
        col_info, col_actions = st.columns([4, 1])

        with col_info:
            summary = style.get("extracted_summary", "")
            if summary:
                st.markdown(f"""
                <div style="color:#0F172A;font-size:0.88rem;line-height:1.7;
                            margin-bottom:1rem;">{summary[:350]}{'...' if len(summary) > 350 else ''}</div>
                """, unsafe_allow_html=True)

            # Mood / typography hints
            mood = style.get("mood", "")
            if mood:
                st.markdown(f'<div style="font-size:0.8rem;color:#64748B;margin-bottom:0.75rem;"><strong>Klimat:</strong> {mood}</div>',
                            unsafe_allow_html=True)

            # Color palette
            palette = style.get("palette") or []
            if palette:
                section_title("Paleta kolorów")
                palette_html = ""
                for color in palette[:8]:
                    palette_html += f"""
                    <div style="display:inline-block;text-align:center;margin-right:0.5rem;margin-bottom:0.5rem;">
                        <div style="width:44px;height:44px;background:{color};border-radius:10px;
                                    border:1px solid rgba(0,0,0,0.08);box-shadow:0 2px 6px rgba(0,0,0,0.1);"></div>
                        <div style="font-size:0.62rem;color:#64748B;margin-top:0.3rem;font-family:monospace;">{color}</div>
                    </div>
                    """
                st.markdown(f'<div style="margin:0.5rem 0 1rem;">{palette_html}</div>', unsafe_allow_html=True)

            # Reference images
            refs = style.get("reference_image_paths") or []
            if refs:
                section_title(f"Zdjęcia referencyjne ({len(refs)})")
                ref_cols = st.columns(min(len(refs), 5))
                for i, ref in enumerate(refs[:5]):
                    with ref_cols[i]:
                        if Path(ref).exists():
                            st.image(ref, use_container_width=True)

        with col_actions:
            st.markdown('<div style="padding-top:0.25rem;"></div>', unsafe_allow_html=True)

            if not is_preferred:
                if st.button("⭐ Preferowany", key=f"prefer_{style['id']}", use_container_width=True):
                    for s in list_styles(style["brand_id"]):
                        update_style(s["id"], is_preferred=0)
                    update_style(style["id"], is_preferred=1)
                    st.rerun()
            else:
                st.markdown("""
                <div style="background:#D1FAE5;color:#059669;border-radius:8px;padding:0.4rem 0.6rem;
                            font-size:0.75rem;font-weight:700;text-align:center;">✓ Preferowany</div>
                """, unsafe_allow_html=True)

            st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)

            if st.button("🗑️ Usuń", key=f"del_{style['id']}", use_container_width=True):
                delete_style(style["id"])
                st.rerun()

            if st.button("{ } JSON", key=f"json_{style['id']}", use_container_width=True):
                st.json(style)


def _render_add_style_form(brand_id: str):
    section_title("Dodaj nowy styl", icon="➕")

    with st.form(f"add_style_{brand_id}", clear_on_submit=False):
        name = st.text_input(
            "Nazwa stylu",
            placeholder="np. 'Pastelowy minimal' albo 'Brutalist neon'",
        )

        uploaded_files = st.file_uploader(
            "Wgraj zdjęcia (zalecane 5-10, max 10)",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="Screenshoty lub zapisane obrazy z karuzel które reprezentują styl. Im więcej — tym lepiej.",
        )

        urls_text = st.text_area(
            "Linki TikTok / Instagram (opcjonalnie — Phase 2)",
            placeholder="https://www.tiktok.com/@user/video/123\nhttps://www.instagram.com/p/abc/",
            help="W Phase 2 system pobierze zdjęcia automatycznie przez Apify. Teraz tylko upload plików.",
        )

        extra_context = st.text_input(
            "Dodatkowy kontekst dla AI (opcjonalnie)",
            placeholder="np. 'to styl Pawła Tkaczyka' lub 'minimalistyczny wellness'",
        )

        submitted = st.form_submit_button("🤖 Analizuj styl przez AI", type="primary", use_container_width=True)

    if submitted:
        if not name:
            st.error("Podaj nazwę stylu.")
            return
        if not uploaded_files and not urls_text.strip():
            st.error("Wgraj co najmniej 3 zdjęcia (lub w Phase 2 podaj linki TT/IG).")
            return
        if uploaded_files and len(uploaded_files) < 3:
            st.warning("Zalecamy co najmniej 5 zdjęć — z mniejszej liczby AI będzie zgadywać.")

        _process_new_style(brand_id, name, uploaded_files, urls_text, extra_context)


def _process_new_style(brand_id: str, name: str, uploaded_files, urls_text: str, extra_context: str):
    style_id = generate_id("sty")
    style_dir = STYLES_DIR / brand_id / style_id
    ensure_dir(style_dir)

    saved_paths = []
    for i, f in enumerate(uploaded_files or []):
        ext = Path(f.name).suffix or ".png"
        p = style_dir / f"ref_{i+1:02d}{ext}"
        p.write_bytes(f.getbuffer())
        saved_paths.append(str(p))

    urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
    if urls:
        st.info(f"Phase 1: pobieranie z URL-i jeszcze niedostępne ({len(urls)} URL-i pominięte). "
                f"Zapisz screenshoty i wgraj ręcznie — Phase 2 to zautomatyzuje.")

    if not saved_paths:
        st.error("Brak zdjęć do analizy.")
        return

    try:
        progress = st.progress(0.0, text=f"Analizuję {len(saved_paths)} zdjęć przez AI Vision...")

        profile = extract_style_profile(saved_paths, extra_context=extra_context)
        progress.progress(0.8, text="Zapisuję profil...")

        profile["reference_image_paths"] = saved_paths
        create_style(style_id, brand_id, name, profile)

        progress.progress(1.0, text="Gotowe!")

        st.success(f"Styl **{name}** utworzony! Możesz teraz generować karuzele w tym stylu.")
        st.balloons()
        st.rerun()

    except Exception as e:
        st.error(f"Błąd analizy stylu: {e}")
