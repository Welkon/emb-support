"""Local web UI for a connected supply: setpoints, output, live chart."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .common import die, load_config
from .drivers import open_device


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
.big{font-size:26px;font-weight:600}.unit{font-size:12px;color:var(--dim)}
.readings{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.readings div{background:#12151b;border:1px solid var(--line);border-radius:8px;padding:10px}
#msg{color:var(--red);font-size:12px;min-height:16px;margin-top:8px}
canvas{width:100%;height:230px;display:block;background:#12151b;border-radius:8px}
.legend{font-size:11px;color:var(--dim);margin-top:6px}
.legend i{display:inline-block;width:10px;height:3px;margin:0 5px 2px 12px;vertical-align:middle}
@media(max-width:760px){.grid{grid-template-columns:1fr}.readings{grid-template-columns:1fr}}
</style>
<div class="wrap">
<h1>Power Supply <span id="state" class="sub"></span></h1>
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
    <div class="row"><div><label>OVP (V)</label><input id="ovp" type="number" step="0.01"></div>
      <div><label>OCP (A)</label><input id="ocp" type="number" step="0.001"></div></div>
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
    <div class="legend"><i style="background:var(--blue)"></i>Voltage<i style="background:var(--orange)"></i>Current</div>
    <canvas id="chart" width="900" height="230"></canvas>
    <div class="row"><button onclick="download()">Download CSV</button></div>
  </div>
</div>
<div class="sub" id="limits"></div>
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
  $('state').textContent=s.output?('output '+s.output):'';
  $('mv').textContent=fmt(s.measurement.voltage); $('mi').textContent=fmt(s.measurement.current); $('mp').textContent=fmt(s.measurement.power);
  $('v').value=fmt(s.setpoint.voltage,3); $('i').value=fmt(s.setpoint.current,3);
  if(s.limits) $('limits').textContent='limits: '+JSON.stringify(s.limits);
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
function draw(){
  const c=$('chart'),g=c.getContext('2d'),W=c.width,H=c.height;
  g.clearRect(0,0,W,H); g.strokeStyle='#262b36'; g.lineWidth=1;
  for(let k=1;k<5;k++){g.beginPath();g.moveTo(0,H*k/5);g.lineTo(W,H*k/5);g.stroke();}
  const h=S.history; if(h.length<2) return;
  const vs=h.map(p=>p.v).filter(x=>x!=null), is=h.map(p=>p.i).filter(x=>x!=null);
  const vmin=Math.min(...vs), vmax=Math.max(...vs), imin=Math.min(...is), imax=Math.max(...is);
  const vy=x=>H-10-(x-vmin)/Math.max(1e-9,vmax-vmin)*(H-20);
  const iy=x=>H-10-(x-imin)/Math.max(1e-9,imax-imin)*(H-20);
  const line=(arr,fy,color)=>{g.beginPath();arr.forEach((p,k)=>{const x=k/(h.length-1)*W;const y=fy(p);k?g.lineTo(x,y):g.moveTo(x,y)});g.strokeStyle=color;g.lineWidth=2;g.stroke();};
  line(h.map(p=>p.v),vy,'#5da9ff'); line(h.map(p=>p.i),iy,'#ffb454');
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
                 bind: str = "127.0.0.1", port: int = 8765):
        self.device = device
        self.max_voltage = float(max_voltage)
        self.max_current = float(max_current)
        self.lock = threading.Lock()
        self.httpd = ThreadingHTTPServer((bind, port), self._handler())

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def _state(self, ch: int) -> dict:
        if ch not in self.device.channels:
            raise ValueError(f"channel {ch} not available")
        return {
            "ok": True,
            "idn": self.device.idn,
            "family": self.device.family,
            "channels": list(self.device.channels),
            "ch": ch,
            "output": self.device.output_state(ch),
            "setpoint": {"voltage": self.device.get_voltage(ch),
                         "current": self.device.get_current(ch)},
            "measurement": {"voltage": self.device.measure_voltage(ch),
                            "current": self.device.measure_current(ch),
                            "power": self.device.measure_power(ch)
                            if self.device.supports_power else None},
            "limits": {"max_voltage": self.max_voltage, "max_current": self.max_current},
        }

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
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

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send(200, INDEX_HTML, "text/html; charset=utf-8")
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
    url = f"http://{a.bind}:{server.port}/"
    print(f"web UI: {url}")
    if a.open:
        webbrowser.open(url)
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
