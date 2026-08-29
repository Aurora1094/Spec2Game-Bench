#!/usr/bin/env bash
set -euo pipefail

workspace_path="${1:?Usage: run_main.sh <absolute-workspace> [run-id] [round-id] [config]}"
run_id="${2:-main_r1}"
round_id="${3:-}"
config_path="${4:-}"

case "$workspace_path" in
  /*) ;;
  *) echo "Workspace must be an absolute path" >&2; exit 2 ;;
esac

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cli_arguments=("main.py" "benchmark" "--workspace" "$workspace_path" "--run-id" "$run_id")
if [[ -n "$round_id" ]]; then cli_arguments+=("--round-id" "$round_id"); fi
if [[ -n "$config_path" ]]; then cli_arguments+=("--config" "$config_path"); fi
cd "$repository_root"
exec python "${cli_arguments[@]}"
