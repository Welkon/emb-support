import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, CanvasRenderer]);

export type Point = { t: number; v: number | null; i: number | null; p: number | null };
export type LiveChartHandle = { history: () => Point[] };
const LEAD_MS = 30;

function niceBounds(lo: number, hi: number): [number, number] {
  const raw = (hi - lo) / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step];
}

function baseRange(kind: "v" | "i", vset?: number | null, iset?: number | null): [number, number] | null {
  if (kind === "v" && vset != null && Number.isFinite(vset)) {
    const span = Math.max(0.05, Math.abs(vset) * 0.005);
    return niceBounds(vset - span, vset + span);
  }
  if (kind === "i" && iset != null && Number.isFinite(iset)) {
    const span = Math.max(0.03, Math.abs(iset) * 0.03);
    return niceBounds(iset - span, iset + span);
  }
  return null;
}

function baseFromValues(values: number[], minSpan: number): [number, number] | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const center = sorted[Math.floor(sorted.length / 2)];
  const half = Math.max(minSpan, (sorted[sorted.length - 1] - sorted[0]) * 0.6);
  return niceBounds(center - half, center + half);
}

function stableRange(values: number[], current: [number, number] | null, base: [number, number] | null): [number, number] {
  if (!values.length) return base ?? current ?? [0, 1];
  const dataLo = Math.min(...values), dataHi = Math.max(...values);
  let lo = base ? base[0] : dataLo;
  let hi = base ? base[1] : dataHi;
  if (dataLo < lo || dataHi > hi) {
    const pad = Math.max((hi - lo) * 0.15, 1e-6);
    [lo, hi] = niceBounds(Math.min(lo, dataLo - pad), Math.max(hi, dataHi + pad));
  } else if (base && (!current || (current[1] - current[0]) > (base[1] - base[0]) * 4)) {
    return base;
  }
  if (current && lo >= current[0] && hi <= current[1]) return current;
  return [lo, hi];
}

export const LiveChart = forwardRef<LiveChartHandle, {
  streamUrl: string; historyUrl: string; dark: boolean; height?: number; windowMs: number;
  cache: boolean; vset?: number | null; iset?: number | null; showV: boolean; showA: boolean; paused: boolean; enabled: boolean;
  vManual?: [number, number] | null; iManual?: [number, number] | null; smooth?: number; delayMs?: number;
  poll?: boolean;
}>(function LiveChart({ streamUrl, historyUrl, dark, height = 430, windowMs, cache, vset, iset, showV, showA, paused, enabled,
  vManual = null, iManual = null, smooth = 0, delayMs = 160, poll = false }, ref) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const bufferRef = useRef<Point[]>([]);
  const vRangeRef = useRef<[number, number] | null>(null);
  const iRangeRef = useRef<[number, number] | null>(null);
  const windowRef = useRef(windowMs);
  const cacheRef = useRef(cache);
  const pausedRef = useRef(paused);

  const darkRef = useRef(dark);
  const showVRef = useRef(showV);
  const showARef = useRef(showA);
  const vsetRef = useRef(vset);
  const isetRef = useRef(iset);
  const enabledRef = useRef(enabled);
  const vManualRef = useRef(vManual);
  const iManualRef = useRef(iManual);
  const smoothRef = useRef(smooth);
  const delayRef = useRef(delayMs);
  const rafRef = useRef(0);
  const [hasData, setHasData] = useState(false);
  const hasDataRef = useRef(false);
  windowRef.current = windowMs;
  cacheRef.current = cache;
  pausedRef.current = paused;
  darkRef.current = dark;
  showVRef.current = showV;
  showARef.current = showA;
  vsetRef.current = vset;
  isetRef.current = iset;
  enabledRef.current = enabled;
  vManualRef.current = vManual;
  iManualRef.current = iManual;
  smoothRef.current = smooth;
  delayRef.current = delayMs;

  useImperativeHandle(ref, () => ({ history: () => bufferRef.current.slice() }), []);

  const draw = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const now = Date.now();
    const displayNow = now - delayRef.current;
    const cutoff = displayNow - windowRef.current - 2000;
    const start = displayNow - windowRef.current + LEAD_MS;
    const end = displayNow + LEAD_MS;
    const vData: [number, number][] = [];
    const iData: [number, number][] = [];
    const vs: number[] = [];
    const is: number[] = [];
    const alpha = 1 - smoothRef.current;
    let vEma: number | null = null;
    let iEma: number | null = null;
    for (const p of bufferRef.current) {
      if (p.t < cutoff || p.t > end) continue;
      if (p.v != null) {
        vEma = vEma == null ? p.v : vEma + alpha * (p.v - vEma);
        vData.push([p.t, vEma]); vs.push(vEma);
      }
      if (p.i != null) {
        iEma = iEma == null ? p.i : iEma + alpha * (p.i - iEma);
        iData.push([p.t, iEma]); is.push(iEma);
      }
    }
    if (smoothRef.current > 0) {
      if (vEma != null) { vData.push([end, vEma]); vs.push(vEma); }
      if (iEma != null) { iData.push([end, iEma]); is.push(iEma); }
    } else {
      const interpolate = (key: "v" | "i", t: number): number | null => {
        let prev = null, next = null;
        for (const p of bufferRef.current) {
          if (p[key] == null) continue;
          if (p.t <= t) prev = p;
          else { next = p; break; }
        }
        if (!prev) return next && next[key] != null ? next[key] : null;
        if (!next || next[key] == null) return prev[key];
        const f = (t - prev.t) / Math.max(1, next.t - prev.t);
        return (prev[key] as number) + f * ((next[key] as number) - (prev[key] as number));
      };
      const headV = interpolate("v", end);
      const headI = interpolate("i", end);
      if (headV != null) { vData.push([end, headV]); vs.push(headV); }
      if (headI != null) { iData.push([end, headI]); is.push(headI); }
    }
    const vBase = baseFromValues(vs, 0.05) ?? baseRange("v", vsetRef.current, isetRef.current);
    const iBase = baseFromValues(is, 0.03) ?? baseRange("i", vsetRef.current, isetRef.current);
    const vRange = vManualRef.current ?? stableRange(vs, vRangeRef.current, vBase);
    const iRange = iManualRef.current ?? stableRange(is, iRangeRef.current, iBase);
    vRangeRef.current = vRange;
    iRangeRef.current = iRange;
    const axis = darkRef.current ? "#94a3b8" : "#64748b";
    const grid = darkRef.current ? "rgba(148,163,184,0.18)" : "rgba(100,116,139,0.18)";
    const vStep = (vRange[1] - vRange[0]) / 4;
    const iStep = (iRange[1] - iRange[0]) / 4;
    const vDigits = 3;
    const iDigits = 3;
    const vColor = darkRef.current ? "#FF8A5C" : "#C2410C";
    const iColor = darkRef.current ? "#5CC8E5" : "#0E7490";
    chart.setOption({
      animation: false,
      useDirtyRect: true,
      grid: { left: showVRef.current ? 52 : 16, right: showARef.current ? 56 : 16, top: 38, bottom: 28 },
      tooltip: {
        trigger: "axis", confine: true, animation: false,
        backgroundColor: darkRef.current ? "#111827" : "#ffffff",
        borderColor: darkRef.current ? "rgba(148,163,184,0.25)" : "rgba(100,116,139,0.2)",
        textStyle: { color: axis, fontSize: 11, fontFamily: "ui-monospace, monospace" },
        axisPointer: { type: "line", lineStyle: { color: grid } },
        formatter: (params: any[]) => {
          if (!params?.length) return "";
          const stamp = new Date(params[0].value[0]).toLocaleTimeString();
          const rows = params.map((p: any) => {
            const unit = p.seriesName === "Voltage" ? "V" : "A";
            return `${p.marker}${p.seriesName}  <b>${Number(p.value[1]).toFixed(3)} ${unit}</b>`;
          });
          return `<div>${stamp}<br/>${rows.join("<br/>")}</div>`;
        },
      },
      xAxis: {
        type: "time", min: start, max: end, boundaryGap: false, showMaxLabel: true, showMinLabel: true,
        axisLine: { lineStyle: { color: grid } },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: grid, type: "dashed", opacity: 0.45 } },
        axisLabel: {
          color: axis, fontSize: 11, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          hideOverlap: true, splitNumber: 6,
          formatter: (value: number) => {
            const sec = Math.round((value - Date.now()) / 1000);
            return sec >= 0 ? "now" : `${sec}s`;
          },
        },
      },
      yAxis: [
        {
          type: "value",
          show: showVRef.current, min: vRange[0], max: vRange[1], position: "left",
          splitNumber: 4, interval: (vRange[1] - vRange[0]) / 4,
          axisLine: { show: false }, axisTick: { show: true, length: 3, lineStyle: { color: grid } },
          axisLabel: { color: axis, fontSize: 11, fontFamily: "ui-monospace, monospace", formatter: (v: number) => v.toFixed(vDigits) },
          splitLine: { lineStyle: { color: grid } },
        },
        {
          type: "value",
          show: showARef.current, min: iRange[0], max: iRange[1], position: "right",
          splitNumber: 4, interval: (iRange[1] - iRange[0]) / 4,
          axisLine: { show: false }, axisTick: { show: true, length: 3, lineStyle: { color: grid } },
          axisLabel: { color: axis, fontSize: 11, fontFamily: "ui-monospace, monospace", formatter: (v: number) => v.toFixed(iDigits) },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "Voltage", type: "line", data: showVRef.current ? vData : [], yAxisIndex: 0,
          showSymbol: false, smooth: 0.25, animation: false, emphasis: { disabled: true },
          lineStyle: { width: 2.2, color: vColor }, itemStyle: { color: vColor },
          markLine: {
            silent: true, symbol: "none",
            lineStyle: { color: vColor, width: 1, type: "dashed", opacity: 0.35 },
            label: { show: false },
            data: vsetRef.current != null ? [{ yAxis: vsetRef.current }] : [],
          },
        },
        {
          name: "Current", type: "line", data: showARef.current ? iData : [], yAxisIndex: 1,
          showSymbol: false, smooth: 0.25, animation: false, emphasis: { disabled: true },
          lineStyle: { width: 2, color: iColor }, itemStyle: { color: iColor },
          markLine: {
            silent: true, symbol: "none",
            lineStyle: { color: iColor, width: 1, type: "dashed", opacity: 0.3 },
            label: { show: false },
            data: isetRef.current != null ? [{ yAxis: isetRef.current }] : [],
          },
        },
        {
          name: "", type: "scatter", data: showVRef.current && vData.length ? [vData[vData.length - 1]] : [],
          yAxisIndex: 0, symbolSize: 5, silent: true, tooltip: { show: false },
          itemStyle: { color: vColor, borderColor: darkRef.current ? "#1E1C1A" : "#FBFAF7", borderWidth: 2 },
        },
        {
          name: "", type: "scatter", data: showARef.current && iData.length ? [iData[iData.length - 1]] : [],
          yAxisIndex: 1, symbolSize: 5, silent: true, tooltip: { show: false },
          itemStyle: { color: iColor, borderColor: darkRef.current ? "#1E1C1A" : "#FBFAF7", borderWidth: 2 },
        },
      ],
    }, { lazyUpdate: false });
  }, []);

  const scheduleDraw = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      draw();
    });
  }, [draw]);

  const appendPoint = useCallback((p: Point) => {
    if (!enabledRef.current) return;
    const buf = bufferRef.current;
    if (buf.length && p.t <= buf[buf.length - 1].t) return;
    buf.push(p);
    const keep = cacheRef.current ? 3_600_000 : windowRef.current + 2000;
    const cutoff = Date.now() - keep;
    while (buf.length && buf[0].t < cutoff) buf.shift();
    if (buf.length > 108_000) buf.splice(0, buf.length - 108_000);
    if (!hasDataRef.current) { hasDataRef.current = true; setHasData(true); }
    if (!pausedRef.current) scheduleDraw();
  }, [scheduleDraw]);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const chart = echarts.init(host, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(host);
    draw();
    return () => {
      ro.disconnect();
      cancelAnimationFrame(rafRef.current);
      chart.dispose();
      chartRef.current = null;
    };
  }, [draw]);

  useEffect(() => { scheduleDraw(); }, [dark, showV, showA, paused, smooth, delayMs, vManual, iManual, scheduleDraw]);

  useEffect(() => {
    let raf = 0;
    let last = 0;
    const tick = (ts: number) => {
      raf = requestAnimationFrame(tick);
      if (document.hidden || pausedRef.current || ts - last < 33) return;
      last = ts;
      draw();
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [scroll]);
  useEffect(() => {
    if (!enabled) {
      bufferRef.current = [];
      hasDataRef.current = false;
      setHasData(false);
      scheduleDraw();
    }
  }, [enabled, scheduleDraw]);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let timer: number | undefined;
    const appendSamples = (d: { samples?: { t: number; voltage?: number | null; current?: number | null; power?: number | null }[] }) => {
      if (cancelled || !d?.samples) return;
      for (const s of d.samples) {
        appendPoint({ t: s.t, v: s.voltage ?? null, i: s.current ?? null, p: s.power ?? null });
      }
    };
    const startStream = () => {
      if (cancelled) return;
      es = new EventSource(streamUrl);
      es.onmessage = (ev) => {
        let d: { t?: number; voltage?: number | null; current?: number | null; power?: number | null; error?: string };
        try { d = JSON.parse(ev.data); } catch { return; }
        if (d.error || d.t == null) return;
        appendPoint({ t: d.t, v: d.voltage ?? null, i: d.current ?? null, p: d.power ?? null });
      };
    };
    const pollOnce = async () => {
      try {
        const url = new URL(historyUrl, location.origin);
        url.searchParams.set("seconds", "4");
        appendSamples(await (await fetch(url)).json());
      } catch { /* retry below */ }
      if (!cancelled) timer = window.setTimeout(pollOnce, 120);
    };
    fetch(historyUrl)
      .then((r) => r.json())
      .then((d) => {
        appendSamples(d);
        if (poll) pollOnce(); else startStream();
      })
      .catch(() => { if (poll) pollOnce(); else startStream(); });
    return () => { cancelled = true; es?.close(); if (timer) window.clearTimeout(timer); };
  }, [historyUrl, streamUrl, appendPoint, poll]);

  const vC = dark ? "#FF8A5C" : "#C2410C";
  const iC = dark ? "#5CC8E5" : "#0E7490";
  return (
    <div className="relative w-full" style={{ height }}>
      <div ref={hostRef} className="h-full w-full" />
      <div className="pointer-events-none absolute inset-x-0 top-1.5 flex items-center justify-between px-[56px] font-mono text-[10px] font-semibold tracking-widest">
        {showV && <span style={{ color: vC }}>V</span>}
        {showA && <span style={{ color: iC }}>A</span>}
      </div>
      {!enabled ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          Output is off · 输出未开启
        </div>
      ) : !hasData ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          waiting for samples…
        </div>
      ) : null}
    </div>
  );
});
