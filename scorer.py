from __future__ import annotations

import re
from typing import Any


def _count_alias_hits(text: str, aliases: list[str]) -> list[str]:
    hits: list[str] = []
    for alias in aliases:
        pattern = r"(?<!\w)" + re.escape(alias.lower()) + r"(?!\w)"
        if re.search(pattern, text):
            hits.append(alias)
    return hits


def score_job(
    description: str,
    title: str,
    scoring_rules: dict[str, Any],
    resume_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    searchable_text = f"{title}\n{description}".lower()
    title_text = title.lower()
    total_score = 0
    matched_categories: list[str] = []
    matched_keywords: list[str] = []
    breakdown_parts: list[str] = []

    for category, rule in scoring_rules.items():
        weight = int(rule.get("weight", 1))
        keywords = rule.get("keywords", [])
        hits = [keyword for keyword in keywords if keyword.lower() in searchable_text]
        if hits:
            total_score += weight * len(hits)
            matched_categories.append(category)
            matched_keywords.extend(hits)
            breakdown_parts.append(f"{category}: +{weight * len(hits)}")

    if resume_profile:
        matched_resume_categories: dict[str, int] = {}
        for skill_name, skill_data in resume_profile.get("skills", {}).items():
            aliases = skill_data.get("aliases", [skill_name])
            hits = _count_alias_hits(searchable_text, aliases)
            if not hits:
                continue

            years = float(skill_data.get("years", 0))
            category = skill_data.get("category", "Other")
            skill_score = int(round(years * 4))
            total_score += skill_score
            matched_keywords.append(skill_name)
            matched_resume_categories[category] = matched_resume_categories.get(category, 0) + 1
            breakdown_parts.append(f"{skill_name} ({years:g}y): +{skill_score}")

        for category, count in matched_resume_categories.items():
            if count >= 2:
                depth_bonus = count * 2
                total_score += depth_bonus
                if category not in matched_categories:
                    matched_categories.append(category)
                breakdown_parts.append(f"{category} depth: +{depth_bonus}")

        for phrase, bonus in resume_profile.get("preferred_title_keywords", {}).items():
            if phrase.lower() in title_text:
                total_score += int(bonus)
                breakdown_parts.append(f"Title match '{phrase}': +{int(bonus)}")

        for phrase, penalty in resume_profile.get("title_penalties", {}).items():
            if phrase.lower() in title_text:
                total_score += int(penalty)
                breakdown_parts.append(f"Title penalty '{phrase}': {int(penalty)}")

    return {
        "match_score": total_score,
        "score": total_score,
        "matched_categories": ", ".join(matched_categories),
        "matched_keywords": ", ".join(dict.fromkeys(matched_keywords)),
        "score_breakdown": " | ".join(breakdown_parts),
    }
