"""``exactdocs admin create``: clear messages and a non-zero exit, never a traceback."""

import io

import pytest

from exactdocs.bootstrap import cli
from exactdocs.identity.adapters.driven.memory import InMemoryFailedSignInLog

GOOD = "correct horse battery staple"


def run(monkeypatch: pytest.MonkeyPatch, stdin: str, *args: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    cli.app(["admin", "create", *args], exit_on_error=False, result_action="return_value")


def refused(monkeypatch: pytest.MonkeyPatch, stdin: str, *args: str) -> str:
    with pytest.raises(SystemExit) as raised:
        run(monkeypatch, stdin, *args)
    assert isinstance(raised.value.code, str), "a non-zero exit with a message"
    return raised.value.code


def test_creates_the_admin_then_refuses_a_second(monkeypatch: pytest.MonkeyPatch) -> None:
    run(monkeypatch, GOOD + "\n", "--username", "ada", "--password-stdin")

    message = refused(monkeypatch, GOOD + "\n", "--username", "bob", "--password-stdin")

    assert "already set up" in message
    assert GOOD not in message


def test_without_a_terminal_or_stdin_it_says_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    for args in (["--username", "ada", "--password-stdin"], ["--username", "ada"], []):
        message = refused(monkeypatch, "", *args)

        assert "--password-stdin" in message


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_a_password_outside_the_bounds_names_both_bounds(
    monkeypatch: pytest.MonkeyPatch, password: str
) -> None:
    message = refused(monkeypatch, password + "\n", "--username", "ada", "--password-stdin")

    assert "12 to 1024 characters" in message
    assert password not in message


def reset(monkeypatch: pytest.MonkeyPatch, stdin: str, *args: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    cli.app(["admin", "reset-password", *args], exit_on_error=False, result_action="return_value")


def test_reset_password_changes_the_password_and_never_prints_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run(monkeypatch, GOOD + "\n", "--username", "ada", "--password-stdin")
    new = "a brand new passphrase"

    reset(monkeypatch, new + "\n", "--username", "Ada", "--password-stdin")

    out, err = capsys.readouterr()
    assert "Password of 'ada' changed" in out  # the stored name, as `admin create` prints it
    assert new not in out + err
    assert GOOD not in out + err
    assert "warning" not in err  # the throttle was cleared: nothing to add


async def _busy(_log: InMemoryFailedSignInLog, _key: str) -> bool:
    return False


async def _broken(_log: InMemoryFailedSignInLog, _key: str) -> bool:
    message = "connection lost"
    raise OSError(message)


@pytest.mark.parametrize("method", ["forget", "forget_remembered"])
@pytest.mark.parametrize(("forget", "cause"), [(_busy, "was busy"), (_broken, "failed")])
def test_reset_password_warns_when_the_throttle_was_not_cleared(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    method: str,
    forget: object,
    cause: str,
) -> None:
    run(monkeypatch, GOOD + "\n", "--username", "ada", "--password-stdin")
    monkeypatch.setattr(InMemoryFailedSignInLog, method, forget)

    reset(monkeypatch, "a brand new passphrase\n", "--username", "ada", "--password-stdin")

    out, err = capsys.readouterr()
    assert "Password of 'ada' changed; all its sessions ended." in out
    assert f"the password was changed, but the sign-in throttle {cause}" in err
    assert "count or the addresses it remembers for this username" in err
    assert "Run the command again to retry (that is safe)" in err
    assert "Retry-After" in err
    assert "Traceback" not in err


def test_reset_password_of_an_unknown_account_names_the_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run(monkeypatch, GOOD + "\n", "--username", "ada", "--password-stdin")

    with pytest.raises(SystemExit) as raised:
        reset(monkeypatch, GOOD + "\n", "--username", "nobody", "--password-stdin")

    assert "no account" in str(raised.value.code)


def test_reset_password_refuses_a_short_password_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run(monkeypatch, GOOD + "\n", "--username", "ada", "--password-stdin")

    with pytest.raises(SystemExit) as raised:
        reset(monkeypatch, "short\n", "--username", "ada", "--password-stdin")

    assert "12 to 1024 characters" in str(raised.value.code)
    assert "short\n" not in str(raised.value.code)


def test_serve_without_git_fails_fast_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")

    with pytest.raises(SystemExit) as raised:
        cli.app(["serve"], exit_on_error=False, result_action="return_value")

    assert "git is not installed" in str(raised.value.code)


def test_serve_runs_one_process_even_when_web_concurrency_asks_for_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Jobs, their recovery and the tag lock assume one process (docs/architecture.md)."""
    started: dict[str, object] = {}
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setattr(cli, "_check_startup", lambda _settings: None)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_args, **kwargs: started.update(kwargs))

    cli.app(["serve"], exit_on_error=False, result_action="return_value")

    assert started["workers"] == 1
    assert started["timeout_graceful_shutdown"] is None


def test_serve_on_postgresql_lets_web_concurrency_decide_and_bounds_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On PostgreSQL each worker is a process of its own (#103); a stop must not hang."""
    started: dict[str, object] = {}
    monkeypatch.setenv("EXACTDOCS_DATABASE_URL", "postgresql://u:p@db/x")
    monkeypatch.setattr(cli, "_check_startup", lambda _settings: None)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_args, **kwargs: started.update(kwargs))

    cli.app(["serve"], exit_on_error=False, result_action="return_value")

    assert started["workers"] is None  # uvicorn reads WEB_CONCURRENCY
    assert started["timeout_graceful_shutdown"] == 30
