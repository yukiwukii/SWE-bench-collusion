#!/usr/bin/env bash
# On the server: start ./run_experiment.sh <config> in a detached tmux session named after the config.
# vm.sh run calls this. Log: logs/<name>.log. Attach with: tmux attach -t <name> (detach: Ctrl-b d).
set -euo pipefail
cd "$(dirname "$0")/../.."
cfg=${1:?usage: infra/hetzner/start.sh configs/<x>.yaml}
name=$(basename "${cfg%.*}")
[ -f "$cfg" ] || { echo "no such config: $cfg" >&2; exit 1; }
[ -f .env ] || { echo "no .env on the server: run vm.sh push with --env" >&2; exit 1; }
tmux has-session -t "$name" 2>/dev/null && { echo "already running: tmux session $name" >&2; exit 1; }
mkdir -p logs
tmux new-session -d -s "$name" \
  "export PATH=\$HOME/.local/bin:\$PATH; ./run_experiment.sh '$cfg' 2>&1 | tee -a 'logs/$name.log'"
echo "started tmux session $name; log: $PWD/logs/$name.log"
