#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: remote-rollback.sh DEPLOY_ROOT" >&2
  exit 64
fi

deploy_root="$1"
if [[ ! "$deploy_root" =~ ^/[A-Za-z0-9._/-]+$ ]] ||
  [[ "$deploy_root" == "/" ]] || [[ "$deploy_root" == *"/../"* ]] ||
  [[ "$deploy_root" == */.. ]] || [[ "$deploy_root" == *"//"* ]]; then
  echo "DEPLOY_ROOT must be a specific absolute path without traversal" >&2
  exit 64
fi

current_link="$deploy_root/current"
previous_link="$deploy_root/previous"
[[ -L "$current_link" && -L "$previous_link" ]] || {
  echo "Both current and previous release links are required" >&2
  exit 66
}
current_release="$(readlink -f -- "$current_link")"
previous_release="$(readlink -f -- "$previous_link")"
for release in "$current_release" "$previous_release"; do
  case "$release" in
    "$deploy_root"/releases/*) ;;
    *) echo "Release link points outside DEPLOY_ROOT" >&2; exit 65 ;;
  esac
  [[ -f "$release/.env.production" && -f "$release/compose.prod.yaml" ]] || {
    echo "Release is incomplete: $release" >&2
    exit 65
  }
done

docker compose --env-file "$previous_release/.env.production" \
  -f "$previous_release/compose.prod.yaml" \
  up -d --no-build --wait --wait-timeout 180

run_id="${GITHUB_RUN_ID:-manual}"
[[ "$run_id" =~ ^[A-Za-z0-9._-]+$ ]] || run_id="manual"
ln -sfn -- "$previous_release" "$deploy_root/.current-rollback-$run_id"
mv -Tf -- "$deploy_root/.current-rollback-$run_id" "$current_link"
ln -sfn -- "$current_release" "$deploy_root/.previous-rollback-$run_id"
mv -Tf -- "$deploy_root/.previous-rollback-$run_id" "$previous_link"
echo "Restored previous release: $previous_release"
