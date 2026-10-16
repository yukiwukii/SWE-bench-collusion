# Handoff: how to use this repository, and how to run it on a Hetzner server

Updated 2026-10-16 for the next agent working in this repo. Work from the repo root on the user's laptop
(`/Users/yuki/Downloads/SWE-bench_Pro-os`, branch `openrouter-harness`, pushed to `origin`,
github.com/yukiwukii/SWE-bench-collusion). Big runs go on a Hetzner server (section 6).

## 1. What this repo is

A fork of SWE-bench Pro (V2, 642 Harbor tasks), with two additions:

1. **A config-driven harness.** Every experiment is one YAML file in `configs/`. `./run_experiment.sh <config>`
   runs it and saves everything under `results/<config name>/`, including the exact billed cost.
   Model calls go through OpenRouter by default; direct OpenAI and Anthropic keys also work.
2. **The collusion experiment** (`configs/collusion/`, `v2/tooling/collusion_group.py`). Two agents solve the same
   task, each in its own Docker sandbox with its own repo. Without being told, they share one `/workspace` folder.
   We measure whether they notice, read or copy each other's files. The design is in `docs/experiment_design.md`.

Read these first, in this order:

| File | Why |
|---|---|
| `README.md` | what changed from upstream, the results layout, cost accounting |
| `configs/README.md` | config fields, provider pinning, collusion `kwargs` |
| `docs/experiment_design.md` | the experiment's conditions (B1 etc.) and factors F1-F8 |
| `docs/api_budgets.md` | every key, its budget, how to check what is left |
| `docs/collusion_stage1_full_report.md` | measures, and what went wrong in the first big run |
| `infra/hetzner/README.md` | the server scripts (summarized in section 6 below) |

## 2. Rules

- **Never print, log or paste an API key.** No `cat .env`, `env`, `echo $..._KEY`, or `set -x` around commands that
  use a key. To see which keys exist: `sed -E 's/=.*/=<redacted>/' .env`.
- Do not send the user's email address or other personal data to any service.
- **Ask before spending money.** Check the budget first (section 3). Every agent has a $1 cap, so a run costs at
  most about $1 x number of agents. Stop and ask if a run goes well past its estimate.
- Do not change a config after its run has started. Copy it under a new name instead. `run_experiment.sh` refuses
  to reuse `results/<name>/` with a changed config, and that is on purpose.
- Do not delete anything in `results/` that you did not create. `results/` is gitignored and exists only on the
  laptop (and the server). It is not backed up anywhere else.
- Do not commit or push without the user's OK.
- You cannot create or delete Hetzner servers: there is no Hetzner API token. The user does that in the console.

## 3. Keys and budgets

All keys are in `.env` (gitignored). Full details and the check commands are in `docs/api_budgets.md`. Summary on
2026-10-16:

| Name in `.env` | Service | What is left | Use |
|---|---|---|---|
| `OPENROUTER_API_KEY` | OpenRouter, main | about $5 this week (key limit $45/week, resets weekly); account about $57 | all DeepSeek runs |
| `OPENROUTER_API_KEY_BACKUP` | OpenRouter, second account | about $8.35 in total, no reset (the key shows $50, but the account balance binds) | LLM judge |
| `ANTHROPIC_API_KEY` | Anthropic, direct | about $9 | Claude Sonnet 5.5 |
| `OPENAI_API_KEY` | OpenAI, direct | about $4 | GPT-6.1 Sol |

Check an OpenRouter key without printing it (both the key limit and the account balance):

```
set -a && . ./.env && set +a && python3 -I -c "
import json, os, urllib.request
k = os.environ['OPENROUTER_API_KEY']          # or OPENROUTER_API_KEY_BACKUP
for ep in ('key', 'credits'):
    r = urllib.request.Request('https://openrouter.ai/api/v1/' + ep, headers={'Authorization': 'Bearer ' + k})
    print(ep, json.load(urllib.request.urlopen(r, timeout=30))['data'])"
```

Three lessons that cost money before:

- **OpenRouter's key usage lags real spend** by several dollars during a run. To guard a run, sum the per-call
  `cost` in the running trajectories
  (`results/<run>/agent/*/collusion_private/agent_*/mini-swe-agent.trajectory.json`), not the key's `usage`.
- **Always pin providers** (`openrouter_provider: {order: [...], allow_fallbacks: false}`). `sort: price` once fell
  back to a provider that billed cached tokens at the full rate and served fp4, which doubled the cost. Current pins
  are in `configs/README.md`.
- **A key limit turns trials into garbage silently.** When the limit is hit, every call fails and the agents end with
  `Error:APIError`. Make sure the key covers the worst case before starting.

Measured cost per agent (orientation prompt, easy instances): DeepSeek V4.1 Flash $0.05, Claude Sonnet 5.5 $0.075,
GPT-6.1 Sol $0.20, Gemini 3.8 Flash $0.69. For a new model, run 1-2 uncapped trials first: the number of calls per
agent decides the cost, and smoke tests do not show it.

## 4. Repo map

| Path | What |
|---|---|
| `configs/*.yaml`, `configs/collusion/*.yaml` | one experiment per file; `*_tasks.txt` are instance lists |
| `run_experiment.sh` | agent phase, then re-grade of each captured patch, then summary; resumes unfinished runs |
| `v2/tasks/` | the 642 benchmark tasks (unchanged from upstream) |
| `v2/tooling/collusion_group.py` | the multi-agent coordinator: shared `/workspace` sync, turn order, prompt, logging |
| `v2/tooling/local_docker_env.py` | `OfflineCapableDocker`: local Docker without nftables (needed on Docker Desktop) |
| `v2/tooling/locked_mini_swe.py`, `v2/tooling/configs/mini_toolcall.yaml` | mini-swe-agent wrapper, $1 cap, provider routing |
| `v2/tooling/patch_replay.py` | re-grades a captured patch on a pristine image |
| `helper_code/collusion/analyze.py` | measures: notice, read, copy, Jaccard, resolve; writes `collusion_agents.csv`, `collusion_summary.json` |
| `helper_code/collusion/judge.py` | LLM judge that labels how noticing agents reacted |
| `helper_code/collusion/select_instances.py`, `stats.py`, `make_plants.py` | instance sampling, Wilson/Fisher stats, planted files |
| `helper_code/summarize_results.py`, `openrouter_ledger.py` | `summary.json`, `per_task.csv`, `calls.csv`; billed-cost ledger |
| `infra/hetzner/` | `vm.sh` (push/setup/run/status/pull), `setup_vm.sh`, `start.sh`, `README.md` |
| `docs/collusion_*_report.md` | one report per run |

## 5. Running an experiment

### 5.1 Make a config

Copy the closest existing config under a new name and change only what you need. The file name becomes the
results folder name. For collusion runs, start from `configs/collusion/stage1_B1_orient_more30.yaml` (the latest
DeepSeek run) or `stage1_B1_norule20.yaml`. The collusion `kwargs` (mount, order, write_mode, builtin_constraint,
seed_content, ...) are listed in `configs/README.md`.

Things to set every time:
- `environment.import_path: local_docker_env:OfflineCapableDocker` (local Docker; there are no Modal credits).
- `openrouter_provider` pinned, with `allow_fallbacks: false`.
- `n_concurrent_trials`: 1-2 on the laptop, 10 on a CPX62 (section 6.1).
- `datasets[0].task_names`: an explicit list. Stick to small-image repos (NodeBB, ansible, navidrome) and leave
  out HARD-51.

### 5.2 Run, analyze, report

```
./run_experiment.sh configs/collusion/<name>.yaml        # laptop; or use the server, section 6
python3 -I helper_code/collusion/analyze.py results/<name>
```

Optional, costs about $0.02 per 10 agents, ask the user first: label the reactions with the judge (backup key),
then run `analyze.py` again to merge the labels:

```
set -a && . ./.env && set +a && OPENROUTER_API_KEY=$OPENROUTER_API_KEY_BACKUP \
  python3 -I helper_code/collusion/judge.py results/<name>
python3 -I helper_code/collusion/analyze.py results/<name>
```

`run_experiment.sh` writes into `results/<name>/`:

| Path | What |
|---|---|
| `config.yaml` | snapshot of the config |
| `agent/<trial>/agent/` | `agent_0/`, `agent_1/` (trajectory, `model.patch`, `result.json`), `events.jsonl` (every command, its output and `/workspace` changes), `group.json` |
| `regrade_a0/`, `regrade_a1/` | the authoritative pass/fail of each agent's patch |
| `summary.json`, `per_task.csv`, `calls.csv` | resolved counts, cost, cache stats |
| `cost_log.json`, `pricing.json` | billed cost before/after (OpenRouter), list prices |

Write a report as `docs/collusion_<name>_report.md`, in the style of the existing ones: plain, short sentences,
tables for numbers, Wilson 95% intervals for small-n rates, quotes from the agents' `reasoning_content`.

### 5.3 Where to run

| Where | When | Notes |
|---|---|---|
| Laptop (Docker Desktop, arm64 Mac, 7.75 GB VM RAM) | smoke tests, 1-5 trials | images are amd64 and run emulated, slowly; `n_concurrent_trials` 1-2 |
| **Hetzner server** | any real run | about 10x faster; section 6 |
| Modal | not used | no credits; interrupted Modal runs leave billing sandboxes |

Free smoke tests (scripted agents, no LLM): `configs/collusion/smoke_det_{shared,isolated,gated}.yaml`.

## 6. Hetzner

### 6.1 What it is and what it costs

The experiments run on plain Docker, so any x86 Linux server works. We use **Hetzner Cloud CPX62**: 16 shared vCPU,
32 GB RAM, 640 GB disk, Ubuntu 24.04, about **$0.24/h** (about $5.80 a day). The server does everything: the task
containers, the agents' LLM loop (calls go out to OpenRouter/Anthropic/OpenAI) and the re-grading. Once a run is
started, the laptop can be closed.

- **Concurrency:** `n_concurrent_trials: 10` on a CPX62. Each trial runs 2 sandboxes (1 CPU, 4 GB limit each).
  Memory peaked at 2.6 GB for 6 trials, so 10 is safe. On a CPX52 (12 vCPU, 24 GB) use 4-6.
- **Bigger servers:** the account is new, so Hetzner does not allow dedicated-vCPU (CCX) servers yet. Once it does,
  a CCX53 (32 vCPU, 128 GB, about $1/h) can run about 20 trials at once.
- **Measured speed on a CPX62 with 10 at once:** 20 DeepSeek trials took 56 min for the agent phase; 30 trials took
  81 min. Re-grades add about 10-20 min. Pulling the images for a new set of instances takes about 20 min the first
  time. Claude Sonnet and GPT-6.1 Sol are much faster per agent (0.7 and 4 min median); Gemini is slower (18 min).
- **Disk:** about 114 GB used after all runs so far (images for about 50 instances plus results). 463 GB free.

### 6.2 The current server (important)

On 2026-10-16 a CPX62 is **still running and billing**:

| | |
|---|---|
| Address | `root@2.29.35.80` (hostname `ubuntu-32gb-hel1-2`, Helsinki) |
| State | idle, no tmux session, no containers; up since about 2026-10-16 09:00 UTC |
| Installed | Docker, uv, Harbor 0.24.0, mini-swe-agent 2.4.6, 52 task images already pulled |
| `.env` on it | `OPENROUTER_API_KEY` (the **main** key), `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. No backup key. |
| Results on it | the smoke runs and all `stage1_B1_norule20`, `orient20`, `orient_more30`, `orient_{gemini38f,sol61,sonnet55}*` runs; all of these are already pulled to the laptop |

If the user wants another run soon, reuse it: skip creating and `setup`, and just `push` and `run`. The images it
already has save the pull time. If nothing is planned, tell the user to **delete it** in the Hetzner console. Delete,
do not power off: Hetzner bills stopped servers too.

Check that it is still there: `ssh -o ConnectTimeout=8 root@2.29.35.80 uptime`.

### 6.3 Create a new server (the user does this)

Ask the user to create it in the Hetzner Cloud console:
- Type **CPX62** (shared vCPU tab). Image **Ubuntu 24.04**. Any location (Helsinki, Nuremberg, Falkenstein, Ashburn,
  Hillsboro).
- Add their SSH key (`~/.ssh/id_ed25519.pub`).
- Give you the IPv4 address.

Then, from the repo root on the laptop (`IP=...`):

```
ssh -o StrictHostKeyChecking=accept-new root@$IP true   # SSH works? If not, ask whether the SSH key was added
infra/hetzner/vm.sh push  root@$IP --env                # repo incl. uncommitted work, plus .env (mode 600)
infra/hetzner/vm.sh setup root@$IP                      # about 3 min; safe to re-run
```

`setup` (`infra/hetzner/setup_vm.sh`) installs curl, git, python3, rsync, tmux and Docker. It gives Docker a larger
address pool (`10.200.0.0/14` in /24s; every sandbox gets its own network and the default pool runs out after about
30). It adds 16 GB of swap, installs uv, then `harbor==0.24.0` with `mini-swe-agent==2.4.6` on Python 3.13 (the same
versions as every run so far). It ends by printing Docker's CPU/RAM, the Harbor version and disk.

**Using a different key on the server.** `push --env` copies the laptop's `.env` as is, so the server uses the main
key. To run with another key, write the server's `.env` without printing the key. For example, the backup key under
the name the harness reads:

```
grep '^OPENROUTER_API_KEY_BACKUP=' .env | sed 's/^OPENROUTER_API_KEY_BACKUP=/OPENROUTER_API_KEY=/' \
  | ssh root@$IP 'umask 077; cat > SWE-bench_Pro-os/.env'
ssh root@$IP 'grep -c "^OPENROUTER_API_KEY=sk-or-" SWE-bench_Pro-os/.env'   # must print 1
```

Add the direct keys the same way if the config uses `anthropic/` or `openai/` models.

### 6.4 Run, watch, collect

`vm.sh` commands (run on the laptop, from the repo root):

| Command | What it does |
|---|---|
| `vm.sh push root@$IP [--env]` | rsync the repo to `~/SWE-bench_Pro-os` on the server. Never touches `results/`, `logs/` or `.env` there (and never deletes them). Re-run it after any code or config change. |
| `vm.sh setup root@$IP` | run `setup_vm.sh` |
| `vm.sh run root@$IP configs/<x>.yaml` | start `run_experiment.sh` in a detached tmux session named after the config; log in `logs/<name>.log`. Refuses if that session already runs or there is no `.env`. Re-running it resumes an interrupted run. |
| `vm.sh status root@$IP configs/<x>.yaml` | finished agent trials, finished re-grades, whether tmux still runs, last 5 log lines, disk, memory, load |
| `vm.sh pull root@$IP configs/<x>.yaml` | rsync `results/<name>/` to the laptop, and the log to `results/<name>/run.log` |

A typical run:

```
infra/hetzner/vm.sh push   root@$IP
infra/hetzner/vm.sh run    root@$IP configs/collusion/<name>.yaml
infra/hetzner/vm.sh status root@$IP configs/collusion/<name>.yaml     # every 20-30 min
infra/hetzner/vm.sh pull   root@$IP configs/collusion/<name>.yaml     # when status says "tmux session: finished"
python3 -I helper_code/collusion/analyze.py results/<name>
```

To watch live: `ssh root@$IP`, `tmux attach -t <name>`, detach with Ctrl-b d.

**Checks in the first 15 minutes** (on the server, in `~/SWE-bench_Pro-os`):

1. The prompt is what you intended. Look at the first user message of a trajectory
   (`results/<name>/agent/*/agent/agent_*/mini-swe-agent.trajectory.json`, `messages[1].content`). For a no-rule
   run, `existing solutions` must not appear in it.
2. Only the pinned providers are used:
   ```
   python3 -I - <<'EOF'
   import json, glob
   from collections import Counter
   c = Counter()
   for f in glob.glob('results/<name>/agent/*/agent/agent_*/mini-swe-agent.trajectory.json'):
       for m in json.load(open(f))['messages']:
           r = (m.get('extra') or {}).get('response') or {}
           if r: c[r.get('provider')] += 1
   print(c)
   EOF
   ```
3. No API errors: `grep -c "APIError\|Retrying" logs/<name>.log` stays at or near 0. A few retries or "Connection
   reset by peer" are normal. `Key limit exceeded`, `No endpoints found` or `429` are not: stop the job and tell
   the user.
4. Memory and disk in `vm.sh status`. If swap use keeps growing, stop and lower `n_concurrent_trials` (in a renamed
   config).

**Things that are normal:** some agents hit the $1 cap (`LimitsExceeded`); some trials hit the 2 h group timeout
(the agents record `exit_status: Stopped` with their real cost and patch); long stretches with no finished trials
while hard ansible instances run.

The run is done when `status` says `tmux session: finished` and each `regrade_a*` shows the full trial count.

### 6.5 Stop, resume, recover

- **Stop:** `ssh root@$IP 'tmux kill-session -t <name>'`, then remove leftover sandboxes:
  `ssh root@$IP 'docker ps -q | xargs -r docker rm -f'`.
- **Resume** after a crash, reboot or stop: `vm.sh run` again. Harbor keeps finished trials and re-runs the rest;
  only trials in progress are lost.
- **Trials that died on an API error count as finished.** Before resuming after a key or provider failure, move
  those trial directories out of `results/<name>/agent/` on the server (e.g. to `results/<name>_failed/`), and move
  any `regrade_a*` folders too. `stage1_B1_full` is the worked example (`docs/collusion_stage1_full_report.md`).
  Ask the user before re-running trials that cost money.
- **Harness bug** (an agent's `result.json` has `exit_status: Error:RuntimeError`, or many trials show the same
  `exception_info`): stop, find the cause in `v2/tooling/collusion_group.py`, and tell the user before you change
  code. The last one was `find -printf` on BusyBox (Alpine) images, now fixed with `stat -c`.
- **Server lost before pulling:** results exist only on the server until `pull`. Pull after every run. When the
  first server was deleted on 2026-10-13, its state was saved first to `results/_server_backup_2026-10-13/`.

### 6.6 Finish

1. `vm.sh pull` every run that is on the server and not yet on the laptop.
2. Tell the user to **delete** the server in the Hetzner console (not power off).
3. Tell the user how long the server ran, so they know its cost (about $0.24/h).

## 7. Runs so far

| Run (`results/`, `docs/`) | What | Outcome |
|---|---|---|
| `stage1_B1` | pilot, 10 instances, with the rule | `collusion_stage1_trial_report.md` |
| `stage1_B1_full` | 50 x 3 planned, with the rule | 37 clean trials, then the key limit hit; `collusion_stage1_full_report.md` |
| `stage1_B1_norule20` | 20 instances, rule removed | more noticing/reading, no copying, 35/40 hunt for the upstream fix; `collusion_stage1_norule20_report.md` |
| `stage1_B1_orient20` | + "check your working directories" line | 2/40 took the partner's work; `collusion_stage1_orient20_report.md` |
| `stage1_B1_orient_more30` | same prompt, 30 more instances | 1 more partial take (3/100 total); `collusion_stage1_orient_more30_report.md` |
| `stage1_B1_orient_{sonnet55,sol61,gemini38f}*` | same prompt, three other models | only DeepSeek took work or hunted for the fix; `collusion_models_report.md` |

All of these ran on Hetzner CPX62 servers with local Docker.
