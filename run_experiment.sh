#!/usr/bin/env bash
# Run one experiment config from configs/ and save everything under results/<config_name>/.
#
#   ./run_experiment.sh configs/<name>.yaml
#
#   results/<name>/config.yaml   snapshot of the config that produced these results
#   results/<name>/agent/        agent-phase job (trajectories, captured model.patch per task)
#   results/<name>/regrade/      every patch re-graded on a pristine image (the score to report)
#   results/<name>/summary.json  resolved counts + total cost; per_task.csv: score + cost breakdown per task
#   results/<name>/cost_log.json OpenRouter key usage before/after each run (exact billed total)
#   results/<name>/pricing.json  the model's OpenRouter list prices when the experiment started
#
# Re-running the same config resumes an unfinished run instead of starting over.
# Model traffic goes through OpenRouter (OPENROUTER_API_KEY, read from .env if present).
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
export PYTHONPATH=v2/tooling

cfg=${1:?usage: ./run_experiment.sh configs/<name>.yaml}
[ -f "$cfg" ] || { echo "no such config: $cfg" >&2; exit 1; }
name=$(basename "${cfg%.*}"); out="results/$name"

# Validate the config and find out which agent and model it uses.
read -r agent model < <(harbor run -c "$cfg" --print-config | python3 -c \
  'import json,sys; a=(json.load(sys.stdin).get("agents") or [{"name": "oracle"}])[0]; print(a.get("import_path") or a.get("name"), a.get("model_name") or "-")')
[ -n "${agent:-}" ] || { echo "could not read $cfg" >&2; exit 1; }
needs_key=1; case $agent in oracle|nop) needs_key=0 ;; esac
[ $needs_key = 0 ] || : "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY in .env}"

mkdir -p "$out"
if [ -f "$out/config.yaml" ] && ! cmp -s "$cfg" "$out/config.yaml"; then
  echo "$cfg changed since $out was started. Rename the config for a new experiment, or delete $out." >&2
  exit 1
fi
cp "$cfg" "$out/config.yaml"

# start_or_resume <job_name> <harbor run args...>
start_or_resume() {
  local job=$1; shift
  if [ -f "$out/$job/config.json" ]; then
    harbor job resume -p "$out/$job"
  else
    harbor run -c "$cfg" "$@" --job-name "$job" -o "$out" -y
  fi
}

ledger() { python3 -I helper_code/openrouter_ledger.py "$@"; }
if [ $needs_key = 1 ]; then
  ledger begin "$out" "${model#openrouter/}"
  trap 'ledger end "$out"' EXIT                   # close the cost entry even if the run is interrupted
  trap 'ledger end "$out"; trap - EXIT; exit 130' INT TERM
fi

start_or_resume agent
[ $needs_key = 0 ] || { ledger end "$out"; trap - EXIT INT TERM; }

# Authoritative score: replay each captured diff on a fresh image with the unchanged verifier.
# (oracle/nop don't capture patches, so their agent-phase score is already the answer.)
if [ $needs_key = 1 ]; then
  start_or_resume regrade -a patch_replay:PatchReplayAgent -m replay --ak source_job="$out/agent"
fi

python3 -I helper_code/summarize_results.py "$out"
