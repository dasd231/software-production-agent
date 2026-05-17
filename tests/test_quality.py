from agent.pipeline.quality import calculate_health_score, calculate_wtf_likelihood, should_stop_fixing


def test_wtf_likelihood_formula() -> None:
    score = calculate_wtf_likelihood(fix_count=20, revert_count=1, files_touched=4, remaining_low_only=True)
    assert score == 35


def test_should_stop_fixing() -> None:
    assert should_stop_fixing(wtf_likelihood=21, fix_count=1) is True
    assert should_stop_fixing(wtf_likelihood=10, fix_count=51) is True
    assert should_stop_fixing(wtf_likelihood=10, fix_count=10) is False


def test_health_score_bounds() -> None:
    score = calculate_health_score(test_pass_rate=100, critical_high_count=0, review_score=9, wtf_likelihood=0)
    assert 0.0 <= score <= 10.0
