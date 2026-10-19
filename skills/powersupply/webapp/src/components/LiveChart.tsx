import { useEffect, useRef } from "react";
import { fmt } from "@/lib/utils";

export type ChartPoint = { t: number; v: number | null; i: number | null; p: number | null };
type Metric = "voltage" | "current" | "power";

const KEY: Record<Metric, keyof ChartPoint> = { voltage: "v", current: "i", power: "p" };
export function LiveChart({ points, metric, color, unit, digits, dark, height = 260, windowMs = 10_000 }: {
  points: ChartPoint[]; metric: Metric; color: string; unit: string;
  digits: number; dark: boolean; height?: number; windowMs?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const dataRef = useRef(points);
  const themeRef = useRef(dark);
  dataRef.current = points;
  themeRef.current = dark;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const yr: { v: [number, number] | null } = { v: null };
    let raf = 0;
    let last = 0;
    let w = 0, h = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    const range = (vals: number[]) => {
      let lo = Math.min(...vals), hi = Math.max(...vals);
      if (hi - lo < 1e-9) { const p = Math.max(0.01, Math.abs(hi) * 0.001); lo -= p; hi += p; }
      const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
      return [lo, hi] as const;
    };

    const draw = (ts: number) => {
      raf = requestAnimationFrame(draw);
      if (ts - last < 33) return;
      last = ts;
      const darkNow = themeRef.current;
      const grid = darkNow ? "#262b36" : "#e4e4e7";
      const text = darkNow ? "#8b93a7" : "#71717a";
      const data = dataRef.current;
      ctx.clearRect(0, 0, w, h);
      const L = 56, R = 12, T = 12, B = 22;
      const plotW = Math.max(1, w - L - R);
      const plotH = Math.max(1, h - T - B);
      ctx.strokeStyle = grid;
      ctx.lineWidth = 1;
      for (let k = 0; k <= 4; k++) {
        const y = T + (plotH * k) / 4;
        ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R, y); ctx.stroke();
      }

      const vals = data.map((p) => p[KEY[metric]]).filter((v): v is number => v != null);
      if (!vals.length || data.length < 2) {
        ctx.fillStyle = text;
        ctx.font = "11px ui-monospace, monospace";
        ctx.fillText("waiting for samples…", L + 6, T + 18);
        return;
      }
      const target = range(vals);
      if (!yr.v) yr.v = target;
      else yr.v = [yr.v[0] + (target[0] - yr.v[0]) * 0.12, yr.v[1] + (target[1] - yr.v[1]) * 0.12];
      const [lo, hi] = yr.v;
      const lastT = data[data.length - 1].t;
      const now = Date.now();
      const x = (t: number) => L + plotW * (1 - (now - t) / windowMs);
      const y = (v: number) => T + plotH * (1 - (v - lo) / (hi - lo));

      ctx.save();
      ctx.beginPath(); ctx.rect(L, T, plotW, plotH); ctx.clip();

      const pts: Array<[number, number]> = [];
      for (const p of data) {
        const val = p[KEY[metric]];
        if (val == null) continue;
        const px = x(p.t), py = y(val);
        if (px < L - 2) continue;
        pts.push([px, py]);
      }
      ctx.beginPath();
      if (pts.length === 1) {
        ctx.moveTo(pts[0][0], pts[0][1]);
        ctx.lineTo(pts[0][0], pts[0][1]);
      } else if (pts.length > 1) {
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 0; i < pts.length - 1; i++) {
          const p0 = pts[i - 1] ?? pts[i];
          const p1 = pts[i];
          const p2 = pts[i + 1];
          const p3 = pts[i + 2] ?? p2;
          ctx.bezierCurveTo(
            p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
            p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6,
            p2[0], p2[1],
          );
        }
      }
      if (pts.length) {
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.strokeStyle = color;
        ctx.stroke();
      }

      ctx.lineTo(pts.length ? pts[pts.length - 1][0] : x(lastT), T + plotH);
      ctx.lineTo(pts.length ? pts[0][0] : Math.max(L, x(data[0].t)), T + plotH);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, T, 0, T + plotH);
      grad.addColorStop(0, color + "4d");
      grad.addColorStop(1, color + "05");
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.restore();

      ctx.fillStyle = text;
      ctx.font = "11px ui-monospace, monospace";
      for (let k = 0; k <= 4; k++) {
        const v = hi - ((hi - lo) * k) / 4;
        ctx.fillText(fmt(v, digits), 4, T + (plotH * k) / 4 + 4);
      }
      ctx.textAlign = "right";
      ctx.fillText(unit, w - R, T + 4);
      ctx.textAlign = "left";
      ctx.fillStyle = color;
      const lastVal = data[data.length - 1][KEY[metric]];
      if (lastVal != null) {
        const px = x(lastT), py = y(lastVal);
        ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI * 2); ctx.fill();
      }
    };
    raf = requestAnimationFrame(draw);

    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) raf = requestAnimationFrame(draw);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [color, unit, metric, digits, windowMs]);

  return <canvas ref={ref} style={{ width: "100%", height }} aria-label="live chart" />;
}
