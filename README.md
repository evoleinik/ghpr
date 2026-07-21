# ghpr

One-call PR merge-safety read for agents. Collapses the "read every bot review + check
every gate before merging" dance into a single structured call: all reviews (with
bodies), every check run, mergeable state, and a computed **BLOCKED / READY** verdict
with reasons. Shells out to `gh` — zero auth code, reuses your existing login.

Third of a stateless trio — [`gitx`](https://github.com/evoleinik/gitx) writes (commit to
any branch/repo with no checkout), [`gitw`](https://github.com/evoleinik/gitw) orients
(where am I, in one read), and `ghpr` is the *pre-merge read*: the thing you run before
you trust a green check and merge.

## Install

    ln -sf ~/src/ghpr/ghpr ~/bin/ghpr   # needs `gh` (authed) + python3 on PATH

## Usage

    ghpr <number>                # human summary + verdict
    ghpr <number> --json         # bare JSON object (pipe to jq)
    ghpr <number> --repo owner/name
    ghpr --usage                 # {calls, ok, fail} from ~/.ghpr/usage.jsonl

## What it answers in one call

    { status, ready, number, title, state, url, mergeable, mergeStateStatus,
      reviewDecision, checks:{pass:[],fail:[],pending:[]}, check_counts,
      reviews:[{author,state,body}], comments:[{author,body}], blocking:[reasons] }

`status` ∈ ready · blocked · merged · closed. `blocking` lists exactly why an OPEN PR
can't merge (failing/pending checks, changes-requested, review-required, conflicts,
behind-base). Every bot review body is in `reviews` — so an agent can't merge without
having surfaced the review it was supposed to read.

Checks are **deduped to the latest run per name**, matching how GitHub itself decides.
`gh` returns every run posted against the head sha, so a check that failed and was then
re-run green appears twice; counting both invents a blocker on a PR GitHub already calls
CLEAN. Latest-wins cuts both ways — a green run does not immunize a later failure, and a
re-run still in flight outranks an older completed one.

Exit 0 on a successful read (the verdict is in the payload, not the exit code);
2 = gh not authed, 3 = PR not found, 4 = transient failure (network / rate limit / 5xx)
after retries.

**Exit 4 is the one a polling caller must handle.** A network blip is weather, not a
verdict: transient causes are retried twice with backoff, and only then reported — under
their own code so a loop can back off instead of mistaking silence for "no change". Auth
and not-found are never retried; they are facts about the world, not the connection.

## Test

    python3 -m pytest test_ghpr.py -q

<!-- AI agents: telemetry at ~/.ghpr/usage.jsonl (GHPR_HOME overrides).
     Run `ghpr <N> --json` before ANY merge. `.ready==false` → do not merge;
     read `.blocking` and every `.reviews[].body` first. Single Python file, stdlib, shells to gh. -->
