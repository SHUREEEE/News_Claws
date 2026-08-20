#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: remote-deploy.sh DEPLOY_ROOT IMAGE_SHA IMAGE_DIGEST RUN_ID ROLLBACK_APPROVED GHCR_USER" >&2
  exit 64
fi

deploy_root="$1"
image_sha="$2"
image_digest="$3"
run_id="$4"
rollback_approved="$5"
ghcr_user="$6"

if [[ ! "$deploy_root" =~ ^/[A-Za-z0-9._/-]+$ ]] ||
  [[ "$deploy_root" == "/" ]] || [[ "$deploy_root" == *"/../"* ]] ||
  [[ "$deploy_root" == */.. ]] || [[ "$deploy_root" == *"//"* ]]; then
  echo "DEPLOY_ROOT must be a specific absolute path without traversal" >&2
  exit 64
fi
[[ "$image_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "IMAGE_SHA must be a full Git SHA" >&2; exit 64; }
[[ "$image_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "IMAGE_DIGEST must be a SHA-256 OCI digest" >&2
  exit 64
}
[[ "$run_id" =~ ^[0-9]+$ ]] || { echo "RUN_ID must be numeric" >&2; exit 64; }
[[ "$rollback_approved" =~ ^(true|false)$ ]] || { echo "ROLLBACK_APPROVED must be true or false" >&2; exit 64; }
[[ "$ghcr_user" =~ ^[A-Za-z0-9-]{1,39}$ ]] || { echo "GHCR_USER is invalid" >&2; exit 64; }

incoming="$deploy_root/.incoming-$run_id"
release_id="$image_sha-$run_id"
release_dir="$deploy_root/releases/$release_id"
release_tmp="$deploy_root/releases/.$release_id.tmp"
current_link="$deploy_root/current"
previous_link="$deploy_root/previous"
archive="$incoming/release.tar.gz"
environment_file="$incoming/.env.production"
token_file="$incoming/ghcr-token"
docker_config="$incoming/docker-config"
previous_release=""
rollback_armed=false

compose() {
  local release="$1"
  shift
  docker compose --env-file "$release/.env.production" -f "$release/compose.prod.yaml" "$@"
}

rollback_previous() {
  [[ -n "$previous_release" ]] || return 1
  echo "Deployment failed; restoring the previously approved release"
  compose "$previous_release" up -d --no-build --wait --wait-timeout 180
}

cleanup() {
  local status=$?
  trap - EXIT
  if [[ $status -ne 0 && "$rollback_armed" == "true" && "$rollback_approved" == "true" ]]; then
    rollback_previous || echo "Automatic rollback failed; operator intervention is required" >&2
  fi
  rm -f -- "$token_file"
  if [[ -d "$release_tmp" && "$release_tmp" == "$deploy_root"/releases/.*.tmp ]]; then
    rm -rf -- "$release_tmp"
  fi
  if [[ -d "$incoming" && "$incoming" == "$deploy_root"/.incoming-* ]]; then
    rm -rf -- "$incoming"
  fi
  exit "$status"
}
trap cleanup EXIT

for command in docker find grep python3 tar; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 69; }
done
docker compose version >/dev/null
for required in "$archive" "$environment_file" "$token_file"; do
  [[ -f "$required" ]] || { echo "Missing deployment input: $required" >&2; exit 66; }
done

umask 077
install -d -m 700 -- "$deploy_root" "$deploy_root/releases"
[[ ! -e "$release_dir" ]] || { echo "Release directory already exists: $release_dir" >&2; exit 73; }
[[ ! -e "$release_tmp" ]] || { echo "Temporary release directory already exists" >&2; exit 73; }
mkdir -m 700 -- "$release_tmp"
tar --extract --gzip --file "$archive" --directory "$release_tmp" --no-same-owner --no-same-permissions
for required in compose.prod.yaml deploy/Caddyfile config scripts/validate_production_env.py; do
  [[ -e "$release_tmp/$required" ]] || { echo "Release archive is missing $required" >&2; exit 65; }
done
python3 "$release_tmp/scripts/validate_production_env.py" "$environment_file"
grep -Fxq "NEWS_CLAWS_IMAGE_TAG=$image_sha" "$environment_file" || {
  echo "Prepared environment does not match IMAGE_SHA" >&2
  exit 65
}
install -m 600 -- "$environment_file" "$release_tmp/.env.production"
chmod 700 -- "$release_tmp"
chmod 600 -- \
  "$release_tmp/.env.production" \
  "$release_tmp/compose.prod.yaml" \
  "$release_tmp/scripts/validate_production_env.py"
find "$release_tmp/config" -type d -exec chmod 755 -- {} +
find "$release_tmp/config" -type f -exec chmod 644 -- {} +
chmod 755 -- "$release_tmp/deploy"
chmod 644 -- "$release_tmp/deploy/Caddyfile"
mv -- "$release_tmp" "$release_dir"

if [[ -L "$current_link" ]]; then
  previous_release="$(readlink -f -- "$current_link")"
  case "$previous_release" in
    "$deploy_root"/releases/*) ;;
    *) echo "Current release points outside DEPLOY_ROOT" >&2; exit 65 ;;
  esac
  [[ -f "$previous_release/.env.production" && -f "$previous_release/compose.prod.yaml" ]] || {
    echo "Current release is incomplete" >&2
    exit 65
  }
  container_id="$(compose "$previous_release" ps -q analysis-api)"
  if [[ -z "$container_id" ]] ||
    [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" != "true" ]]; then
    echo "Current analysis-api container must be running for online backup" >&2
    exit 69
  fi
  compose "$previous_release" exec -T analysis-api \
    python scripts/backup.py --database /data/analysis.db --output-dir /backups
fi

mkdir -m 700 -- "$docker_config"
export DOCKER_CONFIG="$docker_config"
ghcr_token="$(<"$token_file")"
[[ -n "$ghcr_token" ]] || { echo "GHCR token is empty" >&2; exit 65; }
printf '%s' "$ghcr_token" | docker login ghcr.io --username "$ghcr_user" --password-stdin >/dev/null
unset ghcr_token
rm -f -- "$token_file"

compose "$release_dir" pull analysis-api caddy
image_ref="ghcr.io/shureeee/news_claws:$image_sha"
expected_repo_digest="ghcr.io/shureeee/news_claws@$image_digest"
docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$image_ref" |
  grep -Fqx "$expected_repo_digest" || {
  echo "Pulled image does not match the verified OCI digest" >&2
  exit 65
}
if [[ -n "$previous_release" ]]; then
  rollback_armed=true
fi
compose "$release_dir" up -d --no-build --wait --wait-timeout 180

if [[ -n "$previous_release" ]]; then
  ln -sfn -- "$previous_release" "$deploy_root/.previous-$run_id"
  mv -Tf -- "$deploy_root/.previous-$run_id" "$previous_link"
fi
ln -sfn -- "$release_dir" "$deploy_root/.current-$run_id"
mv -Tf -- "$deploy_root/.current-$run_id" "$current_link"
rollback_armed=false
echo "Deployed image $image_sha"
