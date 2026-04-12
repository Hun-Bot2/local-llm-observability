"""Human-owned translation quality policy.

This is the initial machine-readable version of the rubric. The human review
process should edit this policy over time, then use the DB rubric history for
experiments and regression checks.
"""

SERVICE_ACCURACY_RUBRIC_VERSION = "service_accuracy_v1"

DEFAULT_RULES = [
    {
        "id": "adequacy",
        "name": "Meaning is preserved",
        "description": "The target text must preserve the source meaning without omission, contradiction, or invented content.",
        "major_error": "Missing or incorrect technical meaning.",
        "critical_error": "Invented sections, links, claims, or instructions.",
    },
    {
        "id": "fluency",
        "name": "Natural target-language prose",
        "description": "Japanese uses natural desu/masu technical blog style; English uses natural developer blog style.",
        "major_error": "Awkward phrasing that changes readability or tone.",
        "critical_error": "Unusable or incoherent target-language output.",
    },
    {
        "id": "terminology",
        "name": "Terminology consistency",
        "description": "Glossary terms, product names, libraries, model names, and technical terms must be consistent.",
        "major_error": "Wrong or inconsistent technical term.",
        "critical_error": "Wrong term that changes implementation meaning.",
    },
    {
        "id": "structure",
        "name": "MDX and Markdown structure preserved",
        "description": "Headings, lists, tables, links, frontmatter, code fences, inline code, and placeholders must not be added, removed, or corrupted.",
        "major_error": "Markdown structure changed.",
        "critical_error": "Code fence/frontmatter/link corruption or invented links.",
    },
    {
        "id": "register",
        "name": "Author voice and register preserved",
        "description": "The translation should preserve the author's developer-log voice without becoming promotional or explanatory.",
        "major_error": "Tone is too formal, promotional, or explanatory.",
        "critical_error": "Translator commentary or unrelated article prose appears.",
    },
]

DEFAULT_WEIGHTS = {
    "adequacy": 0.35,
    "structure": 0.25,
    "terminology": 0.20,
    "fluency": 0.10,
    "register": 0.10,
}

DEFAULT_THRESHOLDS = {
    "segment_pass_rate_mqm": 0.99,
    "structural_validity_pass_rate": 0.999,
    "hard_validator_required": True,
    "critical_errors_allowed": 0,
    "major_errors_allowed_per_segment": 0,
    "review_if_validator_fails": True,
    "review_if_qe_unavailable": False,
    "future_qe_accept_threshold": 0.85,
    "future_qe_review_threshold": 0.70,
}


def default_rubric_for(target_lang: str) -> dict:
    return {
        "name": "service_accuracy",
        "target_lang": target_lang,
        "version": SERVICE_ACCURACY_RUBRIC_VERSION,
        "rules": DEFAULT_RULES,
        "weights": DEFAULT_WEIGHTS,
        "thresholds": DEFAULT_THRESHOLDS,
        "active": True,
    }
