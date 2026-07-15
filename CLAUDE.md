# ghpr — for AI agents

Run `ghpr <N> --json` BEFORE merging any PR. It returns every bot review body + every
check state + a merge verdict in one call, so "green check but a review said no" and
"forgot to read the claude[bot] review" become structurally impossible.

- `.ready == false` → DO NOT MERGE. Read `.blocking` (the exact reasons) and every
  `.reviews[].body` (the bot verdicts) before doing anything else.
- `.status` ∈ `ready` · `blocked` · `merged` · `closed`.
- `.checks.fail` / `.checks.pending` name the specific gates; `.reviewDecision` is the
  required-review state.
- Exit 3 = PR not found, 2 = gh not authed.

Read-only. To open/merge a PR use `gitx pr`; to know which branch you're on use `gitw`.
`ghpr` is the gate you read before you trust a merge.
