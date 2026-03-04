#!/usr/bin/env python3
"""
Stage 3: Submit Judge Prompts to Anthropic Batch API
======================================================

Reads all Stage 1 JSON outputs (evaluation/test_outputs/**/*.json),
calls the appropriate Stage 2 build_judge_prompt() for each record,
packages them into an Anthropic Batch API request, polls until done,
then parses results into a scoring dashboard.

Usage:
    # Submit all test outputs and wait for results
    python -m evaluation.run_judge_batch

    # Submit specific agents only
    python -m evaluation.run_judge_batch --agents outreach tldr

    # Submit without waiting (poll later)
    python -m evaluation.run_judge_batch --no-wait

    # Poll an existing batch (skip submission)
    python -m evaluation.run_judge_batch --batch-id msgbatch_abc123

    # Custom input / output directories
    python -m evaluation.run_judge_batch \\
        --input-dir evaluation/test_outputs \\
        --output-dir evaluation/results

Output layout:
    evaluation/results/
        batch_manifest.json          # Maps custom_id -> test_case metadata
        raw_responses.jsonl          # One line per judge response (raw Batch API format)
        scores.json                  # Parsed per-dimension scores, keyed by test_case_id
        scores.csv                   # Flat CSV for easy import into spreadsheets
        dashboard.md                 # Human-readable markdown summary table
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

import anthropic

logger = logging.getLogger(__name__)

# Judge model — use the most capable available
JUDGE_MODEL = "claude-sonnet-4-6"

# Batch API constraints
MAX_REQUESTS_PER_BATCH = 10_000

# Poll interval (seconds) when --wait is active
POLL_INTERVAL_SECONDS = 30

# Default directories
DEFAULT_INPUT_DIR = "evaluation/test_outputs"
DEFAULT_OUTPUT_DIR = "evaluation/results"


# =============================================================================
# BUILD JUDGE REQUESTS FROM STAGE 1 JSON FILES
# =============================================================================

def load_test_records(input_dir: Path, agents: list[str]) -> list[dict]:
    """
    Load all Stage 1 JSON records from subdirectories matching `agents`.

    Args:
        input_dir: Root directory of Stage 1 outputs (e.g., evaluation/test_outputs)
        agents: List of agent names to include ("outreach", "tldr", "news_aggregator")

    Returns:
        List of record dicts, each with keys: test_case_id, agent, company_bundle, etc.
    """
    records = []
    for agent_name in agents:
        agent_dir = input_dir / agent_name
        if not agent_dir.exists():
            logger.warning(f"Agent output dir not found: {agent_dir} — skipping")
            continue
        for json_file in sorted(agent_dir.glob("*.json")):
            try:
                record = json.loads(json_file.read_text())
                if not record.get("success"):
                    logger.warning(
                        f"Skipping failed test case: {record.get('test_case_id', json_file.name)}"
                    )
                    continue
                records.append(record)
            except Exception as exc:
                logger.error(f"Could not parse {json_file}: {exc}")
    return records


def build_batch_requests(records: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """
    Convert Stage 1 records into Anthropic Batch API request objects.

    Each request has:
        custom_id  — sanitized test_case_id (dots replaced with dashes to satisfy
                     Batch API pattern ^[a-zA-Z0-9_-]{1,64}$)
        params     — {model, max_tokens, system, messages: [{role, content}]}

    Returns (batch_requests, id_map) where id_map maps safe_id → original test_case_id.
    """
    from evaluation.judge_prompts.outreach_judge import build_judge_prompt as outreach_judge
    from evaluation.judge_prompts.tldr_judge import build_judge_prompt as tldr_judge
    from evaluation.judge_prompts.news_aggregator_judge import build_judge_prompt as news_judge

    batch_requests = []
    id_map: dict[str, str] = {}  # safe_id → original test_case_id

    for record in records:
        agent = record.get("agent")
        test_case_id = record.get("test_case_id", "unknown")

        try:
            if agent == "outreach":
                system_prompt, user_prompt = outreach_judge(
                    company_bundle=record.get("company_bundle", {}),
                    agent_output=record.get("agent_output", {}),
                    context_tags=record.get("context_tags", {}),
                )

            elif agent == "tldr":
                system_prompt, user_prompt = tldr_judge(
                    company_bundle=record.get("company_bundle", {}),
                    agent_output=record.get("agent_output", {}),
                    context_tags=record.get("context_tags", {}),
                )

            elif agent == "news_aggregator":
                system_prompt, user_prompt = news_judge(
                    raw_signals=record.get("raw_signals", []),
                    watchlist=record.get("watchlist", []),
                    agent_output=record.get("agent_output", {}),
                    context_tags=record.get("context_tags", {}),
                )

            else:
                logger.warning(f"Unknown agent '{agent}' for {test_case_id} — skipping")
                continue

            # News aggregator has 12 rubric dimensions — needs more output space
            max_tokens = 32000 if agent == "news_aggregator" else 16000

            # Batch API custom_id must match ^[a-zA-Z0-9_-]{1,64}$ — replace dots
            safe_id = test_case_id.replace(".", "-")
            id_map[safe_id] = test_case_id
            batch_requests.append({
                "custom_id": safe_id,
                "params": {
                    "model": JUDGE_MODEL,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            })

        except Exception as exc:
            logger.error(f"Could not build judge prompt for {test_case_id}: {exc}")

    return batch_requests, id_map


# =============================================================================
# BATCH SUBMISSION
# =============================================================================

def submit_batch(
    batch_requests: list[dict],
    client: anthropic.Anthropic,
) -> str:
    """
    Submit batch requests to the Anthropic Batch API.

    If > MAX_REQUESTS_PER_BATCH, splits into multiple batches and returns
    a comma-separated string of batch IDs.

    Returns:
        Batch ID (or comma-separated IDs if multiple batches).
    """
    if not batch_requests:
        raise ValueError("No batch requests to submit")

    batch_ids = []
    chunks = [
        batch_requests[i : i + MAX_REQUESTS_PER_BATCH]
        for i in range(0, len(batch_requests), MAX_REQUESTS_PER_BATCH)
    ]

    for i, chunk in enumerate(chunks, 1):
        logger.info(f"Submitting batch {i}/{len(chunks)} ({len(chunk)} requests)...")
        response = client.messages.batches.create(requests=chunk)
        batch_id = response.id
        batch_ids.append(batch_id)
        logger.info(f"  Batch {i} submitted: {batch_id}")

    return ",".join(batch_ids)


# =============================================================================
# POLLING
# =============================================================================

def poll_until_done(
    batch_ids: list[str],
    client: anthropic.Anthropic,
    interval: int = POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """
    Poll all batches until all are in a terminal state (ended/errored/expired/canceled).

    Returns a dict mapping batch_id -> final batch object.
    """
    remaining = set(batch_ids)
    finished = {}

    while remaining:
        still_running = set()
        for batch_id in remaining:
            batch = client.messages.batches.retrieve(batch_id)
            status = batch.processing_status

            counts = batch.request_counts
            logger.info(
                f"  [{batch_id}] status={status} "
                f"processing={counts.processing} "
                f"succeeded={counts.succeeded} "
                f"errored={counts.errored}"
            )

            if status in ("ended", "expired", "canceled"):
                finished[batch_id] = batch
            else:
                still_running.add(batch_id)

        remaining = still_running
        if remaining:
            logger.info(f"  Waiting {interval}s before next poll...")
            time.sleep(interval)

    return finished


# =============================================================================
# RESULTS PARSING
# =============================================================================

def fetch_and_parse_results(
    batch_ids: list[str],
    client: anthropic.Anthropic,
    output_dir: Path,
    id_map: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Stream all results from completed batches, save raw JSONL, and parse
    each judge response JSON into a structured score record.

    Returns:
        (raw_results, score_records)
        - raw_results: one dict per result (custom_id + raw response content)
        - score_records: one dict per result with parsed dimension scores
    """
    raw_results: list[dict] = []
    score_records: list[dict] = []

    raw_jsonl_path = output_dir / "raw_responses.jsonl"

    with raw_jsonl_path.open("w") as raw_f:
        for batch_id in batch_ids:
            for result in client.messages.batches.results(batch_id):
                safe_id = result.custom_id
                original_id = (id_map or {}).get(safe_id, safe_id)
                result_type = result.result.type  # "succeeded" | "errored" | "expired" | "canceled"

                raw_entry = {
                    "batch_id": batch_id,
                    "custom_id": original_id,
                    "result_type": result_type,
                }

                if result_type == "succeeded":
                    content_blocks = result.result.message.content
                    # Judge always returns a single text block
                    text = content_blocks[0].text if content_blocks else ""
                    raw_entry["content"] = text

                    parsed = _parse_judge_response(original_id, text)
                    score_records.append(parsed)
                else:
                    raw_entry["error"] = str(result.result)
                    score_records.append({
                        "test_case_id": original_id,
                        "judge_success": False,
                        "error": result_type,
                    })

                raw_f.write(json.dumps(raw_entry) + "\n")
                raw_results.append(raw_entry)

    logger.info(f"Raw responses saved to {raw_jsonl_path}")
    return raw_results, score_records


def _parse_judge_response(custom_id: str, text: str) -> dict:
    """
    Extract the JSON block from the judge's chain-of-thought response.

    The judge is prompted to output a fenced JSON block at the end of its
    reasoning. We locate the last ```json ... ``` block in the response.

    Returns a dict with test_case_id + all parsed fields (or error info).
    """
    import re

    # Infer agent from custom_id prefix
    if custom_id.startswith("news_aggregator"):
        agent = "news_aggregator"
    elif custom_id.startswith("tldr"):
        agent = "tldr"
    elif custom_id.startswith("outreach"):
        agent = "outreach"
    else:
        agent = "unknown"

    base = {"test_case_id": custom_id, "agent": agent, "judge_success": False}

    # Find the last ```json ... ``` block (chain-of-thought comes before it)
    matches = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if not matches:
        logger.warning(f"No JSON block found in judge response for {custom_id}")
        base["error"] = "no_json_block"
        base["raw_text"] = text[:500]
        return base

    json_str = matches[-1]  # Take the last (most complete) block
    try:
        parsed = json.loads(json_str)
        parsed["test_case_id"] = custom_id
        parsed["agent"] = agent
        parsed["judge_success"] = True
        return parsed
    except json.JSONDecodeError as exc:
        logger.warning(f"JSON parse error for {custom_id}: {exc}")
        base["error"] = f"json_parse_error: {exc}"
        base["raw_json"] = json_str[:500]
        return base


# =============================================================================
# REAL-TIME (NO-BATCH) MODE
# =============================================================================

def run_realtime(
    batch_requests: list[dict],
    client: anthropic.Anthropic,
    output_dir: Path,
    id_map: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Run judge calls sequentially via the regular Messages API.

    Used with --no-batch for quick iteration without the Batch API delay.
    Produces the same raw_responses.jsonl + score_records as the batch path.

    Returns:
        (raw_results, score_records)
    """
    raw_results: list[dict] = []
    score_records: list[dict] = []
    total = len(batch_requests)

    raw_jsonl_path = output_dir / "raw_responses.jsonl"

    with raw_jsonl_path.open("w") as raw_f:
        for i, req in enumerate(batch_requests, 1):
            safe_id = req["custom_id"]
            original_id = (id_map or {}).get(safe_id, safe_id)
            params = req["params"]
            print(f"  [{i}/{total}] Judging {original_id}...", end=" ", flush=True)

            raw_entry = {"custom_id": original_id, "result_type": "succeeded"}

            try:
                # Use streaming for large max_tokens (required by SDK for >10min ops)
                if params["max_tokens"] > 16000:
                    with client.messages.stream(
                        model=params["model"],
                        max_tokens=params["max_tokens"],
                        system=params["system"],
                        messages=params["messages"],
                    ) as stream:
                        text = stream.get_final_text()
                        final_msg = stream.get_final_message()
                    usage = final_msg.usage
                else:
                    response = client.messages.create(
                        model=params["model"],
                        max_tokens=params["max_tokens"],
                        system=params["system"],
                        messages=params["messages"],
                    )
                    text = response.content[0].text
                    usage = response.usage
                raw_entry["content"] = text
                print(f"({usage.input_tokens}in/{usage.output_tokens}out tokens)")

                parsed = _parse_judge_response(original_id, text)
                score_records.append(parsed)

            except Exception as exc:
                raw_entry["result_type"] = "errored"
                raw_entry["error"] = str(exc)
                score_records.append({
                    "test_case_id": original_id,
                    "judge_success": False,
                    "error": str(exc),
                })
                print(f"ERROR: {exc}")

            raw_f.write(json.dumps(raw_entry) + "\n")
            raw_results.append(raw_entry)

    logger.info(f"Raw responses saved to {raw_jsonl_path}")
    return raw_results, score_records


# =============================================================================
# DASHBOARD GENERATION
# =============================================================================

def build_manifest(records: list[dict]) -> dict:
    """Build a manifest mapping test_case_id to key metadata."""
    return {
        r["test_case_id"]: {
            "agent": r.get("agent"),
            "company_id": r.get("company_id"),
            "investor_key": r.get("investor_key"),
            "output_format": r.get("output_format"),
            "days": r.get("days"),
        }
        for r in records
    }


def save_scores_json(score_records: list[dict], output_dir: Path):
    """Save scores, merging with any existing results (new scores overwrite by test_case_id)."""
    path = output_dir / "scores.json"
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = []
    existing_by_id = {r["test_case_id"]: r for r in existing if "test_case_id" in r}
    for r in score_records:
        if "test_case_id" in r:
            existing_by_id[r["test_case_id"]] = r
    merged = sorted(existing_by_id.values(), key=lambda r: r.get("test_case_id", ""))
    path.write_text(json.dumps(merged, indent=2, default=str))
    logger.info(f"Scores saved to {path}")


def save_scores_csv(score_records: list[dict], output_dir: Path):
    """
    Flatten score records into a CSV with one row per test case.

    Extracts the most common cross-agent fields:
        test_case_id, judge_success, composite_score, pass_fail,
        and a selection of per-dimension scores.
    """
    path = output_dir / "scores.csv"

    # Determine all fieldnames from the union of all records
    all_keys: list[str] = []
    seen: set = set()
    priority_keys = [
        "test_case_id", "agent", "judge_success", "composite_score",
        "weighted_score", "pass_fail", "composite_forced_to_zero",
        "hard_failures_detected", "error",
    ]
    for key in priority_keys:
        if key not in seen:
            all_keys.append(key)
            seen.add(key)
    for record in score_records:
        for key in record.keys():
            if key not in seen and not isinstance(record[key], (dict, list)):
                all_keys.append(key)
                seen.add(key)

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for record in score_records:
            # Flatten nested dicts one level for readability
            flat = {}
            for key, val in record.items():
                if isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        flat[f"{key}.{sub_key}"] = sub_val
                elif isinstance(val, list):
                    flat[key] = json.dumps(val)
                else:
                    flat[key] = val
            writer.writerow(flat)

    logger.info(f"CSV saved to {path}")


def save_dashboard_markdown(
    score_records: list[dict],
    manifest: dict,
    output_dir: Path,
):
    """Generate a human-readable markdown dashboard table."""
    path = output_dir / "dashboard.md"

    lines = [
        "# NEA AI Agents — Judge Evaluation Results",
        f"*Generated: {datetime.utcnow().isoformat()}*",
        "",
        "## Score Summary",
        "",
        "| Test Case | Agent | Composite Score | Pass/Fail | Notes |",
        "|-----------|-------|----------------|-----------|-------|",
    ]

    for record in score_records:
        test_case_id = record.get("test_case_id", "?")
        meta = manifest.get(test_case_id, {})
        agent = meta.get("agent", record.get("agent", "?"))

        if not record.get("judge_success"):
            lines.append(
                f"| {test_case_id} | {agent} | — | ERROR | {record.get('error', 'unknown')} |"
            )
            continue

        # Composite score — field name differs by agent
        composite = (
            record.get("composite_score")
            or record.get("weighted_score")
            or "—"
        )
        if isinstance(composite, (int, float)):
            composite_str = f"{composite:.1f}"
        else:
            composite_str = str(composite)

        pass_fail = record.get("pass_fail", "—")
        forced_zero = " (forced=0)" if record.get("composite_forced_to_zero") else ""
        hard_failures = record.get("hard_failures_detected", [])
        notes = ""
        if hard_failures:
            notes = f"HF: {', '.join(hard_failures[:2])}"

        lines.append(
            f"| {test_case_id} | {agent} | {composite_str}{forced_zero} "
            f"| {pass_fail} | {notes} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Per-Agent Pass Rate",
        "",
    ]

    # Group by agent
    by_agent: dict[str, list[dict]] = {}
    for record in score_records:
        agent = manifest.get(record.get("test_case_id", ""), {}).get("agent") or record.get("agent", "unknown")
        by_agent.setdefault(agent, []).append(record)

    for agent_name, agent_records in sorted(by_agent.items()):
        judged = [r for r in agent_records if r.get("judge_success")]
        passed = [r for r in judged if str(r.get("pass_fail", "")).lower() == "pass"]
        total = len(agent_records)
        pass_pct = f"{len(passed)/len(judged):.0%}" if judged else "n/a"
        lines.append(f"**{agent_name}**: {len(passed)}/{len(judged)} passed ({pass_pct}) of {total} total")
        lines.append("")

    path.write_text("\n".join(lines))
    logger.info(f"Dashboard saved to {path}")


# =============================================================================
# MAIN
# =============================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage 3 — Submit judge prompts to Anthropic Batch API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Real-time, no Batch API (fast for small runs)
  python -m evaluation.run_judge_batch --no-batch

  # Async Batch API (50% cheaper, best for large runs)
  python -m evaluation.run_judge_batch
  python -m evaluation.run_judge_batch --no-wait
  python -m evaluation.run_judge_batch --batch-id msgbatch_abc123

  # Target specific agents
  python -m evaluation.run_judge_batch --no-batch --agents outreach
        """,
    )

    parser.add_argument(
        "--agents",
        nargs="+",
        choices=["outreach", "tldr", "news_aggregator"],
        default=["outreach", "tldr", "news_aggregator"],
        help="Which agent outputs to judge (default: all)",
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Directory containing Stage 1 JSON outputs",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for batch results",
    )
    parser.add_argument(
        "--batch-id",
        default=None,
        help="Existing batch ID(s) to poll (skip submission). Comma-separated.",
    )
    parser.add_argument(
        "--no-batch",
        action="store_true",
        help="Call the Messages API sequentially instead of the Batch API (instant results, same cost)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Submit batch and exit without waiting for completion (batch mode only)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=POLL_INTERVAL_SECONDS,
        help=f"Seconds between batch status polls (default: {POLL_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--model",
        default=JUDGE_MODEL,
        help=f"Judge model (default: {JUDGE_MODEL})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic()

    # ── Step 1: Load records ────────────────────────────────────────────────
    if not args.batch_id:
        print("=" * 65)
        mode = "Real-time (no Batch API)" if args.no_batch else "Batch API"
        print(f"  NEA EVALUATION — Stage 3: Judge [{mode}]")
        print("=" * 65)

        print(f"\n[1/3] Loading Stage 1 outputs from {input_dir}...")
        records = load_test_records(input_dir, args.agents)
        if not records:
            print(f"  No successful test records found in {input_dir}. Run Stage 1 first.")
            return 1
        print(f"  Loaded {len(records)} successful test records")

        # Save manifest
        manifest = build_manifest(records)
        manifest_path = output_dir / "batch_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"  Manifest saved: {manifest_path}")

        # ── Step 2: Build prompts ───────────────────────────────────────────
        print(f"\n[2/3] Building judge prompts...")
        batch_requests, id_map = build_batch_requests(records)
        print(f"  Built {len(batch_requests)} judge prompts")

        if not batch_requests:
            print("  No valid judge prompts built. Check Stage 1 outputs.")
            return 1

        # ── Step 3a: Real-time path (--no-batch) ────────────────────────────
        if args.no_batch:
            print(f"\n[3/3] Running {len(batch_requests)} judge calls in real-time (model: {args.model})...")
            raw_results, score_records = run_realtime(batch_requests, client, output_dir, id_map=id_map)

            save_scores_json(score_records, output_dir)
            # Reload merged scores so CSV and dashboard reflect all agents, not just this run
            merged_scores = json.loads((output_dir / "scores.json").read_text())
            save_scores_csv(merged_scores, output_dir)
            save_dashboard_markdown(merged_scores, manifest, output_dir)

            total = len(merged_scores)
            judged = sum(1 for r in merged_scores if r.get("judge_success"))
            passed = sum(1 for r in merged_scores if str(r.get("pass_fail", "")).lower() == "pass")

            print("=" * 65)
            print(f"  COMPLETE")
            print(f"  Total responses: {total}")
            print(f"  Successfully judged: {judged}/{total}")
            print(f"  Passed: {passed}/{judged}")
            print(f"  Results in: {output_dir.resolve()}")
            print("=" * 65)
            return 0

        # ── Step 3b: Batch API path ──────────────────────────────────────────
        print(f"\n[3/3] Submitting to Anthropic Batch API (model: {args.model})...")
        batch_id_str = submit_batch(batch_requests, client)
        print(f"  Batch ID(s): {batch_id_str}")

        # Save batch IDs for later retrieval
        (output_dir / "batch_ids.txt").write_text(batch_id_str)

        if args.no_wait:
            print(f"\n  --no-wait: exiting. Poll later with:")
            print(f"  python -m evaluation.run_judge_batch --batch-id {batch_id_str}")
            return 0

        batch_ids = [bid.strip() for bid in batch_id_str.split(",")]

    else:
        # Resume: load manifest if it exists, else use empty
        print("=" * 65)
        print("  NEA EVALUATION — Stage 3: Fetch Batch Results")
        print("=" * 65)

        batch_ids = [bid.strip() for bid in args.batch_id.split(",")]
        manifest_path = output_dir / "batch_manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        # Rebuild id_map from manifest keys (original IDs → safe IDs)
        id_map = {k.replace(".", "-"): k for k in manifest.keys()}
        records = []
        print(f"\n  Polling batch IDs: {batch_ids}")

    # ── Poll ────────────────────────────────────────────────────────────────
    print(f"\nPolling for completion (every {args.poll_interval}s)...")
    finished_batches = poll_until_done(batch_ids, client, interval=args.poll_interval)
    print(f"  All batches finished: {list(finished_batches.keys())}")

    # ── Parse results ────────────────────────────────────────────────────────
    print("\nFetching and parsing results...")
    manifest = build_manifest(records) if records else json.loads(
        (output_dir / "batch_manifest.json").read_text()
        if (output_dir / "batch_manifest.json").exists()
        else "{}"
    )
    raw_results, score_records = fetch_and_parse_results(batch_ids, client, output_dir, id_map=id_map)

    save_scores_json(score_records, output_dir)
    # Reload merged scores so CSV and dashboard reflect all agents, not just this run
    merged_scores = json.loads((output_dir / "scores.json").read_text())
    save_scores_csv(merged_scores, output_dir)
    save_dashboard_markdown(merged_scores, manifest, output_dir)

    # ── Summary ─────────────────────────────────────────────────────────────
    total = len(merged_scores)
    judged = sum(1 for r in merged_scores if r.get("judge_success"))
    passed = sum(1 for r in merged_scores if str(r.get("pass_fail", "")).lower() == "pass")

    print("=" * 65)
    print(f"  COMPLETE")
    print(f"  Total responses: {total}")
    print(f"  Successfully judged: {judged}/{total}")
    print(f"  Passed: {passed}/{judged}")
    print(f"  Results in: {output_dir.resolve()}")
    print("=" * 65)

    return 0


if __name__ == "__main__":
    sys.exit(main())
