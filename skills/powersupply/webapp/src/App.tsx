import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, Ban, Download, Gauge, Info, Languages, Moon,
  Power, ShieldCheck, SlidersHorizontal, Sun, Timer, Waves, Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LiveChart } from "@/components/LiveChart";
import { cn, fmt } from "@/lib/utils";

type Lang = "en" | "zh";
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

const WORK_EN = ["NM", "OVP", "OCP", "OPP", "OTP", "REP", "UVP"];
const WORK_ZH = ["正常", "过压", "过流", "过功率", "过温", "反接", "欠压"];

const STR = {
  en: {
    title: "Power Supply", live: "live", connecting: "connecting", noDevice: "no device",
    output: "Output", outputVoltage: "Output voltage", outputCurrent: "Output current",
    outputPower: "Output power", inputVoltage: "Input voltage", vset: "VSET", iset: "ISET",
    limit: "limit", dcInput: "DC input", mode: "mode", state: "state", channel: "channel", of: "of",
    polling: "1 s polling", history: "History", control: "Control", apply: "Apply setpoints",
    on: "ON", off: "OFF", allOff: "ALL OFF", ovp: "OVP", ocp: "OCP", setProtection: "Set protection",
    outputNote: "Output ON requires confirmation. Limits are enforced by the server, not only by this page.",
    status: "Status", setpoint: "Setpoint", limits: "Limits", voltage: "Voltage", current: "Current",
    power: "Power", ovpMax: "OVP max", ocpMax: "OCP max", sessionLog: "Session log",
    samplesBuffered: "{n} samples buffered in this browser session.", downloadCsv: "Download CSV",
    refreshNote: "Refreshing the page clears the buffer; use psu.py log for long recordings.",
    enableOutput: "Enable output?", cancel: "Cancel", enable: "Enable",
    confirmDesc: "CH{ch} will be enabled at {v} V / {i} A. Check the load before continuing.",
    samples: "{n} samples", lastUpdate: "last update", light: "Light", dark: "Dark",
    work: WORK_EN,
  },
  zh: {
    title: "数控电源", live: "在线", connecting: "连接中", noDevice: "未连接设备",
    output: "输出", outputVoltage: "输出电压", outputCurrent: "输出电流",
    outputPower: "输出功率", inputVoltage: "输入电压", vset: "设定电压", iset: "设定电流",
    limit: "上限", dcInput: "直流输入", mode: "模式", state: "状态", channel: "通道", of: "共",
    polling: "1 秒轮询", history: "历史曲线", control: "控制", apply: "应用设定值",
    on: "开", off: "关", allOff: "全部关闭", ovp: "过压保护", ocp: "过流保护", setProtection: "设置保护",
    outputNote: "开启输出需要二次确认；限值由服务端强制，不只是页面限制。",
    status: "状态", setpoint: "设定值", limits: "限值", voltage: "电压", current: "电流",
    power: "功率", ovpMax: "OVP 上限", ocpMax: "OCP 上限", sessionLog: "本次记录",
    samplesBuffered: "当前浏览器缓存 {n} 个采样点。", downloadCsv: "下载 CSV",
    refreshNote: "刷新页面会清空缓存；长时间记录请用 psu.py log。",
    enableOutput: "确认开启输出？", cancel: "取消", enable: "开启",
    confirmDesc: "将开启 CH{ch}，设定 {v} V / {i} A。请先确认负载连接。",
    samples: "{n} 个采样", lastUpdate: "更新于", light: "亮色", dark: "暗色",
    work: WORK_ZH,
  },
} as const;

type Dict = (typeof STR)["en"];

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
        <span className={cn("font-mono font-semibold tabular-nums tracking-tight", big ? "text-4xl" : "text-3xl")}>{value}</span>
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
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem("psu-lang") as Lang) || (navigator.language.startsWith("zh") ? "zh" : "en"));
  const [dark, setDark] = useState<boolean>(() => document.documentElement.classList.contains("dark"));
  const editing = useRef<string | null>(null);
  const t: Dict = STR[lang];
  const locale = lang === "zh" ? "zh-CN" : "en-US";

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("psu-theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    document.documentElement.lang = lang;
    localStorage.setItem("psu-lang", lang);
  }, [lang]);

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
    ch: channel, ovp: ovp === "" ? undefined : parseFloat(ovp), ocp: ocp === "" ? undefined : parseFloat(ocp),
  }));

  const caps = data?.capabilities;
  const on = (data?.output || "").toUpperCase() === "ON";
  const work = data?.status?.work_state;
  const fault = work !== undefined && work !== 0;
  const workName = work === undefined ? "—" : t.work[work] ?? `CODE ${work}`;
  const metrics = useMemo(() => {
    const list: Metric[] = ["voltage", "current"];
    if (caps?.power) list.push("power");
    return list;
  }, [caps?.power]);
  const activeMetric = metrics.includes(metric) ? metric : "voltage";
  const metricMeta = {
    voltage: { unit: "V", color: "#60a5fa", key: "v" as const },
    current: { unit: "A", color: "#fbbf24", key: "i" as const },
    power: { unit: "W", color: "#34d399", key: "p" as const },
  }[activeMetric];
  const last = history[history.length - 1];

  const fill = (s: string, vars: Record<string, string | number>) =>
    s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
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
                <h1 className="text-lg font-semibold tracking-tight">{t.title}</h1>
                <Badge variant="outline" className="font-mono">{data?.family ?? "—"}</Badge>
                <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className={cn("h-1.5 w-1.5 rounded-full", data ? "bg-success" : "bg-muted-foreground/40")} />
                  {data ? t.live : t.connecting}
                </span>
              </div>
              <p className="mt-0.5 font-mono text-xs text-muted-foreground">{data?.idn ?? t.noDevice}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {data?.limits.max_voltage != null && <Badge variant="secondary">0–{data.limits.max_voltage} V</Badge>}
            {data?.limits.max_current != null && <Badge variant="secondary">0–{data.limits.max_current} A</Badge>}
            {data?.limits.max_power != null && <Badge variant="secondary">≤{data.limits.max_power} W</Badge>}
            <Badge variant={on ? "success" : "outline"} className="px-3"><Power className="h-3 w-3" /> {data?.output ? `${t.output} ${data.output}` : `${t.output} —`}</Badge>
            {fault && <Badge variant="destructive"><AlertTriangle className="h-3 w-3" /> {workName}</Badge>}
            <Button variant="outline" size="sm" onClick={() => setLang(lang === "en" ? "zh" : "en")} title="Language">
              <Languages /> {lang === "en" ? "中文" : "EN"}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setDark(!dark)} title="Theme">
              {dark ? <Sun /> : <Moon />} {dark ? t.light : t.dark}
            </Button>
          </div>
        </header>

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
            <Ban className="h-4 w-4 shrink-0" /> {error}
          </div>
        )}

        <Card className="overflow-hidden">
          <div className="flex flex-col divide-y divide-border sm:flex-row sm:divide-x sm:divide-y-0">
            <MetricTile label={t.outputVoltage} value={fmt(data?.measurement.voltage, 3)} unit="V"
              sub={`${t.vset} ${fmt(data?.setpoint.voltage, 3)} V`} icon={Gauge} accent="#60a5fa" big />
            <MetricTile label={t.outputCurrent} value={fmt(data?.measurement.current, 3)} unit="A"
              sub={`${t.iset} ${fmt(data?.setpoint.current, 3)} A`} icon={Activity} accent="#fbbf24" big />
            {caps?.power && <MetricTile label={t.outputPower} value={fmt(data?.measurement.power, 2)} unit="W"
              sub={`${t.limit} ${data?.limits.max_power ?? "—"} W`} icon={Zap} accent="#34d399" big />}
            {caps?.input_voltage && <MetricTile label={t.inputVoltage} value={fmt(data?.measurement.input_voltage, 2)} unit="V"
              sub={t.dcInput} icon={CpuIcon} accent="#a78bfa" big />}
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-border px-5 py-2.5 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><Waves className="h-3 w-3" /> {t.mode} <b className="font-mono text-foreground">{data?.status?.output_mode ?? "—"}</b></span>
            <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3 w-3" /> {t.state} <b className={cn("font-mono", fault ? "text-destructive" : "text-foreground")}>{workName}</b></span>
            <span className="inline-flex items-center gap-1.5"><SlidersHorizontal className="h-3 w-3" /> {t.channel} <b className="font-mono text-foreground">CH{data?.ch ?? channel}</b> {t.of} {data?.channels.length ?? 1}</span>
            <span className="ml-auto inline-flex items-center gap-1.5"><Timer className="h-3 w-3" /> {t.polling}</span>
          </div>
        </Card>

        <div className="grid gap-4 lg:grid-cols-12">
          <Card className="lg:col-span-8">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle>{t.history} · {t[activeMetric]}</CardTitle>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono">{fmt(last?.[metricMeta.key] ?? null, activeMetric === "power" ? 2 : 3)} {metricMeta.unit}</Badge>
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
              <LiveChart
                points={history}
                metric={activeMetric}
                color={metricMeta.color}
                unit={metricMeta.unit}
                digits={activeMetric === "power" ? 2 : 3}
                dark={dark}
                height={260}
              />
              <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                <span>{fill(t.samples, { n: history.length })}</span>
                <span>{t.lastUpdate} {new Date().toLocaleTimeString(locale)}</span>
              </div>
            </CardContent>
          </Card>

          <Card className="lg:col-span-4">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle>{t.control}</CardTitle>
              {(data?.channels.length ?? 1) > 1 && (
                <Tabs value={String(channel)} onValueChange={(v) => { setChannel(Number(v)); setHistory([]); }}>
                  <TabsList>{data!.channels.map((c) => <TabsTrigger key={c} value={String(c)}>CH{c}</TabsTrigger>)}</TabsList>
                </Tabs>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="vset">{t.vset}</Label>
                  <div className="relative">
                    <Input id="vset" inputMode="decimal" value={vset} onChange={(e) => setVset(e.target.value)}
                      onFocus={() => (editing.current = "v")} onBlur={() => (editing.current = null)} className="pr-8" />
                    <span className="pointer-events-none absolute right-3 top-2 text-xs text-muted-foreground">V</span>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="iset">{t.iset}</Label>
                  <div className="relative">
                    <Input id="iset" inputMode="decimal" value={iset} onChange={(e) => setIset(e.target.value)}
                      onFocus={() => (editing.current = "i")} onBlur={() => (editing.current = null)} className="pr-8" />
                    <span className="pointer-events-none absolute right-3 top-2 text-xs text-muted-foreground">A</span>
                  </div>
                </div>
              </div>
              <Button className="w-full" disabled={busy} onClick={setpoints}>{t.apply}</Button>
              <div className="grid grid-cols-3 gap-2">
                <Button variant="success" disabled={busy} onClick={() => setConfirmOn(true)}><Power /> {t.on}</Button>
                <Button variant="secondary" disabled={busy} onClick={() => output(false)}>{t.off}</Button>
                <Button variant="destructive" disabled={busy} onClick={allOff}><Ban /> {t.allOff}</Button>
              </div>

              {(caps?.ovp || caps?.ocp) && (
                <div className="space-y-3 border-t border-border pt-4">
                  <div className="grid grid-cols-2 gap-3">
                    {caps.ovp && (
                      <div className="space-y-1.5">
                        <Label htmlFor="ovp">{t.ovp} <span className="text-muted-foreground/60">≤ {data?.limits.max_ovp ?? "—"} V</span></Label>
                        <Input id="ovp" inputMode="decimal" value={ovp} placeholder="e.g. 6.0" onChange={(e) => setOvp(e.target.value)} />
                      </div>
                    )}
                    {caps.ocp && (
                      <div className="space-y-1.5">
                        <Label htmlFor="ocp">{t.ocp} <span className="text-muted-foreground/60">≤ {data?.limits.max_ocp ?? "—"} A</span></Label>
                        <Input id="ocp" inputMode="decimal" value={ocp} placeholder="e.g. 1.0" onChange={(e) => setOcp(e.target.value)} />
                      </div>
                    )}
                  </div>
                  <Button variant="secondary" className="w-full" disabled={busy} onClick={protect}><ShieldCheck /> {t.setProtection}</Button>
                </div>
              )}

              <p className="flex gap-2 border-t border-border pt-4 text-[11px] leading-relaxed text-muted-foreground">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {t.outputNote}
              </p>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader><CardTitle>{t.status}</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">{t.output}</span>
                <Badge variant={on ? "success" : "outline"}><Power className="h-3 w-3" /> {data?.output ?? "—"}</Badge></div>
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">{t.mode}</span><span className="font-mono">{data?.status?.output_mode ?? "—"}</span></div>
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">{t.state}</span>
                <span className={cn("font-mono", fault && "text-destructive")}>{workName}</span></div>
              <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">{t.setpoint}</span>
                <span className="font-mono">{fmt(data?.setpoint.voltage, 3)} V · {fmt(data?.setpoint.current, 3)} A</span></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>{t.limits}</CardTitle></CardHeader>
            <CardContent className="space-y-3.5">
              <LimitBar label={t.voltage} value={data?.measurement.voltage ?? null} max={data?.limits.max_voltage} unit="V" />
              <LimitBar label={t.current} value={data?.measurement.current ?? null} max={data?.limits.max_current} unit="A" />
              <div className="grid grid-cols-2 gap-2 pt-1 text-[11px] text-muted-foreground">
                <span>{t.ovpMax} <b className="font-mono text-foreground">{data?.limits.max_ovp ?? "—"} V</b></span>
                <span>{t.ocpMax} <b className="font-mono text-foreground">{data?.limits.max_ocp ?? "—"} A</b></span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>{t.sessionLog}</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">{fill(t.samplesBuffered, { n: history.length })}</p>
              <Button variant="secondary" className="w-full" onClick={download} disabled={!history.length}><Download /> {t.downloadCsv}</Button>
              <p className="text-[11px] text-muted-foreground">{t.refreshNote}</p>
            </CardContent>
          </Card>
        </div>

        <Dialog open={confirmOn} onOpenChange={setConfirmOn}>
          <DialogContent>
            <DialogTitle>{t.enableOutput}</DialogTitle>
            <DialogDescription>{fill(t.confirmDesc, { ch: channel, v: vset || "—", i: iset || "—" })}</DialogDescription>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirmOn(false)}>{t.cancel}</Button>
              <Button variant="success" onClick={() => { setConfirmOn(false); output(true); }}><Power /> {t.enable}</Button>
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
