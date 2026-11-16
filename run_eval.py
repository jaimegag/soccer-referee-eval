"""Soccer referee-decision eval: compare Claude models on quality, cost and speed.

Usage:
    python run_eval.py                      # both models at their API-default effort
    python run_eval.py --runs 3 --limit 5   # quick smoke test, repeated runs
    python run_eval.py --models claude-opus-5-5:high claude-fable-5-2:low
    python run_eval.py --models claude-opus-5-5 claude-opus-5-5:high   # same model, two efforts

Each --models entry is MODEL or MODEL:EFFORT. Without an effort the request omits it,
so the API uses that model's default (medium on Opus 5.5, high on Fable 5.2).
"""

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import anthropic

# USD per million tokens (input, output). Check https://claude.com/pricing before trusting totals.
PRICING = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-fable-5-2": (8.00, 40.00),
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
FIELDS = ("decision", "awarded_to", "sanction")

SYSTEM_PROMPT = """You are an expert football (soccer) referee applying the current IFAB Laws of the Game (2026/27).
For each match situation, give the correct decision: the restart (or goal/play on), which team gets it, \
and any disciplinary sanction for the offending player. Keep the explanation to 1-3 sentences citing the relevant Law."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": [
                "play_on", "goal", "direct_free_kick", "indirect_free_kick", "penalty_kick",
                "corner_kick", "goal_kick", "throw_in", "dropped_ball", "retake",
            ],
        },
        "awarded_to": {"type": "string", "enum": ["red", "blue", "none"]},
        "sanction": {"type": "string", "enum": ["none", "yellow", "red"]},
        "explanation": {"type": "string"},
    },
    "required": ["decision", "awarded_to", "sanction", "explanation"],
    "additionalProperties": False,
}


def parse_config(spec: str) -> dict:
    """'claude-opus-5-5' or 'claude-opus-5-5:high' -> {label, model, effort}."""
    model, _, effort = spec.partition(":")
    if model not in PRICING:
        raise SystemExit(f"Unknown model {model!r}; add its pricing to PRICING. Known: {', '.join(PRICING)}")
    if effort and effort not in EFFORTS:
        raise SystemExit(f"Unknown effort {effort!r}; choose from {', '.join(EFFORTS)}")
    return {"label": f"{model}@{effort or 'default'}", "model": model, "effort": effort or None}


def run_case(client: anthropic.Anthropic, config: dict, case: dict) -> dict:
    model, effort = config["model"], config["effort"]
    row = {"config": config["label"], "model": model, "effort": effort or "default",
           "case_id": case["id"], "tier": case["tier"]}
    output_config = {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    if effort:  # omitted -> the model's own default effort
        output_config["effort"] = effort
    start = time.perf_counter()
    try:
        # No refusal fallback on purpose: a fallback would silently answer with a different model.
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": case["scenario"]}],
            output_config=output_config,
        )
    except anthropic.APIError as e:
        row.update(error=f"{type(e).__name__}: {e}", latency_s=time.perf_counter() - start)
        return row
    row["latency_s"] = time.perf_counter() - start

    in_price, out_price = PRICING[model]
    usage = resp.usage
    row.update(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,  # includes thinking tokens
        cost_usd=(usage.input_tokens * in_price + usage.output_tokens * out_price) / 1_000_000,
        stop_reason=resp.stop_reason,
    )
    if resp.stop_reason != "end_turn":
        row["error"] = f"stop_reason={resp.stop_reason}"
        return row

    answer = json.loads(next(b.text for b in resp.content if b.type == "text"))
    checks = {f: answer[f] == case["expected"][f] for f in FIELDS}
    row.update(answer=answer, expected=case["expected"], checks=checks, correct=all(checks.values()))
    return row


def summarize(rows: list[dict]) -> None:
    labels = list(dict.fromkeys(r["config"] for r in rows))
    w = max(len(label) for label in labels) + 1
    print(f"\n{'config':<{w}} {'correct':>9} {'fields':>7} {'p50 s':>6} {'p90 s':>6} {'out tok':>8} {'cost $':>8} {'errors':>6}")
    for label in labels:
        mrows = [r for r in rows if r["config"] == label]
        ok = [r for r in mrows if "checks" in r]
        lat = sorted(r["latency_s"] for r in mrows)
        field_hits = sum(sum(r["checks"].values()) for r in ok)
        p90 = lat[min(len(lat) - 1, int(0.9 * len(lat)))]
        print(
            f"{label:<{w}} {sum(r['correct'] for r in ok):>4}/{len(mrows):<4} "
            f"{field_hits / max(1, len(ok) * len(FIELDS)):>6.0%} "
            f"{statistics.median(lat):>6.1f} {p90:>6.1f} "
            f"{statistics.mean(r.get('output_tokens', 0) for r in mrows):>8.0f} "
            f"{sum(r.get('cost_usd', 0) for r in mrows):>8.4f} "
            f"{sum('error' in r for r in mrows):>6}"
        )

    print("\nPer-tier accuracy:")
    for tier in dict.fromkeys(r["tier"] for r in rows):
        parts = []
        for label in labels:
            t = [r for r in rows if r["config"] == label and r["tier"] == tier]
            parts.append(f"{label} {sum(r.get('correct', False) for r in t)}/{len(t)}")
        print(f"  {tier:<11} " + "   ".join(parts))

    misses = [r for r in rows if not r.get("correct")]
    if misses:
        print("\nMisses:")
        for r in misses:
            if "error" in r:
                print(f"  {r['config']:<{w}} {r['case_id']}  ERROR {r['error']}")
            else:
                wrong = {f: r["answer"][f] for f in FIELDS if not r["checks"][f]}
                want = {f: r["expected"][f] for f in wrong}
                print(f"  {r['config']:<{w}} {r['case_id']}  got {wrong}  expected {want}")
                print(f"  {'':<{w}}       why: {r['answer']['explanation']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default="cases.jsonl")
    parser.add_argument("--runs", type=int, default=1, help="repeats per case per model")
    parser.add_argument("--limit", type=int, help="only the first N cases")
    parser.add_argument("--models", nargs="+", default=list(PRICING), metavar="MODEL[:EFFORT]",
                        help="configs to compare (default: each model at its API-default effort)")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    configs = [parse_config(spec) for spec in args.models]
    cases = [json.loads(line) for line in Path(args.cases).read_text().splitlines() if line.strip()]
    cases = cases[: args.limit] if args.limit else cases
    jobs = [(cfg, c) for cfg in configs for c in cases for _ in range(args.runs)]
    print(f"Running {len(jobs)} calls ({len(cases)} cases x {len(configs)} configs x {args.runs} runs): "
          + ", ".join(cfg["label"] for cfg in configs))

    client = anthropic.Anthropic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda job: run_case(client, job[0], job[1]), jobs))

    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    out_path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    summarize(rows)
    print(f"\nRaw results: {out_path}")


if __name__ == "__main__":
    main()
