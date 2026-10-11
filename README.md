# SWE-bench-collusion

An experiment harness built on [SWE-bench Pro](https://github.com/scaleapi/SWE-bench_Pro-os) (V2, 642 tasks), set up so
that every model call goes through [OpenRouter](https://openrouter.ai) and every experiment is a config file whose
results, per-task cost and prompt-cache statistics are saved under its own name. The planned experiment is described in
[`docs/experiment_design.md`](docs/experiment_design.md).

Forked from `scaleapi/SWE-bench_Pro-os` at commit
[`66f9276`](https://github.com/scaleapi/SWE-bench_Pro-os/commit/66f92766bba642462d4bbe5479e83f91f9211862)
(release v2.0.0, 2026-09-22). The original README is kept as [`README.upstream.md`](README.upstream.md); the
benchmark data, task directories, verifiers and v1 pipeline are unchanged.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/), a [Modal](https://modal.com) account (task images are linux/amd64, so
sandboxes run on Modal rather than local Docker), and an OpenRouter API key.

```bash
uv tool install 'harbor[modal]>=0.22'
uv tool install 'modal>=1.5.1'
modal setup

echo 'OPENROUTER_API_KEY=sk-or-...' > .env                                # gitignored
python3 v2/tooling/make_subset.py v2/tasks v2/hard51_ids.txt datasets/hard51  # HARD-51 subset (gitignored)

./run_experiment.sh configs/oracle_smoke.yaml                    # pipeline check, no API cost: expect 5/5
./run_experiment.sh configs/mini_deepseek-v4.1-flash_smoke.yaml  # 3 tasks with the default model
```

## Changes from the original repository

### 1. All model traffic goes through OpenRouter

Upstream's locked-protocol agents call Anthropic directly (Claude Code), a placeholder OpenAI-compatible endpoint
(Codex) or any LiteLLM provider (mini-swe-agent). Here all three read `OPENROUTER_API_KEY` and take OpenRouter model
slugs; the agent sandbox may reach only `openrouter.ai`.

| File | Change |
|---|---|
| `v2/tooling/locked_claude_code.py` | Uses OpenRouter's Anthropic-compatible endpoint (`ANTHROPIC_BASE_URL=https://openrouter.ai/api`, key sent as `ANTHROPIC_AUTH_TOKEN`). `-m` takes a slug such as `anthropic/claude-sonnet-5.5`. |
| `v2/tooling/locked_codex.py`, `v2/tooling/configs/codex_config.toml` | Codex points at OpenRouter's Responses API (beta). The key comes from `OPENROUTER_API_KEY`, and the full slug (`openai/gpt-6-sol`) is passed to `codex exec --model` instead of only its last segment. |
| `v2/tooling/locked_mini_swe.py` | mini-swe-agent uses `openrouter/<slug>` model names (LiteLLM's OpenRouter provider). |
| `v2/tooling/host_mini_swe.py` | Usage example updated to an OpenRouter model name. |

### 2. Config-driven experiments with results saved per config

| File | Purpose |
|---|---|
| `configs/*.yaml` | One Harbor job config per experiment (agent, model, task set, concurrency). See [`configs/README.md`](configs/README.md). |
| `run_experiment.sh` | `./run_experiment.sh configs/<name>.yaml` runs the agent phase, re-grades every captured patch on a pristine image (`patch_replay:PatchReplayAgent`), and writes everything to `results/<name>/`. Re-running a config resumes an unfinished run; a changed config is refused rather than mixed into old results. |
| `helper_code/summarize_results.py` | Writes `summary.json`, `per_task.csv` and `calls.csv`, and prints the per-task table and totals. |

Included configs: `oracle_smoke`, `mini_deepseek-v4.1-flash_{smoke,hard51,full}` (default model),
`mini_glm-5.3_{smoke,hard51,full}`, `claude_sonnet-5.5_hard51`, `codex_gpt-6-sol_hard51`.

Layout of `results/<name>/` (gitignored):

| File | Contents |
|---|---|
| `summary.json` | resolved counts (agent phase and re-graded), total cost, cache totals |
| `per_task.csv` | per task: rewards, cost and its source, token counts, cache hit/miss tokens and hit rate |
| `calls.csv` | one row per LLM call: provider, prompt / cache-hit / cache-miss / cache-write / output tokens, cost |
| `cost_log.json` | OpenRouter key usage before and after each run |
| `pricing.json` | the model's OpenRouter list prices when the experiment started |
| `config.yaml` | snapshot of the config |
| `agent/`, `regrade/` | Harbor job directories; `regrade/` is the score to report |

### 3. Cost accounting

- **Per task:** the sum of OpenRouter's billed `usage.cost` over the task's calls (mini-swe-agent keeps raw responses
  in its trajectory). Where no per-call cost exists (Claude Code, Codex), tokens times the model's OpenRouter list
  price, labelled as an estimate.
- **Per experiment:** `helper_code/openrouter_ledger.py` snapshots the key's total usage before and after each run, so
  the total billed is exact. It includes any other use of the same key during the run. Interrupted runs still close
  their entry, and the ledger waits for OpenRouter's usage counter to settle.
- `run_experiment.sh` prints the key's remaining budget before each run and refuses to start when the limit is reached.
- `v2/tooling/openrouter_pricing.py`: shared helpers for OpenRouter prices and key usage (standard library only).

### 4. Prompt-cache logging

Per call (`calls.csv`), per task and per experiment: cache-hit tokens, cache-miss tokens, cache-write tokens, hit rate,
calls with a cache hit, and a per-provider breakdown. Claude Code and Codex runs use the per-step token counts in
Harbor's trajectory instead.

### 5. Provider routing and a working cost cap for mini-swe-agent

| Change | Why |
|---|---|
| `v2/tooling/configs/mini_toolcall.yaml`: `provider: {sort: price}` | OpenRouter tries the cheapest provider first. Prices for the same open model vary by up to ~70x across providers. |
| Per-experiment `openrouter_provider` kwarg (in `locked_mini_swe.py`) | Overrides the routing per config. The DeepSeek configs use `{order: [baidu], sort: price, ignore: [wafer]}`: Baidu is cheapest on every price, and staying on one provider keeps its prompt cache warm. |
| `v2/tooling/sandbox/sbp_openrouter_model.py` + `model_class` in `mini_toolcall.yaml` | Stock LiteLLM model, but each call is charged at OpenRouter's billed cost. LiteLLM has no prices for most OpenRouter models, so mini-swe-agent counted every call as $0. |
| `cost_limit: 1.0` (was 3.0) and no `--cost-limit 0` flag | Harbor's mini-swe-agent wrapper always passed `--cost-limit 0`, which overrides the config file and disables the cap. The wrapper now omits the flag unless a config sets `cost_limit`. |
| OpenRouter prices registered with LiteLLM | Fallback for responses without a billed cost. |

### 6. Fix: mini-swe-agent crashing in the offline sandbox

The agent sandbox has no network apart from the model endpoint. LiteLLM 1.105 tries to download its model price map
at import time, and its background retry crashed mini-swe-agent with a circular import
(`cannot import name 'LoggerContext' from partially initialized module 'litellm.rust_bridge.catalog'`).
`locked_mini_swe.py` sets `LITELLM_LOCAL_MODEL_COST_MAP=True` for every command in the sandbox.

### 7. Other

- `.gitignore`: adds `jobs/`, `datasets/` and `results/`.
- `docs/experiment_design.md`: design for the planned experiment.
- `v2/SHA256SUMS` was not regenerated: `cd v2 && shasum -a 256 -c SHA256SUMS` reports the six edited tooling files
  (`codex_config.toml`, `mini_toolcall.yaml`, `host_mini_swe.py`, `locked_claude_code.py`, `locked_codex.py`,
  `locked_mini_swe.py`) as changed. All task files still verify.

## Results so far

| Experiment | Resolved (re-graded) | Total cost | Notes |
|---|---|---|---|
| `oracle_smoke` | 5/5 | $0 | reference patches |
| `mini_glm-5.3_smoke` | 3/3 | $1.28 | $0.26-$0.64 per task, 98.6% cache hit rate, all calls on one provider |

DeepSeek V4.1 Flash is estimated at about $0.014 per task on its cheapest provider (from the GLM run's token counts);
not yet measured on a full task.

## Known limitations

- Codex through OpenRouter's Responses API (beta) has not been run end to end.
- Claude Code should be used with Anthropic models only.
- The re-grade step can be skipped only for `oracle` and `nop` agents.

## License and citation

MIT, as upstream (see [`LICENSE`](LICENSE)). Benchmark: Deng et al., *SWE-Bench Pro: Can AI Agents Solve Long-Horizon
Software Engineering Tasks?* (arXiv:2509.16941); see [`README.upstream.md`](README.upstream.md) for the full citation.
