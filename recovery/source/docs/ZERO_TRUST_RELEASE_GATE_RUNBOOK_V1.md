# ImageLab Zero-Trust Release Gate — Runbook v1

## Purpose

Do not install or distribute a candidate until the exact Windows installer passes G0–G8. The artifact named `UNVERIFIED_INTERNAL_EXACT_CANDIDATE` is internal only and must never be given to a user.

## One-time setup

1. Put this project in a private GitHub repository.
2. Enable GitHub Actions for the repository.
3. Use a genuine previous release that was authorized by this fail-closed finalizer. A merely used, renamed, diagnostic, recovery or internal candidate is not an authorized baseline.
4. The same GitHub Release must contain exactly one installer matching:
   `ImageLab_by_LarannA_RELEASE_AUTHORIZED*_Setup_x64.exe`
5. The same release must contain the prior finalizer output:
   `ImageLab-RELEASE-AUTHORIZATION.json`
6. Independently record both SHA-256 values:
   - SHA-256 of the authorized installer;
   - SHA-256 of `ImageLab-RELEASE-AUTHORIZATION.json`.
7. Do not derive either pinned value from the workflow run that is currently being tested.
8. The authorization record must bind the exact installer name and SHA-256 to `status=RELEASE_AUTHORIZED` and include the previous final verdict and release-evidence digests.

## Run

1. Open **Actions → ImageLab Zero-Trust Release Gate → Run workflow**.
2. Enter:
   - `baseline_release_tag` — tag of the previous authorized release;
   - `baseline_installer_sha256` — independently pinned SHA-256 of that installer;
   - `baseline_authorization_record_sha256` — independently pinned SHA-256 of its prior finalizer authorization record;
   - `enable_attestation` — optional.
3. Start the workflow manually.

## Result interpretation

### Authorized

Only this artifact may be distributed:

`ImageLab-RELEASE-AUTHORIZED`

It appears only when all gates pass. It contains:

- the exact tested installer;
- `ImageLab-RELEASE-AUTHORIZATION.json`, which must accompany the installer when it becomes the baseline for a later release.

### Blocked

Download:

`ImageLab-RELEASE-VERDICT`

Inspect `final-verdict.json` and `release-evidence.zip`. The workflow intentionally ends in failure. Do not install the internal candidate.

## Gates

- G0: source, identity, JavaScript and backend self-test.
- G1: all 26 required test files in isolated processes.
- G2: two byte-identical Windows installer builds.
- G3: clean Windows installation of the exact candidate plus mandatory preinstall and postinstall embedded self-tests.
- G4: installed UI driven in Microsoft Edge.
- G5: binary inspection of PNG, PPI, alpha, halftone, SVG and lineage.
- G6: update from the real previous authorized installer while it is running, with a SHA-pinned prior finalizer authorization record and real-project preservation evidence.
- G7: forced post-promotion failure, exact rollback and real-project restoration.
- G8: independent reinstall, embedded self-tests and UI/output rerun in bundled Chromium.

## Non-negotiable rule

A locally built EXE, a source test PASS, an API test PASS, an internal candidate artifact, a matching filename, or an operator-entered boolean is not a release. Only an exact installer that passed all applicable gates and has a valid finalizer-generated authorization record may become `ImageLab-RELEASE-AUTHORIZED`.
