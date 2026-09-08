import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
DOCKER = shutil.which("docker")
pytestmark = pytest.mark.skipif(DOCKER is None, reason="Docker CLI is required for Compose configuration checks; no daemon is needed.")


def deployment_environment():
    environment = os.environ.copy()
    for filename in ("compose.yaml", "deploy/vm/compose.vm-trial.yaml", "deploy/vm/compose.vm-production.yaml", "deploy/vm/compose.vm-build.yaml"):
        for name in re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", (ROOT / filename).read_text(encoding="utf-8")):
            environment.pop(name, None)
    environment.update({
        "API_IMAGE": "commentary-api:configuration-check",
        "WEB_IMAGE": "commentary-web:configuration-check",
        "BACKEND_BASE_IMAGE": "example.invalid/playwright:configuration-check",
        "PLAYWRIGHT_VERSION": "1.62.0",
        "NODE_BASE_IMAGE": "example.invalid/node:configuration-check",
        "NGINX_BASE_IMAGE": "example.invalid/nginx:configuration-check",
        "PUBLIC_HOST": "commentary.example.invalid",
        "PUBLIC_ORIGIN": "https://commentary.example.invalid",
        "DATABASE_URL": "mysql+pymysql://check:check@mysql.invalid/check?charset=utf8mb4",
        "REDIS_URL": "redis://redis.invalid:6379/0",
        "DOWNLOAD_SECRET": "configuration-check-only-not-a-real-secret",
        "ENTRA_TENANT_ID": "configuration-check",
        "ENTRA_AUDIENCE": "configuration-check",
        "S3_BUCKET": "configuration-check",
        "S3_ENDPOINT_URL": "https://storage.example.invalid",
        "S3_REGION": "configuration-check",
        "S3_ACCESS_KEY_ID": "configuration-check",
        "S3_SECRET_ACCESS_KEY": "configuration-check",
    })
    return environment


def compose_result(*files, environment=None, env_file="deploy/vm/.env.example"):
    command = [DOCKER, "compose", "--env-file", str(ROOT / env_file)]
    for filename in files:
        command.extend(["-f", str(ROOT / filename)])
    command.extend(["config", "--format", "json"])
    return subprocess.run(command, cwd=ROOT, env=environment or deployment_environment(), capture_output=True, text=True, timeout=30)


@pytest.fixture(scope="module")
def production():
    result = compose_result("deploy/vm/compose.vm-production.yaml")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_trial_replaces_public_port_and_shares_backend_image():
    result = compose_result("compose.yaml", "deploy/vm/compose.vm-trial.yaml", env_file=".env.example")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert set(services) == {"db", "redis", "api", "worker", "web"}
    assert len(services["web"]["ports"]) == 1
    assert services["web"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["web"]["ports"][0]["published"] == "18080"
    assert services["api"]["image"] == services["worker"]["image"]
    assert all(service["restart"] == "no" for service in services.values())


def test_production_uses_external_data_services_and_ephemeral_writes(production):
    assert set(production["services"]) == {"migrate", "api", "worker", "web"}
    assert not production.get("volumes")
    for name, service in production["services"].items():
        assert not service.get("volumes")
        assert service["read_only"] is True
        assert service["init"] is True
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["user"] == ("101:101" if name == "web" else "10001:10001")
        assert all("mode=1777" in mount and "size=" in mount for mount in service["tmpfs"])
        assert int(service["mem_limit"]) > 0
        assert float(service["cpus"]) > 0
        assert service["logging"]["options"] == {"max-file": "3", "max-size": "10m"}
        assert not service.get("build")
        if name != "web":
            assert not service.get("ports")
    ports = production["services"]["web"]["ports"]
    assert len(ports) == 1
    assert (ports[0]["host_ip"], ports[0]["published"], ports[0]["target"]) == ("127.0.0.1", "18081", 8080)


def test_backends_share_configuration_and_migration_precedes_workers(production):
    services = production["services"]
    assert services["api"]["environment"] == services["worker"]["environment"] == services["migrate"]["environment"]
    assert services["api"]["image"] == services["worker"]["image"] == services["migrate"]["image"]
    assert services["migrate"]["command"] == ["python", "-m", "alembic", "upgrade", "head"]
    assert services["migrate"]["restart"] == "no"
    for name in ("api", "worker"):
        assert services[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "/api/v1/health" in " ".join(services["api"]["healthcheck"]["test"])
    assert "$$HOSTNAME" in " ".join(services["worker"]["healthcheck"]["test"])
    assert "/healthz" in " ".join(services["web"]["healthcheck"]["test"])
    assert services["web"]["environment"]["NGINX_ENVSUBST_FILTER"] == "^(API_UPSTREAM|SERVER_NAME)$$"


def test_production_modes_cannot_be_downgraded_by_env_file():
    environment = deployment_environment()
    environment.update(AUTH_MODE="LOCAL", STORAGE_BACKEND="LOCAL", ALLOW_TESTING_LANE="true")
    result = compose_result("deploy/vm/compose.vm-production.yaml", environment=environment)
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)["services"]["api"]["environment"]
    assert settings["AUTH_MODE"] == "ENTRA"
    assert settings["STORAGE_BACKEND"] == "S3"
    assert settings["ALLOW_TESTING_LANE"] == "false"


@pytest.mark.parametrize("name", ["API_IMAGE", "WEB_IMAGE", "DATABASE_URL", "REDIS_URL", "DOWNLOAD_SECRET", "ENTRA_TENANT_ID", "ENTRA_AUDIENCE", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "PUBLIC_HOST", "PUBLIC_ORIGIN"])
def test_missing_required_configuration_refuses_compose(name):
    environment = deployment_environment()
    environment.pop(name)
    result = compose_result("deploy/vm/compose.vm-production.yaml", environment=environment)
    assert result.returncode != 0
    assert name in result.stderr


def test_build_uses_existing_vm_dockerfiles_and_same_release_images(production):
    result = compose_result("deploy/vm/compose.vm-build.yaml")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name in ("api", "web"):
        assert services[name]["image"] == production["services"][name]["image"]
        build = services[name]["build"]
        assert (Path(build["context"]) / build["dockerfile"]).is_file()