"""
AI trend analysis across scrape runs.
Reads historical skill data and generates a structured trend report.
Uses claude-sonnet-4-6 for reasoning quality.
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, SONNET


_PROMPT_TEMPLATE = """\
You are a tech talent market analyst. Based on the skill scrape history below,
write a concise trend report. Data covers the last {n_runs} scrape runs.

Each run shows which skills appeared and from which sources.

Top skills by frequency across all runs:
{top_skills_json}

New skills appearing for the first time in the most recent run:
{new_skills_json}

Sources and their run-over-run counts:
{source_counts_json}

Write a JSON report with this exact structure:
{{
  "headline": "One punchy sentence summarising the biggest trend",
  "rising": [
    {{"skill": "skill name", "reason": "why it is rising (1 sentence)"}}
  ],
  "declining": [
    {{"skill": "skill name", "reason": "why it appears to be declining (1 sentence)"}}
  ],
  "emerging": [
    {{"skill": "skill name", "reason": "newly appearing, why it matters (1 sentence)"}}
  ],
  "insight": "2-3 sentence paragraph with the key strategic insight for a recruiter or L&D team"
}}

Limit: 5 items in rising, 3 in declining, 5 in emerging.
Return ONLY the JSON, no markdown fences.
"""


def ai_analyze_trends(runs: list[dict], recent_skills: list[dict], client=None) -> dict:
    """
    Args:
        runs: list of scrape run dicts from db.list_runs()
        recent_skills: skills from the most recent run (db.skills_by_date())

    Returns structured trend report dict, or a fallback if AI not available.
    """
    fallback = {
        "ai_available": False,
        "headline": "AI trend analysis requires ANTHROPIC_API_KEY.",
        "rising": [],
        "declining": [],
        "emerging": [],
        "insight": "Set ANTHROPIC_API_KEY in your environment to enable AI trend analysis.",
        "run_count": len(runs),
    }

    if client is None:
        client = get_client()
    if client is None or not runs:
        return fallback

    # Summarise data to keep prompt size manageable
    from collections import Counter
    source_counts: Counter = Counter()
    for run in runs:
        for src in (run.get("sources") or "").split(","):
            src = src.strip()
            if src:
                source_counts[src] += 1

    # Top skills by name from recent run (up to 40)
    top_skills = [
        {"skill": s.get("skill_name"), "source": s.get("source"), "is_new": s.get("is_new")}
        for s in sorted(recent_skills, key=lambda x: x.get("confidence_score", 0), reverse=True)[:40]
    ]
    new_skills = [s for s in top_skills if s.get("is_new")][:20]

    prompt = _PROMPT_TEMPLATE.format(
        n_runs=len(runs),
        top_skills_json=json.dumps(top_skills, indent=2),
        new_skills_json=json.dumps(new_skills, indent=2),
        source_counts_json=json.dumps(dict(source_counts.most_common()), indent=2),
    )

    try:
        reply = chat(client, SONNET, prompt, max_tokens=2048)
        reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(reply)
        result["ai_available"] = True
        result["run_count"] = len(runs)
        return result
    except Exception as e:
        fallback["error"] = str(e)
        return fallback
