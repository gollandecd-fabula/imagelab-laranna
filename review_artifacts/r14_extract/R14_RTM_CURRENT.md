# ImageLab R14 current RTM

| ID | Milestone | Requirement | Action | Test | Evidence | Artifact | PASS criterion | Actual status |
|---|---|---|---|---|---:|---|---|---|
| R14-0 | Boundary | Accepted R12 modules frozen | Scope-only review changes | Changed-path audit | L0 | PR diff | no product/R12 change | VERIFIED |
| R14-1 | F03 ROI | Manual ROI hard rectangular boundary | exact-R13 working-fragment branch | pixel/bounds/real API | exact-byte + compatibility L2 | R14_EXACT_R13_EXTRACTION_EVIDENCE.md + composite E2E | exact ROI; no outside pixels | PARTIAL — exact extraction implementation verified; full exact product tree unavailable |
| R14-2 | F03 Fragment | Preserve fabric/background/RGBA | non-destructive exact-R13 crop | RGB/RGBA equality + API | exact-byte + compatibility L2 | composite E2E | source pixels/alpha preserved | PARTIAL — source-runtime behavior verified on compatibility scaffold |
| R14-3 | F03 No segmentation | No default segmentation/removal/fallback | hard manual branch | spies/branch/real API | exact-byte + compatibility L2 | composite E2E | no segment/remove/fallback | PARTIAL — spies PASS; full exact product tree unavailable |
| R14-4 | F03 Perspective | Explicit valid 4-point perspective remains | validate/apply explicit transform | identity/non-identity/invalid | L1 + compatibility L2 | extract regression/evidence | valid applies; invalid fail-closed | PARTIAL |
| R14-5 | F03 Dewarp | Alpha silhouette cannot auto-dewarp | disable from manual path | negative straighten + spy | exact-byte + compatibility L2 | composite E2E | silhouette never changes manual geometry | PARTIAL — source-runtime spy PASS |
| R14-6 | F03 Alignment | No guessed alignment | fail closed to unchanged ROI | no-confidence/no-op | L1 + compatibility L2 | diagnostics/tests | unproved correction is no-op | PARTIAL |
| R14-7 | F03->F04 | Extract, Improve, Remove Background remain distinct | preserve pipeline separation | real API chain | compatibility L2 | composite E2E | F03 preserves data; F04 removes bg | PARTIAL — real API chain PASS on compatibility scaffold |
| R14-8 | Diagnostics | Diagnostics/QA truthfully expose working-fragment semantics | explicit semantic contract | real API QA | L1 + compatibility L2 | R14 QA evidence + exact extraction evidence | no ambiguous cutout claims | PARTIAL — QA surrounding-file exact R13 provenance unavailable |
| R14-9 | Client | Manual UI routes strict region working-fragment path | split region vs auto request parameters | exact snippet + Node routing harness | L1 | R14_APP_EXTRACT_ROUTING.patch + R14_CLIENT_ROUTING_EVIDENCE.md | region sends ROI/strict/perspective only; auto cutout controls unchanged | PARTIAL — product/browser runtime not patched |
| R14-10 | Regression | Focused + neighboring regressions | deterministic split regression sets | custom/focused/broad/browser | L1 + compatibility L2 | exact extraction evidence + test logs | no R14 regression; complete required suite | PARTIAL — completed split groups PASS; 3 superseded old-contract assertions and 2 missing pinned Linux dependency classes remain explicitly separated |
| R14-11 | Packaging | R14 exact packaged runtime | build/package exact verified source | packaged E2E | blocker evidence only | dependency intake / package evidence | R14 code executes in exact package | BLOCKED — exact full R13 product tree and retained verified runtime bytes unavailable; intake correctly fail-closed |
| R14-12 | Installed | Installed Windows runtime | install exact package | installed tests | — | installed evidence | installed path works | NOT_STARTED — depends on R14-11 exact package |
| R14-13 | Physical | Physical user path | user tests real image | manual physical | — | user evidence | expected visual behavior | NOT_STARTED — no physical intervention requested yet because earlier gates remain open |
| R14-14 | QA boundary | Working fragment must not be rejected/repaired as cutout | semantic QA + manual repair guard | direct QA + FastAPI + auto regression | L1 + compatibility L2 | R14_QA_REPAIR_SEMANTIC_ROUTING.patch + QA evidence | correct working fragment accepted; bad contract blocked; auto unchanged | PARTIAL — compatibility tests PASS; exact R13 QA/repair provenance unavailable |

No milestone/release completion is claimed while any row is PARTIAL, UNVERIFIED, NOT_STARTED, FAILED, or BLOCKED.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
