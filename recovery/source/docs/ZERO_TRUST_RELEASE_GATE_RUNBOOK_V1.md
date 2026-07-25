# ImageLab Zero-Trust Release Gate — Runbook v1

## Purpose

Do not install or distribute a candidate until the applicable release path passes every required gate. Internal or unverified candidate artifacts must never be given to an end user as a release.

## Normal release path

Use the normal **ImageLab Zero-Trust Release Gate** after at least one genuine authorized release exists.

The previous GitHub Release must contain exactly one installer matching:

`ImageLab_by_LarannA_RELEASE_AUTHORIZED*_Setup_x64.exe`

It must also contain:

`ImageLab-RELEASE-AUTHORIZATION.json`

Independently record the SHA-256 values of both files. The authorization record must bind the exact installer name and SHA-256 to `status=RELEASE_AUTHORIZED` and include the prior final verdict and release-evidence digests.

Run the normal workflow with:

- `baseline_release_tag`;
- `baseline_installer_sha256`;
- `baseline_authorization_record_sha256`;
- optional `enable_attestation`.

A merely used, renamed, diagnostic, recovery or internal candidate is not an authorized baseline.

## One-time genesis first-release path

Use **ImageLab Genesis First Release Gate** only when no genuine authorized ImageLab release has ever existed.

### Step 1 — Exact hosted qualification

Run **ImageLab Zero-Trust Release Gate** for the exact candidate. Because no prior authorized baseline exists, that run must remain `RELEASE_BLOCKED`, but it must produce complete PASS evidence for G0–G5 and G8.

Record:

- the qualification workflow run ID;
- the exact 40-character qualification head SHA.

The genesis finalizer independently revalidates the downloaded candidate, self-tests, installed UI evidence, output evidence and the blocked qualification verdict.

### Step 2 — Physical user-machine L5

Test the exact installer binary on the physical Windows user machine. Produce exactly two release assets:

- `ImageLab-PHYSICAL-L5.json`;
- `ImageLab-PHYSICAL-L5-EVIDENCE.zip`.

The manifest must contain:

- `schema=1` and `status=PASS`;
- `evidence_level=L5`;
- `execution_environment=physical_user_machine`;
- exact installer SHA-256, application, version, build ID and install ID;
- UTC observation time;
- product-owner witness;
- Windows version;
- PASS results for installed launch, browser UI path, resize/PPI, background removal, halftone, vector, history lineage, export and output-file validation;
- SHA-256 of the evidence ZIP;
- the list of evidence files.

The ZIP must contain at minimum:

- `clean-install.json`;
- `preinstall-selftest.json`;
- `postinstall-selftest.json`;
- `ui-gate.json`;
- `output-validation.json`;
- PNG evidence;
- SVG output evidence;
- browser trace evidence.

Upload both files to a GitHub Release used only as the physical-evidence carrier. Do not add any authorized installer or `ImageLab-RELEASE-AUTHORIZATION.json` to that release.

Independently record the SHA-256 values of the manifest and ZIP.

### Step 3 — Run genesis workflow

Enter:

- `qualification_run_id`;
- `qualification_head_sha`;
- `physical_l5_release_tag`;
- `physical_l5_manifest_sha256`;
- `physical_l5_bundle_sha256`;
- optional `enable_attestation`.

The workflow performs a complete paginated GitHub Releases query. It fails if it finds any prior asset matching an authorized ImageLab installer or `ImageLab-RELEASE-AUTHORIZATION.json`.

For this one run only, G6 and G7 are recorded as `NOT_APPLICABLE_FIRST_RELEASE`, not `PASS`.

### Genesis result

Only `ImageLab-GENESIS-RELEASE-AUTHORIZED` may be used when the genesis finalizer succeeds. It contains:

- the exact qualified installer renamed as authorized;
- the first genuine `ImageLab-RELEASE-AUTHORIZATION.json`.

That authorization record becomes the mandatory baseline record for the next normal release.

After the first authorization assets exist, the genesis workflow must fail closed permanently.

## Blocked results

Normal path:

`ImageLab-RELEASE-VERDICT`

Genesis path:

`ImageLab-GENESIS-RELEASE-VERDICT`

Inspect `final-verdict.json` and `release-evidence.zip`. A blocked workflow intentionally ends in failure. Do not distribute the candidate.

## Non-negotiable rules

- Never retroactively label an old installer as authorized.
- Never use the current candidate as its own previous baseline.
- Never replace physical user-machine L5 with a hosted runner or a manually typed PASS flag.
- Never treat `NOT_APPLICABLE_FIRST_RELEASE` as `PASS`.
- Never run genesis after the first genuine authorization record exists.
- A matching filename, source test, API test, internal candidate or operator-entered boolean is not a release.
