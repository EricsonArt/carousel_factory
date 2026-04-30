"""
Onboarding Wizard — AI prowadzi rozmowę po polsku żeby wypełnić Brand Brief.
AI sam dopisuje research gdy użytkownik odpowiada krótko.
"""
import json
import streamlit as st

from config import PROMPTS_DIR
from core.llm import call_claude_json, call_claude
from db import get_brand, upsert_brief, get_brief, update_brand
from ui.theme import page_header, section_title, badge


SECTIONS = [
    ("product",          "Produkt",          "Co dokładnie sprzedajesz?",                       "📦"),
    ("offer",            "Oferta",           "Cena, format płatności, bonusy, gwarancja",       "💰"),
    ("avatars",          "Awatar klienta",   "Do kogo to sprzedajesz? Im konkretniej tym lepiej","👤"),
    ("voice_tone",       "Głos marki",       "Jak marka się komunikuje?",                       "🎙️"),
    ("usps",             "USPs",             "Co odróżnia Twój produkt od konkurencji?",        "⚡"),
    ("social_proof",     "Social proof",     "Liczby, opinie, certyfikaty, znane osoby",        "⭐"),
    ("guarantees",       "Gwarancje",        "Co gwarantujesz klientowi?",                      "🛡️"),
    ("objections",       "Obiekcje",         "Powody dla których klient NIE kupuje",            "🤔"),
    ("cta_url",          "Link CTA",         "Link do strony oferty/sklepu (użyty w karuzelach)","🔗"),
    ("forbidden_claims", "Zakazane claims",  "Czego marka NIE może obiecywać",                 "🚫"),
]


def _load_wizard_prompt() -> str:
    return (PROMPTS_DIR / "brief_wizard.md").read_text(encoding="utf-8")


def render_onboarding(brand_id: str):
    brand = get_brand(brand_id)
    if not brand:
        st.error("Nie znaleziono marki.")
        return

    page_header(
        "Brief marki",
        "AI zadaje pytania i sam uzupełnia research — Ty tylko zatwierdzasz.",
        icon="🧠",
    )

    brief = get_brief(brand_id) or {}
    completion = brand.get("brief_completion", 0.0)
    pct = int(completion * 100)
    completed_sections = sum(1 for s in SECTIONS if brief.get(s[0]))

    # Progress overview
    col1, col2, col3 = st.columns(3)
    with col1:
        color = "#10B981" if pct >= 80 else "#F59E0B" if pct >= 40 else "#EF4444"
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
            <div style="font-size:2rem;font-weight:900;color:{color};">{pct}%</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.2rem;">Ukończony</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
            <div style="font-size:2rem;font-weight:900;color:#7C3AED;">{completed_sections}/{len(SECTIONS)}</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.2rem;">Sekcji</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        remaining = len(SECTIONS) - completed_sections
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
            <div style="font-size:2rem;font-weight:900;color:{'#94A3B8' if remaining == 0 else '#F59E0B'};">{remaining}</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.2rem;">Do uzupełnienia</div>
        </div>
        """, unsafe_allow_html=True)

    st.progress(completion)
    st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)

    # ─────────────── Framework copywritera (per-marka) ───────────────
    _render_framework_picker(brand_id, brief)

    # Section picker as visual grid
    section_title("Wybierz sekcję do wypełnienia", icon="📋")

    # Build section overview
    section_labels = []
    for key, name, hint, icon in SECTIONS:
        done = bool(brief.get(key))
        indicator = "✓" if done else "○"
        section_labels.append(f"{indicator} {icon} {name}")

    selected_idx = st.selectbox(
        "Sekcja",
        range(len(SECTIONS)),
        format_func=lambda i: section_labels[i],
        key=f"section_select_{brand_id}",
        label_visibility="collapsed",
    )

    section_key, section_name, section_hint, section_icon = SECTIONS[selected_idx]
    is_done = bool(brief.get(section_key))

    # Section card
    badge_html = (f'<span style="background:#D1FAE5;color:#059669;padding:2px 10px;border-radius:999px;'
                  f'font-size:0.72rem;font-weight:700;margin-left:0.5rem;">✓ Uzupełnione</span>') if is_done else ""

    st.markdown(f"""
    <div style="background:white;border:1px solid #E2E8F0;border-radius:16px;
                padding:1.5rem;margin:1rem 0;box-shadow:0 1px 6px rgba(0,0,0,0.05);">
        <div style="font-size:1.1rem;font-weight:800;color:#0F172A;margin-bottom:0.4rem;">
            {section_icon} {section_name} {badge_html}
        </div>
        <div style="color:#64748B;font-size:0.88rem;">{section_hint}</div>
    </div>
    """, unsafe_allow_html=True)

    # Show current value
    current_value = brief.get(section_key)
    if current_value:
        with st.expander("📄 Aktualna wartość (kliknij żeby zobaczyć)", expanded=False):
            if isinstance(current_value, (dict, list)):
                st.json(current_value)
            else:
                st.write(current_value)

    user_input = st.text_area(
        "Twoja odpowiedź",
        height=110,
        key=f"input_{brand_id}_{section_key}",
        placeholder=f"Napisz krótko — AI rozbuduje o research. Np. '{section_hint}'",
    )

    col_ai, col_save = st.columns([2, 1])
    with col_ai:
        if st.button("🤖 Zapytaj AI — niech uzupełni", type="primary", use_container_width=True):
            if user_input.strip():
                _ai_research_section(brand, section_key, section_name, user_input, brief)
            else:
                st.warning("Wpisz cokolwiek — choćby jedno słowo — AI resztę dopisze.")

    with col_save:
        if st.button("💾 Zapisz bez AI", use_container_width=True):
            _save_section_raw(brand_id, section_key, user_input)
            st.success("Zapisano!")
            st.rerun()

    # AI Proposal display
    proposal_key = f"ai_proposal_{brand_id}_{section_key}"
    if proposal_key in st.session_state:
        _render_ai_proposal(brand_id, section_key, st.session_state[proposal_key])


def _ai_research_section(brand: dict, section_key: str, section_name: str,
                          user_input: str, current_brief: dict):
    system_prompt = _load_wizard_prompt()

    prompt = f"""Marka: {brand['name']} ({brand.get('niche', '')})
Sekcja do wypełnienia: {section_name} (klucz: {section_key})

Co user wpisał jako odpowiedź: "{user_input}"

Aktualny brief (użyj kontekstu jeżeli pomocny):
{json.dumps({k: v for k, v in current_brief.items() if v}, ensure_ascii=False, indent=2)}

ZADANIE:
1. Zinterpretuj odpowiedź usera
2. Rozbuduj ją o KONKRETY i research z Twojej wiedzy o tej niszy
3. Zwróć gotowy proposal — wartość do zapisu w briefie

Format wyjścia (JSON):
{{
  "ai_message": "<komentarz dla user'a po polsku, max 3 zdania — co dopisałeś i dlaczego>",
  "proposed_value": <wartość gotowa do zapisu — dla 'product' string, dla 'avatars' lista dict, dla 'usps' lista string itp.>,
  "follow_up_questions": ["<opcjonalne pytanie pomocnicze, max 2>"]
}}

Zwróć TYLKO JSON.
"""

    try:
        with st.spinner("AI buduje propozycję..."):
            result = call_claude_json(prompt, system=system_prompt, max_tokens=2500)
        st.session_state[f"ai_proposal_{brand['id']}_{section_key}"] = result
        st.rerun()
    except Exception as e:
        st.error(f"Błąd AI: {e}")


def _render_ai_proposal(brand_id: str, section_key: str, proposal: dict):
    st.markdown('<hr>', unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#F5F3FF,#EDE9FE);border:1px solid #DDD6FE;
                border-radius:16px;padding:1.25rem 1.5rem;margin-bottom:1rem;">
        <div style="font-size:0.75rem;font-weight:700;color:#7C3AED;text-transform:uppercase;
                    letter-spacing:0.1em;margin-bottom:0.5rem;">✨ Propozycja AI</div>
        <div style="color:#0F172A;font-size:0.9rem;line-height:1.6;">{proposal.get('ai_message', '')}</div>
    </div>
    """, unsafe_allow_html=True)

    proposed = proposal.get("proposed_value")

    if isinstance(proposed, (dict, list)):
        edited_str = st.text_area(
            "Edytuj propozycję (JSON)",
            value=json.dumps(proposed, ensure_ascii=False, indent=2),
            height=280,
            key=f"edit_{brand_id}_{section_key}",
        )
        try:
            edited = json.loads(edited_str)
        except Exception:
            st.error("JSON jest niepoprawny — popraw przed zapisem.")
            edited = proposed
    else:
        edited = st.text_area(
            "Edytuj propozycję",
            value=str(proposed) if proposed else "",
            height=180,
            key=f"edit_{brand_id}_{section_key}",
        )

    questions = proposal.get("follow_up_questions") or []
    if questions:
        with st.expander("💡 AI ma pytania pomocnicze"):
            for q in questions:
                st.markdown(f"- {q}")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("✅ Zapisz propozycję", type="primary", key=f"save_{brand_id}_{section_key}",
                      use_container_width=True):
            _save_section(brand_id, section_key, edited)
            del st.session_state[f"ai_proposal_{brand_id}_{section_key}"]
            st.success("Zapisano!")
            st.rerun()

    with col_b:
        if st.button("🔄 Inna propozycja", key=f"regen_{brand_id}_{section_key}",
                      use_container_width=True):
            del st.session_state[f"ai_proposal_{brand_id}_{section_key}"]
            st.rerun()

    with col_c:
        if st.button("✕ Anuluj", key=f"cancel_{brand_id}_{section_key}",
                      use_container_width=True):
            del st.session_state[f"ai_proposal_{brand_id}_{section_key}"]
            st.rerun()


def _save_section(brand_id: str, key: str, value):
    if key == "price":
        try:
            value = float(value)
        except (ValueError, TypeError):
            value = 0.0
    elif key in ("usps", "objections", "guarantees", "social_proof",
                  "forbidden_claims", "avatars"):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = [line.strip() for line in value.splitlines() if line.strip()]
    upsert_brief(brand_id, {key: value})


def _save_section_raw(brand_id: str, key: str, value: str):
    if key in ("usps", "objections", "guarantees", "social_proof", "forbidden_claims"):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    elif key == "avatars":
        value = [{"name": "Awatar 1", "raw_description": value}]
    elif key == "price":
        try:
            value = float(value)
        except Exception:
            value = 0.0
    upsert_brief(brand_id, {key: value})


# ─────────────────────────────────────────────────────────────
# FRAMEWORK COPYWRITERA (per-marka)
# ─────────────────────────────────────────────────────────────

FRAMEWORK_OPTIONS = {
    "default": {
        "label": "Default — uniwersalna struktura",
        "desc": "Klasyczny hook + body + CTA. Pasuje do większości marek: e-commerce produktów fizycznych, "
                "lifestyle, edukacja, B2B, marki korporacyjne. Krótki caption (300-500 znaków), "
                "CTA prowadzi do `cta_url` z briefa.",
    },
    "viral_loop": {
        "label": "Viral Loop — agresywna 9-funkcyjna struktura",
        "desc": "Hook paradoksalny (8 wersji wewnętrznie, top-1 + 3 alternatywy) → personal callout → "
                "open loop story → pain z 3 faktami → pattern interrupt → solution jako koncept (bez "
                "nazwy produktu) → social proof → cliffhanger ze strzałką do opisu → CTA z wyborem "
                "i słowem-trigger w komentarzu. Caption 5-sekcyjny z P.S. anticipated regret. "
                "Dla: info-produkty, kursy, coaching, reselling, SaaS z lead magnetem, personal brand. "
                "NIE dla: e-commerce produktów fizycznych, B2B enterprise, lifestyle afirmatywny.",
    },
}


def _render_framework_picker(brand_id: str, brief: dict):
    current = brief.get("copy_framework") or "default"
    if current not in FRAMEWORK_OPTIONS:
        current = "default"

    keys = list(FRAMEWORK_OPTIONS.keys())
    selected = st.selectbox(
        "🎯 Framework copywritera",
        options=keys,
        index=keys.index(current),
        format_func=lambda k: FRAMEWORK_OPTIONS[k]["label"],
        key=f"framework_{brand_id}",
        help="Określa strukturę psychologiczną generowanych karuzel. Default działa dla większości marek; "
             "Viral Loop to bardziej agresywna struktura dedykowana info-produktom i lead magnetom.",
    )

    st.markdown(f"""
    <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
                padding:0.85rem 1.1rem;margin:0.4rem 0 1.2rem;font-size:0.82rem;
                color:#475569;line-height:1.55;">
        {FRAMEWORK_OPTIONS[selected]["desc"]}
    </div>
    """, unsafe_allow_html=True)

    if selected != current:
        upsert_brief(brand_id, {"copy_framework": selected})
        st.success(f"Framework zmieniony na: {FRAMEWORK_OPTIONS[selected]['label']}")
        st.rerun()
