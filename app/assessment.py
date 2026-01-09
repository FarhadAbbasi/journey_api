from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np

# ---- Config (same shape as your notebook / RunPod script) ----
ASSESSMENT_CONFIG_JSON = r'''
{
  "version": "spec-v0.5-default",
  "stages": ["FS", "HM", "IC", "SA"],
  "answer_scale": [-2, -1, 0, 1, 2],
  "questions": [
    {"id":"Q1","text":"I feel excited about the possibilities of living abroad","weights":{"FS":1,"HM":1,"IC":0,"SA":1}},
    {"id":"Q2","text":"I feel shut out and excluded","weights":{"FS":1,"HM":0,"IC":1,"SA":0}},
    {"id":"Q3","text":"I feel guilty leaving my family and friends behind","weights":{"FS":1,"HM":0,"IC":1,"SA":0}},
    {"id":"Q4","text":"I feel my social relationships are superficial","weights":{"FS":0,"HM":0,"IC":1,"SA":0}},
    {"id":"Q5","text":"I feel lonely and/or isolated","weights":{"FS":0,"HM":0,"IC":1,"SA":0}},
    {"id":"Q6","text":"I feel I can maintain my cultural identity and embrace the new culture","weights":{"FS":0,"HM":1,"IC":0,"SA":1}},
    {"id":"Q7","text":"I feel I understand the values of the country I am assigned to","weights":{"FS":1,"HM":0,"IC":0,"SA":1}},
    {"id":"Q8","text":"I feel sad","weights":{"FS":1,"HM":0,"IC":1,"SA":0}},
    {"id":"Q9","text":"I feel disappointed in myself","weights":{"FS":1,"HM":0,"IC":1,"SA":0}},
    {"id":"Q10","text":"I feel discouraged in my new assignment/country","weights":{"FS":1,"HM":0,"IC":1,"SA":0}},
    {"id":"Q11","text":"I feel I am integrated and belong","weights":{"FS":0,"HM":0,"IC":0,"SA":1}},
    {"id":"Q12","text":"I feel that I (and/or) my family is thriving","weights":{"FS":0,"HM":1,"IC":0,"SA":1}},
    {"id":"Q13","text":"I fear that I am inadequate to succeed","weights":{"FS":0,"HM":0,"IC":1,"SA":0}},
    {"id":"Q14","text":"I wish I was better prepared for living abroad","weights":{"FS":1,"HM":0,"IC":1,"SA":0}},
    {"id":"Q15","text":"I feel like the company will leverage my/partner's skills upon returning home","weights":{"FS":0,"HM":0,"IC":0,"SA":1}},
    {"id":"Q16","text":"I feel like issues at home are impacting my work performance","weights":{"FS":0,"HM":0,"IC":1,"SA":0}},
    {"id":"Q17","text":"I feel that my company cares about my/our well-being","weights":{"FS":1,"HM":1,"IC":0,"SA":1}},
    {"id":"Q18","text":"I feel like I am the best \"me\" I can be","weights":{"FS":1,"HM":0,"IC":0,"SA":1}},
    {"id":"Q19","text":"I have been provided, throughout the assignment, with the tools and resources to adapt in the new country","weights":{"FS":1,"HM":0,"IC":0,"SA":1}},
    {"id":"Q20","text":"I am open to using technology to help me adapt abroad","weights":{"FS":1,"HM":1,"IC":1,"SA":1}}
  ]
}
'''

def load_assessment_config(config_json: str) -> dict:
    cfg = json.loads(config_json)
    assert "stages" in cfg and "questions" in cfg, "Config must include stages and questions."
    for q in cfg["questions"]:
        assert "id" in q and "text" in q and "weights" in q
        q["weights"] = {s: float(q["weights"].get(s, 0)) for s in cfg["stages"]}
    return cfg

def config_hash(cfg: dict) -> str:
    blob = json.dumps(cfg, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]

def assess_stage(cfg: dict, signals: Dict[str, int]) -> Tuple[Dict[str, float], str, Dict[str, float], float]:
    stages = cfg["stages"]
    scores = {s: 0.0 for s in stages}

    for q in cfg["questions"]:
        qid = q["id"]
        v = signals.get(qid, None)
        if v is None:
            continue
        for s in stages:
            scores[s] += q["weights"].get(s, 0.0) * float(v)

    vec = np.array([max(scores[s], 0.0) for s in stages], dtype=float)
    if vec.sum() > 0:
        vec = vec / vec.sum()
    probs = {stages[i]: float(vec[i]) for i in range(len(stages))}

    coverage = sum(1 for q in cfg["questions"] if signals.get(q["id"], None) is not None) / max(len(cfg["questions"]), 1)
    dominance = max(probs.values()) if probs else 0.0
    conf_score = 0.6 * dominance + 0.4 * coverage

    if conf_score >= 0.75:
        conf = "high"
    elif conf_score >= 0.45:
        conf = "medium"
    else:
        conf = "low"

    return probs, conf, scores, coverage

def build_sys_prompt(cfg: dict) -> str:
    qs = cfg["questions"]
    qlines = "\n".join([f"- {q['id']}: {q['text']}" for q in qs])
    scale = cfg.get("answer_scale", [-2,-1,0,1,2])
    scale_str = ", ".join(str(x) for x in scale)
    ids = ", ".join([f'"{q["id"]}": null' for q in qs])

    return f"""You are a Cultural Transition Companion AI.

Your role is NOT to diagnose, classify, or label the user.
Your role is to gently explore the user’s lived experience of adapting to a new culture.

Rules:
- Never mention questionnaires, stages, scores, or assessments.
- Ask at most ONE reflective question per turn.
- Be empathetic, non-clinical, culturally sensitive.
- Do not provide medical or mental-health diagnoses.
- You MUST ALWAYS output a SINGLE, VALID JSON object.
- All keys and string values in the JSON output MUST be enclosed in double quotes.
- Use null (lowercase) for null values, not None.

You MUST output JSON in this exact shape:

{{
  "assistant_message": "<natural language response>",
  "signals": {{
    {ids}
  }}
}}

DO NOT output multiple JSON objects, lists of JSON objects, or any text outside of the single JSON object.

Where each signal value is either null or one of: {scale_str}

Signal meaning:
- Each signal corresponds to the user’s sentiment for the hidden question ID.
- Set ONLY signals you can infer from the user’s latest message; leave others null.
- Do NOT ask the question verbatim; ask a subtle reflective prompt that covers the same idea.

Question bank (DO NOT show this list to the user):
{qlines}
""".strip()

# ---- State update helpers (pure / serializable) ----

def normalize_signals(cfg: dict, incoming: Dict[str, Optional[int]]) -> Dict[str, Optional[int]]:
    allowed = set(cfg.get("answer_scale", [-2,-1,0,1,2]))
    out: Dict[str, Optional[int]] = {}
    for q in cfg["questions"]:
        qid = q["id"]
        v = incoming.get(qid, None)
        if v is None:
            out[qid] = None
            continue
        try:
            iv = int(v)
        except Exception:
            out[qid] = None
            continue
        out[qid] = iv if iv in allowed else None
    return out

def update_user_state(cfg: dict, user_state: dict, incoming: Dict[str, Optional[int]]) -> dict:
    # user_state shape:
    # { "signals": {qid: int}, "history": [snapshots...] }
    user_state = user_state or {"signals": {}, "history": []}

    allowed = set(cfg.get("answer_scale", [-2,-1,0,1,2]))
    for q in cfg["questions"]:
        qid = q["id"]
        v = incoming.get(qid, None)
        if v is None:
            continue
        try:
            iv = int(v)
        except Exception:
            continue
        if iv in allowed:
            user_state["signals"][qid] = iv

    probs, conf, scores, coverage = assess_stage(cfg, user_state["signals"])
    snapshot = {
        "timestamp": datetime.utcnow().isoformat(),
        "config_version": cfg.get("version", "unknown"),
        "config_hash": config_hash(cfg),
        "coverage": coverage,
        "stage_probs": probs,
        "stage_scores": scores
    }
    user_state["history"].append(snapshot)
    return user_state
