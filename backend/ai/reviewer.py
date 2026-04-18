"""
AI-powered taxonomy merge reviewer.
Reviews a batch of proposed skills before they are merged into the taxonomy.
Returns three buckets: approved, flagged (with reason), rejected (with reason).
Uses claude-sonnet-4-6 for careful reasoning.
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, SONNET


_PROMPT_TEMPLATE = """\
You are a senior skills taxonomy architect reviewing proposed skills for addition
to the iMocha Gold Taxonomy — a professional HR taxonomy used by enterprise recruiters.

Review each proposed skill and classify it as:
- "approved": clearly a real, distinct, specific technical or professional skill
- "flagged": potentially valid but needs attention (e.g. too generic, unclear scope, possible duplicate of an existing taxonomy entry)
- "rejected": not a skill (noise, version string, product name without skill meaning, too vague)

Existing taxonomy already contains 25,000+ skills. Flag anything that is likely already covered.

Proposed skills (JSON array):
{skills_json}

Return ONLY a JSON object with three keys:
{{
  "approved": [list of skill_name strings],
  "flagged": [{{"skill_name": "...", "reason": "one sentence"}}],
  "rejected": [{{"skill_name": "...", "reason": "one sentence"}}]
}}

No markdown, no explanation outside the JSON.
"""


def ai_review_merge(proposed_skills: list[dict], client=None) -> dict:
    """
    Review proposed skills before taxonomy merge.

    Args:
        proposed_skills: list of dicts with at least 'skill_name', optionally
                         'proposed_domain', 'proposed_subdomain', 'source', 'confidence_score'

    Returns:
        {
            "approved": [{"skill_name": ...}, ...],
            "flagged":  [{"skill_name": ..., "reason": ...}, ...],
            "rejected": [{"skill_name": ..., "reason": ...}, ...],
            "ai_available": True/False
        }
    """
    fallback = {
        "approved": proposed_skills,
        "flagged": [],
        "rejected": [],
        "ai_available": False,
    }

    if client is None:
        client = get_client()
    if client is None:
        return fallback

    skills_input = [
        {
            "skill_name": s.get("skill_name", ""),
            "proposed_domain": s.get("proposed_domain", ""),
            "proposed_subdomain": s.get("proposed_subdomain", ""),
            "source": s.get("source", ""),
            "confidence_score": s.get("confidence_score", 0),
        }
        for s in proposed_skills
    ]

    prompt = _PROMPT_TEMPLATE.format(skills_json=json.dumps(skills_input, indent=2))
    try:
        reply = chat(client, SONNET, prompt, max_tokens=4096)
        reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(reply)

        # Normalise: approved may be list of strings or list of dicts
        approved_raw = result.get("approved", [])
        approved_names = set(
            a if isinstance(a, str) else a.get("skill_name", "")
            for a in approved_raw
        )
        approved = [s for s in proposed_skills if s.get("skill_name") in approved_names]

        return {
            "approved": approved,
            "flagged": result.get("flagged", []),
            "rejected": result.get("rejected", []),
            "ai_available": True,
        }
    except Exception as e:
        fallback["error"] = str(e)
        return fallback
