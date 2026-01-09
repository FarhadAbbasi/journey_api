from __future__ import annotations

import re
import json
import ast
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import ChatRequest, ChatResponse
from .assessment import (
    load_assessment_config,
    ASSESSMENT_CONFIG_JSON,
    build_sys_prompt,
    normalize_signals,
    update_user_state,
    assess_stage,
)
from .state_store import get_store
from .runpod_client import infer_chat, RunPodError

app = FastAPI(title="Journey CPU API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cfg = load_assessment_config(ASSESSMENT_CONFIG_JSON)
store = get_store()

def _parse_json_from_model(text: str):
    """Robust JSON extraction from model output (derived from your notebook/script approach)."""
    text = (text or "").strip()
    if not text:
        return "Thanks for sharing that. Could you tell me a bit more about how this has been feeling for you?", {}

    candidate_blocks = []
    depth = 0
    start = -1
    in_string = False
    escape = False

    for i, char in enumerate(text):
        if char == '\\':
            escape = not escape
        elif char == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if char in '{[':
                if depth == 0:
                    start = i
                depth += 1
            elif char in '}]':
                depth -= 1
                if depth == 0 and start != -1:
                    candidate_blocks.append(text[start:i+1])
                    start = -1
        if escape and char != '\\':
            escape = False

    final_msg = ""
    signals: Dict[str, Any] = {}
    first_msg = ""
    msg_with_signals = ""

    for block_str in candidate_blocks:
        parsed = None
        try:
            parsed = json.loads(block_str)
        except json.JSONDecodeError:
            try:
                lit = (block_str
                       .replace(': null', ': None')
                       .replace(': true', ': True')
                       .replace(': false', ': False')
                       .replace(' null', ' None')
                       .replace(' true', ' True')
                       .replace(' false', ' False'))
                parsed = ast.literal_eval(lit)
            except Exception:
                pass

        fragments = []
        if isinstance(parsed, dict):
            fragments = [parsed]
        elif isinstance(parsed, list):
            fragments = [x for x in parsed if isinstance(x, dict)]

        for d in fragments:
            msg = ""
            if "assistant_message" in d:
                msg = str(d["assistant_message"]).strip()
            elif "text" in d:
                msg = str(d["text"]).strip()

            if msg and not first_msg:
                first_msg = msg

            if isinstance(d.get("signals"), dict):
                signals.update(d["signals"])
                if msg:
                    msg_with_signals = msg

    if msg_with_signals:
        final_msg = msg_with_signals
    elif first_msg:
        final_msg = first_msg

    if not final_msg:
        cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        cleaned = re.sub(r"\{.*?\}", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\[.*?\]", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.strip()
        final_msg = cleaned if cleaned and cleaned != "}" else "Thanks for sharing that. Could you tell me a bit more?"

    return final_msg, signals

def _trim_history(history: Optional[List[Dict[str, str]]], max_messages: int = 6):
    if not history:
        return []
    history = [h for h in history if isinstance(h, dict) and "role" in h and "content" in h]
    return history[-max_messages:]

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # Load user state
    key = f"journey:user:{req.user_id}"
    state = await store.get(key) or {"signals": {}, "history": []}

    # Build system prompt from config
    sys_prompt = build_sys_prompt(cfg)

    messages: List[Dict[str, str]] = []
    # Internal context that the model must NOT mention (keep minimal)
    messages.append({"role": "system", "content": sys_prompt})

    # Add trimmed history if provided
    messages.extend(_trim_history(req.history, max_messages=6))
    messages.append({"role": "user", "content": req.message})

    # # Call GPU serverless
    # try:
    #     out = await infer_chat(messages=messages, max_tokens=512, temperature=0.7)
    # except RunPodError as e:
    #     raise HTTPException(status_code=502, detail=f"RunPod error: {e}")
    # except Exception as e:
    #     raise HTTPException(status_code=502, detail=f"Inference call failed: {e}")

    # raw_text = out.get("raw_text") or out.get("text") or out.get("output") or ""
    # assistant_message, signals_raw = _parse_json_from_model(raw_text)

    # TEMPORARILY DISABLED: return user's message directly (to isolate CPU API behavior)
    assistant_message = req.message
    signals_raw: Dict[str, Any] = {}

    # Normalize + update state
    clean_signals = normalize_signals(cfg, signals_raw if isinstance(signals_raw, dict) else {})
    # Only update if at least one signal is present
    if any(v is not None for v in clean_signals.values()):
        state = update_user_state(cfg, state, clean_signals)

    await store.set(key, state)

    # Compute latest assessment for response
    probs, conf, scores, coverage = assess_stage(cfg, state.get("signals", {}))
    return ChatResponse(
        assistant_message=assistant_message,
        stage_probs=probs,
        confidence=conf,
        coverage=coverage,
        signals=clean_signals,
        config_version=cfg.get("version", "unknown"),
    )
