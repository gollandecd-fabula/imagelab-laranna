# ImageLab by LarannA — Codex collaboration plan v1

Date: 2026-07-25  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Repository: `gollandecd-fabula/imagelab-laranna`  
Active branch: `bootstrap/zero-trust-gate`  
Active PR: `#2` — draft, unmerged, release blocked

## Purpose

Add Codex as an implementation and independent review resource without transferring release authority to an agent and without weakening the current technical specification, RTM, evidence rules, or physical L5 requirement.

## Current verified state

- Exact candidate: `1.4.9-recovery-candidate`.
- Build ID: `REC-RT8-M6-20260724-06`.
- Exact Windows installer SHA-256: `12817550c2fac6a6453945c38eefe86368cd4cfa1991c1565e49b092bd818d56`.
- Hosted Windows B0–B5 and B8: PASS.
- Technical update and rollback mechanism diagnostic: PASS, non-authorizing.
- G6: BLOCKED because no historical `RELEASE_AUTHORIZED` baseline exists.
- Physical user-machine L5: NOT VERIFIED.
- Final state: `RELEASE_BLOCKED`.

## Roles

| Role | Responsibility | Cannot do |
|---|---|---|
| Dmitry — Product Owner | Approve material changes to the specification; define product priorities; perform or directly witness physical Windows L5; decide whether a verified release may be authorized | Cannot replace missing evidence with approval alone |
| ChatGPT — Technical Lead / Integrator | Maintain RTM; split work into bounded tasks; prepare Codex prompts; inspect patches and CI; verify evidence; integrate accepted changes into the recovery branch; report exact release state | Cannot fabricate G6 history, replace physical L5, or merge/publish a blocked release |
| Codex Agent A — Implementer | Implement one bounded task; add tests; run checks; create a draft PR with exact evidence | Cannot change the specification, weaken gates, merge, publish, or self-authorize its work |
| Codex Agent B — Red-Team Reviewer | Independently review Agent A's patch, tests, failure modes, and evidence; propose corrections | Cannot treat Agent A's claims as proof or approve release |
| Codex Agent C — Test/Evidence Specialist | Expand adversarial tests, reproduce failures, verify deterministic outputs and evidence schemas | Cannot invent external or physical evidence |
| GitHub Actions | Execute source, packaging, Windows, browser, output, and reproducibility checks | Cannot satisfy physical user-machine L5 or create an authorized historical baseline |

## Branch and PR model

- Integration branch remains `bootstrap/zero-trust-gate`.
- PR #2 remains draft and unmerged.
- Each Codex task uses a separate branch/worktree: `codex/imagelab-<task>`.
- Each task creates a separate draft PR targeting `bootstrap/zero-trust-gate`, not `main`.
- ChatGPT reviews the patch and evidence before any integration.
- No agent may merge its own PR.

## Updated stages

### Stage 0 — Codex repository onboarding

Status: repository side prepared; user-side Codex connection still required.

Actions:

1. Keep root `AGENTS.md` as the mandatory agent entry point.
2. Connect the Codex environment to `gollandecd-fabula/imagelab-laranna`.
3. Select `bootstrap/zero-trust-gate` as the working branch or create task worktrees from it.
4. Run a read-only orientation task before allowing code changes.
5. Confirm Codex can read the RTM, runbook, source, and current evidence.

PASS criteria:

- Codex can access the repository.
- Codex reports the exact current candidate identity and blockers without contradiction.
- No files are changed during orientation.

Estimated active effort: 20–45 minutes, excluding GitHub synchronization delay and account authorization.

### Stage 1 — Independent Codex audit of the current recovery state

Owner: Codex Agent B, reviewed by ChatGPT.

Scope:

- Compare RTM requirements with current evidence.
- Detect stale documentation, conflicting status claims, missing evidence links, and unsafe workflow paths.
- Confirm that G6 and physical L5 remain externally blocked.
- Produce findings only; no production code changes.

PASS criteria:

- Every finding maps to an RTM row, file, and evidence gap.
- No speculative PASS claims.
- No proposed weakening of G0–G8.

Estimated active effort: 1.5–3 hours.

### Stage 2 — Plan and specification consistency patch

Owner: Codex Agent A; red-team review by Agent B; integration by ChatGPT.

Scope:

- Update stale status documentation to match the current exact 1.4.9 evidence.
- Add a machine-readable current-state index.
- Add checks that prevent stale candidate identity from being presented as current.
- Do not change G6 or introduce a Genesis exception unless Dmitry explicitly approves that specification change.

PASS criteria:

- Documentation and machine-readable state agree with exact evidence hashes.
- Existing release gates remain unchanged.
- Full tests remain PASS.

Estimated active effort: 2–4 hours.

### Stage 3 — First-release deadlock decision

Owner: Dmitry; analysis prepared by ChatGPT and independently challenged by Codex Agent B.

Decision options:

A. Provide a genuine historical `RELEASE_AUTHORIZED` installer and independently pinned SHA-256.  
B. Explicitly amend the RTM with a first-release or Genesis rule that applies only to the initial authorized release.  
C. Keep the current RTM unchanged and accept that release remains permanently blocked until option A becomes possible.

Codex role:

- Analyse the proposed amendment for loopholes, circular authorization, downgrade risk, and evidence bypass.
- It does not choose or approve the policy.

Estimated active effort after a decision exists: 1–3 hours for the RTM/change-register/test patch.

### Stage 4 — G6/G7 authorizing implementation or re-execution

Owner: Codex Agent A and Agent C; integration by ChatGPT.

Path A — historical baseline supplied:

- Verify release tag, asset identity, independent SHA-256, and authorization evidence.
- Run real update and forced-failure rollback gates.

Path B — approved first-release rule:

- Implement the exact approved rule.
- Add adversarial tests proving it can apply only once and cannot authorize later releases without a prior authorized baseline.
- Re-run the complete source and Windows gates.

PASS criteria:

- No circular baseline.
- Exact installer identity remains pinned throughout.
- Forced failure restores a runnable installation and preserved project data.
- Evidence is complete and machine-verifiable.

Estimated active effort: 3–7 hours if no new defects are found.

### Stage 5 — Physical Windows L5

Owner: Dmitry; procedure and evidence capture prepared by ChatGPT; Codex may prepare the harness but cannot perform the physical act.

Scope:

- Install the exact authorized candidate on the real target Windows machine.
- Use the installed browser UI.
- Perform upload, resize/PPI, history switching, background removal, halftone, vectorization, and export.
- Validate actual PNG/SVG outputs.
- Preserve screenshots, logs, hashes, system identity, and exact installer identity.

PASS criteria:

- Exact installer SHA matches the gated candidate.
- User-visible workflow succeeds on the real machine.
- Output validators PASS.
- Evidence is complete and independently reviewable.

Estimated active effort: 45–90 minutes for one clean run; additional defect correction is separate.

### Stage 6 — RT8-M7 release readiness

Owner: ChatGPT integrator; independent Codex review.

Scope:

- Reconcile all G0–G8 evidence.
- Ensure no stale or contradictory evidence remains.
- Verify release package, uninstall path, preserved project data, privacy constraints, and operator documentation.
- Keep release blocked on any incomplete gate.

Estimated active effort: 2–5 hours.

### Stage 7 — RT8-M8 controlled first release

Owner: Dmitry for authorization; ChatGPT for execution controls; Codex Agent B for final independent review.

Scope:

- Authorize only the exact installer SHA that passed every applicable gate.
- Create the external release baseline and immutable evidence references.
- Preserve the authorized installer as the mandatory G6 baseline for the next release.
- Do not publish source recovery artifacts as user installers.

Estimated active effort: 1–2 hours after every prerequisite is genuinely PASS.

## Parallel work allocation

After Stage 0, the following may run in parallel without conflicting writes:

- Agent B: RTM/evidence audit.
- Agent C: adversarial test and evidence-schema audit.
- ChatGPT: task decomposition, PR review rubric, and physical L5 procedure.

Code changes remain sequential at integration time. Parallel agents must use separate worktrees and draft PRs.

## Aggregate planning estimate

These are active-work ranges, not a completion promise:

- Repository-side Codex preparation: completed in the recovery branch.
- Codex connection and orientation: 20–45 minutes.
- Audit and consistency work: 3.5–7 hours.
- G6/G7 resolution after an authorized decision/input exists: 3–7 hours.
- Physical L5: 45–90 minutes for one clean run.
- RT8-M7/M8 closure: 3–7 hours.

Best case with no new defects and a prompt policy decision: roughly 1–2 focused working days.  
More realistic case with one or two correction cycles: roughly 2–4 focused working days.  
No schedule can bypass the external G6 decision/input or physical L5 requirement.

## Initial Codex task prompts

### Orientation — read only

> Read `AGENTS.md`, the release RTM and runbook, and the three current evidence summaries. Do not modify files. Report the exact current candidate identity, which gates have evidence-backed PASS, which gates remain blocked, and any contradictions you find. Cite repository paths and evidence fields.

### Independent audit

> Audit the active ImageLab recovery branch against every RTM row. Do not change code. Produce a table: requirement, current claim, actual evidence, mismatch, severity, and exact corrective action. Treat missing or stale evidence as failure. Do not propose weakening any gate.

### Consistency patch

> From the approved audit findings, update only stale status documentation and add tests that detect stale candidate identity. Preserve all release criteria. Run focused tests and the complete source suite. Open a draft PR targeting `bootstrap/zero-trust-gate` with exact commands and results.

## Current release boundary

Until the external G6 condition or an explicitly approved first-release rule exists, and physical L5 is complete:

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
