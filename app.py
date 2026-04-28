"""
carousel_factory — Streamlit entry point.

Phase 1: Foundation + manual generation
  - Multi-brand sidebar
  - AI Brief Wizard
  - Style Library
  - Carousel Generator → ZIP export
"""
from pathlib import Path

import streamlit as st

from db import init_db, list_brands, create_brand, get_brand, get_brief, list_styles, get_today_total_cost
from core.utils import generate_id
from ui.auth import require_password
from ui.theme import inject_css, page_header, badge
from ui.onboarding import render_onboarding
from ui.style_library import render_style_library


st.set_page_config(
    page_title="KaruzelAI",
    page_icon="🎠",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

if not require_password():
    st.stop()

inject_css()


def _init_session():
    if "active_brand_id" not in st.session_state:
        brands = list_brands()
        st.session_state.active_brand_id = brands[0]["id"] if brands else None


_init_session()


# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    # Logo
    st.markdown("""
    <div style="padding:0.75rem 0 1.5rem;">
        <div style="font-size:1.5rem;font-weight:900;color:white;letter-spacing:-0.5px;line-height:1;">
            🎠 Karuzel<span style="background:linear-gradient(135deg,#A855F7,#F59E0B);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;">AI</span>
        </div>
        <div style="font-size:0.62rem;color:#5B21B6;text-transform:uppercase;letter-spacing:0.2em;
                    margin-top:0.35rem;font-weight:700;">Content Automation Studio</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<hr style="border-top:1px solid rgba(124,58,237,0.2);margin:0 0 1rem;">', unsafe_allow_html=True)

    brands = list_brands()

    if brands:
        # Brand switcher
        st.markdown('<div style="font-size:0.65rem;color:#5B21B6;text-transform:uppercase;letter-spacing:0.15em;font-weight:700;margin-bottom:0.4rem;">Aktywna marka</div>',
                    unsafe_allow_html=True)
        brand_options = {b["id"]: b["name"] for b in brands}
        selected = st.selectbox(
            "Aktywna marka",
            options=list(brand_options.keys()),
            format_func=lambda k: brand_options[k],
            index=list(brand_options.keys()).index(st.session_state.active_brand_id)
                  if st.session_state.active_brand_id in brand_options else 0,
            label_visibility="collapsed",
        )
        st.session_state.active_brand_id = selected

        active = get_brand(selected)
        niche = active.get("niche", "")
        completion = active.get("brief_completion", 0.0)
        pct = int(completion * 100)

        st.markdown(f"""
        <div style="background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.2);
                    border-radius:10px;padding:0.75rem 1rem;margin:0.6rem 0 0.2rem;">
            <div style="font-size:0.78rem;color:#C4B5FD;font-weight:500;margin-bottom:0.15rem;">
                {niche or "–"}
            </div>
            <div style="font-size:0.7rem;color:#7C3AED;font-weight:600;">Brief: {pct}% uzupełniony</div>
        </div>
        """, unsafe_allow_html=True)

        completion_col = "#7C3AED" if pct < 80 else "#10B981"
        st.progress(completion)
    else:
        st.markdown('<div style="color:#8B5CF6;font-size:0.88rem;padding:0.5rem 0;">Brak marek — dodaj pierwszą poniżej.</div>',
                    unsafe_allow_html=True)

    st.markdown('<hr style="border-top:1px solid rgba(124,58,237,0.15);margin:1rem 0;">', unsafe_allow_html=True)

    with st.expander("➕ Nowa marka"):
        with st.form("new_brand"):
            new_name = st.text_input("Nazwa marki", placeholder="np. KetoPro")
            new_niche = st.text_input("Nisza", placeholder="np. keto / odchudzanie")
            new_ig = st.text_input("Instagram handle", placeholder="@ketopro")
            new_tt = st.text_input("TikTok handle", placeholder="@ketopro_pl")

            if st.form_submit_button("Utwórz markę"):
                if new_name.strip():
                    bid = generate_id("brd")
                    create_brand(
                        brand_id=bid,
                        name=new_name.strip(),
                        niche=new_niche.strip(),
                        social_handles={"ig": new_ig.strip(), "tiktok": new_tt.strip()},
                    )
                    st.session_state.active_brand_id = bid
                    st.success(f"Utworzono: {new_name}")
                    st.rerun()
                else:
                    st.error("Podaj nazwę marki.")

    # Cost ticker at the bottom
    st.markdown('<hr style="border-top:1px solid rgba(124,58,237,0.15);margin:1rem 0 0.75rem;">', unsafe_allow_html=True)

    today_cost = get_today_total_cost()
    from config import DAILY_COST_CAP_USD
    cost_pct = min(today_cost / DAILY_COST_CAP_USD, 1.0) if DAILY_COST_CAP_USD else 0.0
    cost_color = "#EF4444" if cost_pct > 0.8 else "#F59E0B" if cost_pct > 0.5 else "#10B981"

    st.markdown(f"""
    <div style="padding:0.5rem 0 0.25rem;">
        <div style="font-size:0.62rem;color:#5B21B6;text-transform:uppercase;letter-spacing:0.15em;
                    font-weight:700;margin-bottom:0.4rem;">Koszt dziś</div>
        <div style="font-size:1.2rem;font-weight:800;color:{cost_color};">${today_cost:.2f}</div>
        <div style="font-size:0.72rem;color:#6D28D9;">limit: ${DAILY_COST_CAP_USD:.2f}/dzień</div>
    </div>
    """, unsafe_allow_html=True)
    st.progress(cost_pct)

    st.markdown("""
    <div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid rgba(124,58,237,0.1);">
        <div style="font-size:0.62rem;color:rgba(109,40,217,0.5);text-align:center;">Phase 1 · v0.1.0</div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# MAIN AREA — welcome screen when no brand
# ─────────────────────────────────────────────────────────────

if not st.session_state.active_brand_id:
    st.markdown("""
    <div style="max-width:640px;margin:8vh auto;text-align:center;padding:2rem 1rem;">
        <div style="font-size:4.5rem;margin-bottom:1.25rem;filter:drop-shadow(0 4px 20px rgba(124,58,237,0.3));">🎠</div>
        <h1 style="font-size:2.4rem;font-weight:900;color:#0F172A;letter-spacing:-1.5px;margin:0 0 1rem;">
            Witaj w <span style="background:linear-gradient(135deg,#7C3AED,#9333EA);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;">KaruzelAI</span>
        </h1>
        <p style="color:#64748B;font-size:1.05rem;margin:0 0 2.5rem;line-height:1.7;max-width:480px;margin-left:auto;margin-right:auto;">
            Twoja automatyczna maszyna do tworzenia wiralowych karuzel na Instagram i TikTok.
            Dodaj markę i zacznij generować.
        </p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;text-align:left;margin-bottom:2.5rem;">
            <div style="background:white;border:1px solid #E2E8F0;border-radius:16px;padding:1.5rem;box-shadow:0 1px 6px rgba(0,0,0,0.05);">
                <div style="font-size:1.75rem;margin-bottom:0.6rem;">🧠</div>
                <div style="font-weight:700;color:#0F172A;font-size:0.95rem;margin-bottom:0.3rem;">AI Onboarding</div>
                <div style="color:#64748B;font-size:0.82rem;line-height:1.6;">AI zadaje pytania po polsku i sam dopisuje research.</div>
            </div>
            <div style="background:white;border:1px solid #E2E8F0;border-radius:16px;padding:1.5rem;box-shadow:0 1px 6px rgba(0,0,0,0.05);">
                <div style="font-size:1.75rem;margin-bottom:0.6rem;">🎨</div>
                <div style="font-weight:700;color:#0F172A;font-size:0.95rem;margin-bottom:0.3rem;">Style Library</div>
                <div style="color:#64748B;font-size:0.82rem;line-height:1.6;">Wgraj zdjęcia — AI uczy się Twojego viralowego stylu.</div>
            </div>
            <div style="background:white;border:1px solid #E2E8F0;border-radius:16px;padding:1.5rem;box-shadow:0 1px 6px rgba(0,0,0,0.05);">
                <div style="font-size:1.75rem;margin-bottom:0.6rem;">🎠</div>
                <div style="font-weight:700;color:#0F172A;font-size:0.95rem;margin-bottom:0.3rem;">Generator</div>
                <div style="color:#64748B;font-size:0.82rem;line-height:1.6;">Jednym klikiem gotowa karuzela z obrazkami i opisem.</div>
            </div>
            <div style="background:white;border:1px solid #E2E8F0;border-radius:16px;padding:1.5rem;box-shadow:0 1px 6px rgba(0,0,0,0.05);">
                <div style="font-size:1.75rem;margin-bottom:0.6rem;">📦</div>
                <div style="font-weight:700;color:#0F172A;font-size:0.95rem;margin-bottom:0.3rem;">Export ZIP</div>
                <div style="color:#64748B;font-size:0.82rem;line-height:1.6;">Slajdy + opis + hashtagi gotowe do wrzucenia na social.</div>
            </div>
        </div>
        <p style="color:#94A3B8;font-size:0.85rem;">
            ← Kliknij <strong style="color:#7C3AED;">Nowa marka</strong> w panelu po lewej, żeby zacząć
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# ─────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────

active_brand = get_brand(st.session_state.active_brand_id)
brand_name = active_brand.get("name", "Marka")

st.markdown(f"""
<div style="margin-bottom:0.5rem;">
    <span style="font-size:0.75rem;font-weight:700;color:#7C3AED;text-transform:uppercase;letter-spacing:0.1em;">
        Aktywna marka
    </span>
    <span style="font-size:1.05rem;font-weight:800;color:#0F172A;margin-left:0.5rem;">{brand_name}</span>
</div>
""", unsafe_allow_html=True)

tab_brief, tab_styles, tab_generate, tab_history = st.tabs([
    "🧠  Brief marki",
    "🎨  Style",
    "🎠  Generator",
    "📜  Historia",
])

with tab_brief:
    render_onboarding(st.session_state.active_brand_id)

with tab_styles:
    render_style_library(st.session_state.active_brand_id)

with tab_generate:
    from ui.generate import render_generate
    render_generate(st.session_state.active_brand_id)

with tab_history:
    from ui.history import render_history
    render_history(st.session_state.active_brand_id)
