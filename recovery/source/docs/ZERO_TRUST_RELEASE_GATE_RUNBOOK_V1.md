# ImageLab Zero-Trust Release Gate — Runbook v1

## Purpose

Do not install or distribute a candidate until the exact Windows installer passes G0–G8 and a genuine physical user-machine L5 record is independently SHA-pinned and accepted. The artifact named `UNVERIFIED_INTERNAL_EXACT_CANDIDATE` is internal only and must never be given to a user.

## Normal-release baseline setup

1. Use a genuine previous release authorized by the fail-closed finalizer. A merely used, renamed, diagnostic, recovery or internal candidate is not an authorized baseline.
2. A prior one-time `GENESIS_RELEASE_AUTHORIZED` release is valid as the baseline for later normal releases. Genesis is never reusable as a release mode after an authorized release exists.
3. The same GitHub Release must contain exactly one installer matching `ImageLab_by_LarannA_*RELEASE_AUTHORIZED*_Setup_x64.exe`.
4. The same release must contain exactly one finalizer record matching `ImageLab*RELEASE-AUTHORIZATION.json`.
5. Independently record both SHA-256 values:
   - SHA-256 of the authorized installer;
   - SHA-256 of its finalizer authorization record.
6. Do not derive either pinned value from the workflow run currently being tested.
7. The record must bind the exact installer name and SHA-256 to `RELEASE_AUTHORIZED` or `GENESIS_RELEASE_AUTHORIZED` and include the previous final-verdict and release-evidence digests.

## Physical user-machine L5 record

The physical record is external evidence. A synthetic fixture can test parser behavior but cannot satisfy the real release prerequisite.

The JSON record must be no larger than 1 MiB and contain:

```json
{
  "schema": 1,
  "status": "PASS",
  "execution_environment": "physical_user_windows",
  "hosted_runner": false,
  "executed_at": "UTC ISO-8601 timestamp",
  "candidate": {
    "source_sha256": "64 lowercase hexadecimal characters",
    "installer_name": "exact installer filename",
    "installer_sha256": "64 lowercase hexadecimal characters",
    "version": "exact version",
    "build_id": "exact Build ID",
    "install_id": "install ID observed on the physical machine"
  },
  "scenario": {
    "browser_driven": true,
    "steps": {
      "upload": {"status": "PASS"},
      "operation": {"status": "PASS"},
      "history": {"status": "PASS"},
      "export": {"status": "PASS"}
    }
  },
  "outputs": [
    {
      "name": "generated output filename",
      "sha256": "64 lowercase hexadecimal characters",
      "validator_status": "PASS"
    }
  ],
  "direct_witness": {
    "name": "Dmitry",
    "confirmed": true,
    "statement": "explicit direct-witness statement",
    "witnessed_at": "UTC ISO-8601 timestamp"
  }
}
```

Additional rules:

- `install_id` must differ from the hosted clean and independent runner install IDs.
- The record must be created no more than 72 hours before finalization and must not be future-dated.
- Every required scenario step must be `PASS`.
- At least one generated output must have a valid SHA-256 and `validator_status=PASS`.
- The record is accepted only when its bytes match the independently supplied SHA-256.
- This is a fail-closed witness record. It is not represented as cryptographic proof that the machine was physical.

## Run a normal release gate

1. Open **Actions → ImageLab Zero-Trust Release Gate → Run workflow**.
2. Enter:
   - `baseline_release_tag` — tag of the previous normal or Genesis authorized release;
   - `baseline_installer_sha256` — independently pinned installer SHA-256;
   - `baseline_authorization_record_sha256` — independently pinned prior finalizer-record SHA-256;
   - `physical_l5_evidence_url` — credential-free HTTPS URL of the witnessed physical-L5 JSON;
   - `physical_l5_evidence_sha256` — independently pinned SHA-256 of that JSON;
   - `enable_attestation` — optional.
3. Start the workflow manually.
4. The workflow downloads at most 1 MiB, requires HTTPS after redirects, verifies SHA-256 before publication, validates UTF-8 JSON, and writes the record atomically.

## Result interpretation

### Authorized

Only the artifact `ImageLab-RELEASE-AUTHORIZED` may be distributed. It appears only when every gate and physical L5 pass. It contains:

- the exact tested installer;
- `ImageLab-RELEASE-AUTHORIZATION.json`, which must accompany the installer when it becomes a later baseline.

### Blocked

Download `ImageLab-RELEASE-VERDICT` and inspect `final-verdict.json` plus `release-evidence.zip`. The workflow intentionally ends in failure. Stale normal and Genesis authorization outputs are deleted before evaluation and on every failure.

## Gates

- G0: source, identity, JavaScript and backend self-test.
- G1: all required test files in isolated processes.
- G2: two byte-identical Windows installer builds.
- G3: clean Windows installation plus mandatory preinstall and postinstall embedded self-tests.
- G4: installed UI driven in Microsoft Edge.
- G5: binary inspection of PNG, PPI, alpha, halftone, SVG and lineage.
- G6: update from a real prior normal or Genesis authorized installer, with independently pinned installer and authorization-record hashes.
- G7: forced post-promotion failure, exact rollback and complete real-project restoration.
- G8: independent reinstall, embedded self-tests and UI/output rerun in bundled Chromium.
- Physical L5: separate real-machine browser path and output validation witnessed directly by Dmitry.

## Non-negotiable rule

A local EXE, source PASS, API PASS, hosted L5, internal candidate, matching filename, synthetic JSON or operator-entered boolean is not a release. Only an exact installer that passes all applicable gates and has a valid finalizer-generated authorization record may be distributed.
