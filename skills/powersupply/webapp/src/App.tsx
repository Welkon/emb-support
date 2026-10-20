import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CircularInput, CircularProgress, CircularThumb, CircularTrack } from "react-circular-input";
import {
  Activity, AlertTriangle, ChevronDown, Cpu, Database, Download, Gauge, Info, Languages, Minus, Moon, Pause, Play,
  Plus, Power, RotateCcw, Settings2, ShieldCheck, SlidersHorizontal, Square, Sun, Trash2, Volume2, VolumeX, Waves, X, Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LiveChart, type LiveChartHandle } from "@/components/LiveChart";
import { cn, fmt } from "@/lib/utils";

type Lang = "en" | "zh";
type Limits = { max_voltage?: number; max_current?: number; max_ovp?: number; max_ocp?: number; max_power?: number };
type Caps = { power: boolean; ovp: boolean; ocp: boolean; output_state: boolean; input_voltage: boolean; temperature: boolean };
type Measurement = { voltage: number | null; current: number | null; power: number | null; input_voltage: number | null; temperature: number | null };
type Preset = { v: number; i: number };
type ChartSettings = { vDiv: number; vPos: number; iDiv: number; iPos: number; smooth: number; delay: number };
const DEFAULT_CHART_SETTINGS: ChartSettings = {
  vDiv: 0.05, vPos: 0, iDiv: 0.02, iPos: 0, smooth: 0, delay: 160,
};
const VDIV = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10];
const IDIV = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2];

const DEFAULT_PRESETS: Preset[] = [
  { v: 1.8, i: 0.5 }, { v: 3.3, i: 0.5 }, { v: 5, i: 0.5 }, { v: 8, i: 0.5 },
  { v: 9, i: 1 }, { v: 12, i: 1 }, { v: 24, i: 0.5 },
];

type Device = {
  id: string; name: string; idn: string; model: string; serial_number_hex: string;
  family?: string; firmware_version?: string; hardware?: string; output: string;
};
type State = {
  ok: boolean; idn: string; family: string; channels: number[]; ch: number; device?: string; device_name?: string;
  output: string | null; setpoint: { voltage: number | null; current: number | null };
  measurement: Measurement; status: { output_mode?: string; work_state?: number } | null;
  capabilities: Caps; limits: Limits; device_info: Record<string, unknown>;
};

const WORK_EN = ["NM", "OVP", "OCP", "OPP", "OTP", "REP", "UVP"];
const WORK_ZH = ["正常", "过压", "过流", "过功率", "过温", "反接", "欠压"];

const STR = {
  en: {
    title: "Power Supply", live: "live", connecting: "connecting", noDevice: "no device",
    connected: "Connected", disconnected: "Disconnected", pause: "Pause", resume: "Resume", quick: "Quick V",
    presets: "Presets", savePreset: "Save current", presetPlaceholder: "Select a preset…",
    soundOn: "Sound on", soundOff: "Muted",
    chartSettings: "Chart settings", chartSettingsHint: "Tune the Y range, smoothing and display buffer.",
    autoY: "Auto Y range", voltageRange: "Voltage", currentRange: "Current",
    voltsPerDiv: "V / div", ampsPerDiv: "A / div", center: "Center", vPos: "V pos", aPos: "A pos",
    smoothing: "Smoothing", displayDelay: "Display buffer (ms)", reset: "Reset", applySettings: "Apply",
    min: "Min", max: "Max",
    wheelHint: "Scroll to adjust the last digit", applyHint: "Enter or click away to apply",
    deviceAlert: "Device alert", connectionLost: "Device disconnected", operationFailed: "Operation failed",
    connectionHint: "Check the USB cable and power. The page retries automatically.",
    overtemp: "High temperature", overtempHint: "Device temperature is {t} °C. Check ventilation and reduce load.",
    faultHints: {
      0: "Device reports a normal state.",
      1: "Over-voltage protection. Check the load and voltage setting, then re-enable output.",
      2: "Over-current protection. Check the load and current limit, then re-enable output.",
      3: "Over-power protection. Reduce the load before re-enabling output.",
      4: "Over-temperature protection. Let the device cool down and check ventilation.",
      5: "Reverse polarity detected. Check the output wiring.",
      6: "Input under-voltage. Check the DC input supply.",
    },
    output: "Output", outputVoltage: "Output voltage", outputCurrent: "Output current",
    outputPower: "Output power", inputVoltage: "Input voltage", vset: "VSET", iset: "ISET",
    limit: "limit", dcInput: "DC input", mode: "mode", state: "state", channel: "channel", of: "of",
    polling: "5 Hz live", history: "Live", control: "Control", apply: "Apply setpoints",
    devices: "Devices", allOff: "All off",
    on: "ON", off: "OFF", ovp: "OVP", ocp: "OCP", setProtection: "Set protection",
    outputNote: "Output ON requires confirmation. Limits are enforced by the server, not only by this page.",
    status: "Status", setpoint: "Setpoint", limits: "Limits", voltage: "Voltage", current: "Current",
    power: "Power", ovpMax: "OVP max", ocpMax: "OCP max", sessionLog: "Session log",
    samplesBuffered: "{n} samples buffered in this browser session.", downloadCsv: "Download CSV",
    refreshNote: "Refreshing clears the buffer; use psu.py log for long recordings.",
    enableOutput: "Enable output?", cancel: "Cancel", enable: "Enable",
    confirmDesc: "CH{ch} will be enabled at {v} V / {i} A. Check the load before continuing.",
    samples: "{n} samples", lastUpdate: "last update", light: "Light", dark: "Dark",
    basic: "Basic", advanced: "Advanced", device: "Device", basicInfo: "Basic info",
    model: "Model", hardware: "Hardware", app: "App", serial: "Serial", temperature: "Temperature",
    sequence: "Serial output", sequenceHint: "Setpoint list; each row runs in order.",
    addRow: "Add row", run: "Run", stop: "Stop", delay: "Delay (s)", step: "Step",
    voltageScan: "Voltage scanning", currentScan: "Current scanning", start: "Start", end: "End",
    idle: "Idle", running: "Running", row: "Row", cache: "Cache", cacheOn: "Cache on", cacheOff: "Cache off",
    cacheHint: "Off: keep only the visible window. On: keep up to 1 hour for CSV export (chart still draws only the window).",
    showAdvanced: "Show advanced", hideAdvanced: "Hide advanced",
    advancedHint: "Sequence output · voltage/current scan", work: WORK_EN,
  },
  zh: {
    title: "程控电源", live: "在线", connecting: "连接中", noDevice: "未连接设备",
    connected: "已连接", disconnected: "未连接", pause: "暂停", resume: "继续", quick: "常用电压",
    presets: "预设", savePreset: "保存当前", presetPlaceholder: "选择预设…",
    soundOn: "音效开", soundOff: "静音",
    chartSettings: "图表设置", chartSettingsHint: "调整 Y 轴范围、平滑程度和显示缓冲。",
    autoY: "自动 Y 轴范围", voltageRange: "电压", currentRange: "电流",
    voltsPerDiv: "V / 格", ampsPerDiv: "A / 格", center: "中心", vPos: "V 位置", aPos: "A 位置",
    smoothing: "平滑", displayDelay: "显示缓冲 (ms)", reset: "重置", applySettings: "应用",
    min: "最小", max: "最大",
    wheelHint: "滚轮微调最后一位", applyHint: "回车或移出输入框即应用",
    deviceAlert: "设备异常", connectionLost: "设备连接中断", operationFailed: "操作失败",
    connectionHint: "请检查 USB 线和供电；页面会自动重试连接。",
    overtemp: "温度过高", overtempHint: "设备温度 {t} °C，请检查散热并降低负载。",
    faultHints: {
      0: "设备状态正常。",
      1: "过压保护。请检查负载和设定电压，排除后重新开启输出。",
      2: "过流保护。请检查负载和限流设定，排除后重新开启输出。",
      3: "过功率保护。请降低负载后重新开启输出。",
      4: "过温保护。请等待设备冷却并检查散热。",
      5: "输出反接。请检查输出接线。",
      6: "输入欠压。请检查直流输入电源。",
    },
    output: "输出", outputVoltage: "输出电压", outputCurrent: "输出电流",
    outputPower: "输出功率", inputVoltage: "输入电压", vset: "设定电压", iset: "设定电流",
    limit: "上限", dcInput: "直流输入", mode: "模式", state: "状态", channel: "通道", of: "共",
    polling: "5 Hz 实时", history: "实时曲线", control: "控制", apply: "应用设定值",
    devices: "设备", allOff: "全部关闭",
    on: "开", off: "关", ovp: "过压保护", ocp: "过流保护", setProtection: "设置保护",
    outputNote: "开启输出需要二次确认；限值由服务端强制，不只是页面限制。",
    status: "状态", setpoint: "设定值", limits: "限值", voltage: "电压", current: "电流",
    power: "功率", ovpMax: "OVP 上限", ocpMax: "OCP 上限", sessionLog: "本次记录",
    samplesBuffered: "当前浏览器缓存 {n} 个采样点。", downloadCsv: "下载 CSV",
    refreshNote: "刷新页面会清空缓存；长时间记录请用 psu.py log。",
    enableOutput: "确认开启输出？", cancel: "取消", enable: "开启",
    confirmDesc: "将开启 CH{ch}，设定 {v} V / {i} A。请先确认负载连接。",
    samples: "{n} 个采样", lastUpdate: "更新于", light: "亮色", dark: "暗色",
    basic: "基础", advanced: "高级", device: "设备信息", basicInfo: "基本信息",
    model: "型号", hardware: "硬件版本", app: "软件版本", serial: "序列号", temperature: "温度",
    sequence: "序列输出", sequenceHint: "按行依次设置电压/电流，每行可设置延时。",
    addRow: "新增一行", run: "运行", stop: "停止", delay: "延时 (s)", step: "步进",
    voltageScan: "电压扫描", currentScan: "电流扫描", start: "起始", end: "结束",
    idle: "空闲", running: "运行中", row: "行", cache: "缓存", cacheOn: "缓存开", cacheOff: "缓存关",
    cacheHint: "关闭时只保留当前窗口；开启时最多保留 1 小时，用于导出 CSV。",
    showAdvanced: "展开高级功能", hideAdvanced: "收起高级功能",
    advancedHint: "序列输出 · 电压/电流扫描", work: WORK_ZH,
  },
} as const;
type Dict = (typeof STR)[Lang];

async function api(path: string, body?: unknown): Promise<State> {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data as State;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

function MetricsSkeleton() {
  return (
    <div className="overflow-hidden border-y border-border">
      <div className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-4 sm:divide-y-0">
        {[0, 1, 2, 3].map((k) => (
          <div key={k} className="px-5 py-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-9 w-32" />
            <Skeleton className="mt-2 h-3 w-20" />
          </div>
        ))}
      </div>
      <div className="border-t border-border px-5 py-3"><Skeleton className="h-3 w-56" /></div>
    </div>
  );
}

function MetricTile({ label, value, unit, sub, icon: Icon, accent }: {
  label: string; value: string; unit: string; sub?: string; icon: React.ElementType; accent: string;
}) {
  return (
    <div className="flex-1 px-5 py-4">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" style={{ color: accent }} /> {label}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="font-mono text-3xl font-semibold tabular-nums tracking-tight">{value}</span>
        <span className="text-xs text-muted-foreground">{unit}</span>
      </div>
      <div className="mt-1 h-4 text-[11px] text-muted-foreground">{sub ?? ""}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-mono">{value}</span>
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
  const [connected, setConnected] = useState(false);
  const chartRef = useRef<LiveChartHandle>(null);
  const [sampleCount, setSampleCount] = useState(0);
  const [channel, setChannel] = useState(1);
  const [tab, setTab] = useState(() => (new URLSearchParams(location.search).get("advanced") === "1" ? "advanced" : "basic"));
  const [showV, setShowV] = useState(() => localStorage.getItem("psu-show-v") !== "0");
  const [showA, setShowA] = useState(() => localStorage.getItem("psu-show-a") !== "0");
  const [windowMs, setWindowMs] = useState(() => {
    const saved = Number(localStorage.getItem("psu-window-v2"));
    return [10000, 30000, 60000].includes(saved) ? saved : 30000;
  });
  const [cache, setCache] = useState(false);
  const [paused, setPaused] = useState(false);
  const [chartSettings, setChartSettings] = useState<ChartSettings>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem("psu-chart-settings") || "null");
      if (!raw) return DEFAULT_CHART_SETTINGS;
      const saved = { ...DEFAULT_CHART_SETTINGS, ...raw };
      if (!VDIV.includes(saved.vDiv)) saved.vDiv = DEFAULT_CHART_SETTINGS.vDiv;
      if (!IDIV.includes(saved.iDiv)) saved.iDiv = DEFAULT_CHART_SETTINGS.iDiv;
      return saved;
    } catch { return DEFAULT_CHART_SETTINGS; }
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<ChartSettings>(chartSettings);
  const [vScopeRef, setVScopeRef] = useState(chartSettings.vPos);
  const [iScopeRef, setIScopeRef] = useState(chartSettings.iPos);
  const [vset, setVset] = useState("");
  const [iset, setIset] = useState("");
  const [ovp, setOvp] = useState("");
  const [ocp, setOcp] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmOn, setConfirmOn] = useState(false);
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem("psu-lang") as Lang) || (navigator.language.startsWith("zh") ? "zh" : "en"));
  const [dark, setDark] = useState<boolean>(() => document.documentElement.classList.contains("dark"));
  const editing = useRef<string | null>(null);
  const lastAlertRef = useRef("");
  const headerRef = useRef<HTMLElement>(null);
  const [headerH, setHeaderH] = useState(72);
  const [desktop] = useState(() => new URLSearchParams(location.search).has("desktop") || Boolean((window as any).wails?.Window));
  const wailsWindow = () => (window as any).wails?.Window;
  const [devices, setDevices] = useState<Device[]>([]);
  const [deviceId, setDeviceId] = useState(() => localStorage.getItem("psu-device") || "");
  const [toast, setToast] = useState<{ title: string; detail: string } | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const [sound, setSound] = useState(() => localStorage.getItem("psu-sound") !== "0");
  const soundRef = useRef(sound);
  const audioRef = useRef<AudioContext | null>(null);
  const prevOutputRef = useRef<string | null>(null);
  const prevAlertSoundRef = useRef("");
  soundRef.current = sound;
  const playTone = useCallback((freq: number, duration = 0.09, delay = 0, gain = 0.035) => {
    if (!soundRef.current) return;
    try {
      const Ctx = window.AudioContext || (window as any).webkitAudioContext;
      if (!Ctx) return;
      let ctx = audioRef.current;
      if (!ctx) { ctx = new Ctx(); audioRef.current = ctx; }
      if (ctx.state === "suspended") void ctx.resume();
      const at = ctx.currentTime + delay;
      const osc = ctx.createOscillator();
      const amp = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, at);
      amp.gain.setValueAtTime(0.0001, at);
      amp.gain.exponentialRampToValueAtTime(gain, at + 0.012);
      amp.gain.exponentialRampToValueAtTime(0.0001, at + duration);
      osc.connect(amp).connect(ctx.destination);
      osc.start(at);
      osc.stop(at + duration + 0.03);
    } catch { /* audio is optional */ }
  }, []);
  useEffect(() => { localStorage.setItem("psu-sound", sound ? "1" : "0"); }, [sound]);
  const [presets, setPresets] = useState<Preset[]>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem("psu-presets") || "null");
      if (Array.isArray(raw)) {
        const valid = raw.filter((p: any) => p && Number.isFinite(p.v) && Number.isFinite(p.i));
        if (valid.length) return valid.slice(0, 8);
      }
    } catch { /* ignore */ }
    return DEFAULT_PRESETS;
  });
  const t = STR[lang];
  const locale = lang === "zh" ? "zh-CN" : "en-US";

  useLayoutEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setHeaderH(el.getBoundingClientRect().height));
    ro.observe(el);
    setHeaderH(el.getBoundingClientRect().height);
    return () => ro.disconnect();
  }, []);
  useEffect(() => { localStorage.setItem("psu-window-v2", String(windowMs)); }, [windowMs]);
  useEffect(() => { localStorage.setItem("psu-chart-settings", JSON.stringify(chartSettings)); }, [chartSettings]);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("psu-theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    document.documentElement.lang = lang;
    localStorage.setItem("psu-lang", lang);
  }, [lang]);
  useEffect(() => { localStorage.setItem("psu-presets", JSON.stringify(presets)); }, [presets]);
  useEffect(() => {
    localStorage.setItem("psu-show-v", showV ? "1" : "0");
    localStorage.setItem("psu-show-a", showA ? "1" : "0");
  }, [showV, showA]);

  const applyState = useCallback((s: State) => {
    setData(s);
    setConnected(true);
    setError("");
    const activeId = document.activeElement?.id;
    if (editing.current !== "v" && activeId !== "vset") setVset(fmt(s.setpoint.voltage, 3));
    if (editing.current !== "i" && activeId !== "iset") setIset(fmt(s.setpoint.current, 3));
  }, []);

  const refresh = useCallback(async (ch = channel) => {
    const q = deviceId ? `&device=${encodeURIComponent(deviceId)}` : "";
    try { applyState(await api(`/api/state?ch=${ch}${q}`)); }
    catch (e) { setConnected(false); setError((e as Error).message); }
  }, [applyState, channel, deviceId]);

  const loadDevices = useCallback(async () => {
    try {
      const d = await (await fetch("/api/devices")).json();
      const list: Device[] = d?.devices ?? [];
      setDevices(list);
      setDeviceId((prev) => {
        const saved = localStorage.getItem("psu-device") || "";
        const found = [prev, saved, d?.default, list[0]?.id].find((id) => typeof id === "string" && list.some((x) => x.id === id));
        return found ?? "";
      });
    } catch { /* keep the last list */ }
  }, []);
  useEffect(() => {
    loadDevices();
    const id = window.setInterval(loadDevices, 5000);
    return () => window.clearInterval(id);
  }, [loadDevices]);
  useEffect(() => {
    if (deviceId) localStorage.setItem("psu-device", deviceId);
  }, [deviceId]);
  useEffect(() => {
    setData(null);
    setConnected(false);
    setVset("");
    setIset("");
    prevOutputRef.current = null;
  }, [deviceId]);
  const allOff = async () => {
    try {
      await api("/api/all-off", {});
      await loadDevices();
      refresh();
    } catch (e) { setError((e as Error).message); }
  };
  const autoRate = data?.family === "dp100" ? 20 : 10;
  const hz = autoRate;
  useEffect(() => {
    refresh(channel);
    const id = setInterval(() => { if (!document.hidden) refresh(channel); }, 500);
    return () => clearInterval(id);
  }, [channel, refresh]);
  useEffect(() => {
    const id = setInterval(() => setSampleCount(chartRef.current?.history().length ?? 0), 1000);
    return () => clearInterval(id);
  }, []);

  const followUntil = useRef(0);
  useEffect(() => {
    if ((data?.output || "").toUpperCase() === "ON") followUntil.current = Date.now() + 2000;
  }, [data?.setpoint.voltage, data?.setpoint.current, data?.output]);
  useEffect(() => {
    if ((data?.output || "").toUpperCase() !== "ON" || Date.now() > followUntil.current) return;
    const v = data?.measurement.voltage;
    const i = data?.measurement.current;
    const followV = v != null && Math.abs(v - chartSettings.vPos) > chartSettings.vDiv * 2.2;
    const followI = i != null && Math.abs(i - chartSettings.iPos) > chartSettings.iDiv * 2.2;
    if (!followV && !followI) return;
    setChartSettings((prev) => ({
      ...prev,
      ...(followV && v != null ? { vPos: v } : {}),
      ...(followI && i != null ? { iPos: i } : {}),
    }));
    if (followV && v != null) setVScopeRef(v);
    if (followI && i != null) setIScopeRef(i);
  }, [data?.measurement.voltage, data?.measurement.current, data?.output,
      chartSettings.vPos, chartSettings.vDiv, chartSettings.iPos, chartSettings.iDiv]);

  useEffect(() => {
    const current = (data?.output || "").toUpperCase() === "ON";
    const prev = prevOutputRef.current;
    if (prev !== null && prev !== current) {
      if (current) { playTone(660, 0.1); playTone(880, 0.14, 0.11); }
      else { playTone(520, 0.1); playTone(390, 0.15, 0.11); }
    }
    prevOutputRef.current = current;
  }, [data?.output, playTone]);

  const run = async (fn: () => Promise<State>, quiet = false) => {
    if (!quiet) setBusy(true);
    try { applyState(await fn()); }
    catch (e) { setError((e as Error).message); }
    finally { if (!quiet) setBusy(false); }
  };

  const setpoints = () => run(() => api("/api/set", { device: deviceId, ch: channel, voltage: parseFloat(vset), current: parseFloat(iset) }), true);
  const output = (on: boolean) => run(() => api("/api/output", { device: deviceId, ch: channel, on, confirm: on })).then(loadDevices);
  const protect = () => run(() => api("/api/protect", { device: deviceId, ch: channel, ovp: ovp === "" ? undefined : parseFloat(ovp), ocp: ocp === "" ? undefined : parseFloat(ocp) }));

  const caps = data?.capabilities;
  const on = (data?.output || "").toUpperCase() === "ON";
  const work = data?.status?.work_state;
  const fault = work !== undefined && work !== 0;
  const workName = work === undefined ? "—" : t.work[work] ?? `CODE ${work}`;
  const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
  const applyPreset = (preset: Preset) => {
    setVset(fmt(preset.v, 3));
    setIset(fmt(preset.i, 3));
    // Optimistically move the UI so the selection is visible immediately.
    setData((prev) => prev ? { ...prev, setpoint: { voltage: preset.v, current: preset.i } } : prev);
    // Presets are explicit user intent: apply both setpoints even while output is ON.
    run(() => api("/api/set", { device: deviceId, ch: channel, voltage: preset.v, current: preset.i }), true);
  };
  const savePreset = () => {
    const v = parseFloat(vset), i = parseFloat(iset);
    if (!Number.isFinite(v) || !Number.isFinite(i)) return;
    setPresets((list) => [...list.filter((p) => p.v !== v || p.i !== i), { v, i }].slice(-8));
  };
  const download = () => {
    const rows = ["time,voltage,current,power"];
    for (const p of chartRef.current?.history() ?? []) rows.push(`${new Date(p.t).toISOString()},${p.v ?? ""},${p.i ?? ""},${p.p ?? ""}`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
    a.download = "psu-log.csv";
    a.click();
  };

  const faultHint = work !== undefined
    ? ((t.faultHints as Record<number, string>)[work] ?? t.faultHints[0]) : "";
  const vManual: [number, number] = [chartSettings.vPos - chartSettings.vDiv * 2, chartSettings.vPos + chartSettings.vDiv * 2];
  const iManual: [number, number] = [chartSettings.iPos - chartSettings.iDiv * 2, chartSettings.iPos + chartSettings.iDiv * 2];
  const openSettings = () => { setDraft(chartSettings); setSettingsOpen(true); };
  const vDivIndex = Math.max(0, VDIV.indexOf(chartSettings.vDiv));
  const iDivIndex = Math.max(0, IDIV.indexOf(chartSettings.iDiv));
  const vPosLo = vScopeRef - chartSettings.vDiv * 5;
  const vPosHi = vScopeRef + chartSettings.vDiv * 5;
  const iPosLo = iScopeRef - chartSettings.iDiv * 5;
  const iPosHi = iScopeRef + chartSettings.iDiv * 5;
  const setScope = (patch: Partial<ChartSettings>) => {
    setChartSettings((prev) => ({ ...prev, ...patch }));
    setScopeMode("MAN");
  };
  const [scopeMode, setScopeMode] = useState<"AUTO" | "MAN">(() =>
    localStorage.getItem("psu-chart-initialized") === "1" ? "MAN" : "AUTO");
  const [autoPulse, setAutoPulse] = useState(false);
  const autoTimer = useRef<number | undefined>(undefined);
  const [scopeInitialized, setScopeInitialized] = useState(() =>
    localStorage.getItem("psu-chart-initialized") === "1");
  const nearest = (options: number[], want: number) => options.reduce((best, v) => Math.abs(v - want) < Math.abs(best - want) ? v : best, options[0]);
  const autoSet = () => {
    const v = data?.measurement.voltage ?? 0;
    const i = data?.measurement.current ?? 0;
    const centerV = Math.abs(v) > 0.01 ? v : (data?.setpoint.voltage ?? 0);
    const centerI = Math.abs(i) > 1e-4 ? i : 0;
    const vDiv = nearest(VDIV, Math.max(0.005, Math.abs(centerV) * 0.01));
    const iDiv = nearest(IDIV, Math.max(0.01, Math.abs(centerI) * 0.05));
    setChartSettings((prev) => ({ ...prev, vDiv, vPos: centerV, iDiv, iPos: centerI }));
    setVScopeRef(centerV);
    setIScopeRef(centerI);
    setScopeMode("MAN");
    setAutoPulse(true);
    if (autoTimer.current) window.clearTimeout(autoTimer.current);
    autoTimer.current = window.setTimeout(() => setAutoPulse(false), 800);
    setScopeInitialized(true);
    localStorage.setItem("psu-chart-initialized", "1");
  };
  const autoInit = useRef(false);
  useEffect(() => {
    if (data && !scopeInitialized && !autoInit.current) {
      autoInit.current = true;
      autoSet();
    }
  }, [data?.idn, channel, scopeInitialized]);
  const overtemp = caps?.temperature && data?.measurement.temperature != null
    && data.measurement.temperature >= 60;
  const alert = !connected && data
    ? { title: t.connectionLost, detail: error || t.connectionHint }
    : fault
      ? { title: `${t.deviceAlert}: ${workName}`, detail: faultHint }
      : overtemp
        ? { title: t.overtemp, detail: fill(t.overtempHint, { t: fmt(data?.measurement.temperature, 1) }) }
        : error
          ? { title: t.operationFailed, detail: error }
          : null;
  useEffect(() => {
    document.title = alert ? `⚠ ${alert.title} · ${t.title}` : t.title;
  }, [alert?.title, t.title]);

  useEffect(() => {
    // Keep the visual toast for at least 10 s; persistent faults keep it until recovery.
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    if (alert) {
      setToast(alert);
      const severe = fault || (!connected && !!data) || overtemp;
      if (!severe) toastTimer.current = window.setTimeout(() => setToast(null), 10_000);
    } else if (toast) {
      toastTimer.current = window.setTimeout(() => setToast(null), 10_000);
    }
    return () => { if (toastTimer.current) window.clearTimeout(toastTimer.current); };
  }, [alert?.title, alert?.detail, fault, connected, overtemp]);

  useEffect(() => {
    const signature = fault ? `fault:${work}` : (!connected && data ? "offline" : overtemp ? "overtemp" : "");
    if (signature && signature !== prevAlertSoundRef.current) {
      playTone(520, 0.14); playTone(400, 0.14, 0.16); playTone(520, 0.16, 0.32);
    }
    prevAlertSoundRef.current = signature;
  }, [fault, work, connected, data, overtemp, playTone]);

  useEffect(() => {
    // Pop a native alert once per distinct severe condition; reset after recovery.
    const signature = fault ? `fault:${work}` : (!connected && data ? "offline" : overtemp ? "overtemp" : "");
    if (!signature) { lastAlertRef.current = ""; return; }
    if (lastAlertRef.current === signature) return;
    lastAlertRef.current = signature;
    const message = alert ? `${alert.title}\n\n${alert.detail}` : t.deviceAlert;
    const id = window.setTimeout(() => window.alert(message), 80);
    return () => window.clearTimeout(id);
  }, [fault, work, connected, data, overtemp, alert?.title, alert?.detail, t.deviceAlert]);

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-[1440px] space-y-5 px-5 pb-6 lg:px-8" style={{ paddingTop: headerH + 8 }}>
        <header ref={headerRef} className="fixed inset-x-0 top-0 z-40 border-t-2 border-t-primary border-b border-border/60 bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
          {desktop && (
            <div
              className="flex h-8 items-center justify-between border-b border-border/50 bg-background/60 pl-4 pr-2"
              style={{ "--wails-draggable": "drag" } as CSSProperties}
              onDoubleClick={() => wailsWindow()?.ToggleMaximise()}
            >
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-primary/80" />
                Power Supply
                <span className="font-normal text-border">/</span>
                <span className="font-mono font-normal normal-case tracking-normal">{devices.find((d) => d.id === deviceId)?.model ?? data?.family ?? "PSU"}</span>
              </div>
              <div className="flex items-center gap-0.5" style={{ "--wails-draggable": "no-drag" } as CSSProperties}>
                <button type="button" aria-label="Minimise" title="Minimise"
                  className="grid h-7 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  onClick={() => wailsWindow()?.Minimise()}>
                  <Minus className="h-3.5 w-3.5" />
                </button>
                <button type="button" aria-label="Maximise" title="Maximise"
                  className="grid h-7 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  onClick={() => wailsWindow()?.ToggleMaximise()}>
                  <Square className="h-3 w-3" />
                </button>
                <button type="button" aria-label="Close" title="Close"
                  className="grid h-7 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-destructive hover:text-destructive-foreground"
                  onClick={() => wailsWindow()?.Close()}>
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
          <div className="mx-auto max-w-[1440px] px-5 py-3 lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-card shadow-sm">
              <Zap className="h-5 w-5 text-primary" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold tracking-tight">{t.title}</h1>
                <Badge variant="outline" className="font-mono">{data?.family ?? "—"}</Badge>
                <Badge variant={connected ? "success" : data ? "destructive" : "outline"} className="gap-1.5">
                  <span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-success" : "bg-muted-foreground/40")} />
                  {connected ? t.connected : data ? t.disconnected : t.connecting}
                </Badge>
                <Badge variant={on ? "success" : "outline"}
                  className={cn("gap-1.5 px-3 transition-colors", on && "border-success bg-success text-success-foreground shadow-sm")}>
                  {on ? (
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success-foreground/60" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-success-foreground" />
                    </span>
                  ) : <Power className="h-3 w-3" />}
                  {data?.output ? `${t.output} ${data.output}` : `${t.output} —`}
                </Badge>
              </div>
              <p className="mt-0.5 font-mono text-xs text-muted-foreground">{data?.idn ?? t.noDevice}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <div className="mr-1 inline-flex h-8 items-center rounded-lg bg-muted/70 p-1 text-muted-foreground">
              {(["basic", "advanced"] as const).map((key) => (
                <motion.button key={key} onClick={() => setTab(key)} whileTap={{ scale: 0.97 }}
                  className="relative rounded-md px-3 py-1 text-xs font-medium">
                  {tab === key && (
                    <motion.span layoutId="psu-tab-pill" className="absolute inset-0 rounded-md bg-primary/10 ring-1 ring-inset ring-primary/20"
                      transition={{ type: "spring", stiffness: 520, damping: 38 }} />
                  )}
                  <span className={cn("relative z-10 transition-colors", tab === key ? "text-primary" : "hover:text-foreground")}>{t[key]}</span>
                </motion.button>
              ))}
            </div>
            {fault && <Badge variant="destructive"><AlertTriangle className="h-3 w-3" /> {workName}</Badge>}
            <Button variant="outline" size="sm" title={sound ? t.soundOn : t.soundOff}
              onClick={() => { const next = !sound; soundRef.current = next; setSound(next); if (next) playTone(880, 0.1); }}>
              {sound ? <Volume2 /> : <VolumeX />}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setLang(lang === "en" ? "zh" : "en")} title="Language"><Languages /> {lang === "en" ? "中文" : "EN"}</Button>
            <Button variant="outline" size="sm" onClick={() => setDark(!dark)} title="Theme">{dark ? <Sun /> : <Moon />} {dark ? t.light : t.dark}</Button>
          </div>
          </div>
          </div>
          {devices.length > 1 && (
            <div className="border-t border-border/50 bg-background/50">
              <div className="mx-auto flex max-w-[1440px] items-center gap-1.5 overflow-x-auto px-5 py-1.5 lg:px-8">
                <span className="mr-1 shrink-0 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{t.devices}</span>
                {devices.map((d) => {
                  const active = d.id === deviceId;
                  const dOn = (d.output || "").toUpperCase() === "ON";
                  const short = d.serial_number_hex ? d.serial_number_hex.slice(-6).toUpperCase() : d.id.slice(-6);
                  return (
                    <button key={d.id} type="button" onClick={() => setDeviceId(d.id)}
                      className={cn("flex shrink-0 items-center gap-2 rounded-md border px-2.5 py-1 text-[11px] transition-colors",
                        active ? "border-primary/40 bg-primary/10 text-foreground" : "border-transparent text-muted-foreground hover:bg-muted/70 hover:text-foreground")}>
                      <span className={cn("h-1.5 w-1.5 rounded-full", dOn ? "bg-success" : "bg-muted-foreground/40")} />
                      <span className="font-medium">{d.model || "DP100"}</span>
                      <span className="font-mono opacity-70">{short}</span>
                      <span className={cn("font-mono text-[9px] tracking-wide", dOn ? "text-success" : "opacity-60")}>{d.output || "—"}</span>
                    </button>
                  );
                })}
                <button type="button" onClick={allOff} title={t.allOff}
                  className="ml-auto flex shrink-0 items-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:border-destructive/30 hover:bg-destructive/10 hover:text-destructive">
                  <Power className="h-3 w-3" /> {t.allOff}
                </button>
              </div>
            </div>
          )}
        </header>

        {tab === "basic" && (!data ? <MetricsSkeleton /> : (
        <div className="overflow-hidden border-y border-border">
          <div className="h-px bg-gradient-to-r from-primary/60 via-primary/15 to-transparent" />
          <div className="flex flex-col divide-y divide-border sm:flex-row sm:divide-x sm:divide-y-0">
            <MetricTile label={t.outputVoltage} value={fmt(data?.measurement.voltage, 3)} unit="V" sub={`${t.vset} ${fmt(data?.setpoint.voltage, 3)} V`} icon={Gauge} accent="#C96442" />
            <MetricTile label={t.outputCurrent} value={fmt(data?.measurement.current, 3)} unit="A" sub={`${t.iset} ${fmt(data?.setpoint.current, 3)} A`} icon={Activity} accent="#2F8FA8" />
            {caps?.power && <MetricTile label={t.outputPower} value={fmt(data?.measurement.power, 2)} unit="W" sub={`${t.limit} ${data?.limits.max_power ?? "—"} W`} icon={Zap} accent="#7C8C5A" />}
            {caps?.input_voltage && <MetricTile label={t.inputVoltage} value={fmt(data?.measurement.input_voltage, 2)} unit="V" sub={t.dcInput} icon={Cpu} accent="#B08968" />}
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-border px-5 py-2 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><Waves className="h-3 w-3" /> {t.mode} <b className="font-mono text-foreground">{data?.status?.output_mode ?? "—"}</b></span>
            <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3 w-3" /> {t.state} <b className={cn("font-mono", fault ? "text-destructive" : "text-foreground")}>{workName}</b></span>
            {(data?.channels.length ?? 1) > 1 && (
              <span className="inline-flex items-center gap-1.5"><SlidersHorizontal className="h-3 w-3" /> {t.channel} <b className="font-mono text-foreground">CH{data?.ch ?? channel}</b> {t.of} {data?.channels.length}</span>
            )}
            <span className="ml-auto inline-flex items-center gap-1.5">
              <span className={cn("relative flex h-1.5 w-1.5", connected ? "bg-success" : "bg-destructive")}>
                {connected && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />}
                <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", connected ? "bg-success" : "bg-destructive")} />
              </span>
              {connected ? "live" : t.disconnected}
            </span>
          </div>
        </div>
        ))}

        <AnimatePresence mode="wait" initial={false}>
        {tab === "basic" ? (
          <motion.div key="basic" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2, ease: "easeOut" }}
            className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[minmax(0,1fr)_400px]">
            {!data ? (
              <>
                <Card className="h-full min-w-0">
                  <CardHeader><Skeleton className="h-3 w-20" /></CardHeader>
                  <CardContent><Skeleton className="h-[400px] w-full" /></CardContent>
                </Card>
                <Card className="h-full">
                  <CardHeader><Skeleton className="h-3 w-24" /></CardHeader>
                  <CardContent className="space-y-4">
                    <Skeleton className="h-9 w-full" />
                    <Skeleton className="h-9 w-full" />
                    <Skeleton className="h-9 w-full" />
                    <div className="grid grid-cols-2 gap-2"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>
                    <Skeleton className="h-28 w-full" />
                  </CardContent>
                </Card>
              </>
            ) : (
              <>
            <Card className="h-full min-w-0">
              <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
                <CardTitle className="flex items-center gap-2">{t.history}
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                </CardTitle>
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant={showV ? "secondary" : "outline"} onClick={() => setShowV(!showV)}>
                    <span className="h-2 w-2 rounded-full bg-[#C2410C] dark:bg-[#FF8A5C]" /> V
                  </Button>
                  <Button size="sm" variant={showA ? "secondary" : "outline"} onClick={() => setShowA(!showA)}>
                    <span className="h-2 w-2 rounded-full bg-[#0E7490] dark:bg-[#5CC8E5]" /> A
                  </Button>
                  <select value={windowMs} onChange={(e) => setWindowMs(Number(e.target.value))} className="h-8 rounded-md border border-border bg-background px-2 text-xs text-muted-foreground outline-none focus:ring-1 focus:ring-ring" aria-label="time window">
                    <option value={10000}>10s</option><option value={30000}>30s</option><option value={60000}>60s</option>
                  </select>
                  <Button size="sm" variant="outline" onClick={openSettings} title={t.chartSettings}><Settings2 /></Button>
                  <Button size="sm" variant={paused ? "secondary" : "outline"} onClick={() => setPaused(!paused)}>
                    {paused ? <Play /> : <Pause />} {paused ? t.resume : t.pause}
                  </Button>
                  <Button size="sm" variant={cache ? "secondary" : "outline"} onClick={() => setCache(!cache)} title={t.cacheHint}>
                    <Database /> {cache ? t.cacheOn : t.cacheOff}
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex gap-3">
                <div className="min-w-0 flex-1">
                <LiveChart key={deviceId} ref={chartRef} key={channel}
                  streamUrl={`/api/stream?ch=${channel}&hz=${hz}${deviceId ? `&device=${encodeURIComponent(deviceId)}` : ""}`}
                  historyUrl={`/api/history?ch=${channel}&seconds=62${deviceId ? `&device=${encodeURIComponent(deviceId)}` : ""}`}
                  poll={desktop}
                  dark={dark} height={400} windowMs={windowMs}
                  cache={cache} vset={data?.setpoint.voltage} iset={data?.setpoint.current}
                  showV={showV} showA={showA} paused={paused} enabled={on}
                  vManual={vManual} iManual={iManual} smooth={chartSettings.smooth} delayMs={chartSettings.delay} />
                </div>
                <div className="hidden w-[82px] shrink-0 flex-col items-center justify-center gap-2 border-l border-border/60 pl-2 md:flex">
                  <div className="flex w-full gap-1 px-1">
                    <button onClick={autoSet} title="Auto set and save to MAN"
                      className={cn("flex-1 rounded border py-0.5 font-mono text-[9px] tracking-widest transition-all duration-300",
                        autoPulse ? "border-primary bg-primary/20 text-primary" : "border-primary/40 bg-primary/10 text-primary")}>
                      AUTO
                    </button>
                    <button onClick={() => setScopeMode("MAN")} title="Manual"
                      className={cn("flex-1 rounded border py-0.5 font-mono text-[9px] tracking-widest",
                        scopeMode === "MAN" ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground")}>
                      MAN
                    </button>
                  </div>
                  <ScopeKnob label={t.voltsPerDiv}
                    value={vDivIndex / (VDIV.length - 1)}
                    wheelStep={1 / (VDIV.length - 1)}
                    display={chartSettings.vDiv < 1 ? `${Math.round(chartSettings.vDiv * 1000)} mV` : `${chartSettings.vDiv} V`} pulse={autoPulse}
                    onChange={(x) => {
                      const next = VDIV[Math.round(x * (VDIV.length - 1))];
                      setScope({ vDiv: next });
                    }} />
                  <ScopeKnob label={t.vPos}
                    value={(chartSettings.vPos - vPosLo) / (vPosHi - vPosLo)}
                    display={`${chartSettings.vPos.toFixed(2)} V`} pulse={autoPulse}
                    onChange={(x) => setScope({ vPos: vPosLo + x * (vPosHi - vPosLo) })} />
                  <ScopeKnob label={t.ampsPerDiv}
                    value={iDivIndex / (IDIV.length - 1)}
                    wheelStep={1 / (IDIV.length - 1)}
                    display={chartSettings.iDiv < 1 ? `${Math.round(chartSettings.iDiv * 1000)} mA` : `${chartSettings.iDiv} A`} pulse={autoPulse}
                    onChange={(x) => {
                      const next = IDIV[Math.round(x * (IDIV.length - 1))];
                      setScope({ iDiv: next });
                    }} />
                  <ScopeKnob label={t.aPos}
                    value={(chartSettings.iPos - iPosLo) / (iPosHi - iPosLo)}
                    display={`${chartSettings.iPos.toFixed(2)} A`} pulse={autoPulse}
                    onChange={(x) => setScope({ iPos: iPosLo + x * (iPosHi - iPosLo) })} />
                </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3 text-[11px] text-muted-foreground">
                  <span>{fill(t.samples, { n: sampleCount })}</span>
                  <Button size="sm" variant="outline" onClick={download} disabled={!sampleCount}><Download /> CSV</Button>
                </div>
              </CardContent>
            </Card>

            <aside className="min-w-0 space-y-5">
              <ControlCard t={t} caps={caps} data={data} busy={busy} vset={vset} iset={iset} ovp={ovp} ocp={ocp}
                channel={channel} setChannel={setChannel}
                setVset={setVset} setIset={setIset} setOvp={setOvp} setOcp={setOcp} editing={editing}
                onApply={setpoints} onOutput={output} onProtect={protect} onConfirmOn={() => setConfirmOn(true)}
                presets={presets} onPreset={applyPreset} onSavePreset={savePreset} />
            </aside>
              </>
            )}
          </motion.div>
        ) : (
          <motion.div key="advanced" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2, ease: "easeOut" }} className="space-y-8">
            <SequencePanel t={t} channel={channel} device={deviceId} maxV={data?.limits.max_voltage} maxI={data?.limits.max_current}
              onState={applyState} setError={setError} />
            <div className="grid gap-8 border-t border-border pt-8 xl:grid-cols-2">
              <ScanPanel t={t} kind="voltage" channel={channel} device={deviceId} maxV={data?.limits.max_voltage} maxI={data?.limits.max_current}
                onState={applyState} setError={setError} />
              <ScanPanel t={t} kind="current" channel={channel} device={deviceId} maxV={data?.limits.max_voltage} maxI={data?.limits.max_current}
                onState={applyState} setError={setError} />
            </div>
            <div className="grid gap-8 border-t border-border pt-8 md:grid-cols-2">
              <section className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">{t.device}</h3>
                  <span className="font-mono text-[11px] text-muted-foreground">{String(data?.device_info?.serial_number_hex ?? "")}</span>
                </div>
                <div className="space-y-2">
                  <Row label={t.model} value={String(data?.device_info?.model ?? data?.family ?? "—")} />
                  <Row label={t.hardware} value={String(data?.device_info?.hardware_version ?? "—")} />
                  <Row label={t.app} value={String(data?.device_info?.app_version ?? "—")} />
                  {caps?.input_voltage && <Row label={t.inputVoltage} value={`${fmt(data?.measurement.input_voltage, 2)} V`} />}
                  {caps?.temperature && <Row label={t.temperature} value={`${fmt(data?.measurement.temperature, 1)} °C`} />}
                </div>
              </section>
              <section className="space-y-3">
                <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">{t.limits}</h3>
                <div className="space-y-3.5">
                  <LimitBar label={t.voltage} value={data?.measurement.voltage ?? null} max={data?.limits.max_voltage} unit="V" />
                  <LimitBar label={t.current} value={data?.measurement.current ?? null} max={data?.limits.max_current} unit="A" />
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                    <span>{t.ovpMax} <b className="font-mono text-foreground">{data?.limits.max_ovp ?? "—"} V</b></span>
                    <span>{t.ocpMax} <b className="font-mono text-foreground">{data?.limits.max_ocp ?? "—"} A</b></span>
                  </div>
                </div>
              </section>
            </div>
          </motion.div>
        )}
        </AnimatePresence>

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

        <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
          <DialogContent>
            <DialogTitle>{t.chartSettings}</DialogTitle>
            <DialogDescription>{t.chartSettingsHint}</DialogDescription>
            <div className="mt-4 space-y-4">
              <div className="space-y-2">
                <Label>{t.voltageRange}</Label>
                <div className="grid grid-cols-2 gap-2">
                  <select value={draft.vDiv} disabled={draft.autoY}
                    onChange={(e) => setDraft({ ...draft, vDiv: Number(e.target.value) })}
                    className="h-9 rounded-md border border-border bg-background px-2 font-mono text-xs disabled:opacity-50">
                    {VDIV.map((v) => <option key={v} value={v}>{v * 1000 < 1000 ? `${v * 1000} mV/div` : `${v} V/div`}</option>)}
                  </select>
                  <Input inputMode="decimal" placeholder={t.center} value={draft.vPos} disabled={draft.autoY}
                    onChange={(e) => setDraft({ ...draft, vPos: Number(e.target.value) || 0 })} />
                </div>
              </div>
              <div className="space-y-2">
                <Label>{t.currentRange}</Label>
                <div className="grid grid-cols-2 gap-2">
                  <select value={draft.iDiv} disabled={draft.autoY}
                    onChange={(e) => setDraft({ ...draft, iDiv: Number(e.target.value) })}
                    className="h-9 rounded-md border border-border bg-background px-2 font-mono text-xs disabled:opacity-50">
                    {IDIV.map((v) => <option key={v} value={v}>{v * 1000 < 1000 ? `${v * 1000} mA/div` : `${v} A/div`}</option>)}
                  </select>
                  <Input inputMode="decimal" placeholder={t.center} value={draft.iPos} disabled={draft.autoY}
                    onChange={(e) => setDraft({ ...draft, iPos: Number(e.target.value) || 0 })} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>{t.smoothing} · {Math.round(draft.smooth * 100)}%</Label>
                <input type="range" min={0} max={0.9} step={0.05} value={draft.smooth}
                  onChange={(e) => setDraft({ ...draft, smooth: Number(e.target.value) })}
                  className="w-full accent-[hsl(var(--primary))]" />
              </div>
              <div className="space-y-1.5">
                <Label>{t.displayDelay} · {draft.delay} ms</Label>
                <input type="range" min={0} max={400} step={20} value={draft.delay}
                  onChange={(e) => setDraft({ ...draft, delay: Number(e.target.value) })}
                  className="w-full accent-[hsl(var(--primary))]" />
              </div>
            </div>
            <div className="mt-5 flex justify-between gap-2">
              <Button variant="ghost" onClick={() => setDraft(DEFAULT_CHART_SETTINGS)}><RotateCcw /> {t.reset}</Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setSettingsOpen(false)}>{t.cancel}</Button>
                <Button onClick={() => {
                  setChartSettings(draft); setVScopeRef(draft.vPos); setIScopeRef(draft.iPos);
                  setScopeMode("MAN"); setSettingsOpen(false);
                }}>{t.applySettings}</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>

        <AnimatePresence>
        {toast && (
          <motion.div role="alert" initial={{ opacity: 0, y: 18, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.97 }} transition={{ type: "spring", stiffness: 420, damping: 34 }}
            className="fixed bottom-5 right-5 z-50 flex w-[min(380px,calc(100vw-2.5rem))] items-start gap-2.5 rounded-xl border border-destructive/40 bg-card/95 p-3.5 text-sm text-destructive shadow-lg backdrop-blur">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{toast.title}</div>
              <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{toast.detail}</div>
            </div>
            <button className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={() => setToast(null)} title="Dismiss">
              <X className="h-3.5 w-3.5" />
            </button>
          </motion.div>
        )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function NumberInput({ value, onChange, step = 0.1, min = 0, max = 100, ...props }: React.ComponentProps<typeof Input> & {
  value: string; onChange: (v: string) => void; step?: number; min?: number; max?: number;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const latest = useRef({ value, onChange, step, min, max });
  latest.current = { value, onChange, step, min, max };
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (document.activeElement !== el) return;
      e.preventDefault();
      const l = latest.current;
      const dir = e.deltaY < 0 ? 1 : -1;
      const next = Math.min(l.max, Math.max(l.min, (parseFloat(l.value) || 0) + dir * l.step));
      l.onChange(next.toFixed(3));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  return <Input ref={ref} value={value} onChange={(e) => onChange(e.target.value)} {...props} />;
}

function ScopeKnob({ label, value, display, onChange, wheelStep = 0.02, pulse = false }: {
  label: string; value: number; display: string; onChange: (v: number) => void; wheelStep?: number; pulse?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const latest = useRef({ value, onChange, wheelStep });
  latest.current = { value, onChange, wheelStep };
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const l = latest.current;
      const dir = e.deltaY < 0 ? 1 : -1;
      l.onChange(Math.min(1, Math.max(0, l.value + dir * l.wheelStep)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  const v = Math.min(1, Math.max(0, value));
  return (
    <div ref={ref} tabIndex={0} title={`${label} · scroll to adjust`}
      className="flex w-full flex-col items-center gap-0.5 rounded-md outline-none focus-visible:ring-1 focus-visible:ring-ring">
      <div className="relative h-14 w-14">
        <div className={cn("absolute inset-0 rounded-full border border-border bg-card shadow-sm transition-all duration-300",
          pulse && "ring-2 ring-primary/35 shadow-[0_0_16px_-5px_hsl(var(--primary)/0.35)]")}>
          <div className="absolute inset-[6px] rounded-full border border-border/70 bg-muted/60 shadow-[inset_0_1px_2px_rgba(0,0,0,0.08)]" />
          <div className="absolute inset-0" style={{ transform: `rotate(${v * 360}deg)` }}>
            <span className="absolute left-1/2 top-1.5 h-3 w-[2px] -translate-x-1/2 rounded-full bg-primary" />
          </div>
          <div className="absolute left-1/2 top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-border bg-card" />
          <CircularInput value={v} radius={23} onChange={onChange} aria-label={label}
            className="absolute inset-0 h-full w-full">
            <CircularTrack stroke="hsl(var(--border))" strokeWidth={3} />
            <CircularProgress stroke="hsl(var(--primary))" strokeWidth={3} />
            <CircularThumb r={3.5} fill="hsl(var(--primary))" />
          </CircularInput>
        </div>
      </div>
      <span className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="font-mono text-[10px] tabular-nums">{display}</span>
    </div>
  );
}

function ControlCard({ t, caps, data, busy, vset, iset, ovp, ocp, setVset, setIset, setOvp, setOcp, editing, onApply, onOutput, onProtect, onConfirmOn, presets, onPreset, onSavePreset }: {
  t: Dict; caps: Caps | undefined; data: State | null; busy: boolean;
  vset: string; iset: string; ovp: string; ocp: string;
  channel: number; setChannel: (ch: number) => void;
  setVset: (v: string) => void; setIset: (v: string) => void;
  setOvp: (v: string) => void; setOcp: (v: string) => void;
  editing: React.MutableRefObject<string | null>;
  onApply: () => void; onOutput: (on: boolean) => void;
  onProtect: () => void; onConfirmOn: () => void;
  presets: Preset[]; onPreset: (p: Preset) => void; onSavePreset: () => void;
}) {
  const outputOn = (data?.output || "").toUpperCase() === "ON";
  const vFocus = useRef(""); const iFocus = useRef("");
  const liveTimer = useRef<number | undefined>(undefined);
  const onApplyRef = useRef(onApply);
  onApplyRef.current = onApply;
  const stopLive = () => {
    if (liveTimer.current) { window.clearTimeout(liveTimer.current); liveTimer.current = undefined; }
  };
  useEffect(() => {
    if (!editing.current) return;
    const v = parseFloat(vset), i = parseFloat(iset);
    if (!Number.isFinite(v) || !Number.isFinite(i)) return;
    if (v < 0 || v > (data?.limits.max_voltage ?? 30) || i < 0 || i > (data?.limits.max_current ?? 5)) return;
    stopLive();
    liveTimer.current = window.setTimeout(() => {
      liveTimer.current = undefined;
      onApplyRef.current();
    }, 350);
    return stopLive;
  }, [vset, iset, data?.limits.max_voltage, data?.limits.max_current]);
  const blurApply = () => {
    stopLive();
    if (vset !== vFocus.current || iset !== iFocus.current) onApplyRef.current();
  };
  return (
    <div className="relative h-full">
      {outputOn && (
        <motion.div aria-hidden
          className="pointer-events-none absolute -inset-px rounded-lg bg-success/40 blur-[6px]"
          animate={{ opacity: [0.3, 0.95, 0.3] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }} />
      )}
      <Card className="relative flex h-full flex-col">
      {outputOn && (
        <>
          <motion.div aria-hidden
            className="pointer-events-none absolute inset-0 rounded-lg"
            style={{ backgroundColor: "rgb(var(--glow-rgb) / 0.07)" }}
            animate={{ opacity: [0.2, 0.9, 0.2] }}
            transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }} />
          <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden rounded-lg">
            <motion.div
              className="absolute -inset-y-6 w-24 rotate-12 bg-gradient-to-r from-transparent via-success/20 to-transparent"
              initial={{ x: "-140%" }}
              animate={{ x: "620%" }}
              transition={{ duration: 2.6, repeat: Infinity, repeatDelay: 0.9, ease: "easeInOut" }} />
          </div>
        </>
      )}
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">{t.control}
          {outputOn && (
            <motion.span className="h-1.5 w-1.5 rounded-full bg-success"
              animate={{ opacity: [0.3, 1, 0.3], scale: [0.85, 1.25, 0.85] }}
              transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }} />
          )}
        </CardTitle>
        {(data?.channels.length ?? 1) > 1 && (
          <Tabs value={String(channel)} onValueChange={(v) => setChannel(Number(v))}>
            <TabsList>{data!.channels.map((c) => <TabsTrigger key={c} value={String(c)}>CH{c}</TabsTrigger>)}</TabsList>
          </Tabs>
        )}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col justify-between gap-4">
        <div className="space-y-4">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="preset">{t.presets}</Label>
            <Button size="sm" variant="ghost" className="h-7 px-2 text-[11px]" onClick={onSavePreset}>
              <Plus /> {t.savePreset}
            </Button>
          </div>
          <div className="relative">
            <select id="preset" aria-label={t.presets}
              value={(() => {
                const idx = presets.findIndex((p) => Math.abs((parseFloat(vset) || 0) - p.v) < 1e-6
                  && Math.abs((parseFloat(iset) || 0) - p.i) < 1e-6
                  && p.v <= (data?.limits.max_voltage ?? 30) && p.i <= (data?.limits.max_current ?? 5));
                return idx >= 0 ? String(idx) : "";
              })()}
              onChange={(e) => { const p = presets[Number(e.target.value)]; if (p) onPreset(p); }}
              className="h-9 w-full appearance-none rounded-md border border-border bg-background px-2.5 pr-8 font-mono text-xs text-foreground outline-none focus:ring-1 focus:ring-ring">
              <option value="" disabled>{t.presetPlaceholder}</option>
              {presets
                .map((p, idx) => ({ p, idx }))
                .filter(({ p }) => p.v <= (data?.limits.max_voltage ?? 30) && p.i <= (data?.limits.max_current ?? 5))
                .map(({ p, idx }) => (
                  <option key={`${p.v}-${p.i}-${idx}`} value={idx}>
                    {p.v} V / {p.i} A
                  </option>
                ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="vset">{t.vset}</Label>
            <div className="relative">
              <NumberInput id="vset" inputMode="decimal" value={vset} onChange={setVset}
                step={0.001} min={0} max={data?.limits.max_voltage ?? 30} title={t.wheelHint}
                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                onFocus={() => { editing.current = "v"; vFocus.current = vset; iFocus.current = iset; }}
                onBlur={() => { editing.current = null; blurApply(); }} className="pr-8" />
              <span className="pointer-events-none absolute right-3 top-2 text-xs text-muted-foreground">V</span>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="iset">{t.iset}</Label>
            <div className="relative">
              <NumberInput id="iset" inputMode="decimal" value={iset} onChange={setIset}
                step={0.001} min={0} max={data?.limits.max_current ?? 5} title={t.wheelHint}
                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                onFocus={() => { editing.current = "i"; vFocus.current = vset; iFocus.current = iset; }}
                onBlur={() => { editing.current = null; blurApply(); }} className="pr-8" />
              <span className="pointer-events-none absolute right-3 top-2 text-xs text-muted-foreground">A</span>
            </div>
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground">{t.applyHint}</p>
        <div className="grid grid-cols-2 gap-2">
          <Button variant="success" disabled={busy || outputOn} aria-pressed={outputOn}
            className={cn(outputOn && "disabled:opacity-100")} onClick={onConfirmOn}><Power /> {t.on}</Button>
          <Button variant="outline" disabled={busy || !outputOn} onClick={() => onOutput(false)}>{t.off}</Button>
        </div>
        </div>
        <div className="space-y-3">
        {(caps?.ovp || caps?.ocp) && (
          <div className="space-y-3 border-t border-border pt-4">
            <div className="grid gap-3 sm:grid-cols-2">
              {caps.ovp && (
                <div className="space-y-1.5">
                  <Label htmlFor="ovp">{t.ovp} <span className="text-muted-foreground/60">≤ {data?.limits.max_ovp ?? "—"} V</span></Label>
                  <Input id="ovp" inputMode="decimal" value={ovp} placeholder="e.g. 6.0" onChange={(e) => setOvp(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") onProtect(); }} />
                </div>
              )}
              {caps.ocp && (
                <div className="space-y-1.5">
                  <Label htmlFor="ocp">{t.ocp} <span className="text-muted-foreground/60">≤ {data?.limits.max_ocp ?? "—"} A</span></Label>
                  <Input id="ocp" inputMode="decimal" value={ocp} placeholder="e.g. 1.0" onChange={(e) => setOcp(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") onProtect(); }} />
                </div>
              )}
            </div>
            <Button variant="outline" className="w-full" disabled={busy} onClick={onProtect}><ShieldCheck /> {t.setProtection}</Button>
          </div>
        )}
        <p className="flex gap-2 border-t border-border pt-4 text-[11px] leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {t.outputNote}
        </p>
        </div>
      </CardContent>
      </Card>
    </div>
  );
}

type SeqRow = { v: string; i: string; delay: string };

function SequencePanel({ t, channel, device, maxV, maxI, onState, setError }: {
  t: Dict; channel: number; device: string; maxV?: number; maxI?: number;
  onState: (s: State) => void; setError: (e: string) => void;
}) {
  const [rows, setRows] = useState<SeqRow[]>([
    { v: "3.3", i: "0.5", delay: "1" },
    { v: "5.0", i: "0.5", delay: "1" },
    { v: "0.0", i: "0.5", delay: "0" },
  ]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const stopRef = useRef(false);
  useEffect(() => () => { stopRef.current = true; }, []);

  const update = (idx: number, key: keyof SeqRow, value: string) =>
    setRows((r) => r.map((row, i) => (i === idx ? { ...row, [key]: value } : row)));

  const start = async () => {
    stopRef.current = false;
    setRunning(true);
    try {
      for (let i = 0; i < rows.length; i++) {
        if (stopRef.current) break;
        setProgress(i);
        const v = parseFloat(rows[i].v), cur = parseFloat(rows[i].i);
        onState(await api("/api/set", {
          device,
          ch: channel,
          voltage: Number.isFinite(v) ? v : undefined,
          current: Number.isFinite(cur) ? cur : undefined,
        }));
        await sleep((parseFloat(rows[i].delay) || 0) * 1000);
      }
    } catch (e) { setError((e as Error).message); }
    finally { setRunning(false); setProgress(null); }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>{t.sequence}</CardTitle>
          <p className="mt-1 text-[11px] text-muted-foreground">{t.sequenceHint}</p>
        </div>
        <div className="flex items-center gap-2">
          {running ? <Button size="sm" variant="destructive" onClick={() => { stopRef.current = true; }}><Square /> {t.stop}</Button>
            : <Button size="sm" variant="success" onClick={start}><Play /> {t.run}</Button>}
        </div>
      </div>
      <div className="space-y-3">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr className="border-b border-border text-left">
                <th className="w-10 py-2 font-medium">#</th>
                <th className="py-2 font-medium">{t.vset} (V)</th>
                <th className="py-2 font-medium">{t.iset} (A)</th>
                <th className="py-2 font-medium">{t.delay}</th>
                <th className="w-16 py-2 font-medium">{t.status}</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className={cn("border-b border-border/60", progress === i && "bg-primary/5")}>
                  <td className="py-1.5 font-mono text-muted-foreground">{String(i + 1).padStart(3, "0")}</td>
                  <td className="py-1.5 pr-2"><Input className="h-8" value={row.v} onChange={(e) => update(i, "v", e.target.value)} /></td>
                  <td className="py-1.5 pr-2"><Input className="h-8" value={row.i} onChange={(e) => update(i, "i", e.target.value)} /></td>
                  <td className="py-1.5 pr-2"><Input className="h-8" value={row.delay} onChange={(e) => update(i, "delay", e.target.value)} /></td>
                  <td className="py-1.5 text-muted-foreground">{progress === i ? t.running : t.idle}</td>
                  <td className="py-1.5 text-right">
                    <Button size="icon" variant="ghost" className="h-7 w-7" disabled={running} onClick={() => setRows((r) => r.filter((_, k) => k !== i))}><Trash2 /></Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={running} onClick={() => setRows((r) => [...r, { v: "0.0", i: "0.5", delay: "1" }])}><Plus /> {t.addRow}</Button>
          <span className="text-[11px] text-muted-foreground">max {maxV ?? "—"} V / {maxI ?? "—"} A</span>
        </div>
      </div>
    </section>
  );
}

function ScanPanel({ t, kind, channel, device, maxV, maxI, onState, setError }: {
  t: Dict; kind: "voltage" | "current"; channel: number; device: string; maxV?: number; maxI?: number;
  onState: (s: State) => void; setError: (e: string) => void;
}) {
  const isV = kind === "voltage";
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState(isV ? "5" : "1");
  const [step, setStep] = useState(isV ? "1" : "0.1");
  const [delay, setDelay] = useState("1");
  const [other, setOther] = useState(isV ? "0.5" : "5");
  const [running, setRunning] = useState(false);
  const [current, setCurrent] = useState<number | null>(null);
  const stopRef = useRef(false);
  useEffect(() => () => { stopRef.current = true; }, []);

  const run = async () => {
    const s0 = parseFloat(start), e0 = parseFloat(end), st = Math.abs(parseFloat(step)) || 0.1;
    const d = parseFloat(delay) || 0, fixed = parseFloat(other);
    if (!Number.isFinite(s0) || !Number.isFinite(e0)) { setError(t.start + " / " + t.end); return; }
    stopRef.current = false;
    setRunning(true);
    try {
      const dir = e0 >= s0 ? 1 : -1;
      for (let x = s0; dir > 0 ? x <= e0 + 1e-9 : x >= e0 - 1e-9; x += dir * st) {
        if (stopRef.current) break;
        setCurrent(x);
        onState(await api("/api/set", isV
          ? { device, ch: channel, voltage: +x.toFixed(4), current: Number.isFinite(fixed) ? fixed : undefined }
          : { device, ch: channel, current: +x.toFixed(4), voltage: Number.isFinite(fixed) ? fixed : undefined }));
        await sleep(d * 1000);
      }
    } catch (e) { setError((e as Error).message); }
    finally { setRunning(false); setCurrent(null); }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <CardTitle>{isV ? t.voltageScan : t.currentScan}</CardTitle>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          {current != null && <span className="font-mono">{current.toFixed(3)} {isV ? "V" : "A"}</span>}
          {running ? <Button size="sm" variant="destructive" onClick={() => { stopRef.current = true; }}><Square /> {t.stop}</Button>
            : <Button size="sm" variant="success" onClick={run}><Play /> {t.run}</Button>}
        </div>
      </div>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <div className="space-y-1.5"><Label>{t.start} ({isV ? "V" : "A"})</Label><Input className="h-8" value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div className="space-y-1.5"><Label>{t.end} ({isV ? "V" : "A"})</Label><Input className="h-8" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          <div className="space-y-1.5"><Label>{t.step} ({isV ? "V" : "A"})</Label><Input className="h-8" value={step} onChange={(e) => setStep(e.target.value)} /></div>
          <div className="space-y-1.5"><Label>{t.delay}</Label><Input className="h-8" value={delay} onChange={(e) => setDelay(e.target.value)} /></div>
          <div className="space-y-1.5"><Label>{isV ? t.iset : t.vset} ({isV ? "A" : "V"})</Label><Input className="h-8" value={other} onChange={(e) => setOther(e.target.value)} /></div>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">max {isV ? `${maxV ?? "—"} V` : `${maxI ?? "—"} A`}</p>
      </div>
    </section>
  );
}
