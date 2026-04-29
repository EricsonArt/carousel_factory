"""
Zakladka ICP (Ideal Customer Profile) — AI auto-uzupelnia profil klienta.
"""
import streamlit as st

from db import get_brief, upsert_brief, get_brand
from core.icp_filler import auto_fill_icp
from ui.theme import page_header, section_title


def render_icp(brand_id: str):
    page_header(
        "ICP — Ideal Customer Profile",
        "Kim dokładnie jest Twój klient? AI używa tego do tonu, języka i hooków w slajdach.",
        icon="🎯",
    )

    brief = get_brief(brand_id) or {}
    brand = get_brand(brand_id) or {}

    has_icp = bool(brief.get("icp_summary") or brief.get("avatars"))

    # ── AI auto-fill ──────────────────────────────────────────────────
    with st.expander(
        "🤖 Niech AI uzupełni za mnie" if not has_icp else "🤖 AI auto-fill (przepisze ICP)",
        expanded=not has_icp,
    ):
        st.caption(
            "Opisz krótko kto kupuje Twój produkt. AI zaglębi się w głowę klienta, "
            "wygeneruje awatary z pain pointami, językiem klienta i kanałami gdzie ich znajdziesz."
        )

        with st.form("ai_fill_icp"):
            customer_desc = st.text_area(
                "Opis klienta (1-3 zdania)",
                placeholder=(
                    "np. 'kobiety 30-45 lat, mamy małych dzieci, próbowały już wielu diet, "
                    "frustrują się brakiem czasu i brakiem efektów; pracują zazwyczaj w korpo "
                    "lub na macierzyńskim'"
                ),
                height=110,
            )
            extra_ctx = st.text_input(
                "Dodatkowy kontekst (opc.)",
                placeholder="np. komentarze pod postami, wyniki ankiet, opinie",
            )
            submitted_ai = st.form_submit_button(
                "🤖 Uzupełnij za mnie", type="primary", use_container_width=True
            )

        if submitted_ai:
            if not customer_desc.strip():
                st.error("Wpisz krótki opis klienta — AI musi mieć z czego korzystać.")
            else:
                try:
                    with st.spinner("AI buduje ICP — analizuje pain pointy, język, kanały..."):
                        filled = auto_fill_icp(
                            brand_name=brand.get("name", ""),
                            niche=brand.get("niche", ""),
                            product_description=((brief.get("product") or "") + " — " + (brief.get("main_promise") or "")).strip(" —"),
                            customer_description=customer_desc,
                            extra_context=extra_ctx,
                        )
                    update_payload = {
                        "icp_summary": filled.get("icp_summary", ""),
                        "avatars": filled.get("avatars", []),
                        "icp_channels": filled.get("channels", []),
                        "anti_avatar": filled.get("anti_avatar", ""),
                    }
                    upsert_brief(brand_id, update_payload)
                    st.success("✅ ICP gotowy — poniżej pełny profil. Edytuj co chcesz.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Błąd AI: {e}")
                    st.exception(e)

    st.markdown("<hr>", unsafe_allow_html=True)

    if not has_icp:
        st.info("Po wygenerowaniu ICP przez AI tutaj pojawi się edytowalny profil klienta.")
        return

    # ── Edycja ICP ─────────────────────────────────────────────────────
    section_title("Streszczenie ICP", icon="📝")
    icp_summary = st.text_area(
        "icp_summary",
        value=brief.get("icp_summary") or "",
        height=90,
        label_visibility="collapsed",
    )

    avatars = brief.get("avatars") or []
    if not isinstance(avatars, list):
        avatars = []

    section_title(f"Awatary ({len(avatars)})", icon="👥")
    edited_avatars = []
    for i, av in enumerate(avatars):
        if not isinstance(av, dict):
            continue
        with st.expander(f"👤 {av.get('name') or f'Awatar {i+1}'}", expanded=(i == 0)):
            name = st.text_input("Imię + krótki opis", value=av.get("name", ""), key=f"av_name_{i}")
            demo = st.text_input("Demografia", value=av.get("demographics", ""), key=f"av_demo_{i}")
            pains = st.text_area(
                "Pain points (jeden na linię)",
                value="\n".join(av.get("pain_points") or []),
                height=120, key=f"av_pains_{i}",
            )
            struggles = st.text_area(
                "Codzienne irytacje",
                value="\n".join(av.get("daily_struggles") or []),
                height=90, key=f"av_strug_{i}",
            )
            dream = st.text_area(
                "Dream outcome (idealny stan po zakupie)",
                value=av.get("dream_outcome", ""),
                height=70, key=f"av_dream_{i}",
            )
            phrases = st.text_area(
                "Język klienta — dokładne zwroty (jeden na linię)",
                value="\n".join(av.get("language_phrases") or []),
                height=110, key=f"av_phrases_{i}",
                help="Te dokładne słowa AI wstawi w hooki i body slajdów.",
            )
            objections = st.text_area(
                "Obiekcje przed zakupem",
                value="\n".join(av.get("objections") or []),
                height=90, key=f"av_obj_{i}",
            )
            triggers = st.text_area(
                "Buying triggers (co popycha do kupna)",
                value="\n".join(av.get("buying_triggers") or []),
                height=90, key=f"av_trig_{i}",
            )

            edited_avatars.append({
                "name": name.strip(),
                "demographics": demo.strip(),
                "pain_points": [x.strip() for x in pains.splitlines() if x.strip()],
                "daily_struggles": [x.strip() for x in struggles.splitlines() if x.strip()],
                "dream_outcome": dream.strip(),
                "language_phrases": [x.strip() for x in phrases.splitlines() if x.strip()],
                "objections": [x.strip() for x in objections.splitlines() if x.strip()],
                "buying_triggers": [x.strip() for x in triggers.splitlines() if x.strip()],
            })

    section_title("Kanały — gdzie znaleźć klienta online", icon="📡")
    channels_str = "\n".join(brief.get("icp_channels") or [])
    channels_text = st.text_area(
        "channels",
        value=channels_str,
        height=130,
        label_visibility="collapsed",
        help="Konkretne IG/TikTok konta, subreddity, podcasty, blogi, FB grupy.",
    )

    section_title("Anty-awatar (KTO NIE jest klientem)", icon="🚫")
    anti_text = st.text_area(
        "anti_avatar",
        value=brief.get("anti_avatar") or "",
        height=80,
        label_visibility="collapsed",
    )

    if st.button("💾 Zapisz zmiany", type="primary", use_container_width=True):
        upsert_brief(brand_id, {
            "icp_summary": icp_summary.strip(),
            "avatars": edited_avatars,
            "icp_channels": [c.strip() for c in channels_text.splitlines() if c.strip()],
            "anti_avatar": anti_text.strip(),
        })
        st.success("✅ Zapisano.")
        st.rerun()
