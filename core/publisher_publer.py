"""
Klient Publer API — wysyła karuzele do zaplanowanego publikowania na IG i TikTok.
Docs: https://publer.com/docs/api-reference/introduction
"""
import time
import requests
from pathlib import Path
from typing import Optional

PUBLER_BASE = "https://app.publer.com/api/v1"


class PublerError(Exception):
    pass


class PublerClient:
    def __init__(self, api_key: str, workspace_id: str = ""):
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer-API {api_key}"})
        if workspace_id:
            self._session.headers["Publer-Workspace-Id"] = workspace_id

    def set_workspace(self, workspace_id: str):
        self._session.headers["Publer-Workspace-Id"] = workspace_id

    # ── Workspaces ──────────────────────────────────────────────────────────

    def get_workspaces(self) -> list[dict]:
        """Lista workspaces (nie wymaga Publer-Workspace-Id)."""
        resp = self._session.get(f"{PUBLER_BASE}/workspaces", timeout=15)
        self._raise(resp)
        return self._list(resp.json())

    # ── Accounts ─────────────────────────────────────────────────────────────

    def get_accounts(self) -> list[dict]:
        """Lista kont IG / TikTok połączonych z workspace."""
        resp = self._session.get(f"{PUBLER_BASE}/accounts", timeout=15)
        self._raise(resp)
        return self._list(resp.json())

    # ── Media ────────────────────────────────────────────────────────────────

    def upload_media(self, image_path: str) -> str:
        """Wgrywa obrazek PNG/JPG, zwraca media ID do użycia w poście."""
        p = Path(image_path)
        with open(p, "rb") as f:
            resp = self._session.post(
                f"{PUBLER_BASE}/media",
                files={"file": (p.name, f, "image/png")},
                timeout=90,
            )
        self._raise(resp)
        data = resp.json()
        if isinstance(data, dict):
            mid = (
                data.get("id")
                or (data.get("data") or {}).get("id")
                or data.get("media_id")
            )
            if mid:
                return str(mid)
        raise PublerError(f"Brak media ID w odpowiedzi Publer: {data}")

    # ── Posts ────────────────────────────────────────────────────────────────

    def schedule_carousel(
        self,
        ig_account_ids: list[str],
        tt_account_ids: list[str],
        caption: str,
        hashtags: list[str],
        media_ids: list[str],
        scheduled_at: str,
        verify: bool = True,
    ) -> dict:
        """
        Planuje karuzelę na Instagramie i/lub TikToku.

        verify=True → po wyslaniu polluje get_job_status az Publer potwierdzi
                      ze post zostal utworzony. Rzuca PublerError gdy job
                      'completed' ale z bledami w srodku albo gdy 'failed'.
        """
        if not ig_account_ids and not tt_account_ids:
            raise PublerError("Nie wybrano żadnego konta do publikacji.")

        full_caption = caption.strip()
        if hashtags:
            full_caption += "\n\n" + " ".join(hashtags)

        # TikTok wymaga title (max 90 znaków) — wyciągnij z 1. linii caption
        tt_title = full_caption.split("\n", 1)[0][:88].strip() or "New post"

        accounts = [
            {"id": aid, "scheduled_at": scheduled_at}
            for aid in (ig_account_ids + tt_account_ids)
        ]

        networks: dict = {}
        if ig_account_ids:
            # IG carousel: max 10 zdjęć
            networks["instagram"] = {
                "type": "carousel",
                "text": full_caption,
                "media": [{"id": mid, "type": "image"} for mid in media_ids[:10]],
            }
        if tt_account_ids:
            # TikTok photo carousel: max 35 zdjęć. TITLE WYMAGANY.
            # UWAGA: nie dodajemy nieudokumentowanych pol (jak auto_add_music),
            # bo Publer cicho odrzuca caly post zamiast je ignorowac.
            networks["tiktok"] = {
                "type": "photo",
                "title": tt_title,
                "text": full_caption,
                "media": [{"id": mid} for mid in media_ids[:35]],
                "details": {
                    "privacy": "PUBLIC_TO_EVERYONE",
                    "comment": True,
                    "promotional": False,
                    "paid": False,
                    "reminder": False,
                },
            }

        payload = {
            "bulk": {
                "state": "scheduled",
                "posts": [{"accounts": accounts, "networks": networks}],
            }
        }

        resp = self._session.post(
            f"{PUBLER_BASE}/posts/schedule",
            json=payload,
            timeout=30,
        )

        try:
            response_json = resp.json()
        except Exception:
            response_json = {"_raw_text": resp.text[:1000]}

        if not resp.ok:
            raise PublerError(
                f"Publer API {resp.status_code}: {response_json}\n"
                f"Wysłany payload: {payload}"
            )

        job_id = (
            response_json.get("job_id")
            or (response_json.get("data") or {}).get("job_id")
        )

        # ── Weryfikacja: czekamy az Publer faktycznie utworzy posty ──────────
        job_status_final: Optional[dict] = None
        poll_error: Optional[str] = None
        if verify and job_id:
            for attempt in range(15):  # ~30s max
                try:
                    js = self.get_job_status(job_id)
                    job_status_final = js
                    state = (js.get("status") or js.get("state") or "").lower()

                    # Bledy bezposrednie
                    if state in ("failed", "error", "rejected"):
                        errs = self._extract_errors(js)
                        raise PublerError(
                            f"Publer odrzucił post (state={state}): "
                            f"{errs or js}\nWysłany payload: {payload}"
                        )

                    # Job ukonczony — sprawdz czy nie ma ukrytych bledow w srodku
                    if state in ("completed", "complete", "done", "success", "scheduled"):
                        errs = self._extract_errors(js)
                        if errs:
                            raise PublerError(
                                f"Publer ukończył job ale post nie powstał: "
                                f"{errs}\nWysłany payload: {payload}"
                            )
                        break
                except PublerError:
                    raise
                except Exception as poll_exc:
                    poll_error = str(poll_exc)
                time.sleep(2)

        return {
            "request_payload": payload,
            "status_code": resp.status_code,
            "response": response_json,
            "job_id": job_id,
            "post_id": (
                response_json.get("id")
                or (response_json.get("data") or {}).get("id")
            ),
            "job_status_final": job_status_final,
            "poll_error": poll_error,
        }

    def get_job_status(self, job_id: str) -> dict:
        """Sprawdza status async job-a (po schedule)."""
        resp = self._session.get(
            f"{PUBLER_BASE}/job_status/{job_id}",
            timeout=15,
        )
        self._raise(resp)
        return resp.json()

    def delete_post(self, post_id: str) -> bool:
        """
        Kasuje zaplanowany post w Publerze (DELETE /posts/{id}).
        Zwraca True jesli sukces. Tolerancyjny na 404 (post juz nie istnieje).
        """
        if not post_id:
            return False
        resp = self._session.delete(
            f"{PUBLER_BASE}/posts/{post_id}",
            timeout=15,
        )
        if resp.status_code == 404:
            return True  # Already gone — traktujemy jako sukces
        self._raise(resp)
        return True

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _list(data) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "items", "accounts", "workspaces"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    def _raise(self, resp: requests.Response):
        if resp.ok:
            return
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:400]
        raise PublerError(f"Publer API {resp.status_code}: {detail}")

    @staticmethod
    def _extract_errors(job_status: dict) -> list:
        """Wyciaga bledy z job_status response — sprawdza wszystkie znane lokalizacje."""
        if not isinstance(job_status, dict):
            return []
        candidates = []
        for key in ("errors", "failures", "error", "failure", "issues"):
            v = job_status.get(key)
            if v:
                candidates.append(v)
        data = job_status.get("data")
        if isinstance(data, dict):
            for key in ("errors", "failures"):
                v = data.get(key)
                if v:
                    candidates.append(v)
            posts = data.get("posts") or []
            if isinstance(posts, list):
                for p in posts:
                    if isinstance(p, dict):
                        st = (p.get("status") or p.get("state") or "").lower()
                        if st in ("failed", "error", "rejected"):
                            candidates.append(p)
                        for key in ("errors", "failures", "error"):
                            v = p.get(key)
                            if v:
                                candidates.append(v)
        return candidates
