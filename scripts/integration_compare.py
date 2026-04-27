#!/usr/bin/env python3
"""
Integration comparison script.

Calls 13 safe GET endpoints against both:
  - LOCAL:  http://localhost:7071  (refactor/semantic-layer branch)
  - AZURE:  https://health.azure.barrimond.net  (main/SemanticLayer monolith)

Both deployments share the same Azure Table Storage, so responses must be
structurally equivalent. Rating per endpoint: PASS / WARN / FAIL.

Usage:
    python scripts/integration_compare.py \
        --azure-key <KEY> \
        --workout-id <ID> \
        [--athlete-id rob]
"""

import argparse
import json
import sys
from typing import Any

import urllib.request
import urllib.error


LOCAL = "http://localhost:7071"
AZURE = "https://health.azure.barrimond.net"


def fetch(url: str, label: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=300) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:
        print(f"  !! {label} request error: {exc}", file=sys.stderr)
        return -1, None


def top_keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj.keys())
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return set(obj[0].keys())
    return set()


def compare(
    name: str,
    local_url: str,
    azure_url: str,
) -> str:
    """Returns PASS, WARN, or FAIL."""
    l_status, l_body = fetch(local_url, "local")
    a_status, a_body = fetch(azure_url, "azure")

    status_match = l_status == a_status

    if not status_match:
        result = "FAIL"
        note = f"status mismatch: local={l_status} azure={a_status}"
    elif l_status >= 400:
        result = "WARN"
        note = f"both returned HTTP {l_status}"
    else:
        l_keys = top_keys(l_body)
        a_keys = top_keys(a_body)
        if l_keys != a_keys:
            result = "FAIL"
            only_local = l_keys - a_keys
            only_azure = a_keys - l_keys
            parts = []
            if only_local:
                parts.append(f"only-local={sorted(only_local)}")
            if only_azure:
                parts.append(f"only-azure={sorted(only_azure)}")
            note = "key mismatch: " + "; ".join(parts)
        else:
            result = "PASS"
            note = f"HTTP {l_status}, keys={sorted(l_keys) or '(list/scalar)'}"

    symbol = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[result]
    print(f"  {symbol}  {result:<4}  {name}", flush=True)
    print(f"         local : {local_url}", flush=True)
    print(f"         azure : {azure_url}", flush=True)
    print(f"         note  : {note}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Local vs Azure integration compare")
    parser.add_argument("--azure-key", required=True, help="Azure function host key")
    parser.add_argument("--workout-id", required=True, help="A real workout_id")
    parser.add_argument("--athlete-id", default="rob")
    args = parser.parse_args()

    key = args.azure_key
    wid = args.workout_id
    aid = args.athlete_id

    def local(path: str) -> str:
        return f"{LOCAL}{path}"

    def azure(path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"{AZURE}{path}{sep}code={key}"

    endpoints: list[tuple[str, str]] = [
        ("GET /api/health",
         "/api/health"),
        ("GET /api/workouts?limit=1",
         f"/api/workouts?athlete_id={aid}&limit=1"),
        ("GET /api/workouts/{workout_id}?laps=false",
         f"/api/workouts/{wid}?athlete_id={aid}&laps=false"),
        ("GET /api/workouts/{workout_id}/laps/0",
         f"/api/workouts/{wid}/laps/0?athlete_id={aid}"),
        ("GET /api/rollups/weekly?weeks=4",
         f"/api/rollups/weekly?athlete_id={aid}&weeks=4"),
        ("GET /api/analysis/zones?days=7",
         f"/api/analysis/zones?athlete_id={aid}&days=7"),
        ("GET /api/analysis/efficiency?days=7",
         f"/api/analysis/efficiency?athlete_id={aid}&days=7"),
        ("GET /api/planning/context",
         f"/api/planning/context?athlete_id={aid}"),
        ("GET /api/physiometrics/current",
         f"/api/physiometrics/current?athlete_id={aid}"),
        ("GET /api/physiometrics/history?days=7",
         f"/api/physiometrics/history?athlete_id={aid}&days=7"),
        ("GET /api/training-state/current",
         f"/api/training-state/current?athlete_id={aid}"),
        ("GET /api/training-state/history?days=7",
         f"/api/training-state/history?athlete_id={aid}&days=7"),
        ("GET /api/agent/context",
         f"/api/agent/context?athlete_id={aid}"),
    ]

    results: list[str] = []
    print(f"\n{'='*70}", flush=True)
    print("Integration Comparison: local (refactor) vs Azure (main)", flush=True)
    print(f"athlete_id : {aid}", flush=True)
    print(f"workout_id : {wid}", flush=True)
    print(f"{'='*70}\n", flush=True)

    for name, path in endpoints:
        r = compare(name, local(path), azure(path))
        results.append(r)
        print(flush=True)

    passed = results.count("PASS")
    warned = results.count("WARN")
    failed = results.count("FAIL")
    total = len(results)

    print("=" * 70, flush=True)
    print(f"SUMMARY: {passed}/{total} PASS  |  {warned} WARN  |  {failed} FAIL", flush=True)
    print("=" * 70, flush=True)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
