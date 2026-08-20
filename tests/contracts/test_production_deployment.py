from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_production_workflow_is_manual_protected_and_fail_closed() -> None:
    path = PROJECT_ROOT / ".github/workflows/deploy-production.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    job = workflow["jobs"]["deploy"]
    steps = job["steps"]

    assert "workflow_dispatch:" in text
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "production",
        "cancel-in-progress": False,
    }
    assert job["environment"] == "production"
    assert any(step.get("uses") == "actions/checkout@v7" for step in steps)
    assert any(step.get("uses") == "actions/setup-python@v7" for step in steps)
    assert "git merge-base --is-ancestor" in text
    assert "docker buildx imagetools inspect" in text
    assert "IMAGE_DIGEST: ${{ steps.image.outputs.digest }}" in text
    assert "'$IMAGE_DIGEST'" in text
    assert "StrictHostKeyChecking yes" in text
    assert "StrictHostKeyChecking no" not in text
    assert "scripts/prepare_deployment_env.py" in text
    assert "scripts/smoke_public.py" in text
    assert "secrets.PRODUCTION_SSH_PRIVATE_KEY" in text
    assert "secrets.PRODUCTION_KNOWN_HOSTS" in text
    assert "secrets.PRODUCTION_ENV_FILE" in text
    assert "secrets.GHCR_READ_TOKEN" in text
    assert "secrets.BASIC_AUTH_PASSWORD" in text
    rollback = next(
        step
        for step in steps
        if step.get("name") == "Restore previous release after failed public smoke"
    )
    assert "inputs.rollback_approved" in rollback["if"]


def test_remote_deployment_backs_up_pulls_and_never_builds() -> None:
    deploy = (PROJECT_ROOT / "deploy/remote-deploy.sh").read_text(encoding="utf-8")
    rollback = (PROJECT_ROOT / "deploy/remote-rollback.sh").read_text(encoding="utf-8")

    assert "^[0-9a-f]{40}$" in deploy
    assert "^sha256:[0-9a-f]{64}$" in deploy
    assert "python scripts/backup.py" in deploy
    assert "Current analysis-api container must be running for online backup" in deploy
    assert "pull analysis-api caddy" in deploy
    assert "Pulled image does not match the verified OCI digest" in deploy
    assert "grep -Fqx" in deploy
    assert "up -d --no-build --wait --wait-timeout 180" in deploy
    assert "ROLLBACK_APPROVED must be true or false" in deploy
    assert "for command in docker find grep python3 tar" in deploy
    assert 'chmod 700 -- "$release_tmp"' in deploy
    assert '"$release_tmp/.env.production"' in deploy
    assert '"$release_tmp/compose.prod.yaml"' in deploy
    assert '"$release_tmp/scripts/validate_production_env.py"' in deploy
    assert 'find "$release_tmp/config" -type d -exec chmod 755 -- {} +' in deploy
    assert 'find "$release_tmp/config" -type f -exec chmod 644 -- {} +' in deploy
    assert 'chmod 755 -- "$release_tmp/deploy"' in deploy
    assert 'chmod 644 -- "$release_tmp/deploy/Caddyfile"' in deploy
    assert "chmod -R go-rwx" not in deploy
    assert "StrictHostKeyChecking=no" not in deploy
    assert "up -d --no-build --wait --wait-timeout 180" in rollback
    assert "Both current and previous release links are required" in rollback

    backup_position = deploy.index("python scripts/backup.py")
    pull_position = deploy.index('compose "$release_dir" pull analysis-api caddy')
    digest_position = deploy.index('grep -Fqx "$expected_repo_digest"')
    start_position = deploy.index('compose "$release_dir" up -d --no-build')
    assert backup_position < pull_position < digest_position < start_position


def test_ci_checks_remote_shell_syntax() -> None:
    ci = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "bash -n deploy/remote-deploy.sh deploy/remote-rollback.sh" in ci
