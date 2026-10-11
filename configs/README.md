# Experiment configs

One YAML file per experiment, in Harbor's job-config format (`harbor job schema` prints the full schema).
Run one with:

```bash
./run_experiment.sh configs/<name>.yaml
```

Results go to `results/<name>/` (the file name without `.yaml`):

| File | Contents |
|---|---|
| `summary.json` | resolved counts (agent phase and re-graded), `cost.total_billed_usd`, `cache` totals (incl. per provider) |
| `per_task.csv` | per task: rewards, `cost_usd` + `cost_source`, token counts, cache hit/miss tokens and hit rate |
| `calls.csv` | one row per LLM call: provider, prompt / cache-hit / cache-miss / cache-write / output tokens, cost |
| `cost_log.json` | OpenRouter key usage before/after each run; the deltas are the exact billed total |
| `pricing.json` | the model's OpenRouter list prices when the experiment started |
| `agent/`, `regrade/` | Harbor job directories; `regrade/` is the score to report |
| `config.yaml` | snapshot of the config |

Per-task `cost_source` is `openrouter_reported` (OpenRouter's own per-call cost; mini-swe-agent), else
`list_price_estimate` (tokens x list price; Claude Code, Codex). The total billed is exact but includes any other
use of the same OpenRouter key while the experiment runs.

Cache hits are input tokens the provider served from its prompt cache (billed far cheaper); misses are processed in
full. A cache only helps when consecutive calls reach the same provider, so `calls.csv` also records the provider.

Re-running the same config resumes an unfinished run. To change an experiment, copy the file under a new name;
the runner refuses to reuse a results folder whose config has changed.

## Writing a new config

The default model is DeepSeek V4.1 Flash (`mini_deepseek-v4.1-flash_{smoke,hard51,full}.yaml`). Copy the closest
existing file and change what you need:

| Field | Notes |
|---|---|
| `agents[0].import_path` | `locked_mini_swe:LockedMiniSwe` (any model), `locked_claude_code:LockedClaudeCode` (Anthropic models), `locked_codex:LockedCodex` (OpenAI models) |
| `agents[0].model_name` | OpenRouter slug (see https://openrouter.ai/models). mini-swe-agent needs an `openrouter/` prefix: `openrouter/z-ai/glm-5.3`. Claude Code and Codex take the plain slug: `anthropic/claude-sonnet-5.5` |
| `agents[0].extra_allowed_hosts` | Keep `[openrouter.ai]`: the agent sandbox is otherwise offline |
| `agents[0].kwargs` | Agent options, e.g. `reasoning_effort`, `config_file` |
| `agents[0].kwargs.openrouter_provider` | mini-swe-agent only, optional: OpenRouter [provider routing](https://openrouter.ai/docs/features/provider-routing), e.g. `{order: [baidu], sort: price, ignore: [wafer]}`. Default: `{sort: price}` |
| `datasets[0].path` | `v2/tasks` (642 tasks) or `datasets/hard51` (51 hard tasks) |
| `datasets[0].n_tasks` | Optional: only the first N tasks (good for smoke tests) |
| `datasets[0].task_names` | Optional: an explicit list of instance IDs |
| `n_concurrent_trials` | Tasks run in parallel on Modal |

mini-swe-agent settings shared by all mini configs live in `v2/tooling/configs/mini_toolcall.yaml`: a $1 per-task cost
cap (counted at OpenRouter's billed cost per call) and `provider.sort: price` (cheapest OpenRouter provider first).
