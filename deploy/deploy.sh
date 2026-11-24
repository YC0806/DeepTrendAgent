#!/usr/bin/env bash
# Package the current workspace and stream the archive to a Linux server over SSH.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 || "${1:-}" == --help ]]; then
  echo "Usage: $0 <ssh-target> [absolute-remote-app-dir]"
  if [[ $# -eq 1 && "${1:-}" == --help ]]; then
    exit 0
  fi
  exit 2
fi

DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
target="$1"
app_dir="${2:-/opt/deeptrend/app}"
if [[ "$app_dir" != /* || "$app_dir" == / ]]; then
  echo "The remote app directory must be an absolute path other than /." >&2
  exit 1
fi

# SSH passes the command to the remote user's shell. Use POSIX quoting for its arguments.
shell_quote() {
  local escaped_quote="'\\''"
  printf "'%s'" "${1//\'/$escaped_quote}"
}

work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
archive="$work_dir/deeptrend.tar.gz"
package_info="$(bash "$DEPLOY_DIR/../make_package.sh" "$archive")"
digest="${package_info##*SHA-256: }"
if [[ ! "$digest" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "Could not read the archive SHA-256 from make_package.sh." >&2
  exit 1
fi

installer="$(shell_quote "$(<"$DEPLOY_DIR/install-release.sh")")"
remote_command="bash -c $installer -- $(shell_quote "$app_dir") $digest"
echo "Deploying DeepTrend to $target:$app_dir ($digest)"
ssh -T -- "$target" "$remote_command" < "$archive"
