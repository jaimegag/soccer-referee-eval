"""Build RESULTS.md and the charts in docs/charts/ from the eval result files.

Usage:
    python report.py

Edit the RUNS block below when you add new result files. Every number in RESULTS.md
is computed from those files, so re-running this script is the only way to update it.
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

# --- Which result files feed the report -------------------------------------------------
RUNS = {
    # Main comparison: both models at their default effort, all 26 cases, 3 runs each.
    "main": "results/20261115-191815.jsonl",
    # Opus 5.5 at high effort (21 cases: run before n06-n10 existed).
    "opus_high": "results/20261114-005008.jsonl",
    # Earlier default-effort run of the same 21 cases; used for run-to-run variation on n05.
    "earlier": "results/20261114-004231.jsonl",
}
CASES_FILE = "cases.jsonl"
OUT_MD = Path("RESULTS.md")
CHART_DIR = Path("docs/charts")
VARIANCE_CASE = "n05"

FIELDS = ("decision", "awarded_to", "sanction")
TIER_ORDER = ["easy", "medium", "tricky", "new_2026_27"]
TIER_LABEL = {"easy": "Easy", "medium": "Medium", "tricky": "Tricky", "new_2026_27": "New in 2026/27"}
CONFIG_LABEL = {
    # Omitting effort uses the model's default: medium on Opus 5.5, high on Fable 5.2.
    "claude-opus-5-5@default": "Opus 5.5 (default: medium)",
    "claude-opus-5-5@high": "Opus 5.5 (high)",
    "claude-fable-5-2@default": "Fable 5.2 (default: high)",
}
CONFIG_ORDER = list(CONFIG_LABEL)

# --- Theme: validated categorical slots 1-3 + chart chrome, light and dark --------------
THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e1e0d9",
        "series": {"claude-opus-5-5@default": "#2a78d6", "claude-fable-5-2@default": "#eb6834",
                   "claude-opus-5-5@high": "#1baf7a"},
        "seq": ["#cde2fb", "#86b6ef", "#3987e5", "#184f95"],  # 0/3 .. 3/3
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "grid": "#2c2c2a",
        "series": {"claude-opus-5-5@default": "#3987e5", "claude-fable-5-2@default": "#d95926",
                   "claude-opus-5-5@high": "#199e70"},
        "seq": ["#0d366b", "#1c5cab", "#3987e5", "#86b6ef"],
    },
}


# --- Data -------------------------------------------------------------------------------
def load(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def by_config(rows: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for r in rows:
        out[r["config"]].append(r)
    return dict(sorted(out.items(), key=lambda kv: CONFIG_ORDER.index(kv[0])))


def stats(rows: list[dict]) -> dict:
    lat = sorted(r["latency_s"] for r in rows)
    return {
        "calls": len(rows),
        "correct": sum(r.get("correct", False) for r in rows),
        "p50": statistics.median(lat),
        "p90": lat[min(len(lat) - 1, int(0.9 * len(lat)))],
        "out_tok": statistics.mean(r.get("output_tokens", 0) for r in rows),
        "cost": sum(r.get("cost_usd", 0) for r in rows),
        "errors": sum("error" in r for r in rows),
    }


def per_case(rows: list[dict]) -> dict[str, tuple[int, int]]:
    out = defaultdict(lambda: [0, 0])
    for r in rows:
        out[r["case_id"]][0] += bool(r.get("correct"))
        out[r["case_id"]][1] += 1
    return {k: tuple(v) for k, v in out.items()}


# --- Charts -----------------------------------------------------------------------------
def style(ax, t, grid_axis="y"):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], length=0, labelsize=9)
    if grid_axis:
        ax.grid(axis=grid_axis, color=t["grid"], linewidth=0.8)
        ax.set_axisbelow(True)


def save(fig, name: str, mode: str):
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHART_DIR / f"{name}-{mode}.svg", facecolor=fig.get_facecolor(), metadata={"Date": None},
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def title(fig, t, text, sub):
    fig.text(0.01, 0.99, text, color=t["ink"], fontsize=12, fontweight="bold", va="top")
    fig.text(0.01, 0.935, sub, color=t["ink2"], fontsize=9, va="top")


def chart_tiers(main: dict, cases: dict, t: dict, mode: str):
    tiers = [x for x in TIER_ORDER if any(c["tier"] == x for c in cases.values())]
    configs = list(main)
    fig, ax = plt.subplots(figsize=(7.2, 3.6), facecolor=t["surface"])
    fig.subplots_adjust(top=0.78)
    style(ax, t)
    width = 0.36
    for i, cfg in enumerate(configs):
        for j, tier in enumerate(tiers):
            rows = [r for r in main[cfg] if r["tier"] == tier]
            ok, n = sum(r.get("correct", False) for r in rows), len(rows)
            x = j + (i - (len(configs) - 1) / 2) * (width + 0.02)
            ax.bar(x, 100 * ok / n, width, color=t["series"][cfg], edgecolor=t["surface"], linewidth=1,
                   label=CONFIG_LABEL[cfg] if j == 0 else None)
            ax.text(x, 100 * ok / n + 2, f"{ok}/{n}", ha="center", va="bottom", fontsize=8, color=t["ink2"])
    ax.set_xticks(range(len(tiers)), [TIER_LABEL[x] for x in tiers], color=t["ink"])
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.legend(frameon=False, labelcolor=t["ink"], fontsize=9, loc="upper left", bbox_to_anchor=(0, 1.13), ncol=2)
    title(fig, t, "Accuracy by difficulty tier", "Correct answers out of all runs (3 runs per case), default effort")
    save(fig, "accuracy-by-tier", mode)


def chart_cost(points: list[dict], t: dict, mode: str, n_cases: int):
    # One horizontal bar per configuration and run: cost is the bar, accuracy is in the label.
    # (The points share nearly the same accuracy, so a scatter plot stacks their labels.)
    fig, ax = plt.subplots(figsize=(7.2, 0.5 * len(points) + 1.3), facecolor=t["surface"])
    fig.subplots_adjust(top=1 - 0.7 / (0.5 * len(points) + 1.3))
    style(ax, t, grid_axis="x")
    ax.spines["bottom"].set_visible(False)
    for i, p in enumerate(points):
        cents = p["cost_per_call"] * 100
        ax.barh(i, cents, 0.6, color=t["series"][p["config"]], edgecolor=t["surface"], linewidth=1)
        ax.text(cents + 0.02, i, f"{cents:.2f}¢   {p['ok']}/{p['n']} correct", va="center",
                fontsize=8.5, color=t["ink"])
    ax.set_yticks(range(len(points)), [f"{CONFIG_LABEL[p['config']]}\nrun {p['run_date']}" for p in points],
                  color=t["ink"], fontsize=9)
    ax.set_ylim(len(points) - 0.5, -0.5)
    ax.set_xlim(0, max(p["cost_per_call"] for p in points) * 100 * 1.45)
    ax.set_xlabel("Average cost per call (US cents)", color=t["ink2"], fontsize=9)
    title(fig, t, "Cost per call and accuracy",
          f"Same {n_cases} cases in every run, 3 runs each; shorter bar = cheaper")
    save(fig, "cost-vs-accuracy", mode)


def chart_grid(grid_cols: list[tuple[str, dict]], case_ids: list[str], cases: dict, t: dict, mode: str):
    fig, ax = plt.subplots(figsize=(7.2, 0.42 * len(case_ids) + 1.3), facecolor=t["surface"])
    fig.subplots_adjust(top=1 - 0.95 / (0.42 * len(case_ids) + 1.3))
    ax.set_facecolor(t["surface"])
    for spine in ax.spines.values():
        spine.set_visible(False)
    for ci, (cfg, pc) in enumerate(grid_cols):
        for ri, cid in enumerate(case_ids):
            if cid in pc:
                ok, n = pc[cid]
                fill = t["seq"][round(3 * ok / n)]
                rgb = matplotlib.colors.to_rgb(fill)
                light_fill = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] > 0.45
                txt, txt_color = f"{ok}/{n}", "#0b0b0b" if light_fill else "#fcfcfb"
            else:
                fill, txt, txt_color = t["surface"], "not run", t["ink2"]
            ax.add_patch(plt.Rectangle((ci + 0.03, ri + 0.06), 0.94, 0.88, color=fill, linewidth=0))
            ax.text(ci + 0.5, ri + 0.5, txt, ha="center", va="center", fontsize=9, color=txt_color)
    ax.set_xlim(0, len(grid_cols))
    ax.set_ylim(len(case_ids), 0)
    ax.set_xticks([i + 0.5 for i in range(len(grid_cols))],
                  [CONFIG_LABEL[c].replace(" (", "\n(") for c, _ in grid_cols], color=t["ink"], fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(case_ids))],
                  [f"{cid}  {cases[cid]['title']}" for cid in case_ids], color=t["ink"], fontsize=9)
    ax.tick_params(length=0)
    shade = "darker" if mode == "light" else "brighter"
    title(fig, t, "Rules new in 2026/27, case by case", f"Correct runs out of 3; {shade} cells = more correct")
    save(fig, "new-rules-grid", mode)


def chart_variance(points: list[dict], t: dict, mode: str):
    configs = [c for c in CONFIG_ORDER if any(p["config"] == c for p in points)]
    fig, ax = plt.subplots(figsize=(7.2, 0.6 * len(configs) + 1.6), facecolor=t["surface"])
    fig.subplots_adjust(top=0.72, left=0.25)
    style(ax, t, grid_axis="x")
    ax.spines["bottom"].set_visible(False)
    for p in points:
        y = configs.index(p["config"]) + (0.12 if p["run"] == "later" else -0.12)
        color = t["series"][p["config"]]
        ax.scatter(p["tokens"], y, s=70, zorder=3, linewidth=2,
                   facecolor=color if p["correct"] else t["surface"], edgecolor=color)
    ax.set_yticks(range(len(configs)), [CONFIG_LABEL[c] for c in configs], color=t["ink"], fontsize=9)
    ax.set_ylim(len(configs) - 0.5, -0.5)
    ax.set_xlim(0, max(p["tokens"] for p in points) * 1.08)
    ax.set_xlabel("Output tokens (mostly thinking)", color=t["ink2"], fontsize=9)
    handles = [Line2D([], [], marker="o", linestyle="", markersize=8, markerfacecolor=t["ink2"],
                      markeredgecolor=t["ink2"], label="correct"),
               Line2D([], [], marker="o", linestyle="", markersize=8, markerfacecolor=t["surface"],
                      markeredgecolor=t["ink2"], markeredgewidth=2, label="wrong (gave the pre-2026/27 yellow card)")]
    ax.legend(handles=handles, frameon=False, labelcolor=t["ink"], fontsize=9, loc="upper left",
              bbox_to_anchor=(0, 1.32), ncol=2)
    title(fig, t, f"Same prompt, different answers: case {VARIANCE_CASE}",
          "Each dot is one run of identical scenario text; upper dots = earlier run file, lower dots = main run")
    save(fig, f"{VARIANCE_CASE}-variance", mode)


def picture(name: str, alt: str) -> str:
    return (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="{CHART_DIR}/{name}-dark.svg">\n'
            f'  <img alt="{alt}" src="{CHART_DIR}/{name}-light.svg">\n</picture>')


# --- Report -----------------------------------------------------------------------------
def main() -> None:
    matplotlib.rcParams.update({"svg.fonttype": "path", "svg.hashsalt": "soccer-eval", "font.size": 9})
    cases = {c["id"]: c for c in map(json.loads, Path(CASES_FILE).read_text().splitlines())}
    runs = {k: load(v) for k, v in RUNS.items()}
    main_cfg = by_config(runs["main"])
    high_cfg = by_config(runs["opus_high"])

    # Cost vs accuracy compares configurations on the cases every run has in common.
    common = sorted({r["case_id"] for r in runs["main"]} & {r["case_id"] for r in runs["opus_high"]},
                    key=list(cases).index)
    cost_points = []
    for key in ("earlier", "main", "opus_high"):
        stamp = Path(RUNS[key]).stem  # e.g. 20261114-004231
        for cfg, rows in by_config(runs[key]).items():
            sub = [r for r in rows if r["case_id"] in common]
            ok = sum(r.get("correct", False) for r in sub)
            cost_points.append({"config": cfg, "key": key, "ok": ok, "n": len(sub),
                                "run_date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}",
                                "cost_per_call": sum(r["cost_usd"] for r in sub) / len(sub)})
    cost_points.sort(key=lambda p: (CONFIG_ORDER.index(p["config"]), p["run_date"]))

    new_ids = [cid for cid, c in cases.items() if c["tier"] == "new_2026_27"]
    grid_cols = [(cfg, per_case(rows)) for cfg, rows in main_cfg.items()]
    grid_cols += [(cfg, per_case(rows)) for cfg, rows in high_cfg.items()]
    grid_cols.sort(key=lambda c: CONFIG_ORDER.index(c[0]))

    variance = [{"config": r["config"], "tokens": r["output_tokens"], "correct": r["correct"], "run": run}
                for run, key in (("earlier", "earlier"), ("later", "main"), ("earlier", "opus_high"))
                for r in runs[key] if r["case_id"] == VARIANCE_CASE and "output_tokens" in r]

    for mode, t in THEMES.items():
        chart_tiers(main_cfg, cases, t, mode)
        chart_cost(cost_points, t, mode, len(common))
        chart_grid(grid_cols, new_ids, cases, t, mode)
        chart_variance(variance, t, mode)

    # Markdown
    md = ["# Results: Opus 5.5 vs Fable 5.2 as a soccer referee", "",
          "_Generated by `report.py` from the files in `results/`. Do not edit by hand._", "",
          f"Each model answered {len({r['case_id'] for r in runs['main']})} referee situations "
          "(IFAB Laws of the Game 2026/27) three times, returning a decision, the team that gets the restart, "
          "and any card. A case counts as correct only if all three match the answer key.", "",
          "## Summary", "",
          "| Configuration | Correct | Accuracy | Median latency | p90 latency | Avg output tokens | Cost per call | Total cost |",
          "|---|---|---|---|---|---|---|---|"]
    for cfg, rows in main_cfg.items():
        s = stats(rows)
        md.append(f"| {CONFIG_LABEL[cfg]} | {s['correct']}/{s['calls']} | {s['correct'] / s['calls']:.0%} | "
                  f"{s['p50']:.1f} s | {s['p90']:.1f} s | {s['out_tok']:.0f} | "
                  f"${s['cost'] / s['calls']:.4f} | ${s['cost']:.2f} |")
    md += ["", f"Source: `{RUNS['main']}`. Prices: Opus 5.5 $4 / $20 and Fable 5.2 $8 / $40 per million "
           "input / output tokens; output tokens include thinking.", "",
           "## Accuracy by tier", "", picture("accuracy-by-tier", "Accuracy by difficulty tier"), "",
           "## Rules new in 2026/27", "", picture("new-rules-grid", "Per-case results for 2026/27 rules"), "",
           "| Case | Situation | Expected | " + " | ".join(CONFIG_LABEL[c] for c, _ in grid_cols) + " |",
           "|---|---|---|" + "---|" * len(grid_cols)]
    for cid in new_ids:
        e = cases[cid]["expected"]
        cells = [f"{pc[cid][0]}/{pc[cid][1]}" if cid in pc else "not run" for _, pc in grid_cols]
        md.append(f"| {cid} | {cases[cid]['title']} | {e['decision']} / {e['awarded_to']} / {e['sanction']} | "
                  + " | ".join(cells) + " |")
    md += ["", "## Cost and accuracy", "", picture("cost-vs-accuracy", "Cost per call and accuracy for each run"), "",
           "| Configuration | Correct | Cost per call | Source |", "|---|---|---|---|"]
    for p in cost_points:
        md.append(f"| {CONFIG_LABEL[p['config']]} | {p['ok']}/{p['n']} | ${p['cost_per_call']:.4f} | "
                  f"`{RUNS[p['key']]}` |")
    md += ["", f"Only the {len(common)} cases present in every run are compared here. The two default-effort runs "
           "used identical prompts, so the gap between them is run-to-run variation.", "",
           f"## Run-to-run variation on {VARIANCE_CASE}", "",
           picture(f"{VARIANCE_CASE}-variance", f"Output tokens and correctness for every run of {VARIANCE_CASE}"), "",
           f"_{cases[VARIANCE_CASE]['scenario']}_", "",
           "| Configuration | Run file | Correct | Output tokens per run |", "|---|---|---|---|"]
    for key in ("earlier", "main", "opus_high"):
        for cfg, rows in by_config(runs[key]).items():
            rr = [r for r in rows if r["case_id"] == VARIANCE_CASE]
            md.append(f"| {CONFIG_LABEL[cfg]} | `{RUNS[key]}` | {sum(r['correct'] for r in rr)}/{len(rr)} | "
                      + ", ".join(str(r["output_tokens"]) for r in rr) + " |")
    md += ["", "## Every miss (main run)", ""]
    for cfg, rows in main_cfg.items():
        misses = [r for r in rows if not r.get("correct")]
        md += [f"<details><summary>{CONFIG_LABEL[cfg]}: {len(misses)} misses</summary>", "",
               "| Case | Got | Expected | Model's explanation |", "|---|---|---|---|"]
        for r in misses:
            if "error" in r:
                md.append(f"| {r['case_id']} | error | | {r['error']} |")
                continue
            wrong = [f for f in FIELDS if not r["checks"][f]]
            got = ", ".join(f"{f}={r['answer'][f]}" for f in wrong)
            exp = ", ".join(f"{f}={r['expected'][f]}" for f in wrong)
            md.append(f"| {r['case_id']} | {got} | {exp} | {r['answer']['explanation'].replace('|', '/')} |")
        md += ["", "</details>", ""]

    OUT_MD.write_text("\n".join(md))
    print(f"Wrote {OUT_MD} and {len(list(CHART_DIR.glob('*.svg')))} charts in {CHART_DIR}/")


if __name__ == "__main__":
    main()
