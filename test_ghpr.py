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


def test_do_not_track_suppresses(tmp_path, monkeypatch):
    monkeypatch.setenv("GHPR_HOME", str(tmp_path))
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    ghpr.log_usage("read", True, 1, None)
    assert not (tmp_path / "usage.jsonl").exists()


def test_first_write_notice_on_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GHPR_HOME", str(tmp_path))
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    ghpr.log_usage("read", True, 1, None)
    captured = capsys.readouterr()
    assert "logging usage to" in captured.err
    assert "DO_NOT_TRACK=1" in captured.err
    ghpr.log_usage("read", True, 1, None)
    captured2 = capsys.readouterr()
    assert "logging usage to" not in captured2.err


def test_sigterm_writes_morgue(tmp_path):
    import subprocess as sp, signal, time as _t
    env = dict(os.environ, GHPR_HOME=str(tmp_path))
    env.pop("DO_NOT_TRACK", None)
    p = sp.Popen(["python3", os.path.join(_here, "ghpr"), "1"],
                 env=env, stdout=sp.PIPE, stderr=sp.PIPE)
    _t.sleep(0.05)
    p.send_signal(signal.SIGTERM)
    p.wait(timeout=10)
    lines = (tmp_path / "usage.jsonl").read_text().strip().splitlines() if (tmp_path / "usage.jsonl").exists() else []
    assert lines, "no record written at all"
    import json as _json
    rec = _json.loads(lines[-1])
    assert rec["ok"] is False
    assert "SIGTERM" in (rec["error"] or "")


# --- latest-run-wins (the airshelf#1192 phantom blocker) --------------------


def _run(name, conclusion, started, typename="CheckRun"):
    return {"__typename": typename, "name": name, "status": "COMPLETED",
            "conclusion": conclusion, "startedAt": started}


def test_rerun_supersedes_the_stale_failure():
    """THE REGRESSION TEST. GitHub counts the latest run per name; so must we, or a
    green re-run reads as a failing check and the PR looks unmergeable."""
    pr = _pr(statusCheckRollup=[
        _run("curation", "FAILURE", "2026-07-20T13:28:32Z"),
        _run("curation", "SUCCESS", "2026-07-20T13:46:26Z"),
    ])
    s = ghpr.evaluate(pr)
    assert s["check_counts"] == {"pass": 1, "fail": 0, "pending": 0}
    assert s["blocking"] == [] and s["ready"] is True


def test_a_rerun_that_went_red_still_blocks():
    """Latest-wins cuts both ways: a green run does not immunize a later failure."""
    pr = _pr(mergeStateStatus="BLOCKED", statusCheckRollup=[
        _run("ci", "SUCCESS", "2026-07-20T13:00:00Z"),
        _run("ci", "FAILURE", "2026-07-20T14:00:00Z"),
    ])
    s = ghpr.evaluate(pr)
    assert s["check_counts"]["fail"] == 1 and s["status"] == "blocked"


def test_in_flight_rerun_beats_an_older_completed_run():
    """A re-run in progress is the live state of that check, not the old verdict."""
    pr = _pr(statusCheckRollup=[
        _run("ci", "SUCCESS", "2026-07-20T13:00:00Z"),
        {"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS",
         "conclusion": None, "startedAt": "2026-07-20T14:00:00Z"},
    ])
    s = ghpr.evaluate(pr)
    assert s["check_counts"] == {"pass": 0, "fail": 0, "pending": 1}


def test_distinct_checks_are_never_collapsed():
    pr = _pr(mergeStateStatus="BLOCKED", statusCheckRollup=[
        _run("lint", "SUCCESS", "2026-07-20T13:00:00Z"),
        _run("test", "FAILURE", "2026-07-20T13:00:00Z"),
        {"__typename": "StatusContext", "context": "Vercel", "state": "SUCCESS",
         "startedAt": "2026-07-20T13:00:00Z"},
    ])
    s = ghpr.evaluate(pr)
    assert s["check_counts"] == {"pass": 2, "fail": 1, "pending": 0}


def test_entries_without_timestamps_keep_list_order():
    """Older gh versions / odd payloads omit startedAt -- last one listed wins,
    which matches how the rollup is ordered, instead of throwing."""
    pr = _pr(mergeStateStatus="BLOCKED", statusCheckRollup=[
        {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"},
    ])
    s = ghpr.evaluate(pr)
    assert s["check_counts"]["fail"] == 1


# --- transient-failure handling -------------------------------------------
# A network blip is not a verdict. These pin that it is retried, that it ends
# up under its own exit code (4) rather than the generic 1, and that failures
# which are NOT weather (auth, missing PR, real errors) are never retried.

class _FakeRun:
    """Scripts subprocess.run: each call pops one (returncode, stderr)."""

    def __init__(self, outcomes, stdout='{"ok": 1}'):
        self.outcomes = list(outcomes)
        self.stdout_val = stdout
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        code, err = self.outcomes.pop(0)
        return type("P", (), {"returncode": code, "stdout": self.stdout_val, "stderr": err})()


def _with_run(monkeypatch, fake):
    monkeypatch.setattr(ghpr.subprocess, "run", fake)
    return []


def test_transient_network_error_is_retried_then_succeeds(monkeypatch):
    fake = _FakeRun([(1, "error connecting to api.github.com"), (0, "")])
    monkeypatch.setattr(ghpr.subprocess, "run", fake)
    slept = []
    out = ghpr.gh(["pr", "view", "1"], sleep=slept.append)
    assert out == '{"ok": 1}'
    assert fake.calls == 2          # retried exactly once before succeeding
    assert slept and slept[0] > 0   # and backed off before retrying


def test_persistent_transient_failure_exits_4_not_1(monkeypatch):
    import pytest
    fake = _FakeRun([(1, "error connecting to api.github.com")] * (ghpr.GH_RETRIES + 1))
    monkeypatch.setattr(ghpr.subprocess, "run", fake)
    with pytest.raises(ghpr.GhprError) as e:
        ghpr.gh(["pr", "view", "1"], sleep=lambda _s: None)
    assert e.value.code == 4, "a poller must be able to tell 'retry me' from 'broken'"
    assert fake.calls == ghpr.GH_RETRIES + 1
    assert "retry" in e.value.msg.lower()


def test_rate_limit_counts_as_transient(monkeypatch):
    import pytest
    fake = _FakeRun([(1, "API rate limit exceeded for user")] * (ghpr.GH_RETRIES + 1))
    monkeypatch.setattr(ghpr.subprocess, "run", fake)
    with pytest.raises(ghpr.GhprError) as e:
        ghpr.gh(["pr", "view", "1"], sleep=lambda _s: None)
    assert e.value.code == 4


def test_auth_failure_is_not_retried(monkeypatch):
    import pytest
    fake = _FakeRun([(1, "gh: not logged in to any hosts")])
    monkeypatch.setattr(ghpr.subprocess, "run", fake)
    with pytest.raises(ghpr.GhprError) as e:
        ghpr.gh(["pr", "view", "1"], sleep=lambda _s: None)
    assert e.value.code == 2 and fake.calls == 1


def test_missing_pr_is_not_retried(monkeypatch):
    import pytest
    fake = _FakeRun([(1, "no pull requests found for branch")])
    monkeypatch.setattr(ghpr.subprocess, "run", fake)
    with pytest.raises(ghpr.GhprError) as e:
        ghpr.gh(["pr", "view", "1"], sleep=lambda _s: None)
    assert e.value.code == 3 and fake.calls == 1


def test_real_error_still_exits_1_and_is_not_retried(monkeypatch):
    import pytest
    fake = _FakeRun([(1, "unknown flag: --nope")])
    monkeypatch.setattr(ghpr.subprocess, "run", fake)
    with pytest.raises(ghpr.GhprError) as e:
        ghpr.gh(["pr", "view", "1"], sleep=lambda _s: None)
    assert e.value.code == 1 and fake.calls == 1
