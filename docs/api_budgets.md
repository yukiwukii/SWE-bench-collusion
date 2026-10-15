# API keys and budgets

Status on 2026-10-15; balances after the model runs of 2026-10-16 are in section 4. All keys are in `.env`
(gitignored). Never print a key. To list the names only: `sed -E 's/=.*/=<redacted>/' .env`.

## 1. Keys

| Name in `.env` | Service | Budget | Notes |
|---|---|---|---|
| `OPENROUTER_API_KEY` | OpenRouter (main) | $45 per week (key limit); about $21.70 left on 2026-10-15 during the orientation run | The account behind it has about $84 of credit, so the weekly key limit is what binds. Used for all DeepSeek runs. |
| `OPENROUTER_API_KEY_BACKUP` | OpenRouter (second account) | **about $8.77 in total** | The key shows a $50 limit (`/api/v1/key`), but the account only has $155 of credit with $146.23 used. The account balance binds, not the key limit. `docs/handoff.md` says $8; the $50 shown by the key is wrong. Used for the LLM judge (`judge.py`), about $0.02 per 10 agents. |
| `OPENAI_API_KEY` | OpenAI, direct | **about $12** | Added 2026-10-15 for GPT-6.1 Sol. |
| `ANTHROPIC_API_KEY` | Anthropic, direct | **about $12** | Added 2026-10-15 for Claude Sonnet 5.5. It was saved as `ANTHROPIC_API_KEy` (lowercase y); renamed so LiteLLM finds it. |

## 2. Checking what is left

OpenRouter, for either key (prints amounts only):

```
set -a && . ./.env && set +a && python3 -I -c "
import json, os, urllib.request
k = os.environ['OPENROUTER_API_KEY']          # or OPENROUTER_API_KEY_BACKUP
for ep in ('key', 'credits'):
    r = urllib.request.Request('https://openrouter.ai/api/v1/' + ep, headers={'Authorization': 'Bearer ' + k})
    print(ep, json.load(urllib.request.urlopen(r, timeout=30))['data'])"
```

`key` gives the key's limit and usage. `credits` gives the account's `total_credits` and `total_usage`; the
difference is what can really be spent. Check both: the backup key looks like it has $50 but its account has $8.77.

OpenAI and Anthropic have no simple balance endpoint for an API key. Check the balance in their consoles. During a
run, spend is the sum of `cost` in the agents' `result.json` files, which the harness computes from LiteLLM's price
table (direct APIs do not return a billed cost the way OpenRouter does).

## 3. How runs stay inside these budgets

- Every agent has a $1 cost cap (`cost_limit` in `v2/tooling/configs/mini_toolcall.yaml`). The most a run can cost is
  therefore about $1 x the number of agents.
- For the direct keys ($12 each), runs are sized so that this worst case fits: 5 trials x 2 agents x $1 = $10.
- The estimated cost of a 20-trial run, using the token counts of the DeepSeek no-rule run (139M prompt tokens, 98%
  cached, 1.6M output tokens) and listed prices on 2026-10-15:

| Model | Route | Est. 20 trials | Est. per agent |
|---|---|---|---|
| DeepSeek V4.1 Flash | OpenRouter, DeepInfra | $1.76 (measured) | $0.044 |
| Gemini 3.8 Flash | OpenRouter, Google flex tier | about $9.50 | about $0.24 |
| Claude Sonnet 5.5 | Anthropic direct | about $37 | about $0.92 |
| GPT-6.1 Sol | OpenAI direct | about $37 | about $0.92 |

  These estimates assume each model uses as many tokens as DeepSeek. Real use can differ by 2-3x either way.
  Sonnet and Sol are close to the $1 cap per agent, so some of their agents may stop at the cap.
- A listed cache price does not guarantee the provider applies it (see `docs/collusion_stage1_full_report.md`,
  section 5.2). Check the first agents' cost after a run starts.

## 4. After the runs of 2026-10-15/16

| Key | Spent on these runs | Left |
|---|---|---|
| `OPENROUTER_API_KEY` | DeepSeek orientation run $1.98, Gemini 3.8 Flash about $12.6 (over its $10 cap, see `docs/collusion_models_report.md` section 4) | **$8.35 this week** (key limit); account $60.94 |
| `OPENROUTER_API_KEY_BACKUP` | LLM judge, about $0.20 | **$8.67** (account) |
| `ANTHROPIC_API_KEY` | Claude Sonnet 5.5, $3.06 (LiteLLM estimate) | about $9 |
| `OPENAI_API_KEY` | GPT-6.1 Sol, $7.97 (LiteLLM estimate) | about $4 |

Check the Anthropic and OpenAI figures in their consoles; the harness estimates them from token counts.

**OpenRouter's key usage lags.** During the Gemini run the key showed $9.75 when the agents' recorded costs were
already $13.19. A spend guard must sum the per-call `cost` in the running trajectories
(`results/<run>/agent/*/collusion_private/agent_*/mini-swe-agent.trajectory.json`), not poll the key.

Measured cost per agent with the orientation prompt (20 easy instances): DeepSeek V4.1 Flash $0.050, Claude Sonnet
5.5 $0.075, GPT-6.1 Sol $0.198, Gemini 3.8 Flash $0.691. The estimates in section 3 were far off for Sonnet and Sol
(they make 8-14 calls per agent, not ~50) and too low for Gemini (~158 calls).
