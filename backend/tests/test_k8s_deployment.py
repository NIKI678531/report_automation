from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
ACCOUNTS = {"uat": "978533598453", "prd": "449732370091"}


def manifest_paths(environment):
    root = ROOT / "k8s" / environment
    return [*root.glob("*.yaml"), *root.joinpath("ingress").glob("*.yaml")]


def resources(environment):
    return [
        resource
        for path in manifest_paths(environment)
        for resource in yaml.safe_load_all(path.read_text(encoding="utf-8"))
    ]


@pytest.mark.parametrize("environment", ACCOUNTS)
def test_environment_resources_have_consistent_references(environment):
    documents = [doc for doc in resources(environment) if doc["kind"] != "Namespace"]
    identities = {(doc["kind"], doc["metadata"]["name"]) for doc in documents}
    assert len(identities) == len(documents) == 6
    names = {doc["metadata"]["name"]: doc for doc in documents if doc["kind"] == "ConfigMap"}
    deployments = [doc for doc in documents if doc["kind"] == "Deployment"]
    assert len(deployments) == 2
    assert {doc["metadata"]["namespace"] for doc in documents} == {"ih"}
    base = f"ih-{environment}-remote-fund-cmt-auto"
    for doc in documents:
        assert doc["metadata"]["labels"]["env"] == environment
        assert doc["metadata"]["labels"]["app"] == base
        assert doc["kind"] not in {"PersistentVolumeClaim", "PersistentVolume", "Namespace"}
        if doc["kind"] == "ConfigMap":
            assert all(isinstance(value, str) for value in doc["data"].values())
            assert not {"DATABASE_URL", "DA_REPORT_DATABASE_URL", "REDIS_URL", "DOWNLOAD_SECRET", "S3_SECRET_ACCESS_KEY", "FMP_API_KEY", "DA_REPORT_OBJECT_URL"} & doc["data"].keys()
    for deployment in deployments:
        selector = deployment["spec"]["selector"]["matchLabels"]
        assert selector.items() <= deployment["spec"]["template"]["metadata"]["labels"].items()
        service = next(doc for doc in documents if doc["kind"] == "Service" and doc["metadata"]["name"] == deployment["metadata"]["name"])
        assert service["spec"]["type"] == "ClusterIP"
        assert service["spec"]["selector"] == selector
        pod = deployment["spec"]["template"]["spec"]
        port_names = {port["name"] for container in pod["containers"] for port in container.get("ports", [])}
        assert all(port["targetPort"] in port_names for port in service["spec"]["ports"])
        for container in pod["containers"] + pod.get("initContainers", []):
            for source in container["envFrom"]:
                if "configMapRef" in source:
                    assert source["configMapRef"]["name"] in names
                else:
                    assert source["secretRef"]["name"] == f"{base}-srvapp-secret"
    backend = names[f"{base}-srvapp-config"]["data"]
    web = names[f"{base}-webapp-config"]["data"]
    assert (backend["AUTH_MODE"], backend["ALLOW_TESTING_LANE"]) == ("REMOTE", "false")
    assert backend["TASK_MODE"] == "EAGER"
    assert not any(key.startswith("S3_") or key == "STORAGE_BACKEND" for key in backend)
    assert web["API_UPSTREAM"] == f"{base}-srvapp:8000"
    assert not any(key.startswith("ENTRA_") for key in backend)


@pytest.mark.parametrize("environment", ACCOUNTS)
def test_two_deployments_have_hardened_pods_with_only_ephemeral_storage(environment):
    for doc in resources(environment):
        if doc["kind"] != "Deployment":
            continue
        spec = doc["spec"]
        pod = spec["template"]["spec"]
        is_backend = doc["metadata"]["labels"]["component"] == "srvapp"
        assert spec["replicas"] == 1
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        assert pod["securityContext"]["fsGroup"] == (10001 if is_backend else 101)
        assert all("emptyDir" in volume and "sizeLimit" in volume["emptyDir"] for volume in pod["volumes"])
        volume_names = {volume["name"] for volume in pod["volumes"]}
        for container in pod["containers"] + pod.get("initContainers", []):
            security = container["securityContext"]
            assert security["allowPrivilegeEscalation"] is False
            assert security["readOnlyRootFilesystem"] is True
            assert security["capabilities"]["drop"] == ["ALL"]
            assert container["imagePullPolicy"] == "Always"
            image_prefix = f"{ACCOUNTS[environment]}.dkr.ecr.ap-east-1.amazonaws.com/ih-{environment}-remote-fund-cmt-auto-"
            assert container["image"].startswith(image_prefix)
            assert container["image"].endswith(":latest")
            assert not container.get("command"), "Kubernetes must preserve the image's tini and startup guard."
            assert all(mount["name"] in volume_names for mount in container["volumeMounts"])
            assert {"cpu", "memory"} <= container["resources"]["requests"].keys()
            assert {"cpu", "memory"} <= container["resources"]["limits"].keys()
        for container in pod["containers"]:
            assert {"startupProbe", "readinessProbe", "livenessProbe"} <= container.keys()
        if is_backend:
            assert spec["strategy"]["type"] == "Recreate"
            assert [container["name"] for container in pod["containers"]] == ["srvapp"]
            migrate, = pod["initContainers"]
            api, = pod["containers"]
            assert migrate["args"] == ["python", "-m", "alembic", "upgrade", "head"]
            assert migrate["image"] == api["image"]
            assert migrate["envFrom"] == api["envFrom"]
            assert api["readinessProbe"]["httpGet"]["path"] == "/api/v1/health"
            assert pod["terminationGracePeriodSeconds"] >= 240
        else:
            assert pod["containers"][0]["readinessProbe"]["httpGet"]["path"] == "/healthz"
            assert pod["containers"][0]["ports"] == [{"name": "http", "containerPort": 3030}]
            service = next(item for item in resources(environment) if item["kind"] == "Service" and item["metadata"]["name"] == doc["metadata"]["name"])
            assert service["spec"]["ports"] == [{"name": "http", "port": 3030, "targetPort": "http"}]


@pytest.mark.parametrize("environment", ACCOUNTS)
def test_remote_application_has_no_ingress_or_live_secret_in_apply_directory(environment):
    documents = resources(environment)
    assert all(doc["kind"] not in {"Ingress", "Secret", "PersistentVolumeClaim"} for doc in documents)
    assert next(doc for doc in documents if doc["kind"] == "Namespace")["metadata"]["name"] == "ih"
    template = yaml.safe_load((ROOT / "k8s" / environment / "secret.example.yaml.txt").read_text(encoding="utf-8"))
    assert all(value == "" for value in template["stringData"].values())


def test_uat_and_prd_are_structurally_identical_without_corrupting_view_names():
    for path in manifest_paths("uat"):
        source = path.read_text(encoding="utf-8").replace(ACCOUNTS["uat"], ACCOUNTS["prd"]).replace("UAT", "PRD")
        normalized = re.sub(r"(?<![a-z])uat(?![a-z])", "prd", source)
        target = ROOT / "k8s" / "prd" / path.relative_to(ROOT / "k8s" / "uat")
        expected = list(yaml.safe_load_all(normalized))
        actual = list(yaml.safe_load_all(target.read_text(encoding="utf-8")))
        if path.name == "configmap.yaml":
            assert expected[0]["data"].pop("DA_REPORT_CACHE_DIR") == "/tmp/commentary-da"
            assert "DA_REPORT_CACHE_DIR" not in actual[0]["data"]
            # Only Production has been authorized to read the DA-Report RDS (ADR-0030).
            for key, value in {"DA_REPORT_MYSQL_SSL_CA": "/app/backend/app/integrations/certs/aws-rds-ap-east-1.pem",
                               "DA_REPORT_MYSQL_SSL_VERIFY_IDENTITY": "true", "DA_REPORT_TIMEOUT_SECONDS": "10"}.items():
                assert key not in expected[0]["data"]
                assert actual[0]["data"].pop(key) == value
        assert expected == actual


@pytest.mark.parametrize("environment", ACCOUNTS)
def test_build_contexts_resolve_to_existing_shared_images(environment):
    path = ROOT / f"docker-compose.{environment}.yml"
    services = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
    assert set(services) == {"srvapp", "webapp"}
    for name, service in services.items():
        assert service["image"].startswith(f"{ACCOUNTS[environment]}.dkr.ecr.ap-east-1.amazonaws.com/ih-{environment}-remote-fund-cmt-auto-{name}:")
        assert (path.parent / service["build"]["context"] / service["build"]["dockerfile"]).is_file()


def test_manifest_discovery_does_not_read_private_secret_files(tmp_path, monkeypatch):
    monkeypatch.setitem(manifest_paths.__globals__, "ROOT", tmp_path)
    root = tmp_path / "k8s" / "uat"
    (root / "secrets").mkdir(parents=True)
    (root / "secrets" / "secret.local.yaml").write_text("not valid: [private-value", encoding="utf-8")
    (root / "configmap.yaml").write_text("kind: ConfigMap\n", encoding="utf-8")
    assert resources("uat") == [{"kind": "ConfigMap"}]
