from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

GENESIS_RULE = "GENESIS-FIRST-RELEASE-V1"
AUTHORIZED_INSTALLER_PREFIX = "ImageLab_by_LarannA_RELEASE_AUTHORIZED"
AUTHORIZED_INSTALLER_SUFFIX = "_Setup_x64.exe"
AUTHORIZATION_RECORD_NAME = "ImageLab-RELEASE-AUTHORIZATION.json"


def _flatten_releases(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("GitHub releases response must be a JSON array")
    releases: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, list):
            for nested in item:
                if not isinstance(nested, dict):
                    raise TypeError("GitHub release page contains a non-object item")
                releases.append(nested)
        elif isinstance(item, dict):
            releases.append(item)
        else:
            raise TypeError("GitHub releases response contains a non-object item")
    return releases


def inspect_releases(value: Any, repository: str) -> dict[str, Any]:
    if not repository or "/" not in repository:
        raise ValueError("repository must be owner/name")

    releases = _flatten_releases(value)
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
            is_installer = name.startswith(AUTHORIZED_INSTALLER_PREFIX) and name.endswith(AUTHORIZED_INSTALLER_SUFFIX)
            is_record = name == AUTHORIZATION_RECORD_NAME
            if is_installer:
                installer_count += 1
            if is_record:
                record_count += 1
            if is_installer or is_record:
                matching_assets.append({"tag": tag, "name": name})

    status = "PASS" if installer_count == 0 and record_count == 0 else "FAIL"
    return {
        "schema": 1,
        "status": status,
        "release_mode": "genesis_first_release",
        "protocol_rule": GENESIS_RULE,
        "repository": repository,
        "query_source": "github_api_releases_paginated",
        "query_complete": True,
        "release_count_scanned": len(releases),
        "authorized_installer_asset_count": installer_count,
        "authorization_record_asset_count": record_count,
        "matching_assets": matching_assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--releases-json", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = json.loads(args.releases_json.read_text("utf-8-sig"))
        result = inspect_releases(value, args.repository)
    except Exception as exc:
        result = {
            "schema": 1,
            "status": "FAIL",
            "release_mode": "genesis_first_release",
            "protocol_rule": GENESIS_RULE,
            "repository": args.repository,
            "query_source": "github_api_releases_paginated",
            "query_complete": False,
            "release_count_scanned": 0,
            "authorized_installer_asset_count": None,
            "authorization_record_asset_count": None,
            "matching_assets": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
