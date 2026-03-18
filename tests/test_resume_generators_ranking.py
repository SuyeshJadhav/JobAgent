from backend.services import resume_generators
from backend.services.resume_generators import (
    build_ranked_projects_section,
    rank_projects_for_jd,
)


def test_rank_projects_for_jd_prefers_keyword_overlap():
    context_bank = {
        "project": [
            {
                "name": "Web Platform",
                "tools_used": "React, Node.js",
                "what_does_it_do": "General web app",
                "bullet_1": [
                    {
                        "what_did_you_build": "Built a dashboard",
                        "how_it_works": "REST API integration",
                    }
                ],
            },
            {
                "name": "ML Pipeline",
                "tools_used": "Python, FastAPI, Transformers, PyTorch",
                "what_does_it_do": "NLP pipeline",
                "bullet_1": [
                    {
                        "what_did_you_build": "Built transformer inference",
                        "how_it_works": "NLP embeddings and scoring",
                        "metric": "75ms per item",
                    }
                ],
            },
        ]
    }

    jd_text = "We need Python, FastAPI, NLP, transformers, and ML systems."
    ranked, diagnostics = rank_projects_for_jd(jd_text, context_bank)

    assert ranked[0]["name"] == "ML Pipeline"
    assert diagnostics["ranked"][0]["name"] == "ML Pipeline"


def test_rank_projects_for_jd_returns_stable_list_shape():
    context_bank = {
        "project": [
            {
                "name": "Project A",
                "tools_used": "Python",
                "what_does_it_do": "A",
            },
            {
                "name": "Project B",
                "tools_used": "JavaScript",
                "what_does_it_do": "B",
            },
        ]
    }

    ranked, diagnostics = rank_projects_for_jd(
        "intern software engineer role", context_bank)

    assert len(ranked) == 2
    assert "ranked" in diagnostics
    assert "keywords" in diagnostics
    assert all("score" in item for item in ranked)


def test_build_ranked_projects_section_uses_dates_in_heading(monkeypatch):
    context_bank = {
        "project": [
            {
                "name": "Job Search Automation Tool",
                "tools_used": "Python, FastAPI",
                "dates": "December 2025 -- Present",
                "what_does_it_do": "Automates job search and resume tailoring.",
                "bullet_1": [
                    {
                        "what_did_you_build": "A pipeline",
                        "how_it_works": "Parallelized sources",
                    }
                ],
            },
            {
                "name": "Personal AI Agent",
                "tools_used": "Python, ChromaDB",
                "dates": "June 2024 -- Present",
                "what_does_it_do": "Agent runtime.",
                "bullet_1": [
                    {
                        "what_did_you_build": "A runtime",
                        "how_it_works": "Tool orchestration",
                    }
                ],
            },
            {
                "name": "WolfCafe+",
                "tools_used": "React, Node.js",
                "dates": "August 2024 -- November 2024",
                "what_does_it_do": "Ordering app.",
                "bullet_1": [
                    {
                        "what_did_you_build": "Backend APIs",
                        "how_it_works": "JWT and RBAC",
                    }
                ],
            },
        ]
    }

    monkeypatch.setattr(
        resume_generators,
        "extract_jd_keywords",
        lambda _jd_text: {
            "required_skills": [],
            "required_tools": [],
            "action_verbs": [],
            "seniority_signals": [],
            "domain_focus": [],
        },
    )
    monkeypatch.setattr(
        resume_generators,
        "rewrite_bullets_with_validation",
        lambda section_name, current_text, keywords, context_bank: current_text,
    )

    section_text, diagnostics = build_ranked_projects_section(
        "intern software engineer role",
        context_bank,
        strategy="full_rewrite",
    )

    assert "{Selected Project}" not in section_text
    assert "{December 2025 -- Present}" in section_text
    assert "{June 2024 -- Present}" in section_text
    assert "{August 2024 -- November 2024}" in section_text
    assert diagnostics["selected_projects"] == [
        "Job Search Automation Tool",
        "Personal AI Agent",
        "WolfCafe+",
    ]


def test_build_ranked_projects_section_bolds_keywords(monkeypatch):
    context_bank = {
        "project": [
            {
                "name": "Project One",
                "tools_used": "Python, FastAPI, SQLite",
                "dates": "2026",
                "what_does_it_do": "Build APIs",
                "bullet_1": [
                    {
                        "what_did_you_build": "Built FastAPI services",
                        "how_it_works": "Persisted data in SQLite",
                    }
                ],
            },
            {
                "name": "Project Two",
                "tools_used": "React",
                "dates": "2025",
                "what_does_it_do": "UI",
                "bullet_1": [{"what_did_you_build": "Built React UI"}],
            },
            {
                "name": "Project Three",
                "tools_used": "Node.js",
                "dates": "2024",
                "what_does_it_do": "Backend",
                "bullet_1": [{"what_did_you_build": "Built backend"}],
            },
        ]
    }

    monkeypatch.setattr(
        resume_generators,
        "extract_jd_keywords",
        lambda _jd_text: {
            "required_skills": ["FastAPI"],
            "required_tools": ["SQLite"],
            "action_verbs": [],
            "seniority_signals": [],
            "domain_focus": [],
        },
    )
    monkeypatch.setattr(
        resume_generators,
        "rewrite_bullets_with_validation",
        lambda section_name, current_text, keywords, context_bank: current_text,
    )

    section_text, _diagnostics = build_ranked_projects_section(
        "Role needs FastAPI and SQLite",
        context_bank,
        strategy="full_rewrite",
    )

    assert r"\textbf{FastAPI}" in section_text
    assert r"\textbf{SQLite}" in section_text
