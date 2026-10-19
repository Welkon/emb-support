import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, Ban, Download, Gauge, Info, Power, ShieldCheck,
  SlidersHorizontal, Timer, Waves, Zap,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
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
const METRIC_META: Record<Metric, { unit: string; color: string; key: keyof Point; label: string }> = {
  voltage: { unit: "V", color: "#60a5fa", key: "v", label: "Voltage" },
  current: { unit: "A", color: "#fbbf24", key: "i", label: "Current" },
  power: { unit: "W", color: "#34d399", key: "p", label: "Power" },
};

async function api(path: string, body?: unknown): Promise<State> {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data as State;
}

function MetricTile({ label, value, unit, sub, icon: Icon, accent, big }: {
  label: string; value: string; unit: string; sub?: string;
  icon: React.ElementType; accent: string; big?: boolean;
}) {
  return (
    <div className="relative flex-1 px-5 py-4">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" style={{ color: accent }} /> {label}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className={cn("font-mono font-semibold tabular-nums tracking-tight", big ? "text-4xl" : "text-3xl")}>
          {value}
        </span>
        <span className="text-xs text-muted-foreground">{unit}</span>
      </div>
      <div className="mt-1 h-4 text-[11px] text-muted-foreground">{sub ?? ""}</div>
    </div>
  );
}

function LimitBar({ label, value, max, unit }: { label: string; value: number | null; max?: number; unit: string }) {
  const pct = max && value != null ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono tabular-nums">{fmt(value, unit === "A" ? 3 : 2)} / {max ?? "—"} {unit}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary/80 transition-all" style={{ width: `${pct}%` }} />
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
    setHistory((h) => [...h, { t: Date.now(), v: s.measurement.voltage, i: s.measurement.current, p: s.measurement.power }].slice(-240));
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

  const setpoints = () => run(() => api("/api/set", { ch: channel, voltage: parseFloat(vset), current: parseFloat(iset) }));
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
  const meta = METRIC_META[activeMetric];
  const last = history[history.length - 1];

  const download = () => {
    const rows = ["time,voltage,current,power"];
    for (const p of history) rows.push(`${new Date(p.t).toISOString()},${p.v ?? ""},${p.i ?? ""},${p.p ?? ""}`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
    a.download = "psu-log.csv";
    a.click();
  };

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-[1180px] space-y-5 px-5 py-7 lg:px-8">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-card shadow-sm">
              <Zap className="h-5 w-5 text-primary" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold tracking-tight">Power Supply</h1>
                <Badge variant="outline" className="font-mono">{data?.family ?? "—"}</Badge>
                <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className={cn("h-1.5 w-1.5 rounded-full", data ? "bg-success" : "bg-muted-foreground/40")} />
                  {data ? "live" : "connecting"}
                </span>
              </div>
              <p className="mt-0.5 font-mono text-xs text-muted-foreground">{data?.idn ?? "no device"}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {data?.limits.max_voltage != null && <Badge variant="secondary">0–{data.limits.max_voltage} V</Badge>}
            {data?.limits.max_current != null && <Badge variant="secondary">0–{data.limits.max_current} A</Badge>}
            {data?.limits.max_power != null && <Badge variant="secondary">≤{data.limits.max_power} W</Badge>}
            <Badge variant={on ? "success" : "outline"} className="px-3">
              <Power className="h-3 w-3" /> {data?.output ? `OUTPUT ${data.output}` : "OUTPUT —"}
            </Badge>
            {fault && <Badge variant="destructive"><AlertTriangle className="h-3 w-3" /> {WORK_STATES[work!] ?? `STATE ${work}`}</Badge>}
          </div>
        </header>

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
            <Ban className="h-4 w-4 shrink-0" /> {error}
          </div>
        )}

        <Card className="overflow-hidden">
          <div className={cn("flex flex-col divide-y divide-border sm:flex-row sm:divide-x sm:divide-y-0")}>
            <MetricTile label="Output voltage" value={fmt(data?.measurement.voltage, 3)} unit="V"
              sub={`VSET ${fmt(data?.setpoint.voltage, 3)} V`} icon={Gauge} accent="#60a5fa" big />
            <MetricTile label="Output current" value={fmt(data?.measurement.current, 3)} unit="A"
              sub={`ISET ${fmt(data?.setpoint.current, 3)} A`} icon={Activity} accent="#fbbf24" big />
            {caps?.power && <MetricTile label="Output power" value={fmt(data?.measurement.power, 2)} unit="W"
              sub={`limit ${data?.limits.max_power ?? "—"} W`} icon={Zap} accent="#34d399" big />}
            {caps?.input_voltage && <MetricTile label="Input voltage" value={fmt(data?.measurement.input_voltage, 2)} unit="V"
              sub="DC input" icon={CpuIcon} accent="#a78bfa" big />}
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-border px-5 py-2.5 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><Waves className="h-3 w-3" /> mode <b className="font-mono text-foreground">{data?.status?.output_mode ?? "—"}</b></span>
            <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3 w-3" /> state <b className={cn("font-mono", fault ? "text-destructive" : "text-foreground")}>{work === undefined ? "—" : WORK_STATES[work] ?? `CODE ${work}`}</b></span>
            <span className="inline-flex items-center gap-1.5"><SlidersHorizontal className="h-3 w-3" /> channel <b className="font-mono text-foreground">CH{data?.ch ?? channel}</b> of {data?.channels.length ?? 1}</span>
            <span className="ml-auto inline-flex items-center gap-1.5"><Timer className="h-3 w-3" /> 1 s polling</span>
          </div>
        </Card>

        <div className="grid gap-4 lg:grid-cols-12">
          <Card className="lg:col-span-8">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle>History · {meta.label}</CardTitle>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono">{fmt(last?.[meta.key] ?? null, activeMetric === "power" ? 2 : 3)} {meta.unit}</Badge>
                <Tabs value={activeMetric} onValueChange={(v) => setMetric(v as Metric)}>
                  <TabsList>
                    <TabsTrigger value="voltage">V</TabsTrigger>
                    <TabsTrigger value="current">A</TabsTrigger>
                    {caps?.power && <TabsTrigger value="power">W</TabsTrigger>}
                  </TabsList>
                </Tabs>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-[260px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={history} margin={{ top: 8, right: 10, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={meta.color} stopOpacity={0.30} />
                        <stop offset="100%" stopColor={meta.color} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="hsl(240 3.7% 15.9%)" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="t" hide />
                    <YAxis width={54} domain={["auto", "auto"]} tickLine={false} axisLine={false}
                      tick={{ fill: "hsl(240 5% 64%)", fontSize: 11 }}
                      tickFormatter={(v: number) => v.toFixed(activeMetric === "power" ? 2 : 3)} />
                    <Tooltip
                      contentStyle={{ background: "hsl(240 6% 8%)", border: "1px solid hsl(240 3.7% 18%)", borderRadius: 10, fontSize: 12 }}
                      labelFormatter={(t) => new Date(Number(t)).toLocaleTimeString()}
                      formatter={(v: number) => [`${v} ${meta.unit}`, meta.label]}
                    />
                    <Area type="monotone" dataKey={meta.key} stroke={meta.color} strokeWidth={2}
                      fill="url(#fill)" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                <span>{history.length} samples</span>
                <span>last update {new Date().toLocaleTimeString()}</span>
              </div>
            </CardContent>
          </Card>

          <Card className="lg:col-span-4">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle>Control</CardTitle>
              {(data?.channels.length ?? 1) > 1 && (
                <Tabs value={String(channel)} onValueChange={(v) => { setChannel(Number(v)); setHistory([]); }}>
                  <TabsList>
                    {data!.channels.map((c) => <TabsTrigger key={c} value={String(c)}>CH{c}</TabsTrigger>)}
                  </TabsList>
                </Tabs>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
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
                <Button variant="secondary" disabled={busy} onClick={() => output(false)}>OFF</Button>
                <Button variant="destructive" disabled={busy} onClick={allOff}><Ban /> ALL OFF</Button>
              </div>

              {(caps?.ovp || caps?.ocp) && (
                <div className="space-y-3 border-t border-border pt-4">
                  <div className="grid grid-cols-2 gap-3">
                    {caps.ovp && (
                      <div className="space-y-1.5">
                        <Label htmlFor="ovp">OVP <span className="text-muted-foreground/60">≤ {data?.limits.max_ovp ?? "—"} V</span></Label>
                        <Input id="ovp" inputMode="decimal" value={ovp} placeholder="e.g. 6.0" onChange={(e) => setOvp(e.target.value)} />
                      </div>
                    )}
                    {caps.ocp && (
                      <div className="space-y-1.5">
                        <Label htmlFor="ocp">OCP <span className="text-muted-foreground/60">≤ {data?.limits.max_ocp ?? "—"} A</span></Label>
                        <Input id="ocp" inputMode="decimal" value={ocp} placeholder="e.g. 1.0" onChange={(e) => setOcp(e.target.value)} />
                      </div>
                    )}
                  </div>
                  <Button variant="secondary" className="w-full" disabled={busy} onClick={protect}><ShieldCheck /> Set protection</Button>
                </div>
              )}

              <p className="flex gap-2 border-t border-border pt-4 text-[11px] leading-relaxed text-muted-foreground">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Output ON requires confirmation. Limits are enforced by the server, not only by this page.
              </p>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader><CardTitle>Status</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">Output</span>
                <Badge variant={on ? "success" : "outline"}><Power className="h-3 w-3" /> {data?.output ?? "—"}</Badge></div>
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">Mode</span><span className="font-mono">{data?.status?.output_mode ?? "—"}</span></div>
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">Work state</span>
                <span className={cn("font-mono", fault && "text-destructive")}>{work === undefined ? "—" : WORK_STATES[work] ?? `CODE ${work}`}</span></div>
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">Setpoint</span>
                <span className="font-mono">{fmt(data?.setpoint.voltage, 3)} V · {fmt(data?.setpoint.current, 3)} A</span></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Limits</CardTitle></CardHeader>
            <CardContent className="space-y-3.5">
              <LimitBar label="Voltage" value={data?.measurement.voltage ?? null} max={data?.limits.max_voltage} unit="V" />
              <LimitBar label="Current" value={data?.measurement.current ?? null} max={data?.limits.max_current} unit="A" />
              <div className="grid grid-cols-2 gap-2 pt-1 text-[11px] text-muted-foreground">
                <span>OVP max <b className="font-mono text-foreground">{data?.limits.max_ovp ?? "—"} V</b></span>
                <span>OCP max <b className="font-mono text-foreground">{data?.limits.max_ocp ?? "—"} A</b></span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Session log</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">{history.length} samples buffered in this browser session.</p>
              <Button variant="secondary" className="w-full" onClick={download} disabled={!history.length}>
                <Download /> Download CSV
              </Button>
              <p className="text-[11px] text-muted-foreground">Refreshing the page clears the buffer; use <span className="font-mono">psu.py log</span> for long recordings.</p>
            </CardContent>
          </Card>
        </div>

        <Dialog open={confirmOn} onOpenChange={setConfirmOn}>
          <DialogContent>
            <DialogTitle>Enable output?</DialogTitle>
            <DialogDescription>
              CH{channel} will be enabled at {vset || "—"} V / {iset || "—"} A. Check the load before continuing.
            </DialogDescription>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirmOn(false)}>Cancel</Button>
              <Button variant="success" onClick={() => { setConfirmOn(false); output(true); }}><Power /> Enable</Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

function CpuIcon(props: React.ComponentProps<"svg">) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <rect x="9" y="9" width="6" height="6" />
      <path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" />
    </svg>
  );
}
