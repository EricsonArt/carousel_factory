"""
Bulk reschedule — przesuwa wiele karuzel naraz na nowe terminy w przyszlosci
z losowymi odstepami (np. co 1-2h ±15 min jitter).

Dla kazdej karuzeli:
  - jezeli ma publer_post_id i status='scheduled' → DELETE starego z Publera, schedule nowego
  - jezeli draft (brak publer_post_id) → schedule nowego od scratch
  - jezeli posted/failed → skip (nie ruszamy historii)
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.publisher_publer import PublerClient, PublerError
from db import get_carousel, update_carousel, delete_carousel


def delete_carousel_permanently(
    carousel_id: str,
    publer_api_key: str = "",
    publer_workspace_id: str = "",
) -> dict:
    """
    Permanentnie usuwa karuzelę:
      1. Kasuje post w Publerze (jeśli istnieje publer_post_id)
      2. Usuwa pliki obrazów z dysku
      3. Usuwa rekord z bazy danych

    Zwraca: {"ok": bool, "publer_deleted": bool, "files_deleted": int, "error": str|None}
    """
    import shutil
    from pathlib import Path

    carousel = get_carousel(carousel_id)
    if not carousel:
        return {"ok": False, "error": "Karuzela nie istnieje w bazie."}

    result = {"ok": False, "publer_deleted": False, "files_deleted": 0, "error": None}

    # 1. Usuń z Publer
    post_id = (carousel.get("publer_post_id") or "").strip()
    if post_id and publer_api_key:
        try:
            client = PublerClient(publer_api_key, publer_workspace_id)
            if not publer_workspace_id:
                try:
                    ws = client.get_workspaces()
                    if ws:
                        client.set_workspace(str(ws[0].get("id", "")))
                except PublerError:
                    pass
            client.delete_post(post_id)
            result["publer_deleted"] = True
        except PublerError as e:
            msg = str(e).lower()
            # 404 = już nie istnieje w Publerze — OK, kontynuuj
            if "404" in msg or "not found" in msg:
                result["publer_deleted"] = True
            else:
                result["error"] = f"Błąd Publer: {e}"
                # Nie przerywamy — i tak usuwamy z DB i dysku

    # 2. Usuń pliki z dysku
    slides = carousel.get("slides") or []
    deleted_files = 0
    dirs_to_try: set = set()
    for slide in slides:
        path_str = slide.get("image_path") or ""
        if not path_str:
            continue
        p = Path(path_str)
        dirs_to_try.add(p.parent)
        if p.exists():
            try:
                p.unlink()
                deleted_files += 1
            except OSError:
                pass

    # Usuń katalog karuzeli jeśli pusty
    for d in dirs_to_try:
        try:
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass

    result["files_deleted"] = deleted_files

    # 3. Usuń z bazy danych
    delete_carousel(carousel_id)
    result["ok"] = True
    return result


def delete_all_carousels(
    brand_id: str,
    publer_api_key: str = "",
    publer_workspace_id: str = "",
    progress_callback=None,
) -> dict:
    """
    NUKE: usuwa WSZYSTKIE karuzele marki — z bazy, z dysku i z Publera.
    Nieodwracalne.

    Zwraca: {"deleted": int, "publer_cancelled": int, "errors": int, "details": [...]}
    """
    from db import list_carousels

    carousels = list_carousels(brand_id, limit=1000)
    if not carousels:
        return {"deleted": 0, "publer_cancelled": 0, "errors": 0, "details": [],
                "message": "Brak karuzel do usunięcia."}

    deleted = 0
    publer_cancelled = 0
    errors = 0
    details: list[str] = []
    n = len(carousels)

    for i, c in enumerate(carousels):
        cid = c["id"]
        if progress_callback:
            progress_callback(f"Usuwam {i+1}/{n}: {cid[:8]}...", i / n)

        try:
            res = delete_carousel_permanently(
                cid,
                publer_api_key=publer_api_key,
                publer_workspace_id=publer_workspace_id,
            )
            if res.get("ok"):
                deleted += 1
                if res.get("publer_deleted"):
                    publer_cancelled += 1
                details.append(f"✅ {cid[:8]} usunięty"
                                + (" + Publer" if res.get("publer_deleted") else ""))
            else:
                errors += 1
                details.append(f"❌ {cid[:8]}: {res.get('error', '?')}")
        except Exception as e:
            errors += 1
            details.append(f"❌ {cid[:8]}: {e}")

    if progress_callback:
        progress_callback("Gotowe", 1.0)

    return {
        "deleted": deleted,
        "publer_cancelled": publer_cancelled,
        "errors": errors,
        "details": details,
        "total_before": n,
    }


def nuke_all_publer_scheduled(
    publer_api_key: str,
    publer_workspace_id: str = "",
    progress_callback=None,
) -> dict:
    """
    NUKE Publer: pobiera WSZYSTKIE zaplanowane posty bezpośrednio z API Publera
    i kasuje je. Niezależne od bazy lokalnej.

    Zwraca: {"found": int, "deleted": int, "errors": int, "details": [...],
              "diagnostics": [...]}
    """
    if not publer_api_key:
        return {"found": 0, "deleted": 0, "errors": 0,
                "message": "Brak PUBLER_API_KEY w secrets / .env"}

    client = PublerClient(publer_api_key, publer_workspace_id)
    diagnostics: list[str] = []

    # Test 1: workspaces
    workspace_label = "?"
    if not publer_workspace_id:
        try:
            ws = client.get_workspaces()
            diagnostics.append(f"✓ workspaces OK ({len(ws)} found)")
            if ws:
                wid = str(ws[0].get("id", ""))
                client.set_workspace(wid)
                workspace_label = ws[0].get("name", wid)
                diagnostics.append(f"✓ używam workspace: {workspace_label} ({wid})")
        except PublerError as e:
            diagnostics.append(f"❌ /workspaces: {e}")
            return {"found": 0, "deleted": 0, "errors": 1,
                    "message": f"Błąd workspace: {e}",
                    "diagnostics": diagnostics}
    else:
        diagnostics.append(f"✓ użyto workspace_id z config: {publer_workspace_id}")

    # Test 2: accounts (czy klucz w ogóle działa)
    try:
        accounts = client.get_accounts()
        diagnostics.append(f"✓ accounts OK ({len(accounts)} kont)")
    except PublerError as e:
        diagnostics.append(f"❌ /accounts: {e}")

    if progress_callback:
        progress_callback("Pobieranie listy zaplanowanych postów...", 0.05)

    # Test 3: list scheduled
    try:
        posts = client.list_scheduled_posts(limit=500)
        diag = getattr(client, "_last_list_diagnostics", [])
        diagnostics.extend([f"  {d}" for d in diag])
    except PublerError as e:
        diagnostics.append(f"❌ list_scheduled_posts: {e}")
        return {"found": 0, "deleted": 0, "errors": 1,
                "message": f"Błąd listowania: {e}",
                "diagnostics": diagnostics}

    if not posts:
        diagnostics.append("⚠️ Wszystkie endpointy zwróciły pustą listę albo 404")
        return {"found": 0, "deleted": 0, "errors": 0,
                "message": ("Publer API nie zwrócił żadnych postów. "
                           "Możliwe: (1) klucz API ma tylko prawa write, nie read; "
                           "(2) Publer zmienił endpointy; "
                           "(3) faktycznie nic nie ma. "
                           "Sprawdź szczegóły poniżej."),
                "diagnostics": diagnostics}

    diagnostics.append(f"✓ Znaleziono {len(posts)} postów do usunięcia")

    n = len(posts)
    deleted = 0
    errors = 0
    details: list[str] = []

    for i, post in enumerate(posts):
        post_id = str(post.get("id") or post.get("_id") or "")
        if not post_id:
            errors += 1
            details.append(f"❌ post bez ID: {post}")
            continue

        text_preview = (post.get("text") or post.get("caption") or "")[:50]
        if progress_callback:
            progress_callback(
                f"Anuluję {i+1}/{n}: {text_preview}...",
                0.05 + 0.9 * (i / max(n, 1)),
            )

        try:
            client.delete_post(post_id)
            deleted += 1
            details.append(f"✅ {post_id[:12]} — {text_preview}")
        except PublerError as e:
            msg = str(e).lower()
            if "404" in msg or "not found" in msg:
                deleted += 1
                details.append(f"⏭ {post_id[:12]} — już nie istnieje")
            else:
                errors += 1
                details.append(f"❌ {post_id[:12]} — {e}")

    if progress_callback:
        progress_callback("Gotowe", 1.0)

    return {
        "found": n,
        "deleted": deleted,
        "errors": errors,
        "details": details,
        "diagnostics": diagnostics,
    }


def cancel_all_scheduled(
    brand_id: str,
    publer_api_key: str,
    publer_workspace_id: str = "",
    progress_callback=None,
) -> dict:
    """
    Anuluje WSZYSTKIE zaplanowane (status='scheduled') karuzele dla marki:
    kasuje posty w Publerze + ustawia karuzelom status='draft', publer_post_id=''.
    NIE rusza karuzel ze statusem 'posted', 'failed' albo 'draft' bez publer_post_id.

    Zwraca: {'cancelled': int, 'failed': int, 'skipped': int, 'details': [...]}
    """
    from db import list_carousels

    carousels = list_carousels(brand_id, limit=500)
    scheduled = [
        c for c in carousels
        if (c.get("status") or "").lower() == "scheduled"
        and (c.get("publer_post_id") or "").strip()
    ]

    if not scheduled:
        return {"cancelled": 0, "failed": 0, "skipped": 0, "details": [],
                "message": "Brak zaplanowanych postów do anulowania."}

    client = None
    if publer_api_key:
        client = PublerClient(publer_api_key, publer_workspace_id)
        if not publer_workspace_id:
            try:
                ws = client.get_workspaces()
                if ws:
                    client.set_workspace(str(ws[0].get("id", "")))
            except PublerError:
                pass

    cancelled = 0
    failed = 0
    details: list[str] = []
    n = len(scheduled)

    for i, c in enumerate(scheduled):
        cid = c["id"]
        post_id = c.get("publer_post_id", "")
        if progress_callback:
            progress_callback(f"Anuluję {i+1}/{n}: {cid[:8]}...", (i / n))

        deleted_in_publer = False
        if client:
            try:
                client.delete_post(post_id)
                deleted_in_publer = True
            except PublerError as e:
                # Tolerujemy 404 i podobne — post mogl juz nie istniec w Publerze
                msg = str(e).lower()
                if "404" in msg or "not found" in msg:
                    deleted_in_publer = True
                else:
                    failed += 1
                    details.append(f"❌ {cid}: {e}")
                    continue

        # Reset DB tak czy siak — nawet jak Publer odpowiedzial 404
        update_carousel(cid, publer_post_id="", status="draft", scheduled_at="")
        cancelled += 1
        details.append(f"✅ {cid[:8]} — {'usunieto z Publera + reset DB' if deleted_in_publer else 'reset DB'}")

    if progress_callback:
        progress_callback("Gotowe", 1.0)

    return {
        "cancelled": cancelled,
        "failed": failed,
        "skipped": 0,
        "details": details,
        "total_scheduled_before": n,
    }


def bulk_reschedule(
    carousel_ids: list[str],
    start_dt_utc: datetime,
    gap_minutes_min: int = 60,
    gap_minutes_max: int = 120,
    jitter_minutes: int = 15,
    publer_api_key: str = "",
    publer_workspace_id: str = "",
    ig_account_ids: Optional[list[str]] = None,
    tt_account_ids: Optional[list[str]] = None,
    progress_callback=None,
) -> dict:
    """
    Przeplanowuje liste karuzel zaczynajac od start_dt_utc, kazda kolejna
    losowo gap_minutes_min..gap_minutes_max + jitter ±jitter_minutes.

    Zwraca: {
      "total": N,
      "scheduled": int,    # ile zaplanowanych w Publerze
      "db_only": int,      # ile zaktualizowanych tylko w DB (brak Publera)
      "skipped": int,      # ile pominietych (posted/failed/no_images)
      "errors": int,
      "results": [...],    # szczegoly per-karuzela
    }
    """
    ig_account_ids = ig_account_ids or []
    tt_account_ids = tt_account_ids or []

    use_publer = bool(publer_api_key and (ig_account_ids or tt_account_ids))
    client: Optional[PublerClient] = None
    if use_publer:
        client = PublerClient(publer_api_key, publer_workspace_id)
        if not publer_workspace_id:
            workspaces = client.get_workspaces()
            if workspaces:
                client.set_workspace(str(workspaces[0].get("id", "")))

    results: list[dict] = []
    counters = {"scheduled": 0, "db_only": 0, "skipped": 0, "errors": 0}
    next_time = start_dt_utc.astimezone(timezone.utc)

    n = len(carousel_ids)
    for i, carousel_id in enumerate(carousel_ids):
        if progress_callback:
            progress_callback(
                f"Karuzela {i+1}/{n}...",
                0.05 + 0.9 * (i / max(n, 1)),
            )

        carousel = get_carousel(carousel_id)
        if not carousel:
            counters["errors"] += 1
            results.append({"id": carousel_id, "status": "not_found"})
            continue

        # Skip karuzel ktore juz poszly
        cur_status = (carousel.get("status") or "").lower()
        if cur_status in ("posted", "published", "failed"):
            counters["skipped"] += 1
            results.append({"id": carousel_id, "status": f"skipped_{cur_status}"})
            continue

        scheduled_iso = next_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Step 1: jezeli juz w Publerze - delete stary post
        old_post_id = (carousel.get("publer_post_id") or "").strip()
        deleted_old = False
        if old_post_id and use_publer and client is not None:
            try:
                client.delete_post(old_post_id)
                deleted_old = True
            except PublerError:
                # Stary post moze byc juz opublikowany albo zniknal — kontynuuj
                pass

        # Step 2: schedule nowego (jezeli mozemy)
        if use_publer and client is not None:
            try:
                slides = carousel.get("slides") or []
                image_paths = [s["image_path"] for s in slides if s.get("image_path")]
                if not image_paths:
                    counters["skipped"] += 1
                    results.append({"id": carousel_id, "status": "no_images"})
                    continue

                media_ids: list[str] = []
                for path in image_paths:
                    mid = client.upload_media(path)
                    media_ids.append(mid)

                publer_result = client.schedule_carousel(
                    ig_account_ids=ig_account_ids,
                    tt_account_ids=tt_account_ids,
                    caption=carousel.get("caption", ""),
                    hashtags=carousel.get("hashtags") or [],
                    media_ids=media_ids,
                    scheduled_at=scheduled_iso,
                    verify=False,  # nie czekamy na potwierdzenie - bulk = szybkosc nad pewnoscia
                )

                new_post_id = (
                    publer_result.get("post_id")
                    or publer_result.get("job_id")
                    or "ok"
                )
                update_carousel(
                    carousel_id,
                    status="scheduled",
                    scheduled_at=scheduled_iso,
                    publer_post_id=str(new_post_id),
                )
                counters["scheduled"] += 1
                results.append({
                    "id": carousel_id,
                    "status": "scheduled",
                    "new_time": scheduled_iso,
                    "new_post_id": str(new_post_id),
                    "deleted_old": deleted_old,
                })
            except Exception as e:
                # Nie udalo sie schedulowac w Publerze — zostaw w bazie z nowym czasem ale jako draft
                update_carousel(
                    carousel_id,
                    status="draft",
                    scheduled_at=scheduled_iso,
                    publer_post_id="",
                )
                counters["errors"] += 1
                results.append({
                    "id": carousel_id,
                    "status": "publer_error",
                    "new_time": scheduled_iso,
                    "error": str(e)[:200],
                })
        else:
            # Bez Publera — tylko update DB
            update_carousel(
                carousel_id,
                scheduled_at=scheduled_iso,
            )
            counters["db_only"] += 1
            results.append({
                "id": carousel_id,
                "status": "db_only",
                "new_time": scheduled_iso,
            })

        # Step 3: oblicz czas dla nastepnej
        gap = random.uniform(gap_minutes_min, gap_minutes_max)
        jitter = random.uniform(-jitter_minutes, jitter_minutes)
        next_time = next_time + timedelta(minutes=gap + jitter)

    if progress_callback:
        progress_callback("Gotowe!", 1.0)

    return {
        "total": n,
        **counters,
        "results": results,
    }
