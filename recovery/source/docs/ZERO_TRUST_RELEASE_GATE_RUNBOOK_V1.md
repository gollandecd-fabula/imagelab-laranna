# ImageLab Zero-Trust Release Gate — Runbook v1

## Purpose

Do not install or distribute a candidate until the exact Windows installer passes G0–G8. The artifact named `UNVERIFIED_INTERNAL_EXACT_CANDIDATE` is internal only and must never be given to a user.

## One-time setup

1. Put this project in a private GitHub repository.
2. Enable GitHub Actions for the repository.
3. Create a GitHub Release containing the last known installer that was actually used before the new candidate.
4. Name the baseline asset so it matches:
   `ImageLab_by_LarannA_RELEASE_AUTHORIZED*_Setup_x64.exe`
5. Record its SHA-256 independently. Do not derive the value from the workflow run that is being tested.

## Run

1. Open **Actions → ImageLab Zero-Trust Release Gate → Run workflow**.
2. Enter:
   - `baseline_release_tag` — tag of the previous authorized release;
   - `baseline_installer_sha256` — exact pinned SHA-256 of that installer;
   - `enable_attestation` — optional.
3. Start the workflow manually.

## Result interpretation

### Authorized

Only this artifact may be distributed:

`ImageLab-RELEASE-AUTHORIZED`

It appears only when all gates pass and contains the exact tested installer.

### Blocked

Download:

`ImageLab-RELEASE-VERDICT`

Inspect `final-verdict.json` and `release-evidence.zip`. The workflow intentionally ends in failure. Do not install the internal candidate.

## Gates

- G0: source, identity, JavaScript and backend self-test.
- G1: all 18 test files in isolated processes.
- G2: two byte-identical Windows installer builds.
- G3: clean Windows installation of the exact candidate.
- G4: installed UI driven in Microsoft Edge.
- G5: binary inspection of PNG, PPI, alpha, halftone, SVG and lineage.
- G6: update from the real previous authorized installer while it is running.
- G7: forced post-promotion failure and rollback.
- G8: independent reinstall and UI/output rerun in bundled Chromium.

## Non-negotiable rule

A locally built EXE, a source test PASS, an API test PASS, or an internal candidate artifact is not a release. Only `ImageLab-RELEASE-AUTHORIZED` may be offered for installation.
