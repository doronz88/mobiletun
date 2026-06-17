"""Web control surface so the remote can drive the host over WireGuard
without SSH. Bound to all interfaces by default."""

import asyncio
import os
import subprocess
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from tunneldup.paths import CLIENT_CONF, SERVER_TUNNELD_IP, TUNNELD_PORT, WEB_PORT

ALLOWED_BIN = "pymobiledevice3"
# Tunneld's canonical location on the host where tunneldup runs. Overridable
# so the web UI can be pointed at a tunneld on a non-default host/port.
TUNNELD_URL = os.environ.get("TUNNELDUP_TUNNELD_URL", f"http://127.0.0.1:{TUNNELD_PORT}")


def _fetch_tunneld() -> tuple[Any, Optional[str]]:
    """Returns (parsed_json, error_str)."""
    import requests

    try:
        resp = requests.get(TUNNELD_URL, timeout=2)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def build_app() -> FastAPI:
    app = FastAPI(title="tunneldup", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.get("/devices")
    async def devices() -> Any:
        """Devices known to the locally-running tunneld, flattened. Source of
        truth covers iPhones reached via usbmux OR USB-NCM/bonjour OR upstream."""
        data, err = _fetch_tunneld()
        if err:
            return JSONResponse({"_error": f"tunneld at {TUNNELD_URL} unreachable: {err}"}, status_code=503)
        flat = []
        for udid, entries in (data or {}).items():
            for e in entries:
                flat.append({
                    "udid": udid,
                    "tunnel_address": e.get("tunnel-address"),
                    "tunnel_port": e.get("tunnel-port"),
                    "interface": e.get("interface"),
                })
        return flat

    @app.get("/tunneld")
    async def tunneld_passthrough() -> Any:
        """Verbatim pass-through of the local tunneld's `GET /` response.
        Used by a remote `tunneldup add` so a remote tunneld can register
        THIS URL as an upstream and federate our devices."""
        data, err = _fetch_tunneld()
        if err:
            return JSONResponse({"_error": f"tunneld at {TUNNELD_URL} unreachable: {err}"}, status_code=503)
        return data

    @app.get("/config")
    async def get_config() -> PlainTextResponse:
        if not CLIENT_CONF.exists():
            raise HTTPException(404, "no client.conf; run `tunneldup host` first")
        return PlainTextResponse(CLIENT_CONF.read_text(), media_type="text/plain")

    class ExecReq(BaseModel):
        args: list[str]
        stdin: Optional[str] = None
        timeout: int = 60

    @app.post("/exec")
    async def exec_pmd3(req: ExecReq) -> JSONResponse:
        cmd = [ALLOWED_BIN, *req.args]
        try:
            p = await asyncio.to_thread(
                subprocess.run,
                cmd,
                input=req.stdin,
                capture_output=True,
                text=True,
                timeout=req.timeout,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "command timed out") from None
        return JSONResponse({
            "cmd": cmd,
            "returncode": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
        })

    return app


_INDEX_HTML = """<!doctype html>
<html><head><meta charset=utf-8><title>tunneldup</title>
<style>
:root { --bg:#0b0b0f; --panel:#161620; --panel2:#1a1a26; --border:#2a2a35; --text:#dcdce0; --muted:#888; --ok:#7fd17f; --err:#ff7a7a; --accent:#7aa7ff }
body{font-family:-apple-system,sans-serif;max-width:920px;margin:1.5em auto;padding:0 1em;background:var(--bg);color:var(--text)}
h1{font-size:1.4em;margin:0}
h2{border-bottom:1px solid #333;padding-bottom:.3em;margin-top:1.8em;font-size:1.05em;font-weight:600;letter-spacing:.02em;text-transform:uppercase;color:#bbb}
pre,code{background:var(--panel);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
pre{padding:1em;border-radius:6px;overflow:auto;font-size:.85em}
code{padding:.1em .35em;border-radius:3px;font-size:.85em}
button,input,select{background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:.4em .8em;font:inherit}
button{cursor:pointer;transition:background .15s,border-color .15s}
button:hover{background:#222232;border-color:#444}
button.primary{background:#1d3a6a;border-color:#2c5599}
button.primary:hover{background:#244680}
input{width:100%}
select{min-width:18em}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.row{display:flex;gap:.5em;margin:.5em 0;align-items:center;flex-wrap:wrap}
.header{display:flex;align-items:baseline;justify-content:space-between;gap:1em;margin-bottom:.2em}
.status{font-size:.8em;color:var(--muted)}
.status>.dot{display:inline-block;width:.6em;height:.6em;border-radius:50%;background:var(--muted);margin-right:.4em;vertical-align:middle}
.status.ok>.dot{background:var(--ok)}
.status.err>.dot{background:var(--err)}
.snippet{position:relative}
.snippet>.copy{position:absolute;top:.5em;right:.5em;padding:.2em .6em;font-size:.8em;opacity:.5;cursor:pointer;transition:opacity .15s}
.snippet:hover>.copy{opacity:1}
.snippet>.copy.ok{color:var(--ok);border-color:var(--ok);opacity:1}
.devices{display:grid;gap:.6em}
.device{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:.7em .9em}
.device>.title{display:flex;align-items:center;gap:.5em;margin-bottom:.4em;flex-wrap:wrap}
.device>.title>.model{font-weight:600;color:#fff}
.device>.title>.udid{font-family:ui-monospace,monospace;font-size:.85em;color:#aab;cursor:pointer}
.device>.title>.udid:hover{color:#fff}
.device>.title>.badge{font-size:.7em;padding:.15em .5em;border-radius:99px;background:var(--panel2);color:#9aa;border:1px solid var(--border)}
.device>.title>.badge.usb{color:#abe;border-color:#345}
.device>.title>.badge.wifi{color:#cae;border-color:#534}
.device>.facts{font-size:.82em;color:#aab;display:grid;grid-template-columns:auto 1fr;gap:.1em .8em;margin:.3em 0}
.device>.facts>.lbl{color:#778}
.device>.facts>code{background:#0e0e15;cursor:pointer}
.device>.facts>code:hover{background:#1e1e2a}
.device>.actions{margin-top:.5em;display:flex;gap:.4em;flex-wrap:wrap}
.device>.actions>button{font-size:.8em;padding:.25em .7em}
.empty{padding:1em;text-align:center;color:var(--muted);background:var(--panel);border:1px dashed var(--border);border-radius:8px}
.flash{position:fixed;bottom:1em;left:50%;transform:translateX(-50%);background:var(--panel);border:1px solid var(--ok);color:var(--ok);padding:.4em 1em;border-radius:6px;font-size:.85em;opacity:0;transition:opacity .2s;pointer-events:none}
.flash.show{opacity:1}
#out{min-height:3em;white-space:pre-wrap}
.muted{color:var(--muted);font-size:.85em}
</style></head>
<body>
<div class="header">
  <h1>tunneldup</h1>
  <div id="status" class="status"><span class="dot"></span><span id="status-text">checking tunneld…</span></div>
</div>
<p class="muted">Devices below are merged from your local tunneld and any registered upstream tunnelds (federated via <code>POST /upstream</code>).</p>

<h2>devices</h2>
<div id="devices" class="devices"></div>

<h2>run pymobiledevice3</h2>
<div class="row">
  <select id="target-select"><option value="">(no --tunnel flag)</option></select>
  <input id="cmd" placeholder="e.g. lockdown info" value="lockdown info" style="flex:1;min-width:14em">
  <button class="primary" onclick="runCmd()">run</button>
</div>
<pre id="out">(idle)</pre>

<h2>connect from another Mac</h2>
<div class="snippet"><button class="copy" data-target="connect-cmds">Copy</button>
<pre id="connect-cmds"></pre></div>

<p><a href="/config">download client.conf</a></p>
<div id="flash" class="flash">Copied</div>

<script>
const base = window.location.origin;
const $ = id => document.getElementById(id);

const a = new URL(base);
document.getElementById("connect-cmds").textContent =
`# on the remote machine connecting in — needs:
#   brew install wireguard-tools wireguard-go
#   pip install tunneldup

# 1. start your local tunneld if it isn't already (own shell)
sudo pymobiledevice3 remote tunneld

# 2. connect to this host — brings up WG, federates this tunneld into yours,
#    picks a device. Ctrl-C tears everything down cleanly.
sudo tunneldup add ${a.hostname}${a.port === "9246" || a.port === "" ? "" : ":" + a.port}

# 3. in another shell, use pymobiledevice3 as normal — your tunneld now
#    shows your own local devices PLUS the ones on this host:
pymobiledevice3 lockdown info --tunnel ""
`;

function flash(msg){
  const f = $("flash"); f.textContent = msg; f.classList.add("show");
  clearTimeout(flash._t); flash._t = setTimeout(()=>f.classList.remove("show"), 1200);
}

async function copyText(text, label){
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position="fixed"; ta.style.opacity="0";
    document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); document.body.removeChild(ta);
  }
  flash("Copied " + (label||""));
}

function shortUdid(u){ return u.length > 12 ? u.slice(0,8) + "…" + u.slice(-4) : u }

function transportBadge(iface){
  if (!iface) return "";
  if (iface.startsWith("usbmux-")) return '<span class="badge usb">USBMUX</span>';
  if (iface.includes("%en") || iface.includes("ncm")) return '<span class="badge usb">USB-NCM</span>';
  if (iface.includes("wifi") || iface.includes("remotepairing")) return '<span class="badge wifi">Wi-Fi</span>';
  return '<span class="badge">' + iface.split("-")[0] + '</span>';
}

function render(devices){
  const root = $("devices");
  const select = $("target-select");
  const prevTarget = select.value;
  if (!devices || devices.length === 0){
    root.innerHTML = '<div class="empty">No devices visible to your tunneld. Plug in an iPhone, or run <code>tunneldup client</code> to federate a remote host.</div>';
    select.innerHTML = '<option value="">(no --tunnel flag)</option>';
    return;
  }
  // dedup by (udid, interface) since federated + local can overlap
  const seen = new Set();
  const dedup = devices.filter(d => {
    const k = d.udid + "|" + (d.interface||"");
    if (seen.has(k)) return false; seen.add(k); return true;
  });
  // Group by UDID so a device with multiple transports shows once
  const byUdid = new Map();
  for (const d of dedup){
    if (!byUdid.has(d.udid)) byUdid.set(d.udid, []);
    byUdid.get(d.udid).push(d);
  }
  root.innerHTML = "";
  select.innerHTML = '<option value="">(no --tunnel flag)</option>';
  for (const [udid, entries] of byUdid){
    const first = entries[0];
    const card = document.createElement("div");
    card.className = "device";
    const badges = entries.map(e => transportBadge(e.interface)).join(" ");
    card.innerHTML = `
      <div class="title">
        <span class="model">iPhone</span>
        <span class="udid" data-copy="${udid}" title="click to copy full UDID">${shortUdid(udid)}</span>
        ${badges}
      </div>
      <div class="facts">
        ${entries.map(e => `
          <span class="lbl">tunnel</span><code data-copy="[${e.tunnel_address}]:${e.tunnel_port}">[${e.tunnel_address}]:${e.tunnel_port}</code>
          <span class="lbl">via</span><code title="interface">${e.interface||""}</code>
        `).join("")}
      </div>
      <div class="actions">
        <button data-act="target" data-udid="${udid}">Target</button>
        <button data-act="info" data-udid="${udid}">lockdown info</button>
        <button data-act="apps" data-udid="${udid}">apps list</button>
        <button data-act="copy-udid" data-udid="${udid}">Copy UDID</button>
      </div>
    `;
    root.appendChild(card);

    const opt = document.createElement("option");
    opt.value = udid; opt.textContent = shortUdid(udid);
    select.appendChild(opt);
  }
  if (prevTarget && [...select.options].some(o => o.value === prevTarget)){
    select.value = prevTarget;
  }
}

async function refresh(){
  let data;
  try { const r = await fetch("/devices"); data = await r.json(); }
  catch (e){ data = {_error: String(e)}; }
  const status = $("status"); const statusText = $("status-text");
  if (Array.isArray(data)){
    status.classList.remove("err"); status.classList.add("ok");
    statusText.textContent = `tunneld online · ${data.length} device${data.length===1?"":"s"}`;
    render(data);
  } else {
    status.classList.remove("ok"); status.classList.add("err");
    statusText.textContent = data._error || "tunneld unreachable";
    $("devices").innerHTML = `<div class="empty">tunneld unreachable: <code>${(data._error||"unknown").replace(/</g,"&lt;")}</code></div>`;
    $("target-select").innerHTML = '<option value="">(no --tunnel flag)</option>';
  }
}

async function runCmd(udidOverride){
  const target = (udidOverride !== undefined) ? udidOverride : $("target-select").value;
  const cmdStr = $("cmd").value.trim();
  const tokens = cmdStr.match(/(?:[^\\s"]+|"[^"]*")+/g) || [];
  const args = tokens.map(a => a.replace(/^"|"$/g, ""));
  if (target) args.push("--tunnel", target);
  $("out").textContent = "running…";
  try {
    const r = await fetch("/exec", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({args})});
    const j = await r.json();
    $("out").textContent = `$ ${j.cmd.join(" ")}\\n(exit ${j.returncode})\\n\\n${j.stdout}${j.stderr ? "\\nSTDERR:\\n"+j.stderr : ""}`;
  } catch (e){
    $("out").textContent = "request failed: " + e;
  }
}

// event delegation for device cards
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-act], [data-copy], .snippet > .copy");
  if (!t) return;
  if (t.classList.contains("copy") && t.parentElement.classList.contains("snippet")){
    copyText($(t.dataset.target).textContent, "snippet");
    const orig = t.textContent;
    t.textContent = "Copied"; t.classList.add("ok");
    setTimeout(()=>{ t.textContent = orig; t.classList.remove("ok"); }, 1200);
    return;
  }
  if (t.dataset.copy){
    copyText(t.dataset.copy, "");
    return;
  }
  const udid = t.dataset.udid;
  switch (t.dataset.act){
    case "target":
      $("target-select").value = udid;
      $("cmd").focus();
      flash("Targeting " + shortUdid(udid));
      break;
    case "info":
      $("cmd").value = "lockdown info";
      $("target-select").value = udid;
      runCmd(udid);
      break;
    case "apps":
      $("cmd").value = "apps list";
      $("target-select").value = udid;
      runCmd(udid);
      break;
    case "copy-udid":
      copyText(udid, "UDID");
      break;
  }
});

refresh(); setInterval(refresh, 5000);
</script>
</body></html>
"""


def _print_reachable_urls(bind_host: str, port: int) -> None:
    import socket

    candidates: list[str] = []
    if bind_host in ("0.0.0.0", "::"):
        candidates.append(f"http://127.0.0.1:{port}")
        try:
            for fam, _t, _p, _c, sa in socket.getaddrinfo(socket.gethostname(), None):
                ip = sa[0]
                if ip.startswith(("127.", "fe80:", "::1")):
                    continue
                candidates.append(f"http://{ip}:{port}" if fam == socket.AF_INET else f"http://[{ip}]:{port}")
        except Exception:
            pass
        candidates.append(f"http://{SERVER_TUNNELD_IP}:{port}  (over WireGuard, only if `tunneldup host` is up)")
    else:
        candidates.append(f"http://{bind_host}:{port}")
    print("\n[tunneldup] web UI reachable at:")
    for url in dict.fromkeys(candidates):
        print(f"  {url}")
    print()


def run_web(host: str = "0.0.0.0", port: int = WEB_PORT) -> None:
    _print_reachable_urls(host, port)
    uvicorn.run(build_app(), host=host, port=port, log_level="info")
