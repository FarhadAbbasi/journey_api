from __future__ import annotations

import os
import httpx
from typing import Any, Dict

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "").strip()
RUNPOD_ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID", "").strip()
RUNPOD_SYNC = os.getenv("RUNPOD_SYNC", "true").lower() == "true"
RUNPOD_TIMEOUT_SECONDS = int(os.getenv("RUNPOD_TIMEOUT_SECONDS", "60"))

class RunPodError(RuntimeError):
    pass

def _require_env():
    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        raise RunPodError("Missing RUNPOD_API_KEY or RUNPOD_ENDPOINT_ID")

async def runsync(payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_env()

    url = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/runsync"
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}"}

    async with httpx.AsyncClient(timeout=RUNPOD_TIMEOUT_SECONDS) as client:
        r = await client.post(url, headers=headers, json={"input": payload})
        r.raise_for_status()
        data = r.json()

    # RunPod 'runsync' typically returns { "status": "...", "output": ... } (or error fields)
    if "error" in data and data["error"]:
        raise RunPodError(str(data["error"]))
    return data

async def infer_chat(messages, max_tokens=512, temperature=0.7) -> Dict[str, Any]:
    # Payload must match gpu_serverless/handler.py
    resp = await runsync({
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    })
    # Some templates nest output; support both.
    return resp.get("output", resp)
