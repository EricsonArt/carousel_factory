# carousel_factory

Streamlit aplikacja do automatycznego generowania i publikowania viralowych karuzel na Instagram + TikTok.

**Status:** Phase 1 (Foundation + manual generation) ✅

## Filozofia

- **Multi-brand od dnia 1** - kazda marka ma osobny brief, biblioteke styli, harmonogram
- **AI-led onboarding** - rozmowa po polsku gdzie AI auto-uzupelnia krotkie odpowiedzi research'em
- **Style Library** - wgrywasz zdjecia z viralowych postow, AI Vision (Claude Sonnet) wyciaga styl, generator obrazow replikuje
- **Cascade image generation** - GPT Image (primary, czytelny tekst PL) → Gemini 2.5 Flash Image (style transfer) → Replicate FLUX (fallback)
- **Polskie znaki** zawsze nakladane przez Pillow overlay - generator obrazow czesto psuje polskie diakrytyki

## Setup

```bash
cd C:\Users\48795\Desktop\carousel_factory
pip install -r requirements.txt

# Skopiuj klucze API:
cp .env.example .env
# Wypelnij ANTHROPIC_API_KEY i OPENAI_API_KEY (minimum dla Phase 1)
```

## Uruchamianie

### Lokalnie (localhost)

Double-click `start_local.bat` albo:
```bash
streamlit run app.py
```
App na `http://localhost:8501`.

### Streamlit Community Cloud (REKOMENDOWANE - stale 24/7, darmowe)

Aplikacja dziala 24/7 w chmurze, dostepna z dowolnego urzadzenia, **nawet gdy Twoj komputer jest wylaczony**.

1. Push kodu na GitHub (instrukcje nizej w sekcji "Deploy na GitHub")
2. Wejdz na https://share.streamlit.io
3. Zaloguj sie przez GitHub
4. "New app" → wybierz repo `carousel_factory` → branch `main` → `app.py`
5. **Advanced settings → Secrets** wklej (z prawdziwymi kluczami):
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   OPENAI_API_KEY = "sk-..."
   APP_PASSWORD = "twoje_dlugie_haslo"
   DAILY_COST_CAP_USD = 5.0
   ```
6. Deploy → URL `https://twoja-app.streamlit.app`

Po push'u nowych commitow Streamlit Cloud automatycznie restartuje aplikacje z nowym kodem.

### Publiczny URL przez Cloudflare Tunnel (tymczasowe testy)

Tymczasowy URL `*.trycloudflare.com` aktywny tylko dopoki Twoj komputer dziala.
Cloudflared juz pobrany w `bin/cloudflared.exe`.

**WAZNE:** ustaw `APP_PASSWORD` w `.env` zanim wystawisz publicznie - bez tego ktokolwiek z URLem moze generowac karuzele i kosztowac Cie pieniadze za API!

Double-click `start_public.bat` albo `python scripts/run_public.py`. URL aktywny dopoki okno terminala jest otwarte.

## Deploy na GitHub (jednorazowo)

```bash
# 1. Stworz repo na github.com (Private + bez README)
# 2. W terminalu w katalogu carousel_factory:
git remote add origin https://github.com/TWOJA_NAZWA/carousel_factory.git
git branch -M main
git push -u origin main
# Przy pierwszym push'u: Git poprosi o login GitHub (browser)
```

Po kazdej zmianie:
```bash
git add .
git commit -m "opis zmiany"
git push
```

## Phase 1 - co dziala

1. **Multi-brand picker** w sidebar
2. **AI Brief Wizard** (zakladka 'Brief marki') - 10 sekcji, AI pomaga uzupelniac
3. **Biblioteka styli** - wgrywasz 5-10 zdjec, Claude Vision wyciaga Style Profile JSON
4. **Generator karuzel** - wpisujesz temat, wybierasz styl, AI generuje 5-10 slajdow + caption + hashtagi
5. **Eksport ZIP** - pobierasz gotowe slajdy + caption.txt do recznej publikacji

## Architektura

```
carousel_factory/
├── app.py                          # Streamlit entry
├── config.py                       # Klucze API, modele, sciezki
├── db.py                           # SQLite CRUD
├── prompts/                        # Prompty po polsku
│   ├── brief_wizard.md
│   ├── style_extract.md
│   ├── carousel_copy.md
│   └── viral_replicator.md
├── core/
│   ├── llm.py                      # Claude text + vision wrappers
│   ├── utils.py                    # Polish text utils, slot_randomizer
│   ├── image_router.py             # Cascade GPT/Gemini/Replicate
│   ├── style_extractor.py          # Vision -> StyleProfile
│   └── carousel_generator.py       # Orchestrator pipeline
├── ui/
│   ├── onboarding.py               # Brief Wizard
│   ├── style_library.py            # Upload + extract
│   ├── generate.py                 # Manual generation
│   └── history.py                  # Past carousels + ZIP export
└── data/
    ├── carousels/{brand_id}/{carousel_id}/
    ├── styles/{brand_id}/{style_id}/
    └── carousel_factory.db
```

## Phase 2 (planowane)

- **Viral Replicator** - wkleisz link viralowej karuzeli, AI Vision analizuje strukture, generuje "nasza wersja" z produktem usera
- **URL scraping** w Style Library (Apify dla TikTok/IG)
- **Auto-publish** przez instagrapi (max 2-3/dzien, ryzyko bana na osobistym koncie)
- **Comment mining** - tematy z koment z top kont w niszy

## Phase 3 (planowane)

- **Cascade fallback** w image generation (Gemini + Replicate)
- **Oficjalne API**: Instagram Graph API + TikTok Content Posting API
- **Smart scheduler** - 4 sloty z jitter ±30 min, 90-min gap, ramp-up 2→10/dzien
- **Polski guide** jak zalozyc Business + Meta App + TikTok Developer audit

## Phase 4 (planowane)

- **Analytics** - codzienny polling metryk z IG/TT
- **Learning loop** - ranking stylow/tematow po engagement, auto-deprioritizacja slabych

## KRYTYCZNE zasady bezpieczenstwa

- `.streamlit/secrets.toml` i `.env` sa w `.gitignore` - NIGDY nie commit'uj kluczy
- Sesje instagrapi w `data/sessions/` - tez gitignored
- Daily cost cap w `config.DAILY_COST_CAP_USD` (default $5/dzien) - hard limit
- Walidacja `core/llm.py:validate_against_brief()` blokuje halucynacje + forbidden claims (medyczne, gwarantowane wyniki, income claims) PRZED publikacja

## Reuse z innych projektow

- `viral_video_creator/config.py:_get_secret` → `config.py`
- `viral_video_creator/modules/script_generator.py:_call_llm` patterns → `core/llm.py`
- `viral_video_creator/modules/utils.py` Polish utils → `core/utils.py`
- `lead_hunter/agents/messenger_agent.py` instagrapi pattern → Phase 2 `core/publisher.py`
- `lead_hunter/tools/apify_client.py` Apify runner → Phase 2 `core/scraper.py`

## Plan szczegolowy

`C:\Users\48795\.claude\plans\chcia-bym-aby-zrobi-iterative-backus.md`
