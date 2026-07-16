import importlib.machinery
import importlib.util
import os

_here = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("ghpr", os.path.join(_here, "ghpr"))
_spec = importlib.util.spec_from_loader("ghpr", _loader)
ghpr = importlib.util.module_from_spec(_spec)
_loader.exec_module(ghpr)


def _pr(**kw):
    base = {"number": 1, "title": "t", "state": "OPEN", "url": "u", "isDraft": False,
            "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "reviewDecision": "APPROVED",
            "reviews": [], "comments": [], "statusCheckRollup": []}
    base.update(kw)
    return base


def test_clean_open_pr_is_ready():
    s = ghpr.evaluate(_pr())
    assert s["status"] == "ready" and s["ready"] is True and s["blocking"] == []


def test_failing_check_blocks():
    pr = _pr(mergeStateStatus="BLOCKED", statusCheckRollup=[
        {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}])
    s = ghpr.evaluate(pr)
    assert s["status"] == "blocked" and s["check_counts"]["fail"] == 1
    assert any("ci" in r for r in s["blocking"])


def test_pending_check_blocks():
    pr = _pr(statusCheckRollup=[
        {"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": None}])
    s = ghpr.evaluate(pr)
    assert s["status"] == "blocked" and s["check_counts"]["pending"] == 1


def test_changes_requested_blocks():
    s = ghpr.evaluate(_pr(reviewDecision="CHANGES_REQUESTED"))
    assert s["status"] == "blocked" and "changes requested" in s["blocking"]


def test_review_required_blocks():
    s = ghpr.evaluate(_pr(reviewDecision="REVIEW_REQUIRED"))
    assert s["status"] == "blocked"


def test_merged_is_terminal_not_blocked():
    s = ghpr.evaluate(_pr(state="MERGED", mergeStateStatus="UNKNOWN"))
    assert s["status"] == "merged" and s["ready"] is False and s["blocking"] == []


def test_closed_is_terminal():
    s = ghpr.evaluate(_pr(state="CLOSED"))
    assert s["status"] == "closed" and s["blocking"] == []


def test_statuscontext_style_check_normalized():
    # legacy commit-status entries use `context`/`state` instead of `name`/`conclusion`
    pr = _pr(statusCheckRollup=[{"__typename": "StatusContext", "context": "legacy", "state": "SUCCESS"}])
    s = ghpr.evaluate(pr)
    assert s["check_counts"]["pass"] == 1 and s["status"] == "ready"


def test_reviews_carry_author_state_body():
    pr = _pr(reviews=[{"author": {"login": "claude"}, "state": "APPROVED", "body": "LGTM"}])
    s = ghpr.evaluate(pr)
    assert s["reviews"] == [{"author": "claude", "state": "APPROVED", "body": "LGTM"}]


def test_draft_blocks():
    s = ghpr.evaluate(_pr(isDraft=True, mergeStateStatus="DRAFT"))
    assert s["status"] == "blocked" and any("draft" in r for r in s["blocking"])


def test_log_usage_appends_jsonl(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("GHPR_HOME", str(tmp_path))
    ghpr.log_usage("read", True, 42, None)
    ghpr.log_usage("read", False, 7, "PR not found")
    lines = (tmp_path / "usage.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["cmd"] == "read"
    assert json.loads(lines[1])["ok"] is False


def test_log_usage_never_raises_on_bad_dir(monkeypatch):
    monkeypatch.setenv("GHPR_HOME", "/proc/nonexistent-cannot-create")
    ghpr.log_usage("read", True, 1, None)  # must not raise


def test_usage_error_exits_1_not_2():
    import pytest
    with pytest.raises(SystemExit) as e:
        ghpr.main(["--bogus-flag"])
    assert e.value.code == 1
