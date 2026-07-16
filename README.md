# ghpr

One-call PR merge-safety read for agents. Collapses the "read every bot review + check
every gate before merging" dance into a single structured call: all reviews (with
bodies), every check run, mergeable state, and a computed **BLOCKED / READY** verdict
with reasons. Shells out to `gh` — zero auth code, reuses your existing login.

Companion to [`gitx`](../gitx) (stateless write) and [`gitw`](../gitw) (stateless
orient): `ghpr` is the stateless *pre-merge read* — the thing you must run before you
trust a green check and merge.

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

Exit 0 on a successful read (the verdict is in the payload, not the exit code);
2 = gh not authed, 3 = PR not found.

## Test

    python3 -m pytest test_ghpr.py -q

<!-- AI agents: telemetry at ~/.ghpr/usage.jsonl (GHPR_HOME overrides).
     Run `ghpr <N> --json` before ANY merge. `.ready==false` → do not merge;
     read `.blocking` and every `.reviews[].body` first. Single Python file, stdlib, shells to gh. -->
