from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="Stable user identifier (uuid/email/hash).")
    message: str = Field(..., min_length=1)
    # Optional conversation history (last few turns). If you store history in Redis, you can omit this.
    history: Optional[List[Dict[str, str]]] = None  # [{"role":"user|assistant","content":"..."}]

class ChatResponse(BaseModel):
    assistant_message: str
    stage_probs: Dict[str, float]
    confidence: str
    coverage: float
    signals: Dict[str, Optional[int]]
    config_version: str
