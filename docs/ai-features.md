# TaxoTrack AI Features

TaxoTrack uses the Claude API (Anthropic) to enhance five core workflows.
All features degrade gracefully — if `ANTHROPIC_API_KEY` is not set, the
system falls back to rule-based logic and returns `"ai_available": false`.

## Setup

Add to your environment (Vercel or `.env`):
```
ANTHROPIC_API_KEY=sk-ant-...
```

Models used:
- `claude-haiku-4-5-20251001` — bulk operations (classification, dedup, explanations)
- `claude-sonnet-4-6` — reasoning-heavy tasks (taxonomy review, trend analysis)

---

## Feature A: Smart Skill Classification

**Trigger:** Automatically during every scrape run  
**Model:** Haiku (batches of 20 skills)

After the keyword-based classifier, any skill with an empty `category` is sent to
Claude in batches. Claude returns `category`, `subcategory`, and `skill_type`.

This catches novel skills, acronyms, and niche tools that the static keyword table misses.

---

## Feature B: Semantic Deduplication

**Trigger:** Automatically during every scrape run  
**Model:** Haiku (batches of 30 pairs)

After rapidfuzz deduplication, borderline pairs (fuzzy score 75–91) are sent to
Claude. Claude decides if they represent the same underlying skill. Confirmed
duplicates are merged using the same merge logic as exact matches.

Example: `"React Native"` vs `"React-Native"` → confirmed duplicate

---

## Feature C: Taxonomy Merge Review

**Endpoint:** `POST /api/taxonomy/review`  
**Model:** Sonnet  
**When to use:** Before clicking "Merge" in the Taxonomy Manager

Send the same payload as `POST /api/taxonomy/merge`. Claude reviews each skill and returns:

```json
{
  "approved": [{"skill_name": "FastAPI", ...}],
  "flagged":  [{"skill_name": "Software", "reason": "Too generic for taxonomy"}],
  "rejected": [{"skill_name": "v1.2.3", "reason": "Version string, not a skill"}],
  "ai_available": true
}
```

Only send `approved` to `POST /api/taxonomy/merge` after reviewing flagged/rejected.

---

## Feature E: Trend Analysis

**Endpoint:** `GET /api/skills/trends?runs=5`  
**Model:** Sonnet  
**When to use:** After accumulating multiple scrape runs

Returns a structured trend report:

```json
{
  "headline": "AI infrastructure skills dominating this week",
  "rising":   [{"skill": "LangGraph", "reason": "Mentioned across 4 sources"}],
  "declining":[{"skill": "Docker Swarm", "reason": "Absent from last 3 runs"}],
  "emerging": [{"skill": "eBPF", "reason": "First appeared, 3 high-signal sources"}],
  "insight":  "LLM tooling is splitting into orchestration vs. evaluation layers...",
  "ai_available": true,
  "run_count": 5
}
```

---

## Feature F: Confidence Score Explanation

**Endpoint:** `POST /api/skills/explain`  
**Model:** Haiku (batches of 20)

Pass skills from any scrape result and get human-readable explanations:

```json
{
  "skills": [
    {
      "skill_name": "Qdrant",
      "confidence_score": 0.82,
      "explanation": "High confidence — found on GitHub Trending and StackOverflow tags with 2.1k stars, classified correctly as a Vector Database."
    }
  ]
}
```

---

## Costs (approximate)

| Feature | Model | Tokens per call | Calls per scrape |
|---------|-------|----------------|-----------------|
| A — Classification | Haiku | ~800 | 2–5 chunks |
| B — Semantic dedup | Haiku | ~600 | 1–3 chunks |
| C — Merge review | Sonnet | ~2000 | On-demand |
| E — Trend analysis | Sonnet | ~3000 | On-demand |
| F — Explain | Haiku | ~800 | On-demand |

A full scrape run with AI costs approximately $0.01–0.05 depending on volume.
