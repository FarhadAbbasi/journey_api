from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx


SUPABASE_URL = (os.getenv("SUPABASE_URL", "") or "").strip().rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or os.getenv("SUPABASE_KEY", "") or "").strip()
SUPABASE_TIMEOUT_SECONDS = float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "10"))

SUPABASE_CONVERSATIONS_TABLE = (os.getenv("SUPABASE_CONVERSATIONS_TABLE", "") or "journey_conversations").strip()
SUPABASE_SIGNAL_SNAPSHOTS_TABLE = (os.getenv("SUPABASE_SIGNAL_SNAPSHOTS_TABLE", "") or "journey_signal_snapshots").strip()


def _enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


class SupabaseStore:
    """
    Minimal Supabase persistence using PostgREST (no extra SDK dependency).
    Assumes SUPABASE_URL is your project URL (e.g. https://xxxx.supabase.co)
    and SUPABASE_SERVICE_ROLE_KEY (recommended) or SUPABASE_KEY is provided.
    """

    def __init__(self):
        if not _enabled():
            raise RuntimeError("Supabase is not configured (missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        }

    def _rest_url(self, table: str) -> str:
        return f"{SUPABASE_URL}/rest/v1/{table}"

    async def load_recent_conversation(self, user_id: str, limit: int = 6) -> List[Dict[str, str]]:
        """
        Returns message history in the same shape FastAPI expects:
        [{"role":"user|assistant","content":"..."}]
        """
        params = {
            "select": "role,content,created_at",
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc",
            "limit": str(int(limit)),
        }
        url = self._rest_url(SUPABASE_CONVERSATIONS_TABLE)
        async with httpx.AsyncClient(timeout=SUPABASE_TIMEOUT_SECONDS) as client:
            r = await client.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            rows = r.json() if r.content else []

        # rows come newest-first; return oldest-first
        out: List[Dict[str, str]] = []
        for row in reversed(rows or []):
            role = (row.get("role") or "").strip()
            content = (row.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                out.append({"role": role, "content": content})
        return out

    async def load_latest_signal_snapshot(self, user_id: str) -> Optional[Dict[str, Any]]:
        params = {
            "select": "signals,created_at",
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc",
            "limit": "1",
        }
        url = self._rest_url(SUPABASE_SIGNAL_SNAPSHOTS_TABLE)
        async with httpx.AsyncClient(timeout=SUPABASE_TIMEOUT_SECONDS) as client:
            r = await client.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            rows = r.json() if r.content else []
        if not rows:
            return None
        signals = rows[0].get("signals")
        return signals if isinstance(signals, dict) else None

    async def persist_turn(
        self,
        *,
        user_id: str,
        user_message: str,
        assistant_message: str,
        signals: Dict[str, Any],
        stage_probs: Dict[str, float],
        confidence: str,
        coverage: float,
        config_version: str,
        config_hash: str,
        model_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """
        Persists:
          1) two conversation rows (user + assistant)
          2) one signals snapshot row
        """
        conv_rows = [
            {"user_id": user_id, "role": "user", "content": user_message, "model_id": model_id, "request_id": request_id},
            {"user_id": user_id, "role": "assistant", "content": assistant_message, "model_id": model_id, "request_id": request_id},
        ]
        snap_row = {
            "user_id": user_id,
            "signals": signals,
            "stage_probs": stage_probs,
            "confidence": confidence,
            "coverage": coverage,
            "config_version": config_version,
            "config_hash": config_hash,
            "model_id": model_id,
            "request_id": request_id,
        }

        headers = dict(self._headers())
        headers["Prefer"] = "return=minimal"

        async with httpx.AsyncClient(timeout=SUPABASE_TIMEOUT_SECONDS) as client:
            # Insert conversations
            r1 = await client.post(self._rest_url(SUPABASE_CONVERSATIONS_TABLE), headers=headers, json=conv_rows)
            r1.raise_for_status()
            # Insert snapshot
            r2 = await client.post(self._rest_url(SUPABASE_SIGNAL_SNAPSHOTS_TABLE), headers=headers, json=snap_row)
            r2.raise_for_status()


def get_supabase_store() -> Optional[SupabaseStore]:
    if not _enabled():
        return None
    try:
        return SupabaseStore()
    except Exception:
        return None


async def safe_persist(store: Optional[SupabaseStore], **kwargs) -> None:
    """
    Fire-and-forget helper that never raises, for use in background tasks.
    """
    if not store:
        return
    try:
        await store.persist_turn(**kwargs)
    except Exception:
        return


