from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_production_compose_uses_immutable_image_and_persistent_volumes() -> None:
    compose = yaml.safe_load((PROJECT_ROOT / "compose.prod.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["analysis-api"]

    assert service["image"] == (
        "${NEWS_CLAWS_IMAGE:?NEWS_CLAWS_IMAGE is required}:"
        "${NEWS_CLAWS_IMAGE_TAG:?NEWS_CLAWS_IMAGE_TAG is required}"
    )
    assert "build" not in service
    assert "env_file" not in service
    assert "BASIC_AUTH_HASH" not in service["environment"]
    assert "SMTP_PASSWORD" in service["environment"]
    assert "analysis-data:/data" in service["volumes"]
    assert "analysis-backups:/backups" in service["volumes"]
    assert service["read_only"] is True
    assert "no-new-privileges:true" in service["security_opt"]

    caddy = compose["services"]["caddy"]
    assert "env_file" not in caddy
    assert set(caddy["environment"]) == {
        "DOMAIN",
        "BASIC_AUTH_USER",
        "BASIC_AUTH_HASH",
    }
    assert "ADMIN_TOKEN" not in caddy["environment"]
    assert "SMTP_PASSWORD" not in caddy["environment"]


def test_container_prepares_writable_data_and_backup_mountpoints() -> None:
    dockerfile = (PROJECT_ROOT / "apps/analysis_api/Dockerfile").read_text(encoding="utf-8")

    assert "mkdir -p /data /backups" in dockerfile
    assert "chown -R newsclaws:newsclaws /app /data /backups" in dockerfile
    assert "USER newsclaws" in dockerfile


def test_caddy_protects_everything_except_liveness() -> None:
    caddyfile = (PROJECT_ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")

    assert "@live path /health/live" in caddyfile
    assert "basic_auth" in caddyfile
    assert "reverse_proxy analysis-api:8000" in caddyfile


def test_release_workflow_publishes_sha_tagged_image_with_supply_chain_metadata() -> None:
    workflow_path = PROJECT_ROOT / ".github/workflows/publish-container.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    publish = workflow["jobs"]["publish"]
    steps = publish["steps"]

    assert '- "v*.*.*"' in workflow_text
    assert "value=latest" not in workflow_text
    assert workflow["permissions"]["contents"] == "read"
    assert workflow["permissions"]["packages"] == "write"
    assert set(workflow["permissions"]) == {"contents", "packages"}
    assert any(step.get("uses") == "docker/login-action@v3" for step in steps)
    metadata = next(step for step in steps if step.get("id") == "metadata")
    assert "type=raw,value=${{ github.sha }}" in metadata["with"]["tags"]
    push = next(step for step in steps if step.get("id") == "push")
    assert push["with"]["push"] is True
    assert push["with"]["platforms"] == "linux/amd64"
    assert push["with"]["provenance"] == "mode=max"
    assert push["with"]["sbom"] is True
