"""Offline Compose contract checks; never start services or use local credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKER = shutil.which("docker")
pytestmark = pytest.mark.skipif(DOCKER is None, reason="Docker CLI required; no daemon or service startup is used.")


def config(tmp_path, filename, secrets=None):
    content = yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))
    values = {"MYSQL_ROOT_PASSWORD": "offline-root", "MYSQL_PASSWORD": "offline-db", **(secrets or {})}
    env_path = tmp_path / ".env"
    env_path.write_text("DATABASE_URL=mysql+pymysql://user:literal$word@mysql/app?charset=utf8mb4\nDOWNLOAD_SECRET=literal$word with spaces#and=equals\n", encoding="utf-8")
    for service in content["services"].values():
        if "env_file" in service:
            service["env_file"][0]["path"] = str(env_path)
    path = tmp_path / "compose.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    # Supply an explicit empty interpolation file so nothing reads the developer's .env.
    interpolation = tmp_path / "empty.env"
    interpolation.touch()
    result = subprocess.run([DOCKER, "compose", "--env-file", str(interpolation), "-f", str(path), "config", "--format", "json"],
                            env={**os.environ, **values}, capture_output=True, text=True, timeout=30)
    return result


def test_local_compose_preserves_literal_secrets_and_migration_order(tmp_path):
    result = config(tmp_path, "compose.yaml")
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    services = document["services"]
    assert set(services) == {"mysql", "migrate", "srvapp", "webapp"}
    assert not document.get("volumes")
    for name in ("srvapp", "migrate"):
        service = services[name]
        # Compose serializes literal $ as $$ so its rendered model can be re-used as YAML.
        assert service["environment"]["DOWNLOAD_SECRET"].replace("$$", "$") == "literal$word with spaces#and=equals"
        assert "literal$word" in service["environment"]["DATABASE_URL"].replace("$$", "$")
        assert service["environment"]["TASK_MODE"] == "EAGER"
        assert "REDIS_URL" not in service["environment"]
        assert service["environment"]["AUTH_MODE"] == "REMOTE"
        assert "STORAGE_BACKEND" not in service["environment"]
        assert service["read_only"] is True
        assert not service.get("volumes")
        assert all("mode=1777" in mount for mount in service["tmpfs"])
        assert not service.get("ports")
    assert services["srvapp"]["environment"] == services["migrate"]["environment"]
    assert services["srvapp"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["migrate"]["command"] == ["python", "-m", "alembic", "upgrade", "head"]
    assert services["webapp"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["webapp"]["ports"][0]["target"] == 3030


@pytest.mark.parametrize("key", ["MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD"])
def test_local_compose_refuses_empty_database_password(tmp_path, key):
    result = config(tmp_path, "compose.yaml", {key: ""})
    assert result.returncode != 0
    assert key in result.stderr


@pytest.mark.parametrize("environment,account", [("uat", "978533598453"), ("prd", "449732370091")])
def test_ecr_builds_need_no_secrets_or_login_arguments(tmp_path, environment, account):
    result = config(tmp_path, f"docker-compose.{environment}.yml")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert set(services) == {"srvapp", "webapp"}
    for component, service in services.items():
        assert service["image"] == f"{account}.dkr.ecr.ap-east-1.amazonaws.com/ih-{environment}-remote-fund-cmt-auto-{component}:latest"
        assert not service.get("environment")
        assert not service["build"].get("args")
