# ruff: file-ignore[suspicious-subprocess-import, subprocess-without-shell-equals-true, start-process-with-partial-path]
"""#538, integration: ExactDocs on a Docker network whose only way out is a forward proxy.

Three networks: ``out`` (the internet: a stand-in serving a git repository, the Hugging Face Hub
and a model gateway, under names only Docker's DNS on that network knows), ``in`` (``--internal``:
ExactDocs and the proxy, no route out) and ``corp`` (``--internal``: ExactDocs and the company's
own git server and model gateway, which the proxy cannot reach). The proxy (Squid, pinned, asking
for credentials) is on ``out`` and ``in``.

ExactDocs runs from this checkout's own virtual environment and Python, mounted read-only into a
pinned Debian image with git, with ``HTTP(S)_PROXY`` (credentials in the URL) and ``NO_PROXY``
(the company's domain and its network's CIDR range) set. It pulls a model, checks an AI profile
outside (through the proxy) and one inside (by its address, in the CIDR range), checks again with
wrong proxy credentials, and imports the repository from outside and from inside through the
server's job worker (``exactdocs serve``). The proxy's access log then shows the outside hosts and
none of the inside ones; the inside ones answered, so they were reached directly.

Needs Docker and ``EXACTDOCS_TEST_PROXY_IMAGE`` (the Squid image; CI pins it in
``integration.yml``). ``EXACTDOCS_REQUIRE_PROXY=1`` turns a missing Docker into an error.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import integration
from fixture_repo import build

pytestmark = integration.PROXY

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "packages" / "exactdocs" / "tests" / "fixtures"
WORLD = str(FIXTURES / "proxy_world.py")
RUNTIME_IMAGE = (
    "buildpack-deps:trixie-scm"
    "@sha256:505da14ee66b95066dae9eb29490a243b66bd09d45766acc2e09a0099e1c4a7c"
)
"""Debian with git and curl, multi-arch: the checkout's Python runs in it (glibc)."""
PROXY_USER = "proxy-user"
LOGS = "/var/log/squid-test"
"""Where the proxy writes its logs, in its container (a folder of the test's, mounted)."""
SQUID_CONF = f"""\
http_port 3128
pid_filename none
cache_log stdio:{LOGS}/cache.log
access_log stdio:{LOGS}/access.log
cache deny all
shutdown_lifetime 1 seconds
auth_param basic program /usr/lib/squid/basic_ncsa_auth {LOGS}/passwords
auth_param basic realm exactdocs-test
acl authenticated proxy_auth REQUIRED
http_access allow authenticated
http_access deny all
"""
"""A forward proxy that asks for credentials and allows any host once given them."""
SQUID_START = (
    f'printf "%s:%s\\n" "$PROXY_USER" "$(openssl passwd -apr1 "$PROXY_PASS")" > {LOGS}/passwords'
    " && exec squid -N -f /etc/squid-test/squid.conf"
)


@dataclass(slots=True)
class Docker:
    """Runs the docker CLI and removes what it created."""

    tag: str
    """Prefix of every name."""
    containers: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)

    def __call__(self, *args: str, check: bool = True, timeout: float = 600) -> str:
        done = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
        if check and done.returncode != 0:
            message = f"docker {' '.join(args[:3])} failed: {done.stderr[-2000:]}"
            raise AssertionError(message)
        return done.stdout

    def network(self, name: str, *, internal: bool) -> str:
        full = f"{self.tag}-{name}"
        self("network", "create", *(["--internal"] if internal else []), full)
        self.networks.append(full)
        return full

    def start(self, name: str, *args: str) -> str:
        full = f"{self.tag}-{name}"
        self.containers.append(full)
        self("run", "-d", "--name", full, *args)
        return full

    def clean(self) -> None:
        for container in self.containers:
            self("rm", "-f", container, check=False)
        for network in self.networks:
            self("network", "rm", network, check=False)


@dataclass(frozen=True, slots=True)
class World:
    """What ExactDocs runs against."""

    inside: str
    """The internal network ExactDocs and the proxy share."""
    corp: str
    """The company's internal network, which the proxy is not on."""
    corp_ip: str
    """The company's server's address there."""
    corp_range: str
    """That network's CIDR range."""
    proxy_url: str
    """The proxy's URL, with its credentials."""
    access_log: Path
    """The proxy's access log, on this machine."""


def _docker_works() -> str | None:
    """Why Docker cannot be used here, or ``None`` when it can.

    Returns:
        The reason, or ``None``.
    """
    if shutil.which("docker") is None:
        return "no docker CLI"
    done = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)
    return None if done.returncode == 0 else "the Docker daemon does not answer"


@pytest.fixture
def docker() -> Iterator[Docker]:
    reason = _docker_works()
    if reason is not None:
        if os.environ.get("EXACTDOCS_REQUIRE_PROXY") == "1":
            pytest.fail(f"EXACTDOCS_REQUIRE_PROXY=1 but {reason}")
        pytest.skip(reason)
    python_home = Path(sys.base_prefix).resolve()
    if python_home.parts[:2] in {("/", "usr"), ("/", "bin")}:
        pytest.skip(f"Python lives in {python_home}, which cannot be mounted into a container")
    runner = Docker(tag=f"exd-proxy-{os.getpid()}-{secrets.token_hex(3)}")
    try:
        yield runner
    finally:
        runner.clean()


def _common() -> list[str]:
    """The options of every container that runs the checkout's Python.

    Returns:
        The ``docker run`` options: this user (files it writes stay deletable); the checkout,
        its virtual environment and its Python mounted read-only at the same paths; the
        fixtures on the path.
    """
    # The Python installations' folder, not just this one: the environment's interpreter is a
    # link through a version alias next to it (uv's ``cpython-3.14-...``).
    pythons = Path(sys.base_prefix).resolve().parent
    paths = dict.fromkeys([ROOT, Path(sys.prefix), pythons])
    return [
        "--user", f"{os.getuid()}:{os.getgid()}",
        *(option for path in paths for option in ("-v", f"{path}:{path}:ro")),
        "-e", "HOME=/tmp",
        "-e", f"PYTHONPATH={FIXTURES}",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
    ]  # fmt: skip


def _wait_for_the_proxy(network: str, proxy: str) -> None:
    """Wait until the proxy forwards to the outside stand-in (both just started).

    Args:
        network: The internal network the proxy serves.
        proxy: The proxy's URL, credentials included.

    Raises:
        AssertionError: It never did, within 90 seconds.
    """
    probe = "http://hub.outside.test:8002/api/models/acme/model"
    stderr = ""
    for _ in range(90):
        done = subprocess.run(
            ["docker", "run", "--rm", "--network", network, RUNTIME_IMAGE,
             "curl", "-fsS", "--max-time", "5", "-x", proxy, probe],
            capture_output=True, text=True, check=False, timeout=60,
        )  # fmt: skip
        if done.returncode == 0:
            return
        stderr = done.stderr
        time.sleep(1)
    message = f"the proxy never reached the outside stand-in: {stderr[-500:]}"
    raise AssertionError(message)


def _world(docker: Docker, folder: Path, password: str) -> World:
    """Start the networks, the two stand-ins and the proxy.

    Args:
        docker: The runner.
        folder: Room for the repositories, the proxy's configuration and its logs.
        password: The proxy's password.

    Returns:
        The world.
    """
    outside_repos, inside_repos = folder / "outside-repos", folder / "inside-repos"
    build(outside_repos / "outside" / "docs-repo")
    build(inside_repos / "corp" / "docs-repo")
    conf, logs = folder / "squid", folder / "squid-logs"
    conf.mkdir()
    logs.mkdir()
    logs.chmod(0o777)  # Squid writes its logs as its own user
    (conf / "squid.conf").write_text(SQUID_CONF, encoding="utf-8")
    python = str(Path(sys.executable))
    out = docker.network("out", internal=False)
    inside = docker.network("in", internal=True)
    corp = docker.network("corp", internal=True)
    docker.start(
        "outside", "--network", out,
        "--network-alias", "git.outside.test", "--network-alias", "hub.outside.test",
        "--network-alias", "llm.outside.test",
        *_common(), "-v", f"{outside_repos}:/srv/repos:ro",
        RUNTIME_IMAGE, python, WORLD, "serve", "/srv/repos",
    )  # fmt: skip
    company = docker.start(
        "corp", "--network", corp,
        "--network-alias", "git.corp.test", "--network-alias", "gateway.corp.test",
        *_common(), "-v", f"{inside_repos}:/srv/repos:ro",
        RUNTIME_IMAGE, python, WORLD, "serve", "/srv/repos",
    )  # fmt: skip
    proxy = docker.start(
        "proxy", "--network", out,
        "-v", f"{conf}:/etc/squid-test:ro", "-v", f"{logs}:{LOGS}",
        "-e", f"PROXY_USER={PROXY_USER}", "-e", f"PROXY_PASS={password}",
        "--entrypoint", "sh", os.environ[integration.PROXY_IMAGE], "-c", SQUID_START,
    )  # fmt: skip
    docker("network", "connect", "--alias", "proxy.test", inside, proxy)
    proxy_url = f"http://{PROXY_USER}:{password}@proxy.test:3128"
    _wait_for_the_proxy(inside, proxy_url)
    address = f'{{{{(index .NetworkSettings.Networks "{corp}").IPAddress}}}}'
    subnet = "{{(index .IPAM.Config 0).Subnet}}"
    return World(
        inside=inside,
        corp=corp,
        corp_ip=docker("inspect", "-f", address, company).strip(),
        corp_range=docker("network", "inspect", "-f", subnet, corp).strip(),
        proxy_url=proxy_url,
        access_log=logs / "access.log",
    )


def _drill(docker: Docker, world: World, data: Path) -> dict[str, Any]:
    """Run ExactDocs' side on the internal networks, with the outbound settings.

    Args:
        docker: The runner.
        world: The world.
        data: ExactDocs' data folder.

    Returns:
        What the drill printed.
    """
    drill = f"{docker.tag}-exactdocs"
    docker.containers.append(drill)
    docker(
        "create", "--name", drill, "--network", world.inside, *_common(),
        "-v", f"{data}:/data",
        "-e", f"HTTPS_PROXY={world.proxy_url}", "-e", f"HTTP_PROXY={world.proxy_url}",
        "-e", f"NO_PROXY=.corp.test,{world.corp_range}",
        "-e", "HF_ENDPOINT=http://hub.outside.test:8002",
        "-e", "EXACTDOCS_MODELS_DIR=/data/models",
        "-e", f"DRILL_CORP_GATEWAY=http://{world.corp_ip}:8003/v1",
        "-e", f"DRILL_WRONG_PROXY=http://{PROXY_USER}:wrong-pass@proxy.test:3128",
        RUNTIME_IMAGE, str(Path(sys.executable)), WORLD, "drill",
    )  # fmt: skip
    docker("network", "connect", world.corp, drill)
    output = docker("start", "-a", drill, timeout=900)
    return json.loads(output.strip().splitlines()[-1])


def test_exactdocs_behind_a_proxy_reaches_out_only_through_it(
    docker: Docker, tmp_path: Path
) -> None:
    password = secrets.token_hex(12)
    world = _world(docker, tmp_path, password)
    data = tmp_path / "data"
    data.mkdir()

    found = _drill(docker, world, data)

    access = world.access_log.read_text(encoding="utf-8")
    assert password not in json.dumps(found), "a proxy password was shown"
    assert found["pull"]["code"] == 0, found["pull"]["out"]
    assert "BAAI/bge-small-en-v1.5: ok" in found["pull"]["out"]
    assert found["ai"]["code"] == 0, found["ai"]["out"]
    assert "llm: ok  outside:m" in found["ai"]["out"]
    assert "embedding: ok  corp:e" in found["ai"]["out"]
    refused = found["ai_wrong_credentials"]
    assert refused["code"] != 0
    assert (
        "the proxy http://***@proxy.test:3128 wants credentials to reach llm.outside.test:8003"
        in refused["out"]
    ), refused["out"]
    assert "wrong-pass" not in refused["out"]
    assert found["import_outside"]["state"] == "succeeded", found
    assert found["import_inside"]["state"] == "succeeded", found
    for host in ("git.outside.test:8001", "hub.outside.test:8002", "llm.outside.test:8003"):
        assert host in access, access
    assert "corp.test" not in access  # NO_PROXY by name: never sent to the proxy
    assert world.corp_ip not in access  # NO_PROXY by CIDR range
