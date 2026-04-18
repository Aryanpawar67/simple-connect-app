# Claude AI Integration for TaxoTrack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Claude API into TaxoTrack to power five AI features: smart skill classification, semantic deduplication, taxonomy merge review, trend analysis, and confidence score explanations.

**Architecture:** Add a `backend/ai/` package with one module per feature, all sharing a thin `client.py` wrapper. Features degrade gracefully when `ANTHROPIC_API_KEY` is absent — existing rule-based pipeline continues to work unchanged. High-volume bulk operations (classification, dedup, explanations) use `claude-haiku-4-5-20251001`; reasoning-heavy operations (taxonomy review, trend analysis) use `claude-sonnet-4-6`.

**Tech Stack:** `anthropic` Python SDK, FastAPI (existing), psycopg2 + Neon DB (existing), `claude-haiku-4-5-20251001` and `claude-sonnet-4-6`

---

## File Map

| File | Action | Purpose |
|------|---------|---------|
| `backend/ai/__init__.py` | **Create** | Package marker |
| `backend/ai/client.py` | **Create** | Shared Claude API wrapper: create client, call with retry, batch helper |
| `backend/ai/classifier.py` | **Create** | AI classification for skills that keyword-matching couldn't classify |
| `backend/ai/deduplicator.py` | **Create** | Semantic dedup — Claude decides if fuzzy-match candidates are truly duplicates |
| `backend/ai/reviewer.py` | **Create** | Pre-merge taxonomy review: approved / flagged / rejected |
| `backend/ai/trends.py` | **Create** | Analyze scrape-run history and produce trend report |
| `backend/ai/explainer.py` | **Create** | Generate human-readable explanation for each skill's confidence score |
| `backend/processor/classifier.py` | **Modify** | After rule-based pass, call AI classifier for unmatched skills |
| `backend/processor/deduplicator.py` | **Modify** | After fuzzy pass, call AI dedup on borderline candidates (score 75–91) |
| `backend/api_bridge.py` | **Modify** | After processing, call AI explainer if key present; emit explanations in `complete` event |
| `backend/server.py` | **Modify** | Add `POST /api/taxonomy/review`, `GET /api/skills/trends`, `POST /api/skills/explain` |
| `backend/requirements.txt` | **Modify** | Add `anthropic>=0.40.0` |
| `docs/ai-features.md` | **Create** | User-facing documentation of all five AI features |

---

## Task 1: Install SDK + core AI client

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/ai/__init__.py`
- Create: `backend/ai/client.py`

- [ ] **Add `anthropic` to requirements.txt**

Open `backend/requirements.txt` and append:

```text
# Claude AI
anthropic>=0.40.0
```

- [ ] **Install locally**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
pip install anthropic>=0.40.0
```

Expected: `Successfully installed anthropic-X.Y.Z`

- [ ] **Create `backend/ai/__init__.py`**

```python
"""AI-powered features for TaxoTrack — powered by Anthropic Claude."""
```

- [ ] **Create `backend/ai/client.py`**

```python
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
```

- [ ] **Verify import works**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
python -c "from ai.client import get_client, HAIKU, SONNET; print('OK', HAIKU, SONNET)"
```

Expected: `OK claude-haiku-4-5-20251001 claude-sonnet-4-6`

- [ ] **Commit**

```bash
git add backend/requirements.txt backend/ai/
git commit -m "feat: add ai/ package with shared Claude client"
```

---

## Task 2: AI Skill Classifier (Feature A)

**Files:**
- Create: `backend/ai/classifier.py`
- Modify: `backend/processor/classifier.py`

When the keyword-based classifier returns an empty `category` (i.e., the skill didn't match any lookup entry), Claude classifies it using context from the skill's name, source, tags, and description.

- [ ] **Create `backend/ai/classifier.py`**

```python
"""
AI-powered skill classifier.
Called for skills that keyword matching couldn't classify.
Batches 20 skills per Claude call to minimise latency and cost.
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, HAIKU, batch_chunks


_PROMPT_TEMPLATE = """\
You are an expert IT skills taxonomist. Classify each skill below into the
most appropriate category, subcategory, and skill_type.

Allowed categories and their subcategories:
- AI/ML & Data: Large Language Models, ML Frameworks, MLOps & Pipelines, Vector Databases, Data Engineering, Data Science
- Cloud & Infrastructure: AWS, Azure, GCP, Kubernetes, Infrastructure as Code, Serverless
- DevOps & CI/CD: CI/CD Platforms, GitOps, Observability, Containers, Platform Engineering
- Programming Languages: Python, TypeScript, JavaScript, Rust, Go, Java, Kotlin, Swift, C/C++, Zig
- Frameworks & Libraries: Web Frameworks, Frontend, AI Agents, API
- Databases: Relational, NoSQL, Cache & Messaging, Time Series, Graph
- Security: AppSec, Supply Chain, Zero Trust, Cloud Security
- Methodologies: Architecture, Development Practices, Agile
- Emerging Tech: Quantum Computing, Edge AI, WebAssembly, Spatial Computing, Blockchain
- Mobile Development: Cross-platform, Native iOS, Native Android
- Developer Tools: (catch-all for tools that don't fit above)

Allowed skill_type values:
Framework, Library, Platform, Tool/CLI, Methodology, Programming Language, Package, Product, Technology Tag, Repository/Tool

Skills to classify (JSON array):
{skills_json}

Return ONLY a JSON array of objects with keys: skill_name, category, subcategory, skill_type.
No explanation, no markdown, just the JSON array.
"""


def ai_classify(records: list, client=None) -> list:
    """
    Classify a list of SkillRecord objects that have empty category.
    Mutates records in-place, returns the list.
    Falls back silently if client is None or API call fails.
    """
    if client is None:
        client = get_client()
    if client is None:
        return records

    unclassified = [r for r in records if not r.category]
    if not unclassified:
        return records

    for chunk in batch_chunks(unclassified, 20):
        skills_input = [
            {
                "skill_name": r.skill_name,
                "source": r.source,
                "tags": r.tags[:5],
                "description": r.description[:200],
            }
            for r in chunk
        ]
        prompt = _PROMPT_TEMPLATE.format(skills_json=json.dumps(skills_input, indent=2))
        try:
            reply = chat(client, HAIKU, prompt, max_tokens=2048)
            # Strip markdown fences if model wraps response
            reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results = json.loads(reply)
            result_map = {r["skill_name"]: r for r in results}
            for record in chunk:
                if record.skill_name in result_map:
                    hit = result_map[record.skill_name]
                    record.category = hit.get("category", "") or record.category
                    record.subcategory = hit.get("subcategory", "") or record.subcategory
                    record.skill_type = hit.get("skill_type", "") or record.skill_type
        except Exception:
            # Fail silently — rule-based classification stays as-is
            pass

    return records
```

- [ ] **Hook AI classifier into `backend/processor/classifier.py`**

Add these lines at the very bottom of `classify()` function — after `return record` is reached normally, classification is done. Instead, we call the batch AI classifier from `api_bridge.py` after the full classify pass. Open `backend/processor/classifier.py` and add this at the end of the file (do NOT modify the `classify()` function itself):

```python
# ---------------------------------------------------------------------------
# AI enhancement (optional — only runs when ANTHROPIC_API_KEY is set)
# ---------------------------------------------------------------------------

def ai_enhance_classification(records: list) -> list:
    """
    Run AI classification on any records still missing a category.
    Called from api_bridge.py after the full classify() pass.
    No-op if ANTHROPIC_API_KEY is not set.
    """
    try:
        from ai.classifier import ai_classify
        return ai_classify(records)
    except Exception:
        return records
```

- [ ] **Call `ai_enhance_classification` in `backend/api_bridge.py`**

In `api_bridge.py`, find the line:
```python
emit("processing", message="Classifying skills…")
records = [classify(r) for r in all_records]
```

Replace with:
```python
_emit("processing", message="Classifying skills…")
records = [classify(r) for r in all_records]

_emit("processing", message="AI-enhancing unclassified skills…")
from processor.classifier import ai_enhance_classification
records = ai_enhance_classification(records)
```

- [ ] **Smoke-test locally (no API key needed — should no-op gracefully)**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
python -c "
from processor.classifier import ai_enhance_classification
from scraper.base import SkillRecord
records = [SkillRecord(skill_name='TestSkill', source='github_trending')]
result = ai_enhance_classification(records)
print('OK, records:', len(result))
"
```

Expected: `OK, records: 1` (no crash, no API call)

- [ ] **Commit**

```bash
git add backend/ai/classifier.py backend/processor/classifier.py backend/api_bridge.py
git commit -m "feat(ai): AI skill classifier for unmatched skills (Feature A)"
```

---

## Task 3: Semantic Deduplicator (Feature B)

**Files:**
- Create: `backend/ai/deduplicator.py`
- Modify: `backend/processor/deduplicator.py`

After rapidfuzz's fuzzy pass, there's a grey zone: pairs scoring 75–91 where it's unclear if they're truly the same skill. Claude decides.

- [ ] **Create `backend/ai/deduplicator.py`**

```python
"""
Semantic deduplication using Claude.
Called after rapidfuzz to resolve borderline fuzzy-match candidates
(score between 75 and 91 inclusive).
"""
from __future__ import annotations
import json
from ai.client import get_client, chat, HAIKU, batch_chunks


_PROMPT_TEMPLATE = """\
You are an expert in tech skill taxonomy deduplication.
For each pair of skill names below, decide if they represent the SAME underlying skill.
Be strict: only mark as duplicate if a recruiter or engineer would consider them interchangeable.

Pairs (JSON array of {{a, b}}):
{pairs_json}

Return ONLY a JSON array of objects with keys: a, b, is_duplicate (boolean).
No explanation, no markdown, just the JSON array.
"""


def ai_find_duplicates(candidate_pairs: list[tuple[str, str]], client=None) -> set[tuple[str, str]]:
    """
    Given a list of (name_a, name_b) pairs that fuzzy-matched in the grey zone,
    return the set of pairs Claude confirms as true duplicates.

    Falls back to empty set (keep all as-is) if client is None or API fails.
    """
    if client is None:
        client = get_client()
    if client is None or not candidate_pairs:
        return set()

    confirmed: set[tuple[str, str]] = set()

    for chunk in batch_chunks(candidate_pairs, 30):
        pairs_input = [{"a": a, "b": b} for a, b in chunk]
        prompt = _PROMPT_TEMPLATE.format(pairs_json=json.dumps(pairs_input, indent=2))
        try:
            reply = chat(client, HAIKU, prompt, max_tokens=2048)
            reply = reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            results = json.loads(reply)
            for r in results:
                if r.get("is_duplicate"):
                    confirmed.add((r["a"], r["b"]))
                    confirmed.add((r["b"], r["a"]))  # symmetrical
        except Exception:
            pass

    return confirmed
```

- [ ] **Hook AI dedup into `backend/processor/deduplicator.py`**

Add this function at the bottom of `deduplicator.py` (do NOT change the existing `deduplicate()` function):

```python
# ---------------------------------------------------------------------------
# AI enhancement (optional)
# ---------------------------------------------------------------------------

def ai_enhance_dedup(records: list, fuzzy_low: int = 75, fuzzy_high: int = 91) -> list:
    """
    Find borderline fuzzy candidates (score in [fuzzy_low, fuzzy_high]) and ask
    Claude to confirm which are true duplicates. Merges confirmed pairs.
    No-op if ANTHROPIC_API_KEY is not set.
    """
    try:
        from ai.deduplicator import ai_find_duplicates
    except Exception:
        return records

    names = [r.skill_name for r in records]
    candidate_pairs: list[tuple[str, str]] = []

    used_indices: set[int] = set()
    for i, record in enumerate(records):
        if i in used_indices:
            continue
        results = process.extract(
            record.skill_name,
            names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=fuzzy_low,
            limit=None,
        )
        for _, score_val, j in results:
            if j != i and j not in used_indices and score_val <= fuzzy_high:
                candidate_pairs.append((record.skill_name, records[j].skill_name))

    if not candidate_pairs:
        return records

    confirmed = ai_find_duplicates(candidate_pairs)

    # Merge confirmed duplicate pairs
    name_to_idx = {r.skill_name: i for i, r in enumerate(records)}
    merged_indices: set[int] = set()
    final = []

    for i, record in enumerate(records):
        if i in merged_indices:
            continue
        group = [record]
        for a, b in confirmed:
            if a == record.skill_name and b in name_to_idx:
                j = name_to_idx[b]
                if j not in merged_indices and j != i:
                    group.append(records[j])
                    merged_indices.add(j)
        merged_indices.add(i)
        final.append(_merge_group(group))

    return final
```

- [ ] **Call `ai_enhance_dedup` in `api_bridge.py`**

In `api_bridge.py`, find:
```python
_emit("processing", message="Deduplicating…")
records = deduplicate(records)
```

Replace with:
```python
_emit("processing", message="Deduplicating…")
records = deduplicate(records)

_emit("processing", message="AI semantic dedup check…")
from processor.deduplicator import ai_enhance_dedup
records = ai_enhance_dedup(records)
```

- [ ] **Smoke-test**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
python -c "
from processor.deduplicator import ai_enhance_dedup
from scraper.base import SkillRecord
records = [
    SkillRecord(skill_name='React', source='github_trending'),
    SkillRecord(skill_name='ReactJS', source='npm_trending'),
]
result = ai_enhance_dedup(records)
print('Records after AI dedup:', len(result))
"
```

Expected: `Records after AI dedup: 1` or `2` depending on whether ANTHROPIC_API_KEY is set. No crash either way.

- [ ] **Commit**

```bash
git add backend/ai/deduplicator.py backend/processor/deduplicator.py backend/api_bridge.py
git commit -m "feat(ai): semantic dedup for fuzzy-match grey zone (Feature B)"
```

---

## Task 4: Taxonomy Merge Reviewer (Feature C)

**Files:**
- Create: `backend/ai/reviewer.py`
- Modify: `backend/server.py`

New endpoint `POST /api/taxonomy/review` that Claude reviews before the user confirms a merge.

- [ ] **Create `backend/ai/reviewer.py`**

```python
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
```

- [ ] **Add `POST /api/taxonomy/review` to `backend/server.py`**

Read `server.py` and find the taxonomy routes section (around the `POST /api/taxonomy/merge` endpoint). Add this new endpoint immediately before it:

```python
@app.post("/api/taxonomy/review")
async def taxonomy_review(body: MergeRequest):
    """
    AI review of proposed skills before merge.
    Returns approved / flagged / rejected buckets.
    Falls back to all-approved if ANTHROPIC_API_KEY is not set.
    """
    if not body.approved_skills:
        raise HTTPException(status_code=400, detail="No skills provided.")
    from ai.reviewer import ai_review_merge
    proposed = [s.model_dump() for s in body.approved_skills]
    return ai_review_merge(proposed)
```

- [ ] **Smoke-test the endpoint locally**

Start the server locally first:
```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
uvicorn server:app --port 8002 &
sleep 3
```

Then test:
```bash
curl -s -X POST http://localhost:8002/api/taxonomy/review \
  -H "Content-Type: application/json" \
  -d '{"approved_skills":[{"skill_name":"FastAPI","proposed_domain":"Information Technology","proposed_subdomain":"Software Engineering","proposed_cluster":"","proposed_classification":"Technical Skill","proposed_criticality":"No"}]}' \
  | python3 -m json.tool
```

Expected: JSON with `approved`, `flagged`, `rejected` keys and `"ai_available": false` (if no API key set) or `true`.

Kill server:
```bash
kill $(lsof -ti:8002) 2>/dev/null
```

- [ ] **Commit**

```bash
git add backend/ai/reviewer.py backend/server.py
git commit -m "feat(ai): taxonomy merge reviewer endpoint POST /api/taxonomy/review (Feature C)"
```

---

## Task 5: Trend Analyzer (Feature E)

**Files:**
- Create: `backend/ai/trends.py`
- Modify: `backend/server.py`

New endpoint `GET /api/skills/trends` reads the last N scrape runs from Neon, sends skill delta data to Claude, and returns a structured trend report.

- [ ] **Create `backend/ai/trends.py`**

```python
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
```

- [ ] **Add `GET /api/skills/trends` to `backend/server.py`**

Find the Skills Discovery routes section in `server.py`. Add after `/api/skills/history`:

```python
@app.get("/api/skills/trends")
async def skills_trends(runs: int = Query(5, ge=1, le=20)):
    """
    AI trend analysis across the last N scrape runs.
    Requires ANTHROPIC_API_KEY; returns ai_available=false otherwise.
    """
    from ai.trends import ai_analyze_trends
    db = _open_db(_DB_CONFIG)
    if db is None:
        raise HTTPException(status_code=503, detail="DB unavailable.")
    try:
        run_history = db.list_runs(limit=runs)
        if not run_history:
            return {"ai_available": False, "headline": "No scrape runs found.", "run_count": 0}
        # Get skills from most recent run
        most_recent_date = str(run_history[0]["run_date"])
        recent_skills = db.skills_by_date(most_recent_date)
    finally:
        db.close()
    return ai_analyze_trends(run_history, recent_skills)
```

- [ ] **Smoke-test**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
uvicorn server:app --port 8002 &
sleep 3
curl -s "http://localhost:8002/api/skills/trends?runs=3" | python3 -m json.tool
kill $(lsof -ti:8002) 2>/dev/null
```

Expected: JSON with `ai_available`, `headline`, `rising`, `declining`, `emerging`, `insight`, `run_count`.

- [ ] **Commit**

```bash
git add backend/ai/trends.py backend/server.py
git commit -m "feat(ai): trend analysis endpoint GET /api/skills/trends (Feature E)"
```

---

## Task 6: Confidence Score Explainer (Feature F)

**Files:**
- Create: `backend/ai/explainer.py`
- Modify: `backend/server.py`

New endpoint `POST /api/skills/explain` takes a list of skill dicts and returns each with a human-readable explanation of its confidence score.

- [ ] **Create `backend/ai/explainer.py`**

```python
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
```

- [ ] **Add `POST /api/skills/explain` to `backend/server.py`**

Find the Skills Discovery routes in `server.py`. Add after `/api/skills/trends`:

```python
class ExplainRequest(BaseModel):
    skills: list[dict]


@app.post("/api/skills/explain")
async def skills_explain(body: ExplainRequest):
    """
    Generate AI explanations for confidence scores.
    Pass a list of skill dicts (must have skill_name, confidence_score, source).
    Returns same list with 'explanation' field added.
    Falls back to a rule-based explanation if ANTHROPIC_API_KEY is not set.
    """
    if not body.skills:
        raise HTTPException(status_code=400, detail="No skills provided.")
    from ai.explainer import ai_explain_skills
    return {"skills": ai_explain_skills(body.skills)}
```

- [ ] **Smoke-test**

```bash
cd /Users/aryan/Desktop/simple-connect-app/backend
uvicorn server:app --port 8002 &
sleep 3
curl -s -X POST http://localhost:8002/api/skills/explain \
  -H "Content-Type: application/json" \
  -d '{"skills":[{"skill_name":"FastAPI","confidence_score":0.85,"source":"github_trending,stackoverflow_tags","category":"Frameworks & Libraries","is_new":true}]}' \
  | python3 -m json.tool
kill $(lsof -ti:8002) 2>/dev/null
```

Expected: `{"skills": [{"skill_name": "FastAPI", "confidence_score": 0.85, ..., "explanation": "..."}]}`

- [ ] **Commit**

```bash
git add backend/ai/explainer.py backend/server.py
git commit -m "feat(ai): confidence score explainer POST /api/skills/explain (Feature F)"
```

---

## Task 7: Add ANTHROPIC_API_KEY to Vercel + documentation

**Files:**
- Create: `docs/ai-features.md`
- Modify: `backend/.env.example`

- [ ] **Update `.env.example`**

Open `backend/.env.example` and add:

```bash
# Claude AI (optional — all AI features degrade gracefully without this)
ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Create `docs/ai-features.md`**

```markdown
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
```

- [ ] **Push everything**

```bash
git add docs/ai-features.md backend/.env.example
git commit -m "docs: AI features documentation + env example update"
git push origin main
```

- [ ] **Add `ANTHROPIC_API_KEY` to Vercel**

Go to Vercel → Project → Settings → Environment Variables → Add:
- Key: `ANTHROPIC_API_KEY`
- Value: `sk-ant-...` (your key)
- Environment: Production + Preview

Redeploy will trigger automatically on next push.
```

---

## Self-Review

**Spec coverage:**
- Feature A (classification): Task 2 ✓
- Feature B (semantic dedup): Task 3 ✓
- Feature C (taxonomy review): Task 4 ✓
- Feature E (trend analysis): Task 5 ✓
- Feature F (confidence explanation): Task 6 ✓
- Documentation: Task 7 ✓

**Placeholder scan:** All code blocks are complete. No TBDs.

**Type consistency:**
- `ai_classify(records: list)` → called in `ai_enhance_classification(records)` ✓
- `ai_find_duplicates(candidate_pairs: list[tuple[str,str]])` → called in `ai_enhance_dedup()` ✓
- `ai_review_merge(proposed_skills: list[dict])` → called in `/api/taxonomy/review` endpoint ✓
- `ai_analyze_trends(runs, recent_skills)` → called in `/api/skills/trends` endpoint ✓
- `ai_explain_skills(skills: list[dict])` → called in `/api/skills/explain` endpoint ✓
- `batch_chunks(items, size)` → used in classifier, deduplicator, explainer ✓
- `chat(client, model, prompt, max_tokens)` → consistent across all modules ✓
