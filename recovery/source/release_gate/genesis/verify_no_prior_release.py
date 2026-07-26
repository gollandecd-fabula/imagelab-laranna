from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GENESIS_RULE = "GENESIS-FIRST-RELEASE-V1"
AUTHORIZED_INSTALLER_PREFIXES = (
    "ImageLab_by_LarannA_RELEASE_AUTHORIZED",
    "ImageLab_by_LarannA_GENESIS_RELEASE_AUTHORIZED",
)
AUTHORIZED_INSTALLER_SUFFIX = "_Setup_x64.exe"
AUTHORIZATION_RECORD_NAMES = {
    "ImageLab-RELEASE-AUTHORIZATION.json",
    "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json",
}
AUTHORIZED_ARTIFACT_NAMES = {
    "ImageLab-RELEASE-AUTHORIZED",
    "ImageLab-GENESIS-RELEASE-AUTHORIZED",
}
AUTHORIZED_WORKFLOW_NAMES = {
    "ImageLab Zero-Trust Release Gate",
    "ImageLab Genesis First Release Gate",
    "ImageLab Genesis Request Gate",
}


def _flatten_array(value: Any, key: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("GitHub response must be a JSON array")
    items: list[dict[str, Any]] = []
    for page in value:
        if isinstance(page, list):
            candidates = page
        elif isinstance(page, dict) and key is not None:
            candidates = page.get(key, [])
            if not isinstance(candidates, list):
                raise TypeError(f"GitHub page field {key!r} is not an array")
        elif isinstance(page, dict) and key is None:
            candidates = [page]
        else:
            raise TypeError("GitHub response contains a malformed page")
        for item in candidates:
            if not isinstance(item, dict):
                raise TypeError("GitHub response contains a non-object item")
            items.append(item)
    return items


def inspect_history(
    releases_value: Any,
    workflow_runs_value: Any,
    artifacts_value: Any,
    repository: str,
    current_run_id: int,
) -> dict[str, Any]:
    if not repository or "/" not in repository:
        raise ValueError("repository must be owner/name")
    if isinstance(current_run_id, bool) or not isinstance(current_run_id, int) or current_run_id <= 0:
        raise ValueError("current_run_id must be a positive integer")

    releases = _flatten_array(releases_value)
    all_runs = _flatten_array(workflow_runs_value, "workflow_runs")
    all_artifacts = _flatten_array(artifacts_value, "artifacts")
    matching_assets: list[dict[str, str]] = []
    installer_count = 0
    record_count = 0

    for release in releases:
        tag = str(release.get("tag_name") or "")
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            raise TypeError(f"release {tag!r} has malformed assets")
        for asset in assets:
            if not isinstance(asset, dict):
                raise TypeError(f"release {tag!r} contains a malformed asset")
            name = str(asset.get("name") or "")
            is_installer = any(name.startswith(prefix) for prefix in AUTHORIZED_INSTALLER_PREFIXES) and name.endswith(
                AUTHORIZED_INSTALLER_SUFFIX
            )
            is_record = name in AUTHORIZATION_RECORD_NAMES
            if is_installer:
                installer_count += 1
            if is_record:
                record_count += 1
            if is_installer or is_record:
                matching_assets.append({"tag": tag, "name": name})

    relevant_runs = [run for run in all_runs if str(run.get("name") or "") in AUTHORIZED_WORKFLOW_NAMES]
    prior_successful_runs: list[dict[str, Any]] = []
    for run in relevant_runs:
        run_id = int(run.get("id") or 0)
        if run.get("conclusion") == "success" and run_id != current_run_id:
            prior_successful_runs.append(
                {
                    "run_id": run_id,
                    "workflow_name": str(run.get("name") or ""),
                    "head_sha": str(run.get("head_sha") or ""),
                    "created_at": run.get("created_at"),
                }
            )

    relevant_artifacts = [artifact for artifact in all_artifacts if artifact.get("name") in AUTHORIZED_ARTIFACT_NAMES]
    prior_authorized_artifacts: list[dict[str, Any]] = []
    for artifact in relevant_artifacts:
        workflow_run = artifact.get("workflow_run")
        run_id = int(workflow_run.get("id") or 0) if isinstance(workflow_run, dict) else 0
        if run_id != current_run_id:
            prior_authorized_artifacts.append(
                {
                    "artifact_id": artifact.get("id"),
                    "name": artifact.get("name"),
                    "run_id": run_id,
                    "expired": bool(artifact.get("expired")),
                    "created_at": artifact.get("created_at"),
                }
            )

    status = "PASS" if not any((installer_count, record_count, prior_successful_runs, prior_authorized_artifacts)) else "FAIL"
    return {
        "schema": 3,
        "status": status,
        "release_mode": "genesis_first_release",
        "protocol_rule": GENESIS_RULE,
        "repository": repository,
        "query_source": "github_api_releases_all_authorization_runs_artifacts_paginated",
        "query_complete": True,
        "current_run_id": current_run_id,
        "authorization_workflow_names": sorted(AUTHORIZED_WORKFLOW_NAMES),
        "release_count_scanned": len(releases),
        "workflow_run_count_scanned": len(relevant_runs),
        "artifact_count_scanned": len(relevant_artifacts),
        "authorized_installer_asset_count": installer_count,
        "authorization_record_asset_count": record_count,
        "prior_successful_authorization_run_count": len(prior_successful_runs),
        "prior_authorized_artifact_count": len(prior_authorized_artifacts),
        "prior_successful_authorization_runs": prior_successful_runs,
        "prior_authorized_artifacts": prior_authorized_artifacts,
        "matching_assets": matching_assets,
    }


def inspect_releases(value: Any, repository: str) -> dict[str, Any]:
    return inspect_history(value, [], [], repository, 1)


def _failed_result(repository: str, current_run_id: int, error: Exception) -> dict[str, Any]:
    return {
        "schema": 3,
        "status": "FAIL",
        "release_mode": "genesis_first_release",
        "protocol_rule": GENESIS_RULE,
        "repository": repository,
        "query_source": "github_api_releases_all_authorization_runs_artifacts_paginated",
        "query_complete": False,
        "current_run_id": current_run_id,
        "authorization_workflow_names": sorted(AUTHORIZED_WORKFLOW_NAMES),
        "release_count_scanned": 0,
        "workflow_run_count_scanned": 0,
        "artifact_count_scanned": 0,
        "authorized_installer_asset_count": None,
        "authorization_record_asset_count": None,
        "prior_successful_authorization_run_count": None,
        "prior_authorized_artifact_count": None,
        "prior_successful_authorization_runs": [],
        "prior_authorized_artifacts": [],
        "matching_assets": [],
        "error": f"{type(error).__name__}: {error}",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--releases-json", type=Path, required=True)
    parser.add_argument("--workflow-runs-json", type=Path, required=True)
    parser.add_argument("--artifacts-json", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--current-run-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        releases = json.loads(args.releases_json.read_text("utf-8-sig"))
        runs = json.loads(args.workflow_runs_json.read_text("utf-8-sig"))
        artifacts = json.loads(args.artifacts_json.read_text("utf-8-sig"))
        result = inspect_history(releases, runs, artifacts, args.repository, args.current_run_id)
    except Exception as exc:
        result = _failed_result(args.repository, args.current_run_id, exc)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
