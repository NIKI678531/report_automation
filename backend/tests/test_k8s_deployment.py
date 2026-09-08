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
    documents = resources(environment)
    identities = {(doc["kind"], doc["metadata"]["name"]) for doc in documents}
    assert len(identities) == len(documents) == 7
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
            assert not {"DATABASE_URL", "REDIS_URL", "DOWNLOAD_SECRET", "S3_SECRET_ACCESS_KEY", "FMP_API_KEY", "DA_REPORT_OBJECT_URL"} & doc["data"].keys()
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
    assert (backend["AUTH_MODE"], backend["STORAGE_BACKEND"], backend["ALLOW_TESTING_LANE"]) == ("ENTRA", "S3", "false")
    assert backend["S3_PREFIX"].endswith(f"/{environment}")
    assert web["API_UPSTREAM"] == f"{base}-srvapp:8000"
    assert web["NGINX_ENVSUBST_FILTER"] == "^(API_UPSTREAM|SERVER_NAME)$"


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
            assert not container["image"].endswith(":latest")
            assert not container.get("command"), "Kubernetes must preserve the image's tini and startup guard."
            assert all(mount["name"] in volume_names for mount in container["volumeMounts"])
            assert {"cpu", "memory"} <= container["resources"]["requests"].keys()
            assert {"cpu", "memory"} <= container["resources"]["limits"].keys()
        for container in pod["containers"]:
            assert {"startupProbe", "readinessProbe", "livenessProbe"} <= container.keys()
        if is_backend:
            assert spec["strategy"]["type"] == "Recreate"
            assert [container["name"] for container in pod["containers"]] == ["srvapp", "worker"]
            migrate, = pod["initContainers"]
            api, worker = pod["containers"]
            assert migrate["args"] == ["python", "-m", "alembic", "upgrade", "head"]
            assert migrate["image"] == api["image"] == worker["image"]
            assert migrate["envFrom"] == api["envFrom"] == worker["envFrom"]
            assert api["readinessProbe"]["httpGet"]["path"] == "/api/v1/health"
            assert "--pidfile=/tmp/celery.pid" in worker["args"]
            assert "kill -0" in worker["readinessProbe"]["exec"]["command"][-1]
        else:
            assert pod["containers"][0]["readinessProbe"]["httpGet"]["path"] == "/healthz"


@pytest.mark.parametrize("environment", ACCOUNTS)
def test_ingress_and_secret_template_are_not_in_ordinary_apply_directory(environment):
    root = ROOT / "k8s" / environment
    ordinary = [doc for path in root.glob("*.yaml") for doc in yaml.safe_load_all(path.read_text(encoding="utf-8"))]
    assert all(doc["kind"] not in {"Ingress", "Secret"} for doc in ordinary)
    ingress = yaml.safe_load((root / "ingress" / "ingress.yaml").read_text(encoding="utf-8"))
    assert ingress["metadata"]["annotations"]["alb.ingress.kubernetes.io/scheme"] == "internal"
    assert f":{ACCOUNTS[environment]}:" in ingress["metadata"]["annotations"]["alb.ingress.kubernetes.io/certificate-arn"]
    rule, = ingress["spec"]["rules"]
    assert rule["host"]
    assert rule["http"]["paths"][0]["backend"]["service"]["name"] == f"ih-{environment}-remote-fund-cmt-auto-webapp"
    template = yaml.safe_load((root / "secret.example.yaml.txt").read_text(encoding="utf-8"))
    assert all(value == "" for value in template["stringData"].values())


def test_uat_and_prd_are_structurally_identical_without_corrupting_view_names():
    for path in manifest_paths("uat"):
        source = path.read_text(encoding="utf-8").replace(ACCOUNTS["uat"], ACCOUNTS["prd"]).replace("UAT", "PRD")
        normalized = re.sub(r"(?<![a-z])uat(?![a-z])", "prd", source)
        target = ROOT / "k8s" / "prd" / path.relative_to(ROOT / "k8s" / "uat")
        assert list(yaml.safe_load_all(normalized)) == list(yaml.safe_load_all(target.read_text(encoding="utf-8")))


@pytest.mark.parametrize("environment", ACCOUNTS)
def test_build_contexts_resolve_to_existing_shared_images(environment):
    path = ROOT / "deploy" / environment / "compose.build.yaml"
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