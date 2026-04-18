"""
Shared Claude API client for TaxoTrack AI features.

Usage:
    from ai.client import get_client, chat, HAIKU, SONNET

    client = get_client()          # None if ANTHROPIC_API_KEY not set
    if client:
        reply = chat(client, HAIKU, "Classify this skill: FastAPI")
"""
from __future__ import annotations
import os
import textwrap
from typing import Optional

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"


def get_client():
    """
    Return an Anthropic client if ANTHROPIC_API_KEY is set, else None.
    All AI features check this — graceful degradation when key is absent.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


def chat(client, model: str, prompt: str, max_tokens: int = 2048) -> str:
    """
    Send a single user message, return the text reply.
    Raises on API error — callers should catch and fall back to rule-based logic.
    """
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": textwrap.dedent(prompt).strip()}],
    )
    return response.content[0].text.strip()


def batch_chunks(items: list, size: int = 20) -> list[list]:
    """Split a list into chunks of `size` for batched API calls."""
    return [items[i : i + size] for i in range(0, len(items), size)]
