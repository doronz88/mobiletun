"""Thin wrappers around `wg-quick` + sysctl. macOS-flavoured."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Search homebrew paths too — under `sudo` macOS strips PATH down to
# /usr/bin:/bin:/usr/sbin:/sbin so shutil.which can't find wg-quick at
# /opt/homebrew/bin or /usr/local/bin.
_EXTRA_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/local/sbin")


def _log(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}", file=sys.stderr)


def _resolve(tool: str) -> str | None:
    p = shutil.which(tool)
    if p:
        return p
    for d in _EXTRA_PATHS:
        cand = Path(d) / tool
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def require_tools() -> None:
    missing = [t for t in ("wg", "wg-quick") if _resolve(t) is None]
    if missing:
        raise RuntimeError(
            f"missing tools: {missing}; install with: brew install wireguard-tools wireguard-go "
            f"(searched PATH + {', '.join(_EXTRA_PATHS)})"
        )


def require_root() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("must run as root (sudo); WireGuard needs privileges")


def up(conf_path: Path) -> None:
    cmd = [_resolve("wg-quick") or "wg-quick", "up", str(conf_path)]
    _log(cmd)
    subprocess.run(cmd, check=True)


def down(conf_path: Path) -> None:
    """Tear down a WG interface. Quiet about 'is not a WireGuard interface' —
    that just means the interface already wasn't up (defensive double-down,
    stale state files, etc.), not an error worth showing the user. Cleans
    up the stale .name state file so the next `up` starts clean."""
    cmd = [_resolve("wg-quick") or "wg-quick", "down", str(conf_path)]
    _log(cmd)
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode == 0:
        return
    stderr = (result.stderr or "").strip()
    if "is not a WireGuard interface" in stderr:
        stale = Path("/var/run/wireguard") / (Path(conf_path).stem + ".name")
        try:
            stale.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return
    # Real error — surface it.
    if stderr:
        print(stderr, file=sys.stderr)
    if result.stdout:
        print(result.stdout, file=sys.stderr)


def enable_forwarding() -> None:
    for k in ("net.inet6.ip6.forwarding=1", "net.inet.ip.forwarding=1"):
        cmd = ["sysctl", "-w", k]
        _log(cmd)
        subprocess.run(cmd, check=True)


def _detect_lan_ip() -> str | None:
    """Pick a non-loopback IPv4 address from a UP, non-utun interface — the
    one a peer on the same LAN can dial. Prefers private (192.168/16.../10.)
    ranges so we don't accidentally hand out a CGNAT or carrier-assigned addr."""
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    private_prefixes = ("10.", "192.168.")

    def _is_private(ip: str) -> bool:
        return ip.startswith(private_prefixes) or any(ip.startswith(f"172.{i}.") for i in range(16, 32))

    candidates: list[tuple[bool, str]] = []  # (is_private, ip)
    iface = None
    iface_up = False
    for line in out.splitlines():
        if line and not line.startswith("\t"):
            iface = line.split(":", 1)[0]
            iface_up = "UP," in line or "UP>" in line
            continue
        if not iface_up or iface is None:
            continue
        if iface.startswith(("lo", "utun", "feth", "stf", "gif", "anpi", "ap", "awdl", "llw", "bridge")):
            continue
        stripped = line.strip()
        if stripped.startswith("inet ") and "127.0.0.1" not in stripped:
            ip = stripped.split()[1]
            candidates.append((_is_private(ip), ip))

    candidates.sort(key=lambda x: not x[0])  # private first
    return candidates[0][1] if candidates else None


def detect_public_endpoint() -> str:
    """Pick an endpoint the WireGuard client will dial. Order:
    1. TUNNELDUP_ENDPOINT / WG_ENDPOINT env var (explicit override).
    2. A LAN IP if one is available — covers the common case of two
       machines on the same network (no NAT/port-forwarding needed).
    3. The public WAN IP via ifconfig.me as a last resort (requires
       the user to forward UDP/51820 on their router to reach it).
    """
    for env in ("TUNNELDUP_ENDPOINT", "WG_ENDPOINT"):
        v = os.environ.get(env)
        if v:
            return v
    lan = _detect_lan_ip()
    if lan:
        return lan
    try:
        out = subprocess.run(
            ["curl", "-fsS", "-4", "--max-time", "5", "https://ifconfig.me"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if out:
            return out
    except Exception:
        pass
    return "REPLACE_ME.example.com"
