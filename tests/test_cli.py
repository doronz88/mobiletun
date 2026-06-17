"""Tests for the top-level CLI surface (help text, subcommand registration).

Strips ANSI escape codes from help output because typer's Rich-based renderer
inserts color/bold styles between every option's leading `--` and the rest of
the name when CI=true / FORCE_COLOR=1 is set (which GitHub Actions does by
default). The literal `--flag` substring won't be in raw bytes there, but it
is in plain-text mode."""
import re

from typer.testing import CliRunner

from tunneldup.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(result_output: str) -> str:
    return _ANSI_RE.sub("", result_output)


def test_help_lists_all_subcommands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0, r.output
    out = _plain(r.output)
    for cmd in ("host", "client", "devices", "config", "web", "down", "add", "upstreams", "remove", "status"):
        assert cmd in out, f"missing subcommand {cmd!r} in help"


def test_devices_help():
    r = runner.invoke(app, ["devices", "--help"])
    assert r.exit_code == 0


def test_host_help_mentions_web_flag():
    r = runner.invoke(app, ["host", "--help"])
    assert r.exit_code == 0
    assert "--web" in _plain(r.output)


def test_client_help_mentions_conf():
    r = runner.invoke(app, ["client", "--help"])
    assert r.exit_code == 0
    assert "conf" in _plain(r.output).lower()
