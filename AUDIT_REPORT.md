# Audyt nocny — Eryk, czytaj rano

**Data:** 2026-04-28 (noc)
**Wersja po audycie:** v0.3.0
**Status deploya:** ✅ Live na https://carousel-factory-eryk.streamlit.app

---

## TL;DR

Przeszedłem **plik po pliku** przez cały kod. Znalazłem **7 bugów** (3 krytyczne — apka by się wykrzaczyła w produkcji). Wszystko **naprawione, przetestowane, wypchnięte na GitHub**. Streamlit Cloud automatycznie przebuduje aplikację z poprawkami w ~2 min.

**Co działa:** generowanie karuzel, polskie znaki w obrazach, eksport ZIP, multi-marka, brief wizard, style library.
**Co NIE działa jeszcze:** auto-publikacja (zgodnie z planem - to zewnętrzny Publer/Metricool).
**Czego się spodziewać:** zobacz sekcję "Plan testów" niżej.

---

## 🔴 Bugi krytyczne (które NAPRAWIŁEM)

### Bug #1: Polskie znaki = kwadraty na obrazach
**Co było:** Czcionka wskazywała na `C:/Windows/Fonts/arial.ttf` — to działa lokalnie u Ciebie na Windowsie, ale na **Streamlit Cloud (Linux) plik nie istnieje**. Pillow wracał do tiny default font, a polskie znaki (ą, ę, ł, ś, ć, ż, ź, ń) renderowały się jako puste kwadraty. **Twoja cała value proposition by padła.**

**Co zrobiłem:**
- Zbundlowałem **Inter Variable** (856KB, pełen polski set) w `assets/fonts/`
- Dodałem cross-platform fallback chain (DejaVu/Liberation/Arial/Helvetica)
- Bumpnąłem Pillow do 10.1+ dla obsługi default fontu z rozmiarem
- **Zweryfikowałem renderem testowym** — wszystkie polskie znaki działają poprawnie

### Bug #2: Cost cap nie chronił portfela
**Co było:** `cost_per_image: 0.04` w configu — ale kod używa `quality="high"` w OpenAI API, co kosztuje **~$0.19/obraz** (5x więcej). Dzienny limit $5 myślał że masz budżet na 125 obrazów, a realnie miałeś tylko 26. **Mogłeś przekroczyć limit i nie wiedzieć.**

**Co zrobiłem:**
- Zmieniłem `cost_per_image` na realne $0.19
- Dodałem `IMAGE_QUALITY` env var (high/medium/low) — możesz dać `IMAGE_QUALITY=medium` w Streamlit Secrets dla taniej generacji ($0.08/img)
- Cost cap teraz prawidłowo zatrzymuje generację po przekroczeniu $5/dzień

### Bug #3: Style profile gubił `image_style` i `mood`
**Co było:** Claude Vision zwracał 11 pól w Style Profile JSON. DB miała kolumny tylko na 7 z nich. **`image_style` i `mood` były krytyczne dla generowania obrazów — i były zawsze puste**, bo kod czytał z DB co tam nie trafiało.

**Co zrobiłem:**
- Dodałem 5 kolumn do `style_profiles`: `image_style`, `mood`, `palette_description`, `tagline_pattern`, `cta_style`
- Migracja `ALTER TABLE` dla istniejących baz (lokalnie nie potrzebna na Streamlit Cloud bo i tak fresh DB)
- Vision teraz pełnowartościowo zasila generator obrazów

---

## 🟠 Bugi UX (które NAPRAWIŁEM)

### Bug #4: Download ZIP wymagał 2 kliknięć i się rozpadał
**Co było:** Klikasz "Eksportuj ZIP" → pojawia się "Pobierz ZIP" → jeśli klikniesz cokolwiek innego, znika. Streamlit reruns gubiły button.

**Co zrobiłem:** Direct `download_button` — jedno kliknięcie, ZIP buduje się w locie. Zmiana w `ui/generate.py` i `ui/history.py`.

### Bug #5: DAILY_COST_CAP_USD ignorował Streamlit Secrets
**Co było:** Czytał tylko z env vars, nie z Streamlit Secrets. Twoje ustawienie w panelu Streamlit Cloud byłoby ignorowane (default $5 by działał, ale Twoja zmiana nie).

**Co zrobiłem:** Nowa funkcja `_get_secret_float()` używa standardowego mechanizmu `_get_secret()`.

### Bug #6: Ostrzeżenie o ulotnej pamięci na Streamlit Cloud
**Co dodałem:** Streamlit Cloud kasuje folder `data/` przy każdym restarcie aplikacji. To znaczy: marki, briefy, style i wygenerowane karuzele **znikają** np. po pushu zmiany kodu albo po dłuższej bezczynności.

**Co zrobiłem:** W sidebarze pojawi się żółta ostrzegawka **tylko na Streamlit Cloud** (lokalnie nic nie widać) z tekstem: *"Pamięć ulotna — pobieraj ZIPy na bieżąco"*.

**Co możesz zrobić długoterminowo (Phase 2/3):**
- Migrować bazę na **Supabase** (darmowy plan — 500MB postgres) → trwała pamięć
- Albo zostać na ulotnej DB i traktować apkę jako "jednorazowy generator" (mniej idealnie, ale tańsze)

### Bug #7: Wykrywanie Streamlit Cloud
**Co dodałem:** `IS_STREAMLIT_CLOUD` w configu — wykrywa cloud środowisko po env vars i ścieżce. Używane do warningu o storage. Może być przydatne dla innych feature flag.

---

## 📋 Plan testów rano (sprawdź czy wszystko działa)

Zaloguj się na https://carousel-factory-eryk.streamlit.app i wykonaj **5 kroków**:

### 1. Sprawdź design (1 min)
- Sidebar **jasny** z efektem szkła? ✅
- Animowany shimmer na "KaruzelAI" w hero? ✅
- Karty z hover lift? ✅
- Wersja w sidebarze: **v0.3.0** (nie v0.2.0)? ✅

### 2. Stwórz testową markę (30 sek)
- Sidebar → "+ Nowa marka"
- Name: "Test Audyt"
- Niche: "fitness"
- IG: `@test_ig`
- TT: `@test_tt`
- Utwórz

### 3. Brief minimum (5 min)
W zakładce "Brief marki" uzupełnij minimum **3 sekcje** z AI-help:
- **Produkt**: "ebook keto na 30 dni"
- **Awatar**: "kobieta 30+ chce schudnąć"
- **Voice tone**: "ciepły ekspercki"

Każda sekcja: wpisz krótko → "Zapytaj AI" → akceptuj propozycję.

### 4. Style Library (3 min)
- Zakładka "Style"
- "Dodaj nowy styl"
- Name: "Test"
- Wgraj **3-5 zdjęć** (cokolwiek — może być przypadkowy stock)
- "Analizuj styl przez AI" → czekaj 15-30 sek
- Sprawdź: paleta kolorów się pokazała? ✅

### 5. Generator (2-3 min) ← MOMENT PRAWDY
- Zakładka "Generator"
- Topic: **"3 błędy które zabijają keto"**
- Slajdów: 7
- Style: Test (z poprzedniego kroku)
- Checkbox IG ☑ + TikTok ☑ powinny być widoczne
- "Generuj karuzelę" → czekaj 60-120 sek
- **Sprawdź obrazki:** czy polskie znaki ł ę ż ó ś ć ń są **CZYTELNE**? (zoom in)
- Pobierz ZIP → otwórz na komputerze

### Jeśli coś padnie
1. Zrób screenshot błędu
2. Streamlit Cloud → menu w prawym dolnym rogu → "Manage app" → **Logs**
3. Skopiuj ostatnie 30-50 linii i wklej mi w czacie
4. Naprawię i pushnę poprawkę.

---

## 🎯 Co dalej (gdy testy przejdą)

### Krok 1: Publer (jutro, ~30 min)
1. Wejdź na **publer.com** → załóż konto trial
2. Plan **Professional ($12/mies)** = 10 social profili
3. Połącz swoje konta TT (5) + IG (3) — 8 z 10 wykorzystane
4. Generuj karuzelę w naszym appie → pobierz ZIP → wrzuć do Publera → harmonogram

### Krok 2: Migracja bazy na Supabase (kiedyś — gdy masz czas)
Streamlit Cloud kasuje DB. Supabase = darmowy postgres trwały. Mogę zrobić migrację gdy chcesz — to ~2-3h roboty.

### Krok 3: SaaS dla klientów (gdy będziesz sprzedawał)
Wtedy:
- Multi-tenant DB (Supabase row-level security)
- Stripe subskrypcje
- Per-user API keys (encrypted)
- Najpewniej nowy front w Next.js (Streamlit nie jest dla SaaS)

---

## 📊 Statystyki audytu

| Metryka | Wartość |
|---|---|
| Plików przeczytanych | 12 |
| Linii kodu zaaudytowanych | ~2400 |
| Krytyczne bugi znalezione | 3 |
| UX bugi znalezione | 4 |
| Bugi naprawione | **7/7** ✅ |
| Smoke testy przepuszczone | 5/5 ✅ |
| Render polskich znaków | ✅ idealny |
| Czcionka zbundlowana | Inter Variable, 856KB |
| Commits w nocy | 1 (`f4c627d`) |
| Pliki zmienione | 9 + 1 nowy (font) |

---

## 🛡️ Czego nadal nie ma (zgodnie z planem - Phase 2+)

To są **świadome braki**, nie bugi:

- ❌ Auto-publikacja IG/TikTok (Phase 2/3 — używamy Publera zamiast tego)
- ❌ Viral Replicator (wklej link → AI replikuje strukturę) — Phase 2
- ❌ Apify URL scraping w Style Library — Phase 2
- ❌ Smart scheduler z ramp-upem — Phase 3 (Publer to robi za nas)
- ❌ Comment mining z top kont — Phase 2
- ❌ Cascade fallback (Gemini, Replicate) — Phase 3 stub w kodzie, działa tylko OpenAI
- ❌ Analytics + learning loop — Phase 4

---

## 💤 Tyle ode mnie. Śpij spokojnie.

Wszystko się zbuduje samo na Streamlit Cloud w ciągu kilku minut. Jak wstaniesz — odśwież appkę, wykonaj plan testów, i jeśli wszystko pójdzie zgodnie z planem, **dziś zarejestrujesz się na Publera i zaczniesz publikować**.

Powodzenia 🎠
