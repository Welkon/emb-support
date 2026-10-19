"""Local web UI for a connected supply: setpoints, output, live chart."""

from __future__ import annotations

import json
import mimetypes
import threading
import time
from collections import deque
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .common import die, load_config
from .drivers import open_device
from .wsl import is_wsl, open_browser

DIST = Path(__file__).resolve().parents[2] / "webapp" / "dist"


INDEX_HTML = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Power Supply</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--fg:#e6e9ef;--dim:#8b93a7;
--blue:#5da9ff;--orange:#ffb454;--red:#ff5d5d;--green:#59d98e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 ui-monospace,Menlo,Consolas,monospace}
.wrap{max-width:980px;margin:0 auto;padding:24px 18px 40px}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--dim);font-size:12px}
.grid{display:grid;grid-template-columns:1.1fr .9fr;gap:14px;margin-top:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card h2{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin:0 0 10px}
label{display:block;color:var(--dim);font-size:11px;margin:8px 0 3px}
input,select,button{font:inherit;color:var(--fg);background:#12151b;border:1px solid var(--line);
border-radius:6px;padding:6px 8px}
input{width:100%}button{cursor:pointer}button:hover{border-color:#3b4454}
button.primary{background:#1d3a5c;border-color:#2c5a8a}button.danger{background:#3a1b1e;border-color:#6b2b30}
button.on{background:#173a26;border-color:#2b6b45}button.off{background:#2a1b1b;border-color:#5c2a2a}
.row{display:flex;gap:8px;margin-top:10px}.row>*{flex:1}
.big{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}
.unit{font-size:12px;color:var(--dim)}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;
border:1px solid var(--line);margin-left:10px;vertical-align:middle}
.pill.on{color:#7ff0b0;border-color:#2b6b45;background:#12261b}
.pill.off{color:var(--dim);background:#12151b}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.chip{font-size:11px;color:var(--dim);border:1px solid var(--line);
border-radius:99px;padding:2px 9px;background:#12151b}
.readings{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.readings div{background:#12151b;border:1px solid var(--line);border-radius:8px;padding:10px}
#msg{color:var(--red);font-size:12px;min-height:16px;margin-top:8px}
canvas{width:100%;height:230px;display:block;background:#12151b;border-radius:8px}
.legend{font-size:11px;color:var(--dim);margin-top:6px}
.legend i{display:inline-block;width:10px;height:3px;margin:0 5px 2px 12px;vertical-align:middle}
@media(max-width:760px){.grid{grid-template-columns:1fr}.readings{grid-template-columns:1fr}}
</style>
<div class="wrap">
<h1>Power Supply <span id="state" class="pill off">OUTPUT ?</span></h1>
<div class="sub" id="idn">connecting...</div>
<div class="grid">
  <div class="card">
    <h2>Control</h2>
    <label>Channel</label><select id="ch"></select>
    <div class="row"><div><label>Voltage (V)</label><input id="v" type="number" step="0.01"></div>
      <div><label>Current (A)</label><input id="i" type="number" step="0.001"></div></div>
    <div class="row"><button class="primary" onclick="apply()">Apply setpoints</button></div>
    <div class="row"><button class="on" onclick="setOut(true)">Output ON</button>
      <button class="off" onclick="setOut(false)">Output OFF</button></div>
    <div class="row"><button class="danger" onclick="allOff()">ALL OFF</button></div>
    <div class="row"><div><label>OVP (V)</label><input id="ovp" type="number" step="0.01" placeholder="e.g. 6.0"></div>
      <div><label>OCP (A)</label><input id="ocp" type="number" step="0.001" placeholder="e.g. 1.0"></div></div>
    <div class="row"><button onclick="protect()">Set protection</button></div>
    <div id="msg"></div>
  </div>
  <div class="card">
    <h2>Live</h2>
    <div class="readings">
      <div><div class="unit">Voltage</div><div class="big" id="mv">-</div><div class="unit">V</div></div>
      <div><div class="unit">Current</div><div class="big" id="mi">-</div><div class="unit">A</div></div>
      <div><div class="unit">Power</div><div class="big" id="mp">-</div><div class="unit">W</div></div>
    </div>
    <div class="legend" id="legend"><i style="background:var(--blue)"></i>Voltage<i style="background:var(--orange)"></i>Current</div>
    <canvas id="chart" width="900" height="230"></canvas>
    <div class="row"><button onclick="download()">Download CSV</button></div>
  </div>
</div>
<div class="chips" id="limits"></div>
<div class="sub" id="updated"></div>
</div>
<script>
const S={history:[],ch:1,limits:null,timer:null};
const $=id=>document.getElementById(id);
function msg(t){$('msg').textContent=t||''}
async function api(path,body){
  const opt=body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{};
  const r=await fetch(path,opt); const j=await r.json();
  if(!r.ok||j.ok===false) throw new Error(j.error||('HTTP '+r.status)); return j;
}
function fmt(x,n=3){return (x===null||x===undefined)?'-':Number(x).toFixed(n)}
function render(s){
  S.limits=s.limits; $('idn').textContent=s.idn+'  ['+s.family+']';
  const on=(s.output||'').toUpperCase()==='ON';
  $('state').textContent='OUTPUT '+(s.output||'?'); $('state').className='pill '+(on?'on':'off');
  $('mv').textContent=fmt(s.measurement.voltage); $('mi').textContent=fmt(s.measurement.current); $('mp').textContent=fmt(s.measurement.power);
  $('v').value=fmt(s.setpoint.voltage,3); $('i').value=fmt(s.setpoint.current,3);
  if(s.limits){
    const L=s.limits, chips=[];
    if(L.max_voltage!=null) chips.push('0–'+L.max_voltage+' V');
    if(L.max_current!=null) chips.push('0–'+L.max_current+' A');
    if(L.max_ovp!=null) chips.push('OVP ≤'+L.max_ovp+' V');
    if(L.max_ocp!=null) chips.push('OCP ≤'+L.max_ocp+' A');
    if(L.max_power!=null) chips.push('≤'+L.max_power+' W');
    $('limits').innerHTML=chips.map(c=>'<span class="chip">'+c+'</span>').join('');
  }
  $('legend').innerHTML='<i style="background:var(--blue)"></i>Voltage '+fmt(s.measurement.voltage,3)+' V'+
    '<i style="background:var(--orange)"></i>Current '+fmt(s.measurement.current,3)+' A';
  $('updated').textContent='updated '+new Date().toLocaleTimeString();
  S.history.push({t:Date.now(),v:s.measurement.voltage,i:s.measurement.current});
  if(S.history.length>600) S.history.shift(); draw();
}
async function refresh(ch){
  try{const s=await api('/api/state?ch='+(ch||S.ch)); render(s);}
  catch(e){$('state').textContent='disconnected'; msg(e.message)}
}
async function apply(){
  try{await api('/api/set',{ch:S.ch,voltage:parseFloat($('v').value),current:parseFloat($('i').value)}); msg(''); refresh();}
  catch(e){msg(e.message)}
}
async function setOut(on){
  if(on && !confirm('Enable the output?')) return;
  try{await api('/api/output',{ch:S.ch,on,confirm:on}); msg(''); refresh();}
  catch(e){msg(e.message)}
}
async function allOff(){try{await api('/api/all-off',{}); refresh();}catch(e){msg(e.message)}}
async function protect(){
  try{await api('/api/protect',{ch:S.ch,ovp:parseFloat($('ovp').value),ocp:parseFloat($('ocp').value)}); msg('');}
  catch(e){msg(e.message)}
}
function bounds(a){
  let lo=Math.min(...a), hi=Math.max(...a);
  if(hi-lo<1e-9){ hi+=0.5; lo-=0.5; }
  else { const p=(hi-lo)*0.12; hi+=p; lo-=p; }
  return [lo,hi];
}
function draw(){
  const c=$('chart'),g=c.getContext('2d'),W=c.width,H=c.height;
  const L=46,R=10,T=16,B=20;
  g.clearRect(0,0,W,H); g.strokeStyle='#262b36'; g.lineWidth=1;
  for(let k=0;k<=4;k++){const y=T+(H-T-B)*k/4;g.beginPath();g.moveTo(L,y);g.lineTo(W-R,y);g.stroke();}
  const h=S.history;
  if(h.length<1){g.fillStyle='#8b93a7';g.font='11px monospace';g.fillText('waiting for samples…',L+8,T+20);return;}
  const vs=h.map(p=>p.v).filter(x=>x!=null), is=h.map(p=>p.i).filter(x=>x!=null);
  const [vlo,vhi]=bounds(vs.length?vs:[0]), [ilo,ihi]=bounds(is.length?is:[0]);
  const x=k=>L+(W-L-R)*(h.length===1?0.5:k/(h.length-1));
  const y=(v,lo,hi)=>T+(H-T-B)*(1-(v-lo)/(hi-lo));
  const line=(arr,lo,hi,color,dash)=>{g.beginPath();g.setLineDash(dash||[]);arr.forEach((v,k)=>{const px=x(k),py=y(v,lo,hi);k?g.lineTo(px,py):g.moveTo(px,py)});g.strokeStyle=color;g.lineWidth=2;g.stroke();g.setLineDash([]);};
  line(h.map(p=>p.v),vlo,vhi,'#5da9ff'); line(h.map(p=>p.i),ilo,ihi,'#ffb454',[6,4]);
  g.fillStyle='#8b93a7'; g.font='10px monospace';
  g.fillText(vhi.toFixed(2),4,T+4); g.fillText(vlo.toFixed(2),4,H-B);
  g.textAlign='right'; g.fillText(ihi.toFixed(3),W-4,T+4); g.fillText(ilo.toFixed(3),W-4,H-B); g.textAlign='left';
  g.fillStyle='#5da9ff'; g.fillText('V',4,T+16); g.fillStyle='#ffb454'; g.textAlign='right'; g.fillText('A',W-4,T+16); g.textAlign='left';
}
function download(){
  let out='time,voltage,current\\n';
  for(const p of S.history) out+=new Date(p.t).toISOString()+','+p.v+','+p.i+'\\n';
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([out],{type:'text/csv'}));
  a.download='psu-log.csv';a.click();
}
(async function(){
  try{
    const s=await api('/api/state?ch=1'); S.ch=s.ch;
    const sel=$('ch'); s.channels.forEach(ch=>{const o=document.createElement('option');o.value=ch;o.textContent='CH'+ch;sel.appendChild(o)});
    sel.onchange=()=>{S.ch=parseInt(sel.value);S.history=[];refresh(S.ch)};
    render(s); S.timer=setInterval(()=>refresh(),1000);
  }catch(e){msg(e.message)}
})();
</script>
</html>"""


class PsuWebServer:
    def __init__(self, device, max_voltage: float, max_current: float,
                 bind: str = "127.0.0.1", port: int = 8765, start_sampler: bool = True):
        self.device = device
        self.max_voltage = float(max_voltage)
        self.max_current = float(max_current)
        self.lock = threading.Lock()
        self.sample_hz = 30 if getattr(device, "family", "") == "dp100" else 10
        self.history = {ch: deque(maxlen=self.sample_hz * 240) for ch in device.channels}
        self._stop = threading.Event()
        self.httpd = ThreadingHTTPServer((bind, port), self._handler())
        if start_sampler:
            threading.Thread(target=self._sample_loop, daemon=True).start()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def _state(self, ch: int) -> dict:
        if ch not in self.device.channels:
            raise ValueError(f"channel {ch} not available")
        snap = self.device.snapshot(ch) if hasattr(self.device, "snapshot") else None
        if snap:
            output, setpoint, measurement, status = (
                snap["output"], snap["setpoint"], snap["measurement"], snap["status"])
        else:
            output = self.device.output_state(ch)
            setpoint = {"voltage": self.device.get_voltage(ch),
                        "current": self.device.get_current(ch)}
            measurement = {
                "voltage": self.device.measure_voltage(ch),
                "current": self.device.measure_current(ch),
                "power": self.device.measure_power(ch) if self.device.supports_power else None,
                "input_voltage": self.device.measure_input_voltage(ch)
                if self.device.supports_input_voltage else None,
                "temperature": self.device.measure_temperature(ch)
                if self.device.supports_temperature else None,
            }
            status = self.device.status(ch) if hasattr(self.device, "status") else None
        return {
            "ok": True,
            "idn": self.device.idn,
            "family": self.device.family,
            "device_info": self.device.device_info(),
            "channels": list(self.device.channels),
            "ch": ch,
            "output": output,
            "setpoint": setpoint,
            "measurement": measurement,
            "status": status,
            "capabilities": {
                "power": self.device.supports_power,
                "ovp": self.device.supports_ovp,
                "ocp": self.device.supports_ocp,
                "output_state": self.device.supports_output_state,
                "input_voltage": self.device.supports_input_voltage,
                "temperature": self.device.supports_temperature,
            },
            "limits": {**{"max_voltage": self.max_voltage, "max_current": self.max_current},
                        **(getattr(self.device, "limits", None) or {})},
        }

    def _sample_loop(self):
        period = 1.0 / self.sample_hz
        while not self._stop.is_set():
            for ch in self.device.channels:
                try:
                    with self.lock:
                        sample = self._sample(ch)
                    sample = dict(sample)
                    sample["t"] = int(time.time() * 1000)
                    with self.lock:
                        self.history[ch].append(sample)
                except Exception:
                    pass
            self._stop.wait(period)

    def _sample(self, ch: int) -> dict:
        if ch not in self.device.channels:
            raise ValueError(f"channel {ch} not available")
        if hasattr(self.device, "sample"):
            return self.device.sample(ch)
        return {
            "voltage": self.device.measure_voltage(ch),
            "current": self.device.measure_current(ch),
            "power": self.device.measure_power(ch) if self.device.supports_power else None,
            "input_voltage": self.device.measure_input_voltage(ch)
            if self.device.supports_input_voltage else None,
            "temperature": self.device.measure_temperature(ch)
            if self.device.supports_temperature else None,
        }

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, code, body, content_type="application/json"):
                data = body if isinstance(body, bytes) else body.encode()
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json(self, code, payload):
                self._send(code, json.dumps(payload, default=str))

            def _file(self, path: Path, content_type: str | None = None):
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type
                                 or mimetypes.guess_type(str(path))[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/" and (DIST / "index.html").exists():
                    self._file(DIST / "index.html", "text/html; charset=utf-8")
                    return
                if parsed.path == "/":
                    self._send(200, INDEX_HTML, "text/html; charset=utf-8")
                    return
                if parsed.path.startswith("/assets/"):
                    target = (DIST / parsed.path.lstrip("/")).resolve()
                    try:
                        target.relative_to(DIST.resolve())
                    except ValueError:
                        self._json(404, {"ok": False, "error": "not found"})
                        return
                    if target.is_file():
                        self._file(target)
                        return
                if parsed.path == "/api/history":
                    qs = parse_qs(parsed.query)
                    try:
                        ch = int(qs.get("ch", ["1"])[0])
                        seconds = max(1.0, min(120.0, float(qs.get("seconds", ["62"])[0])))
                        if ch not in outer.device.channels:
                            raise ValueError(f"channel {ch} not available")
                        cutoff = time.time() * 1000 - seconds * 1000
                        with outer.lock:
                            samples = [s for s in outer.history[ch] if s["t"] >= cutoff]
                        self._json(200, {"ok": True, "ch": ch, "samples": samples})
                    except Exception as e:  # noqa: BLE001
                        self._json(400, {"ok": False, "error": str(e)})
                    return
                if parsed.path == "/api/stream":
                    qs = parse_qs(parsed.query)
                    try:
                        ch = int(qs.get("ch", ["1"])[0])
                        hz = max(1.0, min(60.0, float(qs.get("hz", ["30"])[0])))
                        if ch not in outer.device.channels:
                            raise ValueError(f"channel {ch} not available")
                    except Exception as e:  # noqa: BLE001
                        self._json(400, {"ok": False, "error": str(e)})
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    # HTTP/1.1 + chunked framing keeps EventSource reliable.
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.close_connection = True
                    period = 1.0 / hz
                    last_t, last_sent = 0, 0.0
                    try:
                        while True:
                            now = time.time()
                            with outer.lock:
                                items = outer.history.get(ch)
                                payload = items[-1] if items else None
                            if payload and payload["t"] > last_t and now - last_sent >= period:
                                chunk = f"data: {json.dumps(payload)}\n\n".encode()
                                self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                                self.wfile.flush()
                                last_t, last_sent = payload["t"], now
                            elif now - last_sent > 5:
                                chunk = b": keepalive\n\n"
                                self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                                self.wfile.flush()
                                last_sent = now
                            time.sleep(period)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                if parsed.path == "/api/state":
                    try:
                        ch = int(parse_qs(parsed.query).get("ch", ["1"])[0])
                        with outer.lock:
                            self._json(200, outer._state(ch))
                    except Exception as e:  # noqa: BLE001
                        self._json(400, {"ok": False, "error": str(e)})
                    return
                self._json(404, {"ok": False, "error": "not found"})

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length) or b"{}")
                except Exception as e:  # noqa: BLE001
                    self._json(400, {"ok": False, "error": f"bad JSON: {e}"})
                    return
                try:
                    with outer.lock:
                        self._handle_post(urlparse(self.path).path, body)
                except Exception as e:  # noqa: BLE001
                    self._json(400, {"ok": False, "error": str(e)})

            def _handle_post(self, path, body):
                dev = outer.device
                ch = int(body.get("ch", 1))
                if path == "/api/set":
                    v, i = body.get("voltage"), body.get("current")
                    if v is not None and (v < 0 or v > outer.max_voltage):
                        raise ValueError(f"voltage outside 0..{outer.max_voltage} V")
                    if i is not None and (i < 0 or i > outer.max_current):
                        raise ValueError(f"current outside 0..{outer.max_current} A")
                    if v is not None:
                        dev.set_voltage(ch, float(v))
                    if i is not None:
                        dev.set_current(ch, float(i))
                elif path == "/api/output":
                    on = bool(body.get("on"))
                    if on and not body.get("confirm"):
                        raise ValueError("output ON requires confirm=true")
                    dev.output(ch, on)
                elif path == "/api/all-off":
                    for channel in dev.channels:
                        try:
                            dev.output(channel, False)
                        except Exception:
                            pass
                elif path == "/api/protect":
                    if body.get("ovp") is not None:
                        dev.set_ovp(ch, float(body["ovp"]))
                    if body.get("ocp") is not None:
                        dev.set_ocp(ch, float(body["ocp"]))
                else:
                    raise ValueError("not found")
                self._json(200, outer._state(ch))

        return Handler

    def serve_forever(self):
        self.httpd.serve_forever()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run(a) -> None:
    dev = open_device(a)
    mv, mi = _limits(a)
    try:
        server = PsuWebServer(dev, mv, mi, bind=a.bind, port=a.web_port)
    except OSError as e:
        die(f"cannot bind {a.bind}:{a.web_port}: {e}")
    host = a.bind if a.bind not in ("127.0.0.1", "0.0.0.0", "::1") else "localhost"
    url = f"http://{host}:{server.port}/"
    print(f"web UI: {url}")
    if is_wsl():
        print("WSL detected: open this URL in a Windows browser "
              "(localhost is forwarded from WSL)")
    if a.open:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        dev.close()


def _limits(a):
    cfg = load_config()
    mv = getattr(a, "max_voltage", None) or cfg.get("max_voltage") or 30.0
    mi = getattr(a, "max_current", None) or cfg.get("max_current") or 5.0
    return float(mv), float(mi)
