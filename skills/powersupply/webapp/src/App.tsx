import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, Ban, Cpu, Download, Gauge, Info, Power,
  ShieldCheck, SlidersHorizontal, Thermometer, Zap,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn, fmt } from "@/lib/utils";

type Limits = { max_voltage?: number; max_current?: number; max_ovp?: number; max_ocp?: number; max_power?: number };
type Caps = { power: boolean; ovp: boolean; ocp: boolean; output_state: boolean; input_voltage: boolean };
type Measurement = { voltage: number | null; current: number | null; power: number | null; input_voltage: number | null };
type State = {
  ok: boolean; idn: string; family: string; channels: number[]; ch: number;
  output: string | null; setpoint: { voltage: number | null; current: number | null };
  measurement: Measurement; status: { output_mode?: string; work_state?: number } | null;
  capabilities: Caps; limits: Limits;
};
type Point = { t: number; v: number | null; i: number | null; p: number | null };
type Metric = "voltage" | "current" | "power";

const WORK_STATES: Record<number, string> = {
  0: "NM", 1: "OVP", 2: "OCP", 3: "OPP", 4: "OTP", 5: "REP", 6: "UVP",
};

async function api(path: string, body?: unknown): Promise<State> {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data as State;
}

function Stat({ icon: Icon, label, value, unit }: {
  icon: React.ElementType; label: string; value: string; unit: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-background/60 p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className="h-3.5 w-3.5" />{label}</div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="font-mono text-3xl font-semibold tabular-nums tracking-tight">{value}</span>
        <span className="text-xs text-muted-foreground">{unit}</span>
      </div>
    </div>
  );
}

export default function App() {
  const [data, setData] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Point[]>([]);
  const [channel, setChannel] = useState(1);
  const [metric, setMetric] = useState<Metric>("voltage");
  const [vset, setVset] = useState("");
  const [iset, setIset] = useState("");
  const [ovp, setOvp] = useState("");
  const [ocp, setOcp] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmOn, setConfirmOn] = useState(false);
  const editing = useRef<string | null>(null);

  const applyState = useCallback((s: State) => {
    setData(s);
    setError("");
    setHistory((h) => [...h, {
      t: Date.now(), v: s.measurement.voltage, i: s.measurement.current, p: s.measurement.power,
    }].slice(-240));
    if (editing.current !== "v") setVset(fmt(s.setpoint.voltage, 3));
    if (editing.current !== "i") setIset(fmt(s.setpoint.current, 3));
  }, []);

  const refresh = useCallback(async (ch = channel) => {
    try { applyState(await api(`/api/state?ch=${ch}`)); }
    catch (e) { setError((e as Error).message); }
  }, [applyState, channel]);

  useEffect(() => {
    refresh(channel);
    const id = setInterval(() => refresh(channel), 1000);
    return () => clearInterval(id);
  }, [channel, refresh]);

  const run = async (fn: () => Promise<State>) => {
    setBusy(true);
    try { applyState(await fn()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const setpoints = () => run(() => api("/api/set", {
    ch: channel, voltage: parseFloat(vset), current: parseFloat(iset),
  }));
  const output = (on: boolean) => run(() => api("/api/output", { ch: channel, on, confirm: on }));
  const allOff = () => run(() => api("/api/all-off", {}));
  const protect = () => run(() => api("/api/protect", {
    ch: channel,
    ovp: ovp === "" ? undefined : parseFloat(ovp),
    ocp: ocp === "" ? undefined : parseFloat(ocp),
  }));

  const caps = data?.capabilities;
  const on = (data?.output || "").toUpperCase() === "ON";
  const work = data?.status?.work_state;
  const fault = work !== undefined && work !== 0;
  const metrics = useMemo(() => {
    const list: Metric[] = ["voltage", "current"];
    if (caps?.power) list.push("power");
    return list;
  }, [caps?.power]);
  const activeMetric = metrics.includes(metric) ? metric : "voltage";
  const series = activeMetric === "voltage" ? "v" : activeMetric === "current" ? "i" : "p";
  const color = activeMetric === "voltage" ? "#5da9ff" : activeMetric === "current" ? "#ffb454" : "#59d98e";

  const download = () => {
    const rows = ["time,voltage,current,power"];
    for (const p of history) rows.push(`${new Date(p.t).toISOString()},${p.v ?? ""},${p.i ?? ""},${p.p ?? ""}`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
    a.download = "psu-log.csv";
    a.click();
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-6xl px-5 py-7 lg:px-8">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <Zap className="h-5 w-5 text-primary" /> Power Supply
              <Badge variant={on ? "success" : "outline"} className="ml-1">
                <Power className="h-3 w-3" /> {data?.output ? `OUTPUT ${data.output}` : "OUTPUT ?"}
              </Badge>
              {fault && <Badge variant="destructive"><AlertTriangle className="h-3 w-3" /> {WORK_STATES[work!] ?? `STATE ${work}`}</Badge>}
            </h1>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {data ? <>{data.idn} <span className="text-muted-foreground/60">[{data.family}]</span></> : "connecting…"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {data?.limits.max_voltage !== undefined && <Badge variant="secondary">0–{data.limits.max_voltage} V</Badge>}
            {data?.limits.max_current !== undefined && <Badge variant="secondary">0–{data.limits.max_current} A</Badge>}
            {data?.limits.max_power !== undefined && <Badge variant="secondary">≤{data.limits.max_power} W</Badge>}
            {caps?.input_voltage && data?.measurement.input_voltage != null &&
              <Badge variant="outline"><Cpu className="h-3 w-3" /> VIN {fmt(data.measurement.input_voltage, 2)} V</Badge>}
          </div>
        </header>

        {error && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
            <Ban className="h-4 w-4 shrink-0" /> {error}
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-7">
            <Card>
              <CardHeader><CardTitle>Live telemetry</CardTitle></CardHeader>
              <CardContent>
                <div className={cn("grid gap-3", caps?.power ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2")}>
                  <Stat icon={Gauge} label="VOUT" value={fmt(data?.measurement.voltage, 3)} unit="V" />
                  <Stat icon={Activity} label="IOUT" value={fmt(data?.measurement.current, 3)} unit="A" />
                  {caps?.power && <Stat icon={Zap} label="POUT" value={fmt(data?.measurement.power, 2)} unit="W" />}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-center justify-between space-y-0">
                <CardTitle>History</CardTitle>
                <Tabs value={activeMetric} onValueChange={(v) => setMetric(v as Metric)}>
                  <TabsList>
                    <TabsTrigger value="voltage">Voltage</TabsTrigger>
                    <TabsTrigger value="current">Current</TabsTrigger>
                    {caps?.power && <TabsTrigger value="power">Power</TabsTrigger>}
                  </TabsList>
                </Tabs>
              </CardHeader>
              <CardContent>
                <div className="h-[230px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={history} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#262b36" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="t" hide />
                      <YAxis width={52} domain={["auto", "auto"]} tickLine={false} axisLine={false}
                        tick={{ fill: "#8b93a7", fontSize: 11 }}
                        tickFormatter={(v: number) => v.toFixed(activeMetric === "power" ? 2 : 3)} />
                      <Tooltip
                        contentStyle={{ background: "#171a21", border: "1px solid #262b36", borderRadius: 8, fontSize: 12 }}
                        labelFormatter={(t) => new Date(Number(t)).toLocaleTimeString()}
                        formatter={(v: number) => [`${v} ${activeMetric === "voltage" ? "V" : activeMetric === "current" ? "A" : "W"}`, activeMetric]}
                      />
                      <Area type="monotone" dataKey={series} stroke={color} strokeWidth={2}
                        fill="url(#fill)" isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                  <span>{history.length} samples · 1 s polling</span>
                  <span>now {fmt(activeMetric === "voltage" ? data?.measurement.voltage : activeMetric === "current" ? data?.measurement.current : data?.measurement.power, activeMetric === "voltage" ? 3 : 2)}</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle><span className="inline-flex items-center gap-2"><SlidersHorizontal className="h-3.5 w-3.5" /> Control</span></CardTitle></CardHeader>
              <CardContent className="space-y-4">
                {(data?.channels.length ?? 1) > 1 && (
                  <Tabs value={String(channel)} onValueChange={(v) => { setChannel(Number(v)); setHistory([]); }}>
                    <TabsList>
                      {data!.channels.map((c) => <TabsTrigger key={c} value={String(c)}>CH{c}</TabsTrigger>)}
                    </TabsList>
                  </Tabs>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="vset">VSET</Label>
                    <div className="relative">
                      <Input id="vset" inputMode="decimal" value={vset} onChange={(e) => setVset(e.target.value)}
                        onFocus={() => (editing.current = "v")} onBlur={() => (editing.current = null)} className="pr-8" />
                      <span className="pointer-events-none absolute right-3 top-2 text-xs text-muted-foreground">V</span>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="iset">ISET</Label>
                    <div className="relative">
                      <Input id="iset" inputMode="decimal" value={iset} onChange={(e) => setIset(e.target.value)}
                        onFocus={() => (editing.current = "i")} onBlur={() => (editing.current = null)} className="pr-8" />
                      <span className="pointer-events-none absolute right-3 top-2 text-xs text-muted-foreground">A</span>
                    </div>
                  </div>
                </div>
                <Button className="w-full" disabled={busy} onClick={setpoints}>Apply setpoints</Button>
                <div className="grid grid-cols-3 gap-2">
                  <Button variant="success" disabled={busy} onClick={() => setConfirmOn(true)}><Power /> ON</Button>
                  <Button variant="outline" disabled={busy} onClick={() => output(false)}>OFF</Button>
                  <Button variant="destructive" disabled={busy} onClick={allOff}><Ban /> ALL OFF</Button>
                </div>

                {(caps?.ovp || caps?.ocp) && (
                  <div className="space-y-3 border-t border-border pt-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                      {caps.ovp && (
                        <div className="space-y-1.5">
                          <Label htmlFor="ovp">OVP {data?.limits.max_ovp !== undefined && <span className="text-muted-foreground/60">≤ {data.limits.max_ovp} V</span>}</Label>
                          <Input id="ovp" inputMode="decimal" value={ovp} placeholder="e.g. 6.0" onChange={(e) => setOvp(e.target.value)} />
                        </div>
                      )}
                      {caps.ocp && (
                        <div className="space-y-1.5">
                          <Label htmlFor="ocp">OCP {data?.limits.max_ocp !== undefined && <span className="text-muted-foreground/60">≤ {data.limits.max_ocp} A</span>}</Label>
                          <Input id="ocp" inputMode="decimal" value={ocp} placeholder="e.g. 1.0" onChange={(e) => setOcp(e.target.value)} />
                        </div>
                      )}
                    </div>
                    <Button variant="secondary" className="w-full" disabled={busy} onClick={protect}><ShieldCheck /> Set protection</Button>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4 lg:col-span-5">
            <Card>
              <CardHeader><CardTitle>Status</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Output</span>
                  <Badge variant={on ? "success" : "outline"} className="px-3 py-1 text-xs">
                    <Power className="h-3 w-3" /> {data?.output ?? "—"}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Mode</span>
                  <span className="font-mono text-sm">{data?.status?.output_mode ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Work state</span>
                  <span className={cn("font-mono text-sm", fault && "text-destructive")}>
                    {work === undefined ? "—" : WORK_STATES[work] ?? `CODE ${work}`}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Setpoint</span>
                  <span className="font-mono text-sm">{fmt(data?.setpoint.voltage, 3)} V · {fmt(data?.setpoint.current, 3)} A</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Channel</span>
                  <span className="font-mono text-sm">CH{data?.ch ?? channel} ({data?.channels.length ?? 1} total)</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle><span className="inline-flex items-center gap-2"><ShieldCheck className="h-3.5 w-3.5" /> Limits</span></CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                {data ? Object.entries(data.limits).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <span className="text-muted-foreground">{k.replace("max_", "").toUpperCase()}</span>
                    <span className="font-mono">{String(v)}{k.endsWith("voltage") || k.endsWith("ovp") ? " V" : k.endsWith("current") || k.endsWith("ocp") ? " A" : k.endsWith("power") ? " W" : ""}</span>
                  </div>
                )) : <span className="text-muted-foreground">—</span>}
                <div className="flex gap-2 rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  Output ON requires confirmation. Limits are enforced by the server, not just the UI.
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle><span className="inline-flex items-center gap-2"><Download className="h-3.5 w-3.5" /> Session log</span></CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">{history.length} samples in this browser session.</p>
                <Button variant="secondary" className="w-full" onClick={download} disabled={!history.length}>Download CSV</Button>
              </CardContent>
            </Card>
          </div>
        </div>

        <Dialog open={confirmOn} onOpenChange={setConfirmOn}>
          <DialogContent>
            <DialogTitle>Enable output?</DialogTitle>
            <DialogDescription>
              CH{channel} will be enabled at {vset || "—"} V / {iset || "—"} A.
              Check the load and probe before continuing.
            </DialogDescription>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirmOn(false)}>Cancel</Button>
              <Button variant="success" onClick={() => { setConfirmOn(false); output(true); }}>
                <Power /> Enable
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
