"""Chat API router — POST /chat and GET /chat/{session_id}/history."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.chat.engine import ChatEngine, create_chat_engine

router = APIRouter(prefix="/chat", tags=["chat"])

# Module-level engine instance, initialized on first request
_engine: Optional[ChatEngine] = None


def _get_engine() -> ChatEngine:
    global _engine
    if _engine is None:
        _engine = create_chat_engine()
    return _engine


class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_id: str = "anonymous"


class ActionResponse(BaseModel):
    label: str
    action_id: str
    value: str = ""
    style: str = "default"


class ChatResponseModel(BaseModel):
    text: str
    structured_data: Optional[Dict[str, Any]] = None
    actions: List[ActionResponse] = []
    severity: str = "info"
    conversation_id: str = ""


@router.post("", response_model=ChatResponseModel)
async def chat(request: ChatRequest) -> ChatResponseModel:
    """Send a message to the Reflex chat agent."""
    engine = _get_engine()
    response = await engine.chat(
        session_id=request.session_id,
        message=request.message,
        user_id=request.user_id,
    )
    return ChatResponseModel(
        text=response.text,
        structured_data=response.structured_data,
        actions=[
            ActionResponse(
                label=a.label,
                action_id=a.action_id,
                value=a.value,
                style=a.style,
            )
            for a in response.actions
        ],
        severity=response.severity,
        conversation_id=response.conversation_id,
    )
