"""Tests for matching.rank_matches (subprocess mocked)."""
import json
import pytest
from unittest.mock import MagicMock, patch

from src.models import Employee, Destination
from src.matching import rank_matches


def _emp() -> Employee:
    return Employee(id="e1", name="Alice", title="Engineer", company="OldCo")


def _dests(n: int = 3) -> list[Destination]:
    return [
        Destination(id=f"d{i}", type="job_req", company=f"Co{i}", role=f"Role {i}")
        for i in range(n)
    ]


def _dims(fs: int, sn: int, tp: int, sf: int, do: int, reasoning: str = "ok") -> dict:
    return {"functional_skill": fs, "seniority": sn, "transition_pattern": tp, "stage_fit": sf, "domain_overlap": do, "reasoning": reasoning}


def _uniform(pct: int, reasoning: str = "ok") -> dict:
    """All five dimensions set to the same value so composite == pct / 100."""
    return _dims(pct, pct, pct, pct, pct, reasoning)


def _mock_run(scores: list[dict]) -> MagicMock:
    result = MagicMock()
    result.stdout = json.dumps({"result": json.dumps(scores)})
    return result


def test_returns_top_n():
    scores = [_uniform(90, "great"), _uniform(50, "ok"), _uniform(10, "weak")]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(3), top_n=2)
    assert len(matches) == 2


def test_sorted_by_score_descending():
    scores = [_uniform(30, "low"), _uniform(90, "high"), _uniform(60, "mid")]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(3), top_n=3)
    assert matches[0].score == 0.9
    assert matches[1].score == 0.6
    assert matches[2].score == 0.3


def test_empty_destinations_returns_empty():
    with patch("src.matching.subprocess.run") as mock_run:
        matches = rank_matches(_emp(), [], top_n=5)
    mock_run.assert_not_called()
    assert matches == []


def test_subprocess_failure_returns_fallback_scores():
    with patch("src.matching.subprocess.run", side_effect=Exception("timeout")):
        matches = rank_matches(_emp(), _dests(2), top_n=5)
    assert len(matches) == 2
    assert all(m.score == 0.0 for m in matches)
    assert all(m.reasoning == "Scoring unavailable" for m in matches)


def test_markdown_fenced_json_is_parsed():
    scores = [_uniform(80, "solid")]
    fenced = "```json\n" + json.dumps(scores) + "\n```"
    result = MagicMock()
    result.stdout = json.dumps({"result": fenced})
    with patch("src.matching.subprocess.run", return_value=result):
        matches = rank_matches(_emp(), _dests(1), top_n=5)
    assert matches[0].score == 0.8


def test_top_n_does_not_exceed_available():
    scores = [_uniform(50)]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(1), top_n=10)
    assert len(matches) == 1


def test_reasoning_is_preserved():
    scores = [_uniform(70, "Good domain fit.")]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(1), top_n=5)
    assert matches[0].reasoning == "Good domain fit."


def test_dimension_scores_are_stored():
    scores = [_dims(85, 90, 75, 70, 80, "Strong skills match.")]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(1), top_n=5)
    m = matches[0]
    assert m.functional_skill == 85
    assert m.seniority == 90
    assert m.transition_pattern == 75
    assert m.stage_fit == 70
    assert m.domain_overlap == 80


def test_composite_score_formula():
    scores = [_dims(100, 100, 0, 0, 0, "skills only")]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(1), top_n=5)
    # 0.30*100 + 0.20*100 + 0.15*0 + 0.20*0 + 0.15*0 = 50 → 0.50
    assert matches[0].score == pytest.approx(0.50)


def test_batching_makes_multiple_calls():
    """With 30 destinations, _BATCH_SIZE=25 should produce 2 subprocess calls."""
    from src.matching import _BATCH_SIZE
    n = _BATCH_SIZE + 5  # 30 destinations
    responses = [
        _mock_run([_uniform(50)] * _BATCH_SIZE),
        _mock_run([_uniform(50)] * 5),
    ]
    with patch("src.matching.subprocess.run", side_effect=responses) as mock_run:
        matches = rank_matches(_emp(), _dests(n), top_n=n)
    assert mock_run.call_count == 2
    assert len(matches) == n
