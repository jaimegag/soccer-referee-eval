# Soccer referee eval: Opus 5.5 vs Fable 5.2

A small Python harness that asks two Claude models to rule on soccer situations under the
IFAB Laws of the Game 2026/27, scores their answers automatically, and compares quality, cost
and speed.

**Results and charts: [RESULTS.md](RESULTS.md)**

## How it works

- `cases.jsonl`: 26 referee situations, each with an answer key (decision, team awarded the
  restart, card). Tiers: easy, medium, tricky, and rules new in 2026/27.
- `run_eval.py`: sends every case to each model with structured JSON output, scores the three
  fields, and writes one row per call to `results/<timestamp>.jsonl` (answer, explanation,
  tokens, cost, latency).
- `report.py`: turns selected result files into `RESULTS.md` and the SVG charts in
  `docs/charts/` (light and dark versions).

## How `run_eval.py` uses the Claude API

Each case is one call to the Messages API, made with the official Python SDK (`anthropic`):

```python
client = anthropic.Anthropic()             # reads ANTHROPIC_API_KEY from the environment
resp = client.messages.create(
    model="claude-opus-5-5",               # or "claude-fable-5-2"
    max_tokens=16000,
    system=SYSTEM_PROMPT,                  # "You are an expert referee applying the 2026/27 Laws..."
    messages=[{"role": "user", "content": case["scenario"]}],
    output_config={
        "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        "effort": "high",                  # only sent when an effort is chosen
    },
)
```

What matters about these calls:

- **Structured output makes scoring exact.** `output_config.format` constrains the reply to a
  JSON schema: `decision`, `awarded_to` and `sanction` must be values from fixed lists (for
  example `penalty_kick`, `red`, `yellow`), plus a free-text `explanation`. The script
  compares the three fields to the answer key with `==`, with no text parsing and no model
  acting as judge.
- **Effort controls how much the model thinks.** With `--models claude-opus-5-5:high` the
  request sends `effort: "high"`. Without an effort it sends nothing, so the model uses its own
  default (see the table below). Both models always think before answering. Thinking text isn't
  returned, but it is billed as output tokens.
- **Every call is one fresh conversation.** Each request contains only the system prompt and
  one scenario, with no earlier cases, examples or rule text, so each answer comes from the
  model's own knowledge of the Laws.
- **Cost comes from the response.** `resp.usage.input_tokens` and `output_tokens` are multiplied
  by the prices in `PRICING` at the top of the script. Update those if prices change.
- **Latency is wall-clock time** around the call, so it includes network time and the
  model's thinking.
- **Incomplete answers count as errors.** If `stop_reason` isn't `end_turn` (for example
  `max_tokens` or `refusal`), the row is recorded as an error and scored as wrong.
- **No fallback model.** The script doesn't retry a refused request on another model. A
  fallback would let a different model answer and mix its results into this one's.
- **Calls run in parallel.** 4 threads by default (`--workers`). The SDK retries rate-limit
  and server errors on its own (2 retries by default). With `--runs 3` every case is sent
  three times, because the same prompt can get different answers.

Each call becomes one line in `results/<timestamp>.jsonl`. A line holds the configuration,
case, answer, explanation, per-field checks, tokens, cost and latency, so `report.py` can rebuild
everything without calling the API again.

## Models and effort

| Model | Model ID | Price per million tokens (input / output) | Default effort |
|---|---|---|---|
| Opus 5.5 | `claude-opus-5-5` | $4 / $20 | medium |
| Fable 5.2 | `claude-fable-5-2` | $8 / $40 | high |

"Default" means the request leaves `effort` out, so each model uses its own default. That means
the main comparison is Opus at **medium** against Fable at **high**, not equal settings. Opus was
also run once at high effort. Thinking is always on for both models, and its tokens are billed
as output.

## Running it

Requires Python 3.10+ and an Anthropic API key.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Each model at its default effort, 3 runs per case
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python run_eval.py --runs 3

# Choose models and effort per model
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python run_eval.py --models claude-opus-5-5:high claude-fable-5-2

# Rebuild the report (edit RUNS at the top of report.py to pick result files)
.venv/bin/python report.py
```

## What surprised me

**The models know the Laws, just not this season's.** Both scored 100% on long-established rules
(easy, medium and tricky tiers), but only 16/30 (Opus) and 21/30 (Fable) on rules new in
2026/27. The misses weren't random: they confidently applied the old rule, even though the
prompt named the 2026/27 edition. For example, both said "advantage is not applied to an
incorrectly taken throw-in" (n06), and both cautioned the defender for a failed handball on the
goal line (n07), which no longer earns a card. On n10, Opus also invented a rule and gave a red card
where the answer is a yellow, in 2 of 3 runs.

**More effort made Opus worse, not better.** Run on the same day with the same 21 cases, Opus
at high effort scored 60/63 against 62/63 at its default (medium). It failed n05 in all three
attempts, where medium got it right twice, and it cost about 11% more per call. Extra thinking
seems to have argued it into the pre-2026/27 answer more reliably. (n05 is noisy, though: a
later medium run also went 0/3.)

**The same prompt can flip from always right to always wrong.** Fable answered n05 correctly
3/3 in one run and 0/3 in the next, with identical text. The right answers came after about
1,000 thinking tokens and the wrong ones after about 125, so whether the model "stops to think"
decided the result more than anything in the prompt. One run per case would have hidden this
completely.

**Fable's extra cost only pays off on the newest material.** Fable costs about 1.75 times as
much per call (1.30¢ against 0.74¢). On the 21 cases every setup ran, the latest runs of all
three setups tied at 60/63. Fable's lead shows only on n08 to n10, the newest cases, where it
went 9/9 against Opus's 3/9.
