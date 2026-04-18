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
