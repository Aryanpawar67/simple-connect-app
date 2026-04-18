"""
AI confidence score explainer.
Takes skills with confidence_score + metadata and generates a 1-sentence
explanation of why the score is what it is.
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, HAIKU, batch_chunks


_PROMPT_TEMPLATE = """\
You are explaining confidence scores assigned to tech skills discovered by a scraper.
The score (0.0 to 1.0) is based on: source quality, how many sources mentioned it,
popularity signals (stars/downloads), whether it has a recognised category, and noise filters.

For each skill, write a single concise sentence (max 20 words) explaining the score in plain English.
Be specific: mention the sources, the score range meaning (0.0-0.4 = low, 0.4-0.7 = medium, 0.7-1.0 = high).

Skills (JSON array):
{skills_json}

Return ONLY a JSON array of objects: [{{"skill_name": "...", "explanation": "one sentence"}}]
No markdown, no extra keys.
"""


def ai_explain_skills(skills: list[dict], client=None) -> list[dict]:
    """
    Add an 'explanation' field to each skill dict.
    Falls back gracefully — returns skills with a default explanation if API unavailable.

    Args:
        skills: list of dicts with at minimum: skill_name, confidence_score, source

    Returns:
        Same list with 'explanation' field added to each.
    """
    if client is None:
        client = get_client()

    if client is None:
        for s in skills:
            score = s.get("confidence_score", 0)
            level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
            s["explanation"] = (
                f"{level.capitalize()} confidence ({score:.2f}) based on source quality "
                f"and appearance count. Set ANTHROPIC_API_KEY for detailed explanations."
            )
        return skills

    for chunk in batch_chunks(skills, 20):
        skills_input = [
            {
                "skill_name": s.get("skill_name", ""),
                "confidence_score": round(s.get("confidence_score", 0), 3),
                "source": s.get("source", ""),
                "category": s.get("category", ""),
                "is_new": s.get("is_new", True),
            }
            for s in chunk
        ]
        prompt = _PROMPT_TEMPLATE.format(skills_json=json.dumps(skills_input, indent=2))
        try:
            reply = chat(client, HAIKU, prompt, max_tokens=2048)
            reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results = json.loads(reply)
            result_map = {r["skill_name"]: r["explanation"] for r in results}
            for skill in chunk:
                skill["explanation"] = result_map.get(
                    skill.get("skill_name", ""),
                    f"Score {skill.get('confidence_score', 0):.2f} based on source signals.",
                )
        except Exception:
            for skill in chunk:
                score = skill.get("confidence_score", 0)
                skill["explanation"] = f"Score {score:.2f} based on source signals."

    return skills
