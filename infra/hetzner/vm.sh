#!/usr/bin/env bash
# Run experiments on a remote Linux server instead of this laptop. Run from the repo root on the laptop.
#
#   infra/hetzner/vm.sh push   root@<ip> [--env]          copy this repo (with uncommitted work) to the server;
#                                                         --env also copies .env (your OpenRouter key)
#   infra/hetzner/vm.sh setup  root@<ip>                  install Docker, uv, Harbor, mini-swe-agent
#   infra/hetzner/vm.sh run    root@<ip> configs/<x>.yaml start the experiment in tmux; safe to disconnect
#   infra/hetzner/vm.sh status root@<ip> configs/<x>.yaml finished trials, last log lines, disk
#   infra/hetzner/vm.sh pull   root@<ip> configs/<x>.yaml copy results/<x>/ back to this laptop
#
# The server runs everything (containers, agent LLM loop, grading). The laptop can be closed after `run`.
# Re-running `run` on an interrupted experiment resumes it.
set -euo pipefail
cd "$(dirname "$0")/../.."
cmd=${1:?usage: vm.sh push|setup|run|status|pull root@<ip> [...]}
host=${2:?missing root@<ip>}
dir=SWE-bench_Pro-os

name_of() { local cfg=${1:?missing configs/<x>.yaml}; basename "${cfg%.*}"; }

case $cmd in
  push)
    # results/ and .env stay out; excluded paths are also never deleted on the server
    rsync -az --delete --exclude 'results/' --exclude 'logs/' --exclude '.env' --exclude '__pycache__/' \
      ./ "$host:$dir/"
    if [ "${3:-}" = --env ]; then
      scp -q .env "$host:$dir/.env" && ssh "$host" "chmod 600 $dir/.env"
      echo "copied .env"
    fi
    echo "pushed to $host:$dir" ;;
  setup)
    ssh "$host" "bash $dir/infra/hetzner/setup_vm.sh" ;;
  run)
    ssh "$host" "cd $dir && infra/hetzner/start.sh '${3:?missing configs/<x>.yaml}'" ;;
  status)
    name=$(name_of "${3:-}")
    ssh "$host" "cd $dir
      echo \"agent trials finished: \$(ls results/$name/agent/*/result.json 2>/dev/null | wc -l)\"
      for d in results/$name/regrade_a*; do [ -d \"\$d\" ] && echo \"\$(basename \$d): \$(ls \$d/*/result.json 2>/dev/null | wc -l)\"; done
      tmux has-session -t '$name' 2>/dev/null && echo 'tmux session: running' || echo 'tmux session: finished'
      tail -5 logs/$name.log 2>/dev/null; df -h / | tail -1; free -g | head -3; uptime" ;;
  pull)
    name=$(name_of "${3:-}")
    mkdir -p results
    rsync -az "$host:$dir/results/$name" results/
    rsync -az "$host:$dir/logs/$name.log" "results/$name/run.log" 2>/dev/null || true
    echo "pulled results/$name" ;;
  *)
    echo "unknown command: $cmd" >&2; exit 1 ;;
esac
