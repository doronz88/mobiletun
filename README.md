# tunneldup

Federate iPhones connected to one Mac into another Mac's `pymobiledevice3 tunneld`, over WireGuard.

You plug an iPhone into Mac **A**. Mac **B** runs one command and now `pymobiledevice3 lockdown info --tunnel <UDID>` on B works against A's iPhone, exactly as if the device were attached locally. The trick is a small REST extension to pymobiledevice3's tunneld (an `/upstream` registry) and a thin WireGuard layer so B can actually route to the device's tunnel address.

tunneldup does **not** rewrite or replace tunneld — it composes with the tunneld you already have running. A's tunneld serves A's iPhones; B's tunneld serves B's iPhones plus A's (after federation). You can chain more machines (C, D, …) the same way.

## Architecture

```
  ┌─ Mac A (iPhones plugged in) ───────────┐         ┌─ Mac B (no iPhones) ────────────────┐
  │ pymobiledevice3 remote tunneld         │         │  pymobiledevice3 remote tunneld     │
  │   ← serves A's devices on :49151       │         │    ← upstream registry includes     │
  │                                        │         │      http://A:9246/tunneld          │
  │ tunneldup host --web                   │ <─WG──> │  tunneldup add A                    │
  │   ← WireGuard server :51820            │         │    ← installs WG client + POSTs     │
  │   ← web UI :9246 (config, devices,     │         │      /upstream to local tunneld     │
  │     /tunneld JSON passthrough)         │         │                                     │
  └────────────────────────────────────────┘         └─────────────────────────────────────┘
                                                       ↓
                                  pymobiledevice3 lockdown info --tunnel <A's UDID>
                                  ↳ tunneld GET / merges local + every /upstream
                                  ↳ TCP connect to A's iPhone tunnel address routes over WG
```

The federation is REST-only: `POST /upstream {url}` registers, `DELETE /upstream {url}` removes, `GET /` on tunneld fetches every registered upstream in parallel and merges the device entries by UDID. The WireGuard tunnel only exists so B can route to the per-device ULA addresses A's tunneld hands out (`fd…::1/64` per session); the federation handshake itself is plain HTTP.

## Requirements

- macOS, Python ≥ 3.10.
- `brew install wireguard-tools wireguard-go` on every Mac that will run `tunneldup host` or `tunneldup add`.
- `pymobiledevice3` ≥ the version that includes the `/upstream` REST endpoints (the fork at [github.com/doronz88/pymobiledevice3](https://github.com/doronz88/pymobiledevice3), branch `feature/tunneld-upstreams`).

## Install

```sh
# either:
uv tool install tunneldup --from git+https://github.com/doronz88/tunneldup.git
# or:
pip install git+https://github.com/doronz88/tunneldup.git
```

## Usage

### On the Mac with iPhones plugged in (A)

In separate shells:

```sh
sudo pymobiledevice3 remote tunneld          # your normal tunneld
sudo tunneldup host --web                    # WG server + tunneld bridge + web UI
```

`tunneldup host` autodetects the LAN endpoint (`192.168.x.x` if present), falling back to the public WAN IP via `ifconfig.me` only when no private IP is available. To force a specific endpoint, pass `--endpoint`.

The web UI is at `http://<A's-IP>:9246`. It serves
| path | what |
| --- | --- |
| `/` | HTML dashboard — device cards, per-device action buttons, command runner |
| `/devices` | flat JSON device list (UDID, tunnel address, transport, interface) |
| `/tunneld` | verbatim pass-through of A's tunneld `GET /` — this is the URL another machine registers as an upstream |
| `/config` | A's WireGuard client config (used by `tunneldup add`) |
| `POST /exec` | runs `pymobiledevice3 <args>` on A, returns stdout/stderr/exit code |

### On a remote Mac (B)

```sh
sudo pymobiledevice3 remote tunneld          # B's normal tunneld
sudo tunneldup add 192.168.0.175             # connect to A
```

`tunneldup add` does exactly four things, then holds until Ctrl-C:

1. `GET http://A:9246/devices` to populate the interactive picker.
2. `GET http://A:9246/config` and brings up WireGuard on B.
3. `POST http://127.0.0.1:49151/upstream {"url":"http://A:9246/tunneld"}` against B's local tunneld.
4. Prints `pymobiledevice3 lockdown info --tunnel <UDID>` snippets for the device you picked.

On Ctrl-C / SIGTERM, the cleanup `finally` block runs: `DELETE /upstream` then `wg-quick down`. No stale upstream entry, no leaked WG interface.

After that, on B:

```sh
pymobiledevice3 lockdown info --tunnel <A's-UDID>
pymobiledevice3 apps list --tunnel <A's-UDID>
pymobiledevice3 syslog live --tunnel <A's-UDID>
```

### Manual upstream management (no WireGuard, REST only)

If A and B already share a network and A's tunneld is bound to a routable address, you don't need WireGuard. Just register manually:

```sh
tunneldup upstreams                              # list registered upstreams
tunneldup remove http://A:9246/tunneld           # deregister one
```

`add` is the "give me the full lifecycle" command; `upstreams` / `remove` are the bare REST primitives.

## CLI reference

| command | what |
| --- | --- |
| `tunneldup host [--web] [--endpoint <ip>]` | bring up WG server + tunneld bridge (+ web UI); regenerates `client.conf` |
| `tunneldup client <client.conf>` | bring up WG using a manually-shipped config (alternative to `add`) |
| `tunneldup add <host>[:<port>]` | one-shot: fetch conf, WG up, register upstream, picker, hold until Ctrl-C |
| `tunneldup upstreams` | list registered upstream URLs |
| `tunneldup remove <host>` | deregister an upstream |
| `tunneldup web` | run only the web UI (use `host --web` if you want WG too) |
| `tunneldup devices` | list iPhones reachable on this Mac via USB (requires sudo) |
| `tunneldup status` | show WG state + tunneld reachability |
| `tunneldup config` | print the host-side client config |
| `tunneldup down` | tear down WG on either side |

All commands respect `TUNNELDUP_DIR` (default `~/.config/tunneldup`) for configs and keys, and `TUNNELDUP_TUNNELD_URL` to point the web UI at a non-default tunneld.

## Configuration

| file | purpose |
| --- | --- |
| `~/.config/tunneldup/meta.json` | persisted WireGuard keypair for the host. **Do not commit this.** |
| `~/.config/tunneldup/server.conf` | WireGuard server config (regenerated each `tunneldup host` run) |
| `~/.config/tunneldup/client.conf` | WireGuard client config served at `GET /config` |

WireGuard networking:

| | IPv4 | IPv6 |
| --- | --- | --- |
| WG net | `10.42.0.0/24` | `fdaa:1234::/64` |
| server | `10.42.0.1` | `fdaa:1234::1` |
| client | `10.42.0.2` | `fdaa:1234::2` |
| listen port | UDP `51820` | |
| client AllowedIPs | `10.42.0.0/24`, `fdaa:1234::/64`, `fd00::/8` | |

`fd00::/8` is in `AllowedIPs` so the client can route to per-device iPhone tunnel ULAs (`fd97:...::1/64` etc., generated fresh by pymobiledevice3 per session). It's wide on purpose: per-session prefixes can't be predicted in advance.

## Development

```sh
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pre-commit install                # one-time per checkout
pytest                            # 24 tests
```

The repo uses `ruff` for lint + format with a `target-version = "py310"` config matching pymobile's. `pre-commit-config.yaml` runs `ruff-check` and `ruff-format` on every commit.

Tests stand up real in-process `TunneldRunner` instances on random ports and exercise the actual REST surface — the federation + upstream-cleanup contract is covered end-to-end, not just at the mock layer.

## Security notes

- `tunneldup host` exposes a WireGuard endpoint. The keypair is generated locally and never leaves the machine; sharing the *client* config with a peer is what grants them access.
- The web UI binds to `0.0.0.0:9246` by default, so it's reachable from your LAN. The `POST /exec` endpoint runs `pymobiledevice3 <args>` with the privileges of the process serving the UI (sudo, if you started it with sudo). Don't run `tunneldup host --web` on a network you don't trust.
- The web UI has no built-in authentication. If you need it accessible only over WG, pass `--host 10.42.0.1` to bind only to the WG interface.

## License

MIT.
