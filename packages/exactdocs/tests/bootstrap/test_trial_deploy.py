"""Exercise trial deployment boundaries without a Docker daemon or Cloudflare credentials."""

import os
import subprocess
import tempfile
from pathlib import Path


class TestTrialDeploy:
    def deploy(self, overrides: str = "", *, secrets: bool = True) -> tuple[int, str, str]:
        """Run the real shell script against isolated host-command fakes."""
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            if secrets:
                (state / "trial.env").write_text("EXACTDOCS_SECRET_KEY=" + "a" * 64 + "\n")
                (state / "admin-password").write_text("b" * 32)
            script = r"""
hostname() { echo dellpromaxgb10; }
docker() {
  printf '%s\n' "$*" >> "$ED_STATE_DIR/calls"
  case "$*" in
    'ps -a '*) return 0 ;;
    'container inspect '*) return 1 ;;
    'volume inspect '*) return 1 ;;
    'run --rm '*) echo 'created'; return 0 ;;
    'image ls '*) return 0 ;;
  esac
}
ss() { :; }
sleep() { :; }
curl() {
  case "$*" in
    *'/api/v1/session'*) echo '{"state":"signed_out"}' ;;
    *'/configurations'*) echo '{"success":true,"result":{"config":{
      "ingress":[{"service":"http_status:404"}]}}}' ;;
  esac
}
export -f hostname docker ss sleep curl
"""
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    script + overrides + "\nbash deploy/trial/deploy.sh " + "a" * 40,
                ],
                cwd=Path(__file__).resolve().parents[4],
                env={
                    **os.environ,
                    "ED_STATE_DIR": directory,
                    "CLOUDFLARE_API_TOKEN": "test",
                    "CLOUDFLARE_ACCOUNT_ID": "test",
                    "CLOUDFLARE_TUNNEL_ID": "test",
                    "CLOUDFLARE_ZONE_ID": "",
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            calls = (state / "calls").read_text() if (state / "calls").exists() else ""
            if secrets and result.returncode == 0:
                assert (
                    state / "trial.env"
                ).read_text() == "EXACTDOCS_SECRET_KEY=" + "a" * 64 + "\n"
                assert (state / "admin-password").read_text() == "b" * 32
                for name in ("trial.env", "admin-password"):
                    assert (state / name).stat().st_mode & 0o777 == 0o600
            return result.returncode, result.stderr, calls

    def test_direct_invocation_refuses_other_hosts_before_docker(self) -> None:
        code, error, calls = self.deploy("hostname() { echo other-host; }; export -f hostname")
        assert code != 0
        assert "dellpromaxgb10" in error
        assert not calls

    def test_existing_volume_requires_original_secret_files(self) -> None:
        code, error, calls = self.deploy(
            'docker() { echo "$*" >> "$ED_STATE_DIR/calls"; return 0; }; export -f docker',
            secrets=False,
        )
        assert code != 0
        assert "restore" in error
        assert "build" not in calls

    def test_unknown_session_state_is_not_routed(self) -> None:
        code, error, _ = self.deploy(
            """curl() { case "$*" in
            *'/api/v1/session'*) echo '{"state":"unexpected"}' ;;
            *'/configurations'*) echo '{"success":true,"result":{"config":{
      "ingress":[{"service":"http_status:404"}]}}}' ;;
            esac; }; export -f curl"""
        )
        assert code != 0
        assert "not routing" in error

    def test_signed_out_instance_deploys(self) -> None:
        code, error, calls = self.deploy()
        assert code == 0, error
        assert "--read-only" in calls
        assert "deployed" in error

    def test_foreign_container_is_not_replaced(self) -> None:
        code, error, calls = self.deploy(
            """docker() {
              echo "$*" >> "$ED_STATE_DIR/calls"
              case "$*" in
                'container inspect '*) return 0 ;;
                'volume inspect '*) return 1 ;;
              esac
            }; export -f docker"""
        )
        assert code != 0
        assert "unmanaged" in error
        assert "rm -f" not in calls
