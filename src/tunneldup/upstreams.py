"""High-level upstream management: query a remote tunneld, register it
with the local one, print device picker. Used by `tunneldup add`/`remove`/
`upstreams`."""

from dataclasses import dataclass
from typing import Optional

import requests

from tunneldup.paths import TUNNELD_PORT

LOCAL_TUNNELD_URL = f"http://127.0.0.1:{TUNNELD_PORT}"


class UpstreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceEntry:
    udid: str
    tunnel_address: str
    tunnel_port: int
    interface: str

    @property
    def short_udid(self) -> str:
        return f"{self.udid[:8]}…{self.udid[-4:]}" if len(self.udid) > 14 else self.udid

    @property
    def transport(self) -> str:
        i = self.interface or ""
        if i.startswith("usbmux-"):
            return "usbmux"
        if "%en" in i or "ncm" in i.lower():
            return "usb-ncm"
        if "wifi" in i.lower() or "remotepairing" in i.lower():
            return "wifi"
        return i.split("-", 1)[0] or "?"


def fetch_devices(url: str, timeout: float = 3.0) -> list[DeviceEntry]:
    """GET / on a tunneld URL and flatten its response into a list."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise UpstreamError(f"could not reach tunneld at {url}: {e}") from e
    out: list[DeviceEntry] = []
    for udid, entries in (data or {}).items():
        for e in entries:
            out.append(
                DeviceEntry(
                    udid=udid,
                    tunnel_address=e.get("tunnel-address", ""),
                    tunnel_port=int(e.get("tunnel-port", 0)),
                    interface=e.get("interface", ""),
                )
            )
    return out


def register(upstream_url: str, local_url: Optional[str] = None, timeout: float = 3.0) -> None:
    local = local_url or LOCAL_TUNNELD_URL
    try:
        r = requests.post(f"{local}/upstream", json={"url": upstream_url}, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        raise UpstreamError(
            f"could not register {upstream_url} with local tunneld at {local}: {e}. "
            f"Is your local tunneld running? (`sudo pymobiledevice3 remote tunneld`)"
        ) from e


def unregister(upstream_url: str, local_url: Optional[str] = None, timeout: float = 3.0) -> None:
    local = local_url or LOCAL_TUNNELD_URL
    try:
        r = requests.delete(f"{local}/upstream", json={"url": upstream_url}, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        raise UpstreamError(f"could not deregister {upstream_url} from {local}: {e}") from e


def list_registered(local_url: Optional[str] = None, timeout: float = 3.0) -> list[str]:
    local = local_url or LOCAL_TUNNELD_URL
    try:
        r = requests.get(f"{local}/upstream", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise UpstreamError(f"could not list upstreams at {local}: {e}") from e


def parse_host_arg(host_arg: str, default_port: int = TUNNELD_PORT) -> str:
    """Accept any of: '1.2.3.4', '1.2.3.4:49151', 'http://host:port'.
    Returns a normalized 'http://host:port' URL."""
    s = host_arg.strip()
    if s.startswith(("http://", "https://")):
        return s.rstrip("/")
    if ":" in s and not s.startswith("["):
        # ipv4:port or host:port; we don't bother with bracketed ipv6 here
        return f"http://{s}"
    return f"http://{s}:{default_port}"
