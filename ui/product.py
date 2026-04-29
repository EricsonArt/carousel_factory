"""
Zakładka "Produkt" — pola optymalizujące konwersję w karuzelach.
AI używa tych danych w slajdach CTA + body żeby push'ować sprzedaż.
"""
import streamlit as st

from db import get_brief, upsert_brief
from ui.theme import page_header, section_title


PRODUCT_TYPES = {
    "digital_ebook":  "📘 Ebook / PDF",
    "digital_course": "🎓 Kurs online (video / cohort)",
    "saas":           "💻 SaaS / aplikacja / subskrypcja",
    "coaching":       "🤝 Coaching / mentoring 1:1",
    "service":        "🔧 Usługa (agencyjna / freelance)",
    "physical":       "📦 Produkt fizyczny",
    "affiliate":      "🔗 Afiliacja / partnerski",
    "other":          "❓ Inne",
}


def render_product(brand_id: str):
    page_header(
        "Produkt i konwersja",
        "AI używa tych pól w slajdach CTA, żeby push'ować sprzedaż. Im konkretniej — tym lepiej konwertuje.",
        icon="💰",
    )

    brief = get_brief(brand_id) or {}

    with st.form("product_form"):
        section_title("Co sprzedajesz?", icon="📦")

        col1, col2 = st.columns([2, 1])
        with col1:
            product = st.text_input(
                "Nazwa produktu",
                value=brief.get("product", ""),
                placeholder="np. 'Ebook Keto 30 dni' / 'Kurs sprzedaży na Vinted'",
            )
        with col2:
            current_type = brief.get("product_type", "digital_ebook")
            if current_type not in PRODUCT_TYPES:
                current_type = "digital_ebook"
            product_type = st.selectbox(
                "Typ produktu",
                options=list(PRODUCT_TYPES.keys()),
                format_func=lambda k: PRODUCT_TYPES[k],
                index=list(PRODUCT_TYPES.keys()).index(current_type),
            )

        main_promise = st.text_input(
            "Główna obietnica (1 zdanie)",
            value=brief.get("main_promise", ""),
            placeholder="np. 'Schudniesz 5kg w 30 dni bez efektu jojo' / 'Zarobisz 1000zł/mies na Vinted'",
            help="Najmocniejsze zdanie sprzedażowe. AI użyje tego w hookach i CTA.",
        )

        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)
        section_title("Cena i oferta", icon="💵")

        col_p, col_a, col_c = st.columns([1, 1, 1])
        with col_p:
            price = st.number_input(
                "Cena (PLN)",
                value=float(brief.get("price") or 0),
                min_value=0.0, step=10.0, format="%.2f",
            )
        with col_a:
            price_anchor = st.number_input(
                "Cena 'przekreslona' (opc.)",
                value=float(brief.get("price_anchor") or 0),
                min_value=0.0, step=10.0, format="%.2f",
                help="Stara/regularna cena dla efektu okazji. Zostaw 0 jeśli brak.",
            )
        with col_c:
            currency = st.text_input(
                "Waluta",
                value=brief.get("currency") or "PLN",
                max_chars=4,
            )

        offer = st.text_area(
            "Oferta — co konkretnie kupuje klient",
            value=brief.get("offer", ""),
            placeholder=(
                "np. '49 PLN, dostęp na zawsze, 100 przepisów + plan zakupów + grupa FB. "
                "Gwarancja 30 dni zwrotu pieniędzy.'"
            ),
            height=80,
        )

        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)
        section_title("CTA — link do sprzedaży", icon="🚀")

        col_url, col_txt = st.columns([3, 2])
        with col_url:
            cta_url = st.text_input(
                "Link do strony sprzedaży",
                value=brief.get("cta_url", ""),
                placeholder="https://twoja-strona.pl/oferta",
                help="AI wkleja ten link w caption + odwołuje się do niego w ostatnim slajdzie.",
            )
        with col_txt:
            cta_text = st.text_input(
                "Tekst CTA",
                value=brief.get("cta_text") or "Klik link w bio",
                placeholder="np. 'Klik link w bio' / 'Sprawdź ofertę poniżej' / 'Komentarz EBOOK'",
            )

        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)
        section_title("Pilność i scarcity (opcjonalne ale BARDZO mocne)", icon="⏰")

        urgency = brief.get("urgency_hooks") or []
        if isinstance(urgency, str):
            urgency_str = urgency
        else:
            urgency_str = "\n".join(urgency)

        urgency_text = st.text_area(
            "Hooki pilności (jeden na linię)",
            value=urgency_str,
            placeholder=(
                "30% rabatu tylko do niedzieli\n"
                "Ostatnie 50 sztuk\n"
                "Cena rośnie w przyszłym tygodniu\n"
                "Bonus +ebook gratis przy zakupie dziś"
            ),
            height=110,
            help="AI losuje jeden z tych hooków do slajdów CTA. Jeśli pusto — używa generycznych.",
        )

        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)
        section_title("Social proof — krótkie liczby/dowody", icon="🏆")

        sp = brief.get("social_proof") or []
        if isinstance(sp, str):
            sp_str = sp
        else:
            sp_str = "\n".join(sp)

        social_proof_text = st.text_area(
            "Dowody (jeden na linię)",
            value=sp_str,
            placeholder=(
                "3000+ zadowolonych klientek\n"
                "Oceny 4.8/5 od 240 osób\n"
                "Polecane przez @znana_marka\n"
                "Ja sama zrzuciłam 8kg dzięki temu"
            ),
            height=110,
        )

        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)
        section_title("Gwarancje (zbijają obiekcje)", icon="🛡️")

        gtees = brief.get("guarantees") or []
        if isinstance(gtees, str):
            gtees_str = gtees
        else:
            gtees_str = "\n".join(gtees)

        guarantees_text = st.text_area(
            "Gwarancje (jedna na linię)",
            value=gtees_str,
            placeholder=(
                "30 dni zwrotu bez pytań\n"
                "Dostęp dożywotnio (nie subskrypcja)\n"
                "Bezpieczna płatność Stripe"
            ),
            height=90,
        )

        submitted = st.form_submit_button("💾 Zapisz", type="primary", use_container_width=True)

    if submitted:
        update_payload = {
            "product": product.strip(),
            "product_type": product_type,
            "main_promise": main_promise.strip(),
            "price": price if price > 0 else None,
            "price_anchor": price_anchor if price_anchor > 0 else None,
            "currency": currency.strip().upper() or "PLN",
            "offer": offer.strip(),
            "cta_url": cta_url.strip(),
            "cta_text": cta_text.strip() or "Klik link w bio",
            "urgency_hooks": [u.strip() for u in urgency_text.splitlines() if u.strip()],
            "social_proof": [s.strip() for s in social_proof_text.splitlines() if s.strip()],
            "guarantees": [g.strip() for g in guarantees_text.splitlines() if g.strip()],
        }
        upsert_brief(brand_id, update_payload)
        st.success("✅ Zapisano. AI od następnej karuzeli będzie używać tych danych w CTA.")
        st.rerun()
