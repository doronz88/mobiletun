"""Remote-side orchestration: bring up WireGuard, register the host's
tunneld as an upstream of the local tunneld via REST, deregister on exit."""

import signal
import sys
import time
from pathlib import Path

import requests

from tunneldup import paths, wg
from tunneldup.paths import SERVER_TUNNELD_IP, TUNNELD_PORT

LOCAL_TUNNELD_URL = f"http://127.0.0.1:{TUNNELD_PORT}"
DEFAULT_UPSTREAM_URL = f"http://{SERVER_TUNNELD_IP}:{TUNNELD_PORT}"


def install_client_conf(src: Path) -> Path:
    """Copy `src` into the canonical CLIENT_CONF location and lock it down.
    CLIENT_CONF is resolved via the `paths` module at call time so tests can
    monkeypatch `paths.CLIENT_CONF` without surprise writes to the real path."""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"config not found: {src}")
    paths.ensure_cfg_dir()
    dest = paths.CLIENT_CONF
    if src.resolve() != dest.resolve():
        dest.write_bytes(src.read_bytes())
        dest.chmod(0o600)
    return dest


def setup_client(conf: Path) -> None:
    wg.require_tools()
    wg.require_root()
    installed = install_client_conf(conf)
    wg.down(installed)
    wg.up(installed)


def _wait_for_tunneld(local_url: str = LOCAL_TUNNELD_URL, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{local_url}/hello", timeout=1)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def register_upstream(upstream_url: str = DEFAULT_UPSTREAM_URL, local_url: str = LOCAL_TUNNELD_URL) -> None:
    r = requests.post(f"{local_url}/upstream", json={"url": upstream_url}, timeout=3)
    r.raise_for_status()


def deregister_upstream(upstream_url: str = DEFAULT_UPSTREAM_URL, local_url: str = LOCAL_TUNNELD_URL) -> None:
    try:
        r = requests.delete(f"{local_url}/upstream", json={"url": upstream_url}, timeout=3)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[tunneldup] could not deregister upstream {upstream_url}: {e}", file=sys.stderr)


def run_lifecycle(upstream_url: str = DEFAULT_UPSTREAM_URL, local_url: str = LOCAL_TUNNELD_URL) -> None:
    """Blocking. Waits for local tunneld, registers upstream, then sleeps until
    SIGINT/SIGTERM. Always deregisters on the way out."""
    if not _wait_for_tunneld(local_url):
        raise RuntimeError(
            f"local tunneld at {local_url} did not respond within 30s. "
            "Start it first: `sudo pymobiledevice3 remote tunneld`."
        )

    register_upstream(upstream_url, local_url)
    print(f"[tunneldup] registered upstream {upstream_url} -> {local_url}", file=sys.stderr)

    def _shutdown(*_):
        raise KeyboardInterrupt

    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, _shutdown)

    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        deregister_upstream(upstream_url, local_url)
        print("[tunneldup] deregistered upstream", file=sys.stderr)


def teardown_client() -> None:
    if paths.CLIENT_CONF.exists():
        wg.down(paths.CLIENT_CONF)
