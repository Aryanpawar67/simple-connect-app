"""
AI reviewer for rejected / unmerged skills.
Identifies which overlooked skills are worth promoting back into the taxonomy.
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, SONNET, batch_chunks

_PROMPT = """\
You are reviewing tech skills that were rejected by an automated scraper (confidence too low)
or scraped but never merged into a professional tech skills taxonomy.

Your job: decide which skills are genuinely valuable and should be reconsidered.

For each skill consider:
- Is this a real, widely-adopted technology, tool, methodology, or recognised skill?
- Is the name clean (not a version string, npm scope, or noise like "the" or "v1.2.3")?
- Would a technical recruiter or senior engineer recognise this as a real skill?
- Higher times_seen = appeared in multiple scrape runs = stronger signal

Skills to review:
{skills_json}

Return ONLY a JSON array. Each object must have exactly:
  - skill_name: string (unchanged from input)
  - verdict: "keep" | "skip"
  - reason: string (max 12 words, plain English)

No markdown, no extra text, no commentary outside the array.
"""


def ai_review_rejected_skills(skills: list[dict], client=None) -> list[dict]:
    if client is None:
        client = get_client()

    if client is None:
        return [
            {
                "skill_name": s.get("skill_name", ""),
                "verdict": "skip",
                "reason": "Set ANTHROPIC_API_KEY for AI recommendations.",
            }
            for s in skills
        ]

    results = []
    for chunk in batch_chunks(skills, 30):
        input_skills = [
            {
                "skill_name": s.get("skill_name", ""),
                "source": s.get("source", ""),
                "confidence_score": round(s.get("confidence_score", 0), 3),
                "category": s.get("category", ""),
                "times_seen": s.get("times_rejected") or s.get("run_count") or 1,
            }
            for s in chunk
        ]
        prompt = _PROMPT.format(skills_json=json.dumps(input_skills, indent=2))
        try:
            reply = chat(client, SONNET, prompt, max_tokens=4096)
            reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            chunk_results = json.loads(reply)
            results.extend(chunk_results)
        except Exception:
            for s in chunk:
                results.append({
                    "skill_name": s.get("skill_name", ""),
                    "verdict": "skip",
                    "reason": "Review failed — check API key and retry.",
                })
    return results
