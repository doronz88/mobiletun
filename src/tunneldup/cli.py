"""tunneldup CLI — kept deliberately small.

tunneldup host                       # on the Mac with iPhone(s) attached
tunneldup client <client.conf>       # on the remote Mac
tunneldup web                        # browser UI on the host (auto-started by `host --web`)
tunneldup devices                    # list iPhones currently visible to this Mac
tunneldup add <host>                 # register a remote tunneld + pick a device
tunneldup upstreams                  # list registered upstream tunnelds
tunneldup remove <host>              # remove a remote tunneld
tunneldup config                     # print the generated client.conf
tunneldup down                       # tear down WireGuard on either side
"""

from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="VPN-bridge a USB-connected iPhone to a remote Mac.",
    pretty_exceptions_enable=False,
)


@app.command(
    help="Bring up WireGuard + tunneld bridge on the Mac with the iPhone (sudo). "
    "Run `pymobiledevice3 remote tunneld` separately."
)
def host(
    endpoint: Optional[str] = typer.Option(None, help="Public address clients will dial (default: autodetect)."),
    web: bool = typer.Option(False, "--web/--no-web", help="Also start the web UI."),
) -> None:
    from tunneldup import server
    from tunneldup import web as webmod
    from tunneldup.paths import SERVER_TUNNELD_IP, TUNNELD_PORT

    client_conf = server.setup_host(endpoint=endpoint)

    try:
        server.start_tunneld_bridge()
        typer.secho(
            f"tunneld bridge: {SERVER_TUNNELD_IP}:{TUNNELD_PORT} -> 127.0.0.1:{TUNNELD_PORT}",
            fg=typer.colors.CYAN,
            err=True,
        )
    except RuntimeError as e:
        typer.secho(f"warning: {e}", fg=typer.colors.YELLOW, err=True)
        typer.echo("(remote tunneld access via WG won't work until this is resolved)", err=True)
    typer.echo("")
    typer.secho(f"client config: {client_conf}", fg=typer.colors.GREEN, err=True)
    typer.echo(f"  scp {client_conf} remote-mac:", err=True)
    typer.echo("  remote: sudo tunneldup client client.conf", err=True)
    typer.echo("")
    typer.secho("In another shell on this Mac, start tunneld:", fg=typer.colors.YELLOW, err=True)
    typer.echo("  sudo pymobiledevice3 remote tunneld", err=True)
    typer.echo("")

    if web:
        webmod.run_web()
    else:
        typer.echo("WireGuard + tunneld bridge are up. Ctrl-C to tear down.", err=True)
        try:
            signal.pause()
        except KeyboardInterrupt:
            pass
        finally:
            typer.echo("tearing down...", err=True)
            server.teardown_host()


@app.command(
    help="Connect to a tunneldup host using its client.conf (sudo). "
    "Brings up WireGuard and registers the host's tunneld as an "
    "upstream of YOUR local tunneld via REST."
)
def client(conf: Path = typer.Argument(..., help="Path to client.conf produced by `tunneldup host`.")) -> None:
    from tunneldup import client as clientmod

    clientmod.setup_client(conf)
    typer.echo("")
    typer.secho(
        "VPN up. Your tunneld must be running (start with `sudo pymobiledevice3 remote tunneld`).",
        fg=typer.colors.GREEN,
        err=True,
    )
    typer.echo('  then in another shell: pymobiledevice3 lockdown info --tunnel ""', err=True)
    typer.echo("")
    try:
        clientmod.run_lifecycle()
    except RuntimeError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        clientmod.teardown_client()
        raise typer.Exit(code=2) from None
    finally:
        typer.echo("disconnecting...", err=True)
        clientmod.teardown_client()


@app.command(help="List iPhones currently reachable over USB (sudo).")
def devices() -> None:
    from tunneldup import discovery

    try:
        ds = discovery.discover()
    except discovery.DiscoveryError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None
    if not ds:
        typer.secho("(no USB iPhones detected)", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps([d.__dict__ for d in ds], indent=2))


@app.command(help="Print the client config (server side only).")
def config() -> None:
    from tunneldup.paths import CLIENT_CONF

    if not CLIENT_CONF.exists():
        typer.secho("no client config; run `tunneldup host` first", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(CLIENT_CONF.read_text())


@app.command(help="Run only the web UI (use `host --web` to combine).")
def web(
    host_ip: str = typer.Option("0.0.0.0", "--host", help="Bind address (default: all interfaces)."),
    port: Optional[int] = typer.Option(None, "--port"),
) -> None:
    from tunneldup import web as webmod
    from tunneldup.paths import WEB_PORT

    webmod.run_web(host=host_ip, port=port or WEB_PORT)


@app.command(help="Show what tunneldup-relevant things are running.")
def status() -> None:
    import socket

    from tunneldup.paths import SERVER_TUNNELD_IP, TUNNELD_PORT

    def probe(host: str, port: int, label: str) -> None:
        s = socket.socket()
        s.settimeout(1.0)
        try:
            s.connect((host, port))
            typer.secho(f"  ✓ {label} ({host}:{port}) reachable", fg=typer.colors.GREEN)
        except OSError as e:
            typer.secho(f"  ✗ {label} ({host}:{port}) unreachable: {e}", fg=typer.colors.RED)
        finally:
            s.close()

    typer.echo("WireGuard interfaces:")
    import subprocess

    r = subprocess.run(["ifconfig"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "10.42.0" in line or "fdaa:1234" in line:
            typer.echo(f"  {line.strip()}")
    typer.echo()
    typer.echo("tunneld reachability:")
    probe("127.0.0.1", TUNNELD_PORT, "local tunneld")
    probe(SERVER_TUNNELD_IP, TUNNELD_PORT, "tunneldup bridge / WG-side tunneld")


def _err(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)


def _info(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.CYAN, err=True)


def _ok(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.GREEN, err=True)


def _warn(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.YELLOW, err=True)


def _fetch_remote_devices(web_url: str) -> list[dict]:
    """Fetch the remote's flat device list, isolated so the picker can show
    just those (not local+federated)."""
    import requests

    try:
        resp = requests.get(f"{web_url}/devices", timeout=5)
        resp.raise_for_status()
        body = resp.json()
    except requests.RequestException as e:
        _err(f"could not reach {web_url}: {e}")
        typer.echo("Is `tunneldup host --web` running on the remote?", err=True)
        raise typer.Exit(code=2) from None
    return body if isinstance(body, list) else []


def _fetch_and_install_wg_config(web_url: str) -> None:
    """GET /config from the remote and drop it into our local CLIENT_CONF."""
    import requests

    from tunneldup import paths

    _info(f"fetching WireGuard config from {web_url}/config ...")
    try:
        resp = requests.get(f"{web_url}/config", timeout=5)
        resp.raise_for_status()
    except requests.RequestException as e:
        _err(f"could not fetch config from {web_url}: {e}")
        raise typer.Exit(code=2) from None
    paths.ensure_cfg_dir()
    paths.CLIENT_CONF.write_text(resp.text)
    paths.CLIENT_CONF.chmod(0o600)


def _select_device(devs: list, no_prompt: bool, web_url: str):
    """Render the device picker and return the chosen DeviceEntry, or None."""
    if not devs:
        _warn("(no devices on the remote right now — plug an iPhone in on the remote)")
        return None
    typer.echo(f"Remote devices (via {web_url}):")
    width = len(str(len(devs)))
    for i, d in enumerate(devs, 1):
        typer.echo(
            f"  [{i:>{width}}] {d.short_udid:<16} "
            + typer.style(f"{d.transport:<8}", fg=typer.colors.BLUE)
            + f"  →  [{d.tunnel_address}]:{d.tunnel_port}"
        )
    typer.echo("")

    if no_prompt:
        return None
    if len(devs) == 1:
        return devs[0]
    idx_raw = typer.prompt("Pick a device #", default="1")
    try:
        idx = int(idx_raw) - 1
    except ValueError:
        idx = -1
    if 0 <= idx < len(devs):
        return devs[idx]
    _warn("invalid selection; continuing without one")
    return None


def _print_selected_examples(chosen) -> None:
    typer.echo("")
    typer.secho(f"Selected: {chosen.udid}", fg=typer.colors.GREEN)
    typer.echo("Try in another shell:")
    for sub in ("lockdown info", "apps list   ", "syslog live "):
        typer.echo(f"  pymobiledevice3 {sub} --tunnel {chosen.udid}")
    typer.echo("")


def _wait_forever_until_interrupted() -> None:
    """Block on SIGINT/SIGTERM so the caller's `finally` runs the cleanup."""
    import contextlib

    def _shutdown(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _shutdown)
    with contextlib.suppress(KeyboardInterrupt):
        signal.pause()


@app.command(
    help="Connect to a remote `tunneldup host --web` server. Brings up "
    "the WireGuard tunnel to the remote, then registers the remote's "
    "tunneld as an upstream of your local tunneld so you can reach "
    "the remote's iPhones. Holds until Ctrl-C and cleans up on exit."
)
def add(
    host: str = typer.Argument(
        ...,
        help="Remote running `tunneldup host --web`. "
        "Accepts 'IP', 'IP:PORT', or 'http://host:port'. "
        "Default port is the tunneldup web port (9246).",
    ),
    no_prompt: bool = typer.Option(False, "--no-prompt", help="Skip the interactive device picker."),
) -> None:
    from tunneldup import client as clientmod
    from tunneldup import paths, upstreams, wg
    from tunneldup.paths import WEB_PORT

    try:
        wg.require_tools()
        wg.require_root()
    except RuntimeError as e:
        _err(str(e))
        raise typer.Exit(code=2) from None

    web_url = upstreams.parse_host_arg(host, default_port=WEB_PORT)
    upstream_url = f"{web_url}/tunneld"

    remote_flat = _fetch_remote_devices(web_url)
    _fetch_and_install_wg_config(web_url)

    _info("bringing up WireGuard tunnel to the remote ...")
    clientmod.setup_client(paths.CLIENT_CONF)

    registered = False
    try:
        if not clientmod._wait_for_tunneld(timeout=30.0):
            _err(
                "local tunneld at 127.0.0.1:49151 didn't respond within 30s.\n"
                "Start it first: sudo pymobiledevice3 remote tunneld"
            )
            raise typer.Exit(code=2)

        _info(f"registering {upstream_url} with the local tunneld ...")
        upstreams.register(upstream_url)
        registered = True
        _ok("registered. the local tunneld now federates the remote's devices.")
        typer.echo("")

        devs = [
            upstreams.DeviceEntry(
                udid=d["udid"],
                tunnel_address=d.get("tunnel_address") or "",
                tunnel_port=int(d.get("tunnel_port") or 0),
                interface=d.get("interface") or "",
            )
            for d in remote_flat
        ]
        chosen = _select_device(devs, no_prompt=no_prompt, web_url=web_url)
        if chosen is not None:
            _print_selected_examples(chosen)

        _ok("VPN + upstream are up. Ctrl-C to disconnect and clean up.")
        _wait_forever_until_interrupted()
    finally:
        if registered:
            try:
                upstreams.unregister(upstream_url)
                typer.echo(f"deregistered upstream {upstream_url}", err=True)
            except upstreams.UpstreamError as e:
                _warn(f"warning: could not deregister upstream: {e}")
        try:
            clientmod.teardown_client()
        except Exception as e:
            _warn(f"warning: WireGuard teardown failed: {e}")


@app.command(help="List upstream tunnelds currently registered with your local tunneld.")
def upstreams() -> None:
    from tunneldup import upstreams as upstreams_mod

    try:
        urls = upstreams_mod.list_registered()
    except upstreams_mod.UpstreamError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None
    if not urls:
        typer.secho("(no upstreams registered)", fg=typer.colors.YELLOW)
        return
    for u in urls:
        typer.echo(u)


@app.command(help="Deregister a remote tunneld from your local tunneld.")
def remove(
    host: str = typer.Argument(..., help="Same host string you passed to `add`."),
) -> None:
    from tunneldup import upstreams as upstreams_mod

    url = upstreams_mod.parse_host_arg(host)
    try:
        upstreams_mod.unregister(url)
    except upstreams_mod.UpstreamError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None
    typer.secho(f"deregistered {url}", fg=typer.colors.GREEN)


@app.command(help="Tear down WireGuard on either side (sudo).")
def down() -> None:
    from tunneldup import client as clientmod
    from tunneldup import server as servermod
    from tunneldup import wg

    try:
        wg.require_root()
    except RuntimeError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None
    servermod.teardown_host()
    clientmod.teardown_client()


if __name__ == "__main__":
    app()
