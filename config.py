from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SEEN_PATH = BASE_DIR / "jobs_seen.json"
OUTPUT_CSV_PATH = BASE_DIR / "linkedin_jobs.csv"
DOTENV_PATH = BASE_DIR / ".env"

DEFAULT_JOB_TITLES = [
    "Software Engineer",
    "Backend Developer",
    "Full Stack Developer",
    "Web Developer",
    "PHP Developer",
    "Java Developer",
    "Node.js Developer",
    "C# Developer",
    "Data Analyst",
    "DBA",
    "DevOps Engineer",
    "Cloud Engineer",
    "IT Support Specialist",
    "Frontend Developer",
]

DEFAULT_RESUME_PROFILE = {
    "preferred_title_keywords": {
        "software engineer": 7,
        "backend": 8,
        "backend developer": 9,
        "full stack": 7,
        "web developer": 5,
        "php developer": 5,
        "java developer": 8,
        "node.js developer": 5,
        "c# developer": 4,
        "data analyst": 4,
        "dba": 6,
        "database administrator": 6,
        "devops engineer": 4,
        "cloud engineer": 4,
        "frontend developer": 5,
        "it support": 3,
    },
    "title_penalties": {
        "senior": -6,
        "lead": -7,
        "principal": -9,
        "manager": -10,
        "director": -12,
        "architect": -6,
        "intern": -4,
    },
    "skills": {
        "Java": {
            "years": 4.0,
            "category": "Programming Languages",
            "aliases": ["java", "core java"],
        },
        "JavaScript": {
            "years": 4.0,
            "category": "Programming Languages",
            "aliases": ["javascript", "js", "ecmascript"],
        },
        "SQL/PL-SQL": {
            "years": 4.0,
            "category": "Databases",
            "aliases": ["sql", "pl/sql", "plsql", "stored procedures"],
        },
        "PHP": {
            "years": 2.0,
            "category": "Programming Languages",
            "aliases": ["php"],
        },
        "C#": {
            "years": 1.0,
            "category": "Programming Languages",
            "aliases": ["c#", ".net", "asp.net"],
        },
        "Spring Boot": {
            "years": 2.0,
            "category": "Web Development",
            "aliases": ["spring boot", "spring"],
        },
        "React.js": {
            "years": 2.0,
            "category": "Web Development",
            "aliases": ["react", "react.js"],
        },
        "Node.js/Express": {
            "years": 1.5,
            "category": "Web Development",
            "aliases": ["node.js", "nodejs", "express", "express.js"],
        },
        "Laravel": {
            "years": 1.0,
            "category": "Web Development",
            "aliases": ["laravel"],
        },
        "Oracle DB": {
            "years": 3.0,
            "category": "Databases",
            "aliases": ["oracle db", "oracle database", "oracle"],
        },
        "MySQL": {
            "years": 2.0,
            "category": "Databases",
            "aliases": ["mysql"],
        },
        "PostgreSQL": {
            "years": 1.0,
            "category": "Databases",
            "aliases": ["postgresql", "postgres"],
        },
        "MongoDB": {
            "years": 1.0,
            "category": "Databases",
            "aliases": ["mongodb", "mongo"],
        },
        "REST APIs": {
            "years": 4.0,
            "category": "Web Development",
            "aliases": ["rest api", "restful api", "api integration", "rest"],
        },
        "System Integration": {
            "years": 3.0,
            "category": "Methodologies",
            "aliases": ["system integration", "integration", "third-party integration"],
        },
        "Git/GitHub": {
            "years": 3.0,
            "category": "Other",
            "aliases": ["git", "github", "gitlab"],
        },
        "Docker": {
            "years": 1.0,
            "category": "Cloud & DevOps",
            "aliases": ["docker", "containerization"],
        },
        "Google Cloud": {
            "years": 1.0,
            "category": "Cloud & DevOps",
            "aliases": ["google cloud", "gcp"],
        },
        "Selenium Automation": {
            "years": 1.0,
            "category": "Other",
            "aliases": ["selenium", "test automation", "automation testing"],
        },
    },
}

DEFAULT_SCORING_RULES = {
    "Programming Languages": {
        "weight": 5,
        "keywords": [
            "python",
            "java",
            "javascript",
            "typescript",
            "php",
            "c#",
            ".net",
            "node.js",
            "nodejs",
            "sql",
        ],
    },
    "Web Development": {
        "weight": 4,
        "keywords": [
            "html",
            "css",
            "react",
            "next.js",
            "vue",
            "angular",
            "rest",
            "api",
            "full stack",
            "frontend",
            "backend",
        ],
    },
    "Cloud & DevOps": {
        "weight": 4,
        "keywords": [
            "aws",
            "azure",
            "gcp",
            "docker",
            "kubernetes",
            "devops",
            "ci/cd",
            "jenkins",
            "terraform",
            "cloud",
        ],
    },
    "Databases": {
        "weight": 4,
        "keywords": [
            "mysql",
            "postgresql",
            "postgres",
            "mongodb",
            "oracle",
            "sql server",
            "database",
            "dba",
            "redis",
        ],
    },
    "Security": {
        "weight": 3,
        "keywords": [
            "security",
            "owasp",
            "iam",
            "sso",
            "oauth",
            "authentication",
            "authorization",
            "cybersecurity",
        ],
    },
    "OS": {
        "weight": 2,
        "keywords": [
            "linux",
            "windows",
            "unix",
            "ubuntu",
        ],
    },
    "Methodologies": {
        "weight": 2,
        "keywords": [
            "agile",
            "scrum",
            "kanban",
            "tdd",
            "oop",
            "microservices",
            "problem solving",
        ],
    },
    "Other": {
        "weight": 1,
        "keywords": [
            "git",
            "communication",
            "team player",
            "documentation",
            "support",
            "troubleshooting",
            "analyst",
        ],
    },
}

DEFAULT_JOB_SOURCES = {
    "linkedin": {
        "enabled": True,
        "source_name": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
        "jobs_url": "https://www.linkedin.com/jobs/",
    },
    "jobstreet": {
        "enabled": True,
        "source_name": "JobStreet",
        "jobs_url_base": "https://ph.jobstreet.com",
    },
    "indeed": {
        "enabled": True,
        "source_name": "Indeed",
        "jobs_url_base": "https://www.indeed.com/jobs",
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "job_titles": DEFAULT_JOB_TITLES,
    "location": "Philippines",
    "date_posted": "today",
    "max_job_age_days": 1,
    "source_name": "LinkedIn",
    "max_applicants": None,
    "max_jobs_per_keyword": 150,
    "jobstreet_login_timeout_seconds": 240,
    "indeed_verification_timeout_seconds": 240,
    "job_sources": DEFAULT_JOB_SOURCES,
    "browser": {
        "headless": False,
        "user_data_dir": "",
        "profile_directory": "",
    },
    "scraping": {
        "scroll_pause_seconds": 1.1,
        "scroll_step_px": 640,
        "card_settle_seconds": 0.8,
        "between_cards_min_seconds": 0.8,
        "between_cards_max_seconds": 1.6,
        "between_keywords_min_seconds": 2.0,
        "between_keywords_max_seconds": 4.0,
    },
    "output_csv": str(OUTPUT_CSV_PATH.name),
    "jobs_seen_file": str(SEEN_PATH.name),
    "linkedin": {
        "login_url": "https://www.linkedin.com/login",
        "jobs_url": "https://www.linkedin.com/jobs/",
    },
    "resume_profile": DEFAULT_RESUME_PROFILE,
    "scoring": DEFAULT_SCORING_RULES,
}


def _merge_dicts(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def ensure_config_file() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")


def load_settings() -> dict[str, Any]:
    ensure_config_file()
    load_dotenv(DOTENV_PATH)

    file_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = _merge_dicts(DEFAULT_CONFIG, file_config)

    email = os.getenv("LINKEDIN_EMAIL", "").strip()
    password = os.getenv("LINKEDIN_PASSWORD", "").strip()
    if not email or not password:
        raise ValueError(
            "Missing LINKEDIN_EMAIL or LINKEDIN_PASSWORD in .env. "
            "Create a .env file beside the Python scripts."
        )

    settings["linkedin_email"] = email
    settings["linkedin_password"] = password
    settings["output_csv_path"] = BASE_DIR / settings["output_csv"]
    settings["jobs_seen_path"] = BASE_DIR / settings["jobs_seen_file"]
    return settings
