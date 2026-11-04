"""``exactdocs admin create``: clear messages and a non-zero exit, never a traceback."""

import io

import pytest

from exactdocs.bootstrap import cli

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

    out = capsys.readouterr().out
    assert "'Ada'" in out
    assert new not in out
    assert GOOD not in out


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
