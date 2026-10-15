# Running experiments on a Hetzner server

The experiments run on local Docker, so any x86 Linux server with Docker works. No Modal account is needed.
The server runs everything: the task containers, the agents' LLM loop (calls go to OpenRouter) and the re-grading.
After `run`, the laptop can be closed or disconnected.

## 1. Create the server (Hetzner Cloud console)

- Type: **CPX62** (shared vCPU tab; 16 vCPU, 32 GB RAM, 640 GB disk, about $0.24/h) with `n_concurrent_trials: 6`.
  New accounts cannot order dedicated-vCPU servers (CCX) for the first few weeks. Once allowed, a CCX53
  (32 vCPU, 128 GB, about $1/h) with 12 is faster. A CPX52 (12 vCPU, 24 GB) works with 4.
  Set `n_concurrent_trials` in the config before `push`. Each trial runs 2 sandboxes with a 4 GB limit each,
  and they usually use much less. `setup` adds 16 GB of swap as a safety margin.
- Image: **Ubuntu 24.04**. Location: any (Ashburn, Hillsboro, Nuremberg, Falkenstein, Helsinki).
- Add your SSH public key (`~/.ssh/id_ed25519.pub`). Note the server's IPv4 address.

## 2. Copy the repo and set up the server (from the repo root on the laptop)

```
infra/hetzner/vm.sh push  root@<ip> --env     # repo incl. uncommitted work, plus .env (OpenRouter key)
infra/hetzner/vm.sh setup root@<ip>           # Docker, uv, harbor 0.24.0, mini-swe-agent 2.4.6 (~3 min)
```

`push` never copies `results/`, and it sends `.env` only with `--env`. The key file is set to mode 600 on the
server. Re-run `push` (without `--env`) after changing code or configs.

## 3. Run

```
infra/hetzner/vm.sh run    root@<ip> configs/collusion/stage1_B1_full.yaml
infra/hetzner/vm.sh status root@<ip> configs/collusion/stage1_B1_full.yaml
```

The job runs in a tmux session named after the config, and its log is `logs/<name>.log` on the server. To watch it
live: `ssh root@<ip>`, then `tmux attach -t stage1_B1_full` (detach with Ctrl-b d). If the server reboots or the
job dies, `run` again resumes it; only trials that were in progress are lost.

## 4. Get the results and delete the server

```
infra/hetzner/vm.sh pull root@<ip> configs/collusion/stage1_B1_full.yaml   # into results/<name>/
python3 -I helper_code/collusion/analyze.py results/stage1_B1_full
```

Then **delete** the server in the console. Hetzner bills stopped servers too.

## Expected size of `stage1_B1_full` (50 instances x 3 seeds = 150 trials)

From the stage 1 pilot (`docs/collusion_stage1_trial_report.md`): about 24 min per trial including re-grades,
$0.07 OpenRouter cost per trial.

- CPX62, 6 trials at once: about 11-12 h, plus about 1 h to pull 50 images. Server about $3.
- CCX53 (12 at once): about 6-8 h, server about $7-8. CPX52 (4 at once): about 16-17 h, server about $3.
- OpenRouter cost is about $11 (more if trials run longer).
- Disk: about 130 GB of images.

Watch memory in the first hour with `vm.sh status` (it prints `free -g`). If swap use keeps growing, stop the job
(`tmux attach`, then Ctrl-c), lower `n_concurrent_trials`, rename the config so it is a new experiment (or delete
the results folder), push and run again.
