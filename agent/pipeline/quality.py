"""Quality helpers inspired by pipeline + gstack self-control rules."""

from __future__ import annotations


def calculate_wtf_likelihood(
    fix_count: int,
    revert_count: int,
    files_touched: int,
    remaining_low_only: bool,
) -> int:
    score = 0
    score += max(revert_count, 0) * 15
    if files_touched > 3:
        score += 5
    if fix_count > 15:
        score += fix_count - 15
    if remaining_low_only:
        score += 10
    return max(0, min(score, 100))


def should_stop_fixing(wtf_likelihood: int, fix_count: int) -> bool:
    if fix_count > 50:
        return True
    return wtf_likelihood > 20


def calculate_health_score(
    test_pass_rate: float,
    critical_high_count: int,
    review_score: float,
    wtf_likelihood: int,
) -> float:
    pass_component = max(0.0, min(test_pass_rate, 100.0)) / 100.0 * 4.0
    severity_penalty = min(max(critical_high_count, 0), 5) * 1.2
    review_component = max(0.0, min(review_score, 10.0)) * 0.4
    wtf_penalty = max(0, min(wtf_likelihood, 100)) / 100.0 * 2.0
    score = pass_component + review_component - severity_penalty - wtf_penalty + 4.0
    return round(max(0.0, min(score, 10.0)), 2)
