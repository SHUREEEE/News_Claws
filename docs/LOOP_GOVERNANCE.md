# Loop Governance Applied To News Claws

## Risk Route

News Claws uses the full path because it introduces external data access, persistence, API contracts, security controls, evidence semantics and compliance boundaries. The product and technical Word documents serve as the phase 01-03 baseline; this repository plan is the phase 04 dependency graph.

## Task Contract

Task states are exactly `ready`, `in_progress`, `blocked`, `failed` and `passed`. Legal transitions are:

- `ready -> in_progress`
- `in_progress -> blocked | failed | passed`
- `blocked -> in_progress` after the dependency clears, or `blocked -> failed` by the owner
- `failed -> ready` only after phase 04 creates a new attempt
- `passed` is terminal for that attempt

Each transition records a trigger, owner and evidence in `STATE.md` or the release run log.

## Maker And Verifier

The implementation pass is the Maker. Verification is a distinct closeout pass that starts from the frozen acceptance criteria and attempts to reject the candidate using tests, contract checks, security cases and real-browser inspection. A task-level PASS does not authorize deployment or production release.

## Repair Rules

- Fix only the smallest root cause that explains a failed check.
- Stable root-cause IDs are recorded in the run log.
- Renaming or splitting a finding does not reset its count.
- Three Checker returns for the same root cause stop the task and require user judgment.
- Material changes to goals, scope, acceptance or evidence boundaries return to the appropriate earlier phase.

## Evidence Classes

Important conclusions are labeled as `verified fact`, `inference`, `unknown` or `decision`. Agreement and historical test results are not current evidence. Evidence artifacts are stored under `evidence/<release-id>/` and retained for 365 days unless the project owner approves another policy.

## Closeout

After the final file edit, only verification, evidence sealing, resource cleanup and final reporting are allowed. Completion requires all tests and browser checks to finish and all temporary browser tabs, preview servers and command sessions to be accounted for and closed.
