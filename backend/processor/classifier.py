from scraper.base import SkillRecord

# ── Taxonomy ───────────────────────────────────────────────────────────────────
# Structure: category -> subcategory -> [keyword_signals]
# Matching is case-insensitive substring. Earlier entries take priority.

TAXONOMY = {
    "AI/ML & Data": {
        "Large Language Models": [
            "llm", "gpt", "llama", "mistral", "claude", "gemini", "palm",
            "transformer", "rlhf", "fine-tuning", "finetuning",
            "langchain", "llamaindex", "openai", "anthropic", "pydantic-ai",
            "langgraph", "autogen", "crewai", "smolagents",
        ],
        "ML Frameworks": [
            "pytorch", "tensorflow", "keras", "jax", "sklearn", "scikit",
            "xgboost", "lightgbm", "catboost",
        ],
        "MLOps & Pipelines": [
            "mlflow", "kubeflow", "metaflow", "dvc", "bentoml",
            "seldon", "ray", "feast", "tecton", "mlops", "zenml",
        ],
        "Vector Databases": [
            "qdrant", "pinecone", "weaviate", "milvus", "chroma", "faiss",
            "pgvector", "vector-db", "embedding",
        ],
        "Data Engineering": [
            "spark", "flink", "kafka", "airflow", "prefect", "dagster",
            "dbt", "duckdb", "iceberg", "delta", "hudi", "trino", "presto",
        ],
        "Data Science": [
            "pandas", "numpy", "matplotlib", "seaborn", "plotly", "jupyter",
            "scipy", "statsmodels",
        ],
    },
    "Cloud & Infrastructure": {
        "AWS": ["aws", "ec2", " s3 ", "lambda", "sagemaker", "boto3", "botocore", "eks", "ecs"],
        "Azure": ["azure", "azureml", "cosmos", "aks"],
        "GCP": ["gcp", "google cloud", "bigquery", "vertex ai", "gke"],
        "Kubernetes": ["kubernetes", "k8s", "helm", "kustomize", "argocd", "fluxcd",
                       "istio", "envoy", "cilium", "calico"],
        "Infrastructure as Code": ["terraform", "pulumi", " cdk", "bicep",
                                   "ansible", "chef", "puppet", "crossplane"],
        "Serverless": ["serverless", "knative", "faas"],
    },
    "DevOps & CI/CD": {
        "CI/CD Platforms": ["github actions", "gitlab ci", "jenkins", "circleci",
                            "travis", "teamcity", "bamboo", "drone", "tekton"],
        "GitOps": ["gitops", "fluxcd", "argocd"],
        "Observability": ["prometheus", "grafana", "datadog", "newrelic", "dynatrace",
                          "opentelemetry", "jaeger", "zipkin", "loki", "tempo"],
        "Containers": ["docker", "podman", "buildah", "containerd", "cri-o"],
        "Platform Engineering": ["platform engineering", "backstage", "opslevel",
                                 "cortex", "idp", "internal developer platform"],
    },
    "Programming Languages": {
        "Python": ["python", ".py"],
        "TypeScript": ["typescript", ".tsx"],
        "JavaScript": ["javascript", "node.js", "nodejs", "deno", "bun"],
        "Rust": ["rustlang", "tokio", "actix", " rust "],
        "Go": ["golang", "gin framework", "fiber framework", "echo framework"],
        "Java": ["spring boot", "quarkus", "micronaut", " java "],
        "Kotlin": ["kotlin", "ktor"],
        "Swift": ["swiftui", "swift "],
        "C/C++": ["c++", "cpp", "clang", "llvm"],
        "Zig": ["ziglang", " zig "],
    },
    "Frameworks & Libraries": {
        "Web Frameworks": ["fastapi", "django", "flask", "express", "nestjs",
                           "next.js", "nuxt", "sveltekit", "astro", "remix",
                           "hono", "elysia", "fastify"],
        "Frontend": ["react", "vue", "angular", "svelte", "solid", "htmx",
                     "tailwind", "shadcn", "radix"],
        "AI Agents": ["langgraph", "autogen", "crewai", "agentops",
                      "smolagents", "agentic framework"],
        "API": ["graphql", "grpc", "trpc", "openapi", "swagger"],
    },
    "Databases": {
        "Relational": ["postgresql", "mysql", "sqlite", "cockroachdb", "tidb",
                       "neon", "planetscale", "supabase"],
        "NoSQL": ["mongodb", "cassandra", "dynamodb", "firestore", "couchdb"],
        "Cache & Messaging": ["redis", "memcached", "rabbitmq", "nats", "pulsar"],
        "Time Series": ["timescaledb", "influxdb", "questdb", "clickhouse"],
        "Graph": ["neo4j", "dgraph", "tigergraph"],
    },
    "Security": {
        "AppSec": ["sast", "dast", "snyk", "sonarqube", "semgrep", "trivy",
                   "codeql", "devsecops"],
        "Supply Chain": ["sbom", "sigstore", "cosign", "slsa", "in-toto",
                         "syft", "grype"],
        "Zero Trust": ["zero trust", "ztna", "okta", "auth0", "keycloak",
                       "vault", "opa", "policy as code"],
        "Cloud Security": ["cspm", "cnapp", "wiz", "prisma cloud", "lacework"],
    },
    "Methodologies": {
        "Architecture": ["domain-driven", "ddd", "event sourcing", "cqrs",
                         "hexagonal", "clean architecture", "microservices",
                         "service mesh"],
        "Development Practices": ["tdd", "bdd", "pair programming", "mob programming",
                                  "trunk based", "feature flags", "chaos engineering"],
        "Agile": ["scrum", "kanban", "okr", "shape up", "lean"],
    },
    "Emerging Tech": {
        "Quantum Computing": ["quantum", "qiskit", "braket", "cirq"],
        "Edge AI": ["edge ai", "tinyml", "onnx", "tensorrt", "tflite", "webnn"],
        "WebAssembly": ["webassembly", "wasm", "wasmtime", "wasmer", "spin"],
        "Spatial Computing": ["spatial computing", "apple vision", " xr "],
        "Blockchain": ["web3", "solidity", "ethereum", "smart contract", "defi"],
    },
    "Mobile Development": {
        "Cross-platform": ["flutter", "react native", "ionic", "capacitor",
                           "expo", "kotlin multiplatform"],
        "Native iOS": ["uikit", "xcode", "swiftui"],
        "Native Android": ["jetpack compose", "android studio"],
    },
}

# Flat lookup: keyword -> (category, subcategory)
_FLAT_LOOKUP: dict = {}
for _cat, _subs in TAXONOMY.items():
    for _sub, _keywords in _subs.items():
        for _kw in _keywords:
            _FLAT_LOOKUP[_kw.lower()] = (_cat, _sub)

SKILL_TYPE_RULES = [
    (["fastapi", "django", "flask", "express", "nestjs", "next.js", "nuxt",
      "sveltekit", "astro", "remix", "hono", "framework"], "Framework"),
    (["pandas", "numpy", "boto3", "langchain", "library", "sdk"], "Library"),
    (["aws", "azure", "gcp", "kubernetes", "k8s", "platform"], "Platform"),
    (["helm", "terraform", "ansible", "docker", "cli", "tool"], "Tool/CLI"),
    (["ddd", "tdd", "bdd", "scrum", "kanban", "gitops", "devops", "mlops",
      "methodology"], "Methodology"),
    (["python", "rust", "golang", "typescript", "javascript", "kotlin",
      "swift", "language"], "Programming Language"),
]


def classify(record: SkillRecord) -> SkillRecord:
    """Assign category, subcategory, skill_type in-place. Returns the record."""
    name_lower = record.skill_name.lower()
    combined = f"{name_lower} {' '.join(record.tags).lower()} {record.description.lower()}"

    matched_cat = ""
    matched_sub = ""

    # Pass 1: match against skill_name only (highest precision)
    for keyword, (cat, sub) in _FLAT_LOOKUP.items():
        if keyword in name_lower:
            matched_cat = cat
            matched_sub = sub
            break

    # Pass 2: if no name match, fall back to combined text (tags + description)
    if not matched_cat:
        for keyword, (cat, sub) in _FLAT_LOOKUP.items():
            if keyword in combined:
                matched_cat = cat
                matched_sub = sub
                break

    record.category = matched_cat or _infer_category_from_source(record)
    record.subcategory = matched_sub

    for signals, skill_type in SKILL_TYPE_RULES:
        if any(sig in combined for sig in signals):
            record.skill_type = skill_type
            break
    if not record.skill_type:
        record.skill_type = _infer_skill_type_from_source(record)

    return record


def _infer_category_from_source(record: SkillRecord) -> str:
    source_to_category = {
        "npm_trending": "Frameworks & Libraries",
        "pypi_trending": "Frameworks & Libraries",
        "cncf_landscape": "Cloud & Infrastructure",
        "thoughtworks_radar": "Methodologies",
        "arxiv": "Emerging Tech",
        "product_hunt": "Emerging Tech",
    }
    return source_to_category.get(record.source, "Developer Tools")


def _infer_skill_type_from_source(record: SkillRecord) -> str:
    source_to_type = {
        "npm_trending": "Package",
        "pypi_trending": "Package",
        "stackoverflow_tags": "Technology Tag",
        "github_trending": "Repository/Tool",
        "product_hunt": "Product",
    }
    return source_to_type.get(record.source, "Tool/CLI")


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
