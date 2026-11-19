"""Exercise browser setup at the external command boundary without modifying the host."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SETUP = ROOT / "e2e" / "install-chromium.sh"
FAKE_COMMAND = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import sys
import signal
import time

name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
state = pathlib.Path(os.environ["TEST_STATE"])
scenario = os.environ["TEST_SCENARIO"]
config = os.environ.get("APT_CONFIG")
with open(os.environ["TEST_CALLS"], "a") as log:
    log.write(json.dumps({"name": name, "args": args, "apt":
        pathlib.Path(config).read_text() if config else None}) + "\n")
if name == "pnpm":
    sys.exit(1 if scenario == "download-fails" else 0)
if name == "sudo":
    if scenario == "no-sudo":
        sys.exit(1)
    sys.exit(subprocess.run(args[1:], check=False).returncode)
if args[0] == "-p":
    print("/unused/playwright-cli.js")
elif "install-deps" in args:
    if scenario == "install-fails":
        sys.exit(1)
    if scenario == "installer-timeout":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        child = os.fork()
        if child:
            state.write_text(f"{os.getpid()} {child}")
        while True:
            time.sleep(1)
    state.touch()
else:
    sys.exit(0 if scenario == "warm" or
        (state.exists() and scenario != "still-broken") else 1)
"""


def _executable(name: str) -> str:
    executable = shutil.which(name)
    assert executable is not None, f"required CI tool missing: {name}"
    return executable


def _run(tmp_path: Path, scenario: str) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    commands = tmp_path / "bin"
    commands.mkdir()
    for name in ("pnpm", "node", "sudo"):
        executable = commands / name
        executable.write_text(FAKE_COMMAND)
        executable.chmod(0o755)
    if scenario == "installer-timeout":
        wrapper = commands / "timeout"
        wrapper.write_text("""#!/usr/bin/env python3
import os
import sys
args = sys.argv[1:]
if "install-deps" in args:
    args[0:2] = ["--kill-after=0.2s", "0.2s"]
os.execv(os.environ["TEST_TIMEOUT_BINARY"], ["timeout", *args])
""")
        wrapper.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    result = subprocess.run(
        [_executable("bash"), str(SETUP)],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "TEST_STATE": str(tmp_path / "ready"),
            "TEST_CALLS": str(calls),
            "TEST_SCENARIO": scenario,
            "TEST_TIMEOUT_BINARY": _executable("timeout"),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, [
        json.loads(line) for line in calls.read_text().splitlines()
    ] if calls.exists() else []


def test_working_browser_never_invokes_sudo_or_apt(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "warm")
    assert result.returncode == 0, result.stderr
    assert not any(call["name"] == "sudo" or "install-deps" in call["args"] for call in calls)
    assert "already works" in result.stdout


def test_cold_runner_installs_with_bounded_apt_then_probes_again(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "cold")
    assert result.returncode == 0, result.stderr
    installer = next(
        call for call in calls if "install-deps" in call["args"] and call["name"] == "node"
    )
    assert 'Acquire::http::Timeout "15"' in installer["apt"]
    assert 'Acquire::https::Timeout "15"' in installer["apt"]
    assert 'Acquire::Retries "1"' in installer["apt"]
    privileged = next(
        call for call in calls if call["name"] == "sudo" and "install-deps" in call["args"]
    )
    assert privileged["args"][0] == "-n"
    assert privileged["args"].index("timeout") < privileged["args"].index("install-deps")
    assert "180s" in privileged["args"]
    assert "--kill-after=10s" in privileged["args"]
    probes = [
        call
        for call in calls
        if call["name"] == "node"
        and any(arg.endswith("probe-chromium.cjs") for arg in call["args"])
    ]
    assert len(probes) == 2
    apt_path = next(
        arg.removeprefix("APT_CONFIG=")
        for arg in privileged["args"]
        if arg.startswith("APT_CONFIG=")
    )
    assert not Path(apt_path).exists()


@pytest.mark.parametrize("scenario", ["install-fails", "still-broken", "no-sudo", "download-fails"])
def test_failed_setup_cannot_continue_to_e2e(tmp_path: Path, scenario: str) -> None:
    result, calls = _run(tmp_path, scenario)
    assert result.returncode != 0
    assert "::error::" in result.stderr
    if scenario == "download-fails":
        assert not any(call["name"] == "sudo" for call in calls)


def test_installer_deadline_kills_descendants_and_removes_apt_config(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, "installer-timeout")
    assert result.returncode != 0
    assert "exceeded 180 seconds" in result.stderr
    for pid in (tmp_path / "ready").read_text().split():
        status = Path(f"/proc/{pid}/stat")
        assert not status.exists() or status.read_text(encoding="utf-8").split()[2] == "Z"
    privileged = next(call for call in calls if call["name"] == "sudo")
    apt_path = next(
        arg.removeprefix("APT_CONFIG=")
        for arg in privileged["args"]
        if arg.startswith("APT_CONFIG=")
    )
    assert not Path(apt_path).exists()
