import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, CanvasRenderer]);

export type Point = { t: number; v: number | null; i: number | null; p: number | null };
export type LiveChartHandle = { history: () => Point[] };
const LEAD_MS = 100;

function niceBounds(lo: number, hi: number): [number, number] {
  const raw = (hi - lo) / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step];
}

function baseRange(kind: "v" | "i", vset?: number | null, iset?: number | null): [number, number] | null {
  if (kind === "v" && vset != null && Number.isFinite(vset)) {
    const span = Math.max(0.01, Math.abs(vset) * 0.002);
    return niceBounds(vset - span, vset + span);
  }
  if (kind === "i" && iset != null && Number.isFinite(iset)) {
    const span = Math.max(0.002, Math.abs(iset) * 0.01);
    return niceBounds(iset - span, iset + span);
  }
  return null;
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
  cache: boolean; vset?: number | null; iset?: number | null; showV: boolean; showA: boolean; paused: boolean;
}>(function LiveChart({ streamUrl, historyUrl, dark, height = 430, windowMs, cache, vset, iset, showV, showA, paused }, ref) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const bufferRef = useRef<Point[]>([]);
  const vRangeRef = useRef<[number, number] | null>(null);
  const iRangeRef = useRef<[number, number] | null>(null);
  const windowRef = useRef(windowMs);
  const cacheRef = useRef(cache);
  const darkRef = useRef(dark);
  const showVRef = useRef(showV);
  const showARef = useRef(showA);
  const vsetRef = useRef(vset);
  const isetRef = useRef(iset);
  const pausedRef = useRef(paused);
  const rafRef = useRef(0);
  const [hasData, setHasData] = useState(false);
  const hasDataRef = useRef(false);
  windowRef.current = windowMs;
  cacheRef.current = cache;
  darkRef.current = dark;
  showVRef.current = showV;
  showARef.current = showA;
  vsetRef.current = vset;
  isetRef.current = iset;
  pausedRef.current = paused;

  useImperativeHandle(ref, () => ({ history: () => bufferRef.current.slice() }), []);

  const draw = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const now = Date.now();
    const cutoff = now - windowRef.current - 2000;
    const start = now - windowRef.current + LEAD_MS;
    const end = now + LEAD_MS;
    const vData: [number, number][] = [];
    const iData: [number, number][] = [];
    const vs: number[] = [];
    const is: number[] = [];
    for (const p of bufferRef.current) {
      if (p.t < cutoff) continue;
      if (p.v != null) { vData.push([p.t, p.v]); vs.push(p.v); }
      if (p.i != null) { iData.push([p.t, p.i]); is.push(p.i); }
    }
    const vRange = stableRange(vs, vRangeRef.current, baseRange("v", vsetRef.current, isetRef.current));
    const iRange = stableRange(is, iRangeRef.current, baseRange("i", vsetRef.current, isetRef.current));
    vRangeRef.current = vRange;
    iRangeRef.current = iRange;
    const axis = darkRef.current ? "#94a3b8" : "#64748b";
    const grid = darkRef.current ? "rgba(148,163,184,0.16)" : "rgba(100,116,139,0.16)";
    const vColor = "#3b82f6";
    const iColor = "#f59e0b";
    chart.setOption({
      animation: false,
      useDirtyRect: true,
      grid: { left: showVRef.current ? 52 : 16, right: showARef.current ? 56 : 16, top: 22, bottom: 30 },
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
        splitLine: { show: false },
        axisLabel: {
          color: axis, fontSize: 11, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          formatter: (value: number) => {
            const s = Math.round((value - Date.now()) / 1000);
            return s >= 0 ? "now" : `${s}s`;
          },
        },
      },
      yAxis: [
        {
          type: "value", name: "V", nameTextStyle: { color: vColor, align: "left" },
          show: showVRef.current, min: vRange[0], max: vRange[1], position: "left",
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: axis, fontSize: 11, fontFamily: "ui-monospace, monospace" },
          splitLine: { lineStyle: { color: grid } },
        },
        {
          type: "value", name: "A", nameTextStyle: { color: iColor, align: "right" },
          show: showARef.current, min: iRange[0], max: iRange[1], position: "right",
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: axis, fontSize: 11, fontFamily: "ui-monospace, monospace" },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "Voltage", type: "line", data: showVRef.current ? vData : [], yAxisIndex: 0,
          showSymbol: false, smooth: 0.25, animation: false, emphasis: { disabled: true },
          lineStyle: { width: 2, color: vColor }, itemStyle: { color: vColor },
        },
        {
          name: "Current", type: "line", data: showARef.current ? iData : [], yAxisIndex: 1,
          showSymbol: false, smooth: 0.25, animation: false, emphasis: { disabled: true },
          lineStyle: { width: 2, color: iColor }, itemStyle: { color: iColor },
        },
      ],
    }, { lazyUpdate: true });
  }, []);

  const scheduleDraw = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      draw();
    });
  }, [draw]);

  const appendPoint = useCallback((p: Point) => {
    const buf = bufferRef.current;
    if (buf.length && p.t <= buf[buf.length - 1].t) return;
    buf.push(p);
    const keep = cacheRef.current ? 3_600_000 : Math.max(windowRef.current + 2000, 62_000);
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

  useEffect(() => { scheduleDraw(); }, [dark, showV, showA, paused, scheduleDraw]);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
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
    fetch(historyUrl)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled || !d?.samples) return;
        for (const s of d.samples) {
          appendPoint({ t: s.t, v: s.voltage ?? null, i: s.current ?? null, p: s.power ?? null });
        }
      })
      .catch(() => { /* history is optional */ })
      .finally(startStream);
    return () => { cancelled = true; es?.close(); };
  }, [historyUrl, streamUrl, appendPoint]);

  return (
    <div className="relative w-full" style={{ height }}>
      <div ref={hostRef} className="h-full w-full" />
      {!hasData && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          waiting for samples…
        </div>
      )}
    </div>
  );
});
