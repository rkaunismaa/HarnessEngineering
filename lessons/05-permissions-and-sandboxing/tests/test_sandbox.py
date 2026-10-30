import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from agent.sandbox import SandboxConfig, build_bwrap_argv, sandbox_available
from agent.tools import make_default_tools
from agent.tools.shell import run_shell
from agent.workspace import Workspace


def sandboxed(tmp_path, **cfg):
    return Workspace(tmp_path, sandbox=SandboxConfig(**cfg))


def bash(ws, command, timeout=10):
    return make_default_tools(ws).dispatch("bash", json.dumps({"command": command,
                                                               "timeout": timeout}))


def test_config_defaults():
    cfg = SandboxConfig()
    assert cfg.enabled is True
    assert cfg.network is False
    assert cfg.extra_writable == []
    assert SandboxConfig().extra_writable is not cfg.extra_writable


def test_workspace_sandbox_default_none(tmp_path):
    assert Workspace(tmp_path).sandbox is None


def test_argv_exact():
    cfg = SandboxConfig(extra_writable=[Path("/home/u/.cache/pip"), Path("/opt/x")])
    argv = build_bwrap_argv("pytest -q", Path("/work/proj/sub"), Path("/work/proj"), cfg)
    assert argv == [
        "bwrap", "--unshare-all",
        "--die-with-parent", "--new-session",
        "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
        "--tmpfs", "/tmp", "--tmpfs", "/run", "--bind", "/work/proj", "/work/proj",
        "--bind", "/home/u/.cache/pip", "/home/u/.cache/pip",
        "--bind", "/opt/x", "/opt/x",
        "--unsetenv", "DBUS_SESSION_BUS_ADDRESS", "--unsetenv", "SSH_AUTH_SOCK",
        "--unsetenv", "XDG_RUNTIME_DIR",
        "--chdir", "/work/proj/sub", "--", "bash", "-c", "pytest -q",
    ]


def test_argv_network_flag():
    root = Path("/work/proj")
    off = build_bwrap_argv("ls", root, root, SandboxConfig())
    on = build_bwrap_argv("ls", root, root, SandboxConfig(network=True))
    assert "--share-net" not in off
    assert on[:3] == ["bwrap", "--unshare-all", "--share-net"]
    assert [a for a in on if a != "--share-net"] == off


def test_tmpfs_before_root_bind():
    root = Path("/tmp/pytest-of-u/proj")
    argv = build_bwrap_argv("ls", root, root, SandboxConfig())
    tmp = argv.index("/tmp")
    bind = argv.index("--bind")
    assert argv[tmp - 1] == "--tmpfs"
    assert argv[bind + 1:bind + 3] == [str(root), str(root)]
    assert tmp < bind


@pytest.mark.parametrize("bad", ["/run/user/1000/proj", "/var/run/x", "/run"])
def test_paths_under_run_refused(bad):
    with pytest.raises(ValueError):
        build_bwrap_argv("ls", Path(bad), Path(bad), SandboxConfig())
    with pytest.raises(ValueError):
        build_bwrap_argv("ls", Path("/w"), Path("/w"),
                         SandboxConfig(extra_writable=[Path(bad)]))


def test_command_is_one_argument():
    root = Path("/work/proj")
    command = "echo 'a b' && ls -- \"$HOME\""
    argv = build_bwrap_argv(command, root, root, SandboxConfig())
    assert argv[-4:] == ["--", "bash", "-c", command]


def test_disabled_sandbox_runs_plain(tmp_path):
    # enabled=False must not go through bwrap: writing next to the project works
    root = tmp_path / "proj"
    root.mkdir()
    ws = Workspace(root, sandbox=SandboxConfig(enabled=False))
    assert run_shell(ws, "echo plain > ../sibling.txt && echo ok", 10) == (0, "ok\n")
    assert (tmp_path / "sibling.txt").read_text() == "plain\n"


def test_run_shell_plain(tmp_path):
    ws = Workspace(tmp_path)
    assert run_shell(ws, "echo hi; exit 4", 10) == (4, "hi\n")
    code, out = run_shell(ws, "echo start; sleep 10", 1)
    assert code is None
    assert "start" in out


def test_sandbox_available_returns_bool():
    assert isinstance(sandbox_available(), bool)


# --- real bubblewrap --------------------------------------------------------

@pytest.mark.sandbox
def test_real_sandbox_available():
    assert sandbox_available() is True


@pytest.mark.sandbox
def test_real_write_inside_ok(tmp_path):
    ws = sandboxed(tmp_path)
    result = bash(ws, "echo made > inside.txt && cat inside.txt && pwd")
    assert result == f"made\n{tmp_path.resolve()}\n\n[exit code: 0]"
    assert (tmp_path / "inside.txt").read_text() == "made\n"


@pytest.mark.sandbox
def test_real_write_outside_blocked(tmp_path):
    probe = Path.home() / ".harness_sandbox_probe"
    probe.unlink(missing_ok=True)
    ws = sandboxed(tmp_path)
    code, out = run_shell(ws, f"echo x > {probe}", 10)
    assert code != 0
    assert "Read-only file system" in out
    assert not probe.exists()


@pytest.mark.sandbox
def test_real_tmp_is_private(tmp_path):
    # /tmp inside the sandbox is a throwaway tmpfs: writes there succeed but never
    # reach the real /tmp, even right next to a project that lives under /tmp
    root = tmp_path / "proj"
    root.mkdir()
    ws = sandboxed(root)
    code, out = run_shell(ws, f"echo x > {tmp_path}/sibling.txt && cat {tmp_path}/sibling.txt", 10)
    assert (code, out) == (0, "x\n")
    assert not (tmp_path / "sibling.txt").exists()


@pytest.mark.sandbox
def test_real_extra_writable(tmp_path):
    root = tmp_path / "proj"
    extra = tmp_path / "cache"
    root.mkdir()
    extra.mkdir()
    ws = Workspace(root, sandbox=SandboxConfig(extra_writable=[extra]))
    code, out = run_shell(ws, f"echo x > {extra}/c.txt", 10)
    assert code == 0, out
    assert (extra / "c.txt").read_text() == "x\n"


NET_PROBE = ("python3 -c \"import socket; s = socket.socket(); s.settimeout(2); "
             "s.connect(('127.0.0.1', 1234)); print('CONNECTED')\"")


@pytest.mark.sandbox
def test_real_no_network(tmp_path):
    ws = sandboxed(tmp_path)
    code, out = run_shell(ws, NET_PROBE, 10)
    assert code != 0
    assert "CONNECTED" not in out


@pytest.mark.sandbox
@pytest.mark.live
def test_real_network_allowed(tmp_path):
    # needs a server on 127.0.0.1:1234 (LM Studio), hence also live
    ws = sandboxed(tmp_path, network=True)
    code, out = run_shell(ws, NET_PROBE, 10)
    assert (code, out) == (0, "CONNECTED\n")


@pytest.mark.sandbox
def test_real_root_under_tmp_visible(tmp_path):
    assert str(tmp_path.resolve()).startswith("/tmp/")
    (tmp_path / "seen.txt").write_text("visible\n")
    ws = sandboxed(tmp_path)
    assert bash(ws, "cat seen.txt") == "visible\n\n[exit code: 0]"


@pytest.mark.sandbox
def test_real_timeout_kills_sandboxed_command(tmp_path):
    ws = sandboxed(tmp_path)
    start = time.monotonic()
    result = bash(ws, "echo start; sleep 30", timeout=1)
    assert time.monotonic() - start < 5
    assert "start" in result
    assert "[timed out after 1s]" in result


@pytest.mark.sandbox
def test_real_exit_code_passes_through(tmp_path):
    ws = sandboxed(tmp_path)
    assert bash(ws, "echo hi; exit 3") == "hi\n\n[exit code: 3]"


# --- escapes the review found: host sockets and leftover processes ------------

def _socket_probe(path):
    return ("python3 -c \"import socket, sys; s = socket.socket(socket.AF_UNIX); "
            f"s.settimeout(2); s.connect('{path}'); print('CONNECTED')\"")


@pytest.mark.sandbox
def test_real_dbus_session_socket_unreachable(tmp_path):
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not address.startswith("unix:path="):
        pytest.skip("no D-Bus session socket path on this host")
    path = address[len("unix:path="):].split(",")[0]
    code, out = run_shell(sandboxed(tmp_path), _socket_probe(path), 10)
    assert code != 0
    assert "CONNECTED" not in out


@pytest.mark.sandbox
def test_real_docker_socket_hidden(tmp_path):
    if not Path("/var/run/docker.sock").exists():
        pytest.skip("no docker socket on this host")
    code, out = run_shell(sandboxed(tmp_path),
                          "test -e /var/run/docker.sock && echo VISIBLE; "
                          + _socket_probe("/var/run/docker.sock"), 10)
    assert "VISIBLE" not in out
    assert "CONNECTED" not in out
    assert code != 0


@pytest.mark.sandbox
def test_real_host_socket_env_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/1000/ssh-agent.socket")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    code, out = run_shell(sandboxed(tmp_path),
                          'echo "[$SSH_AUTH_SOCK][$DBUS_SESSION_BUS_ADDRESS][$XDG_RUNTIME_DIR]"',
                          10)
    assert (code, out) == (0, "[][][]\n")


def _alive(marker):
    # match on the exact process name set with `exec -a`, so nothing else can match
    out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    return [line.split()[0] for line in out.splitlines()
            if line.split()[1:2] == [marker]]


def _cleanup(marker):
    for pid in _alive(marker):
        try:
            os.kill(int(pid), 9)
        except ProcessLookupError:
            pass


@pytest.mark.sandbox
def test_real_background_process_dies_with_call(tmp_path):
    marker = f"harness-l5-bg-{os.getpid()}"
    try:
        start = time.monotonic()
        code, out = run_shell(sandboxed(tmp_path),
                              f"(setsid bash -c 'exec -a {marker} sleep 30' &) ; echo started",
                              10)
        assert time.monotonic() - start < 5
        assert (code, out) == (0, "started\n")
        time.sleep(0.5)
        assert _alive(marker) == []
    finally:
        _cleanup(marker)


def test_plain_background_job_does_not_block(tmp_path):
    # without a sandbox a setsid'd child survives (nothing can stop that), but it must
    # not keep the call waiting on its open output pipe
    marker = f"harness-l5-plain-{os.getpid()}"
    try:
        start = time.monotonic()
        code, out = run_shell(Workspace(tmp_path),
                              f"(setsid bash -c 'exec -a {marker} sleep 30' &) ; echo started",
                              10)
        assert time.monotonic() - start < 5
        assert (code, out) == (0, "started\n")
    finally:
        _cleanup(marker)


def test_plain_background_job_in_group_is_killed(tmp_path):
    marker = f"harness-l5-grp-{os.getpid()}"
    try:
        start = time.monotonic()
        code, out = run_shell(Workspace(tmp_path),
                              f"bash -c 'exec -a {marker} sleep 30' & echo started", 10)
        assert time.monotonic() - start < 5
        assert (code, out) == (0, "started\n")
        time.sleep(0.5)
        assert _alive(marker) == []
    finally:
        _cleanup(marker)


@pytest.mark.sandbox
def test_real_systemd_run_fails(tmp_path):
    if shutil.which("systemd-run") is None:
        pytest.skip("systemd-run not installed")
    escaped = tmp_path.parent / f"harness-l5-escape-{os.getpid()}"
    root = tmp_path / "proj"
    root.mkdir()
    try:
        code, out = run_shell(
            sandboxed(root),
            f"systemd-run --user --wait --quiet touch {escaped}", 20)
        assert code != 0
        assert not escaped.exists()
    finally:
        escaped.unlink(missing_ok=True)
