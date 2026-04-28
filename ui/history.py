"""
Historia wygenerowanych karuzel dla aktywnej marki.
"""
from pathlib import Path

import streamlit as st

from core.carousel_generator import export_carousel_as_zip
from db import list_carousels
from ui.theme import page_header, section_title, empty_state


_STATUS_COLORS = {
    "draft":     ("#EDE9FE", "#7C3AED"),
    "scheduled": ("#FFFBEB", "#D97706"),
    "posted":    ("#D1FAE5", "#059669"),
    "failed":    ("#FEF2F2", "#DC2626"),
}


def render_history(brand_id: str):
    page_header(
        "Historia karuzel",
        "Wszystkie wygenerowane karuzele — pobierz ZIP lub skopiuj caption.",
        icon="📜",
    )

    carousels = list_carousels(brand_id, limit=50)

    if not carousels:
        empty_state(
            "📭",
            "Brak karuzel",
            "Wygeneruj pierwszą w zakładce Generator — pojawi się tutaj.",
        )
        return

    total = len(carousels)
    posted = sum(1 for c in carousels if c.get("status") == "posted")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.1rem 1.5rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
            <div style="font-size:2rem;font-weight:900;color:#7C3AED;">{total}</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.2rem;">Łącznie karuzel</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.1rem 1.5rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
            <div style="font-size:2rem;font-weight:900;color:#10B981;">{posted}</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.2rem;">Opublikowanych</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:1.25rem;"></div>', unsafe_allow_html=True)
    section_title("Lista karuzel", icon="🗂️")

    for c in carousels:
        status = c.get("status", "draft")
        bg, fg = _STATUS_COLORS.get(status, ("#F1F5F9", "#64748B"))
        slides = c.get("slides") or []
        created = (c.get("created_at") or "")[:16].replace("T", " ")

        label = (
            f"{created}  ·  {len(slides)} slajdów  ·  "
            f"{'–' if not c.get('caption') else c['caption'][:40] + '...'}"
        )

        with st.expander(label, expanded=False):
            # Status badge + meta
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem;">
                <span style="background:{bg};color:{fg};padding:3px 12px;border-radius:999px;
                             font-size:0.73rem;font-weight:700;letter-spacing:0.05em;">{status.upper()}</span>
                <span style="color:#94A3B8;font-size:0.8rem;">{created}</span>
                <span style="color:#94A3B8;font-size:0.8rem;">·  {len(slides)} slajdów</span>
            </div>
            """, unsafe_allow_html=True)

            # Slide thumbnails
            if slides:
                thumb_cols = st.columns(min(len(slides), 5))
                for i, slide in enumerate(slides):
                    with thumb_cols[i % len(thumb_cols)]:
                        img_path = slide.get("image_path", "")
                        if img_path and Path(img_path).exists():
                            st.image(img_path, use_container_width=True)
                        else:
                            st.markdown(f"""
                            <div style="background:#F5F3FF;border:1px dashed #DDD6FE;border-radius:8px;
                                        aspect-ratio:4/5;display:flex;align-items:center;justify-content:center;
                                        color:#A78BFA;font-size:0.75rem;font-weight:600;">{i+1}</div>
                            """, unsafe_allow_html=True)
                        headline = (slide.get("headline") or "")[:35]
                        if headline:
                            st.markdown(f'<div style="font-size:0.7rem;color:#64748B;margin-top:0.2rem;line-height:1.3;">{headline}</div>',
                                        unsafe_allow_html=True)

            st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)

            # Caption
            if c.get("caption"):
                section_title("Caption")
                st.text_area(
                    "caption",
                    value=c["caption"],
                    height=100,
                    key=f"cap_hist_{c['id']}",
                    label_visibility="collapsed",
                )

            # Hashtags
            if c.get("hashtags"):
                section_title("Hashtagi")
                st.text_area(
                    "hashtagi",
                    value="  ".join(c["hashtags"]),
                    height=55,
                    key=f"ht_hist_{c['id']}",
                    label_visibility="collapsed",
                )

            # Actions
            col_a, col_b = st.columns([1, 4])
            with col_a:
                if st.button("📦 Eksport ZIP", key=f"zip_hist_{c['id']}", use_container_width=True):
                    try:
                        zip_path = export_carousel_as_zip(c["id"])
                        with open(zip_path, "rb") as f:
                            st.download_button(
                                "⬇️ Pobierz ZIP",
                                data=f.read(),
                                file_name=f"karuzela_{c['id']}.zip",
                                mime="application/zip",
                                key=f"dl_hist_{c['id']}",
                                use_container_width=True,
                            )
                    except Exception as e:
                        st.error(f"Błąd eksportu: {e}")
