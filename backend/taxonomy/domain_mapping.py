"""
Mapping tables from the scraper's internal categories/subcategories/skill_types
to the iMocha Gold Taxonomy column values.

All 11 scraper categories are tech-focused, so they all map to the
"Information Technology" domain in the taxonomy.
"""

# DB `category`  →  Taxonomy `Domain`
CATEGORY_TO_DOMAIN: dict[str, str] = {
    "AI/ML & Data":            "Information Technology",
    "Cloud & Infrastructure":  "Information Technology",
    "Databases":               "Information Technology",
    "DevOps & CI/CD":          "Information Technology",
    "Developer Tools":         "Information Technology",
    "Emerging Tech":           "Information Technology",
    "Frameworks & Libraries":  "Information Technology",
    "Methodologies":           "Information Technology",
    "Mobile Development":      "Information Technology",
    "Programming Languages":   "Information Technology",
    "Security":                "Information Technology",
}

# DB `subcategory`  →  Taxonomy `Subdomain`  (within Information Technology)
SUBCATEGORY_TO_SUBDOMAIN: dict[str, str] = {
    "AI Agents":            "AI & Machine Learning",
    "Edge AI":              "AI & Machine Learning",
    "Large Language Models":"AI & Machine Learning",
    "ML Frameworks":        "AI & Machine Learning",
    "Data Science":         "Data & Analytics",
    "Data Engineering":     "Data & Analytics",
    "AWS":                  "Cloud & Infrastructure",
    "Azure":                "Cloud & Infrastructure",
    "GCP":                  "Cloud & Infrastructure",
    "Containers":           "Cloud & Infrastructure",
    "Kubernetes":           "Cloud & Infrastructure",
    "Serverless":           "Cloud & Infrastructure",
    "Platform Engineering": "Cloud & Infrastructure",
    "AppSec":               "Cybersecurity",
    "Cloud Security":       "Cybersecurity",
    "Zero Trust":           "Cybersecurity",
    "NoSQL":                "Database Management",
    "Relational":           "Database Management",
    "Graph":                "Database Management",
    "Cache & Messaging":    "Database Management",
    "Time Series":          "Database Management",
    "Vector Databases":     "Database Management",
    "Agile":                "DevOps & Automation",
    "CI/CD Platforms":      "DevOps & Automation",
    "GitOps":               "DevOps & Automation",
    "Infrastructure as Code":"DevOps & Automation",
    "MLOps & Pipelines":    "DevOps & Automation",
    "Observability":        "DevOps & Automation",
    "Cross-platform":       "Mobile Development",
    "Kotlin":               "Mobile Development",
    "Native iOS":           "Mobile Development",
    "Swift":                "Mobile Development",
    "API":                  "Software Development",
    "Architecture":         "Software Development",
    "C/C++":                "Software Development",
    "Development Practices":"Software Development",
    "Go":                   "Software Development",
    "Java":                 "Software Development",
    "Python":               "Software Development",
    "Rust":                 "Software Development",
    "Supply Chain":         "Software Development",
    "Zig":                  "Software Development",
    "Blockchain":           "Blockchain & Distributed Ledger Technology",
    "Quantum Computing":    "AI & Machine Learning",
    "Frontend":             "Web Development",
    "JavaScript":           "Web Development",
    "TypeScript":           "Web Development",
    "Web Frameworks":       "Web Development",
    "WebAssembly":          "Web Development",
}

# DB `skill_type`  →  Taxonomy `SkillClassification`
SKILLTYPE_TO_CLASSIFICATION: dict[str, str] = {
    "Framework":          "Tool",
    "Library":            "Tool",
    "Methodology":        "Functional Skill",
    "Package":            "Tool",
    "Platform":           "Technical Skill",
    "Product":            "Tool",
    "Programming Language":"Technical Skill",
    "Repository/Tool":    "Tool",
    "Technology Tag":     "Technical Skill",
    "Tool/CLI":           "Tool",
}

# Fallback defaults when no mapping is found
DEFAULT_DOMAIN = "Information Technology"
DEFAULT_SUBDOMAIN = "Software Development"
DEFAULT_CLASSIFICATION = "Technical Skill"
DEFAULT_CRITICALITY = "No"
