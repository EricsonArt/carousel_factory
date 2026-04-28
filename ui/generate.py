"""
Generator karuzel — manualne wygenerowanie karuzeli z podanym tematem.
Phase 1: brak auto-postingu, tylko ZIP do pobrania.
"""
from pathlib import Path

import streamlit as st

from core.carousel_generator import generate_carousel, export_carousel_as_zip
from db import get_brand, get_brief, list_styles
from config import DEFAULT_SLIDES, MIN_SLIDES, MAX_SLIDES
from ui.theme import page_header, section_title, empty_state


def render_generate(brand_id: str):
    page_header(
        "Generator karuzel",
        "Wpisz temat, wybierz styl — AI tworzy gotowe slajdy w ~60 sekund.",
        icon="🎠",
    )

    brand = get_brand(brand_id)
    brief = get_brief(brand_id) or {}
    completion = brand.get("brief_completion", 0.0)
    pct = int(completion * 100)

    styles = list_styles(brand_id)

    handles = brand.get("social_handles") or {}
    ig_handle = (handles.get("ig") or "").strip()
    tt_handle = (handles.get("tiktok") or "").strip()

    # Status row
    status_items = [
        ("Brief", f"{pct}%", "🧠", "#7C3AED" if pct >= 80 else "#F59E0B"),
        ("Style", str(len(styles)), "🎨", "#7C3AED" if styles else "#94A3B8"),
        ("Gotowość", "OK" if pct >= 50 and styles else "Uzupełnij", "✅" if pct >= 50 and styles else "⚠️",
         "#10B981" if pct >= 50 and styles else "#F59E0B"),
    ]
    cols = st.columns(3)
    for col, (label, val, icon, color) in zip(cols, status_items):
        with col:
            st.markdown(f"""
            <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                        padding:1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
                <div style="font-size:1.5rem;">{icon}</div>
                <div style="font-size:1.3rem;font-weight:800;color:{color};line-height:1.2;margin-top:0.25rem;">{val}</div>
                <div style="font-size:0.7rem;font-weight:600;color:#64748B;text-transform:uppercase;
                            letter-spacing:0.07em;margin-top:0.2rem;">{label}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)

    if pct < 50:
        st.warning(f"Brief uzupełniony tylko w {pct}% — uzupełnij go w zakładce **Brief marki** dla lepszych wyników.")

    if not styles:
        st.info("Nie masz jeszcze stylu — AI użyje stylu generycznego. Dodaj własne zdjęcia referencyjne w zakładce **Style**.")

    st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)

    # Generation form
    section_title("Parametry generacji", icon="⚙️")

    with st.form("generate_carousel"):
        topic = st.text_area(
            "Temat karuzeli",
            placeholder=(
                "np. '3 błędy które niszczą dietę keto'\n"
                "'Dlaczego nie chudniesz mimo diety'\n"
                "'Jak zacząć keto w 7 dni bez efektu jojo'"
            ),
            height=110,
            help="Im bardziej konkretny i wiralowy temat, tym lepsza karuzela."
        )

        col1, col2 = st.columns(2)
        with col1:
            slide_count = st.slider(
                "Liczba slajdów",
                MIN_SLIDES, MAX_SLIDES, DEFAULT_SLIDES,
                help="7-9 slajdów to optimum dla IG/TikTok karuzel."
            )
        with col2:
            if styles:
                style_options = {None: "— brak stylu (generyczny) —"}
                preferred_id = None
                for s in styles:
                    label = s["name"] + ("  ⭐ preferowany" if s.get("is_preferred") else "")
                    style_options[s["id"]] = label
                    if s.get("is_preferred"):
                        preferred_id = s["id"]

                default_idx = list(style_options.keys()).index(preferred_id) if preferred_id else 0
                style_id = st.selectbox(
                    "Styl wizualny",
                    options=list(style_options.keys()),
                    format_func=lambda k: style_options[k],
                    index=default_idx,
                )
            else:
                style_id = None
                st.markdown('<div style="padding-top:1.7rem;"></div>', unsafe_allow_html=True)
                st.info("Brak stylów")

        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.78rem;font-weight:700;color:#475569;'
            'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.4rem;">'
            'Publikuj na</div>',
            unsafe_allow_html=True,
        )
        col_ig, col_tt = st.columns(2)
        with col_ig:
            ig_label = f"📷 Instagram  ({ig_handle})" if ig_handle else "📷 Instagram  (brak handle)"
            publish_ig = st.checkbox(ig_label, value=bool(ig_handle), disabled=not ig_handle, key="pub_ig")
        with col_tt:
            tt_label = f"🎵 TikTok  ({tt_handle})" if tt_handle else "🎵 TikTok  (brak handle)"
            publish_tt = st.checkbox(tt_label, value=bool(tt_handle), disabled=not tt_handle, key="pub_tt")

        if not ig_handle and not tt_handle:
            st.caption("ℹ️ Dodaj handle IG/TikTok w ustawieniach marki, żeby zaznaczyć platformy publikacji.")

        submitted = st.form_submit_button("🎠 Generuj karuzelę", type="primary", use_container_width=True)

    if submitted:
        if not topic.strip():
            st.error("Wpisz temat karuzeli przed generowaniem.")
            return

        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
        progress_bar = st.progress(0.0, text="Inicjalizacja...")

        def on_progress(stage: str, pct: float):
            progress_bar.progress(pct, text=stage)

        try:
            carousel = generate_carousel(
                brand_id=brand_id,
                topic=topic,
                style_id=style_id,
                slide_count=slide_count,
                progress_callback=on_progress,
            )
            progress_bar.progress(1.0, text="Gotowe!")
            targets = []
            if publish_ig:
                targets.append(f"IG {ig_handle}")
            if publish_tt:
                targets.append(f"TikTok {tt_handle}")
            if targets:
                st.success(f"Karuzela wygenerowana! Cel publikacji: {' + '.join(targets)}")
            else:
                st.success("Karuzela wygenerowana pomyślnie!")
            _show_carousel_preview(carousel)
        except ValueError as e:
            st.error(f"Walidacja zablokowała generację: {e}")
        except Exception as e:
            st.error(f"Błąd generacji: {e}")
            st.exception(e)


def _show_carousel_preview(carousel: dict):
    st.markdown('<hr>', unsafe_allow_html=True)

    section_title("Podgląd slajdów", icon="🖼️")

    slides = carousel.get("slides", [])
    if slides:
        cols = st.columns(min(len(slides), 4))
        for i, slide in enumerate(slides):
            with cols[i % len(cols)]:
                if slide.get("image_path"):
                    try:
                        st.image(slide["image_path"], use_container_width=True)
                    except Exception:
                        st.markdown(f"""
                        <div style="background:#F5F3FF;border:1px dashed #DDD6FE;border-radius:10px;
                                    padding:2rem;text-align:center;color:#8B5CF6;font-size:0.8rem;">
                            Slajd {i+1}
                        </div>
                        """, unsafe_allow_html=True)
                st.markdown(f"""
                <div style="padding:0.4rem 0;">
                    <div style="font-size:0.8rem;font-weight:700;color:#0F172A;line-height:1.4;">
                        {slide.get('headline', '')[:60]}
                    </div>
                    {'<div style="font-size:0.72rem;color:#64748B;margin-top:0.2rem;">' + slide.get('body', '')[:80] + '...</div>' if slide.get('body') else ''}
                </div>
                """, unsafe_allow_html=True)

    # Caption + hashtags
    section_title("Caption i hashtagi", icon="✍️")

    st.text_area(
        "Caption",
        value=carousel.get("caption", ""),
        height=130,
        key=f"cap_{carousel['id']}",
        help="Skopiuj i wklej bezpośrednio na Instagram/TikTok."
    )

    hashtags = carousel.get("hashtags") or []
    if hashtags:
        ht_str = "  ".join(hashtags)
        st.text_area(
            "Hashtagi",
            value=ht_str,
            height=60,
            key=f"ht_{carousel['id']}",
        )

    # Export - direct download_button (jednoklik, bez session_state issues)
    st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
    col_a, col_b = st.columns([1, 3])
    with col_a:
        try:
            zip_path = export_carousel_as_zip(carousel["id"])
            with open(zip_path, "rb") as f:
                zip_bytes = f.read()
            st.download_button(
                "⬇️ Pobierz ZIP",
                data=zip_bytes,
                file_name=f"karuzela_{carousel['id']}.zip",
                mime="application/zip",
                key=f"dl_{carousel['id']}",
                use_container_width=True,
                type="primary",
            )
        except Exception as e:
            st.error(f"Błąd eksportu ZIP: {e}")
