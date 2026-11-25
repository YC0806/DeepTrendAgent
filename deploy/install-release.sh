#!/usr/bin/env bash
# Runs on the server with the package on stdin.
set -euo pipefail
umask 022

app_dir="${1%/}"
expected_digest="$2"
app_name="$(basename -- "$app_dir")"
if [[ "$app_dir" != /* || "$app_name" == / || "$app_name" == . || "$app_name" == .. ]]; then
  echo "Invalid app directory: $app_dir" >&2
  exit 1
fi

install_root="$(dirname -- "$app_dir")"
mkdir -p -- "$install_root"
install_root="$(cd -P -- "$install_root" && pwd)"
app_dir="${install_root%/}/$app_name"
release_root="${install_root%/}/.$app_name-releases"
mkdir -p -- "$release_root"

work_dir="$(mktemp -d "$release_root/.stage.XXXXXXXX")"
release_id="${work_dir##*.}"
release_dir="$release_root/release-$release_id"
legacy_dir=""
cleanup() {
  if [[ -n "$legacy_dir" && -d "$legacy_dir" && ! -e "$app_dir" && ! -L "$app_dir" ]]; then
    mv -- "$legacy_dir" "$app_dir" || echo "Restore the previous app from $legacy_dir." >&2
  fi
  rm -rf -- "$work_dir"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

archive="$work_dir/deeptrend.tar.gz"
cat > "$archive"
actual_digest="$(sha256sum "$archive")"
if [[ "${actual_digest%% *}" != "$expected_digest" ]]; then
  echo "Package checksum mismatch." >&2
  exit 1
fi

mkdir -- "$work_dir/app"
tar -xzf "$archive" --strip-components=1 --no-same-owner -C "$work_dir/app"
if [[ ! -x "$work_dir/app/bin/run-deeptrend" || ! -f "$work_dir/app/.opencode/skills/trend-run/SKILL.md" || ! -f "$work_dir/app/src/scripts/run_pipeline.py" ]]; then
  echo "The package is missing the DeepTrend runner, skill, or scripts." >&2
  exit 1
fi
bash -n "$work_dir/app/bin/run-deeptrend"
command -v python3 >/dev/null

exec 9> "$release_root/.deploy.lock"
flock -x 9

previous_release=""
if [[ -e "$app_dir" || -L "$app_dir" ]]; then
  if [[ ! -f "$app_dir/bin/run-deeptrend" || ! -f "$app_dir/.opencode/skills/trend-run/SKILL.md" ]]; then
    echo "Refusing to replace a path that is not a DeepTrend installation: $app_dir" >&2
    exit 1
  fi
  if [[ -L "$app_dir" ]]; then
    previous_release="$(readlink "$app_dir")"
  else
    legacy_dir="$release_root/legacy-$release_id"
    previous_release="$legacy_dir"
  fi
fi

ln -s -- "$release_dir" "$work_dir/app-link"
mv -- "$work_dir/app" "$release_dir"
if [[ -n "$legacy_dir" ]]; then
  mv -- "$app_dir" "$legacy_dir"
fi
# Replace the app symlink itself atomically, including when it points to a directory.
python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$work_dir/app-link" "$app_dir"

echo "Deployed $app_dir -> $release_dir"
if [[ -n "$previous_release" ]]; then
  echo "Previous release: $previous_release"
fi
