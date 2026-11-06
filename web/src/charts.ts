// Hand-built SVG/HTML charts: the readiness "lattice dial", bars, lines and a heatmap.
import { esc } from "./ui.js";

const STOPS: [number, [number, number, number]][] = [
  [0, [240, 80, 74]], [0.35, [245, 138, 52]], [0.65, [233, 196, 64]], [1, [60, 203, 127]],
];

export function riskRamp(t: number): string {
  const x = Math.max(0, Math.min(1, t));
  for (let i = 1; i < STOPS.length; i++) {
    const [p1, c1] = STOPS[i - 1];
    const [p2, c2] = STOPS[i];
    if (x <= p2) {
      const k = (x - p1) / (p2 - p1);
      const c = c1.map((v, j) => Math.round(v + (c2[j] - v) * k));
      return `rgb(${c[0]},${c[1]},${c[2]})`;
    }
  }
  return "rgb(60,203,127)";
}

/** Readiness gauge drawn as a lattice of dots on a half circle; lit dots = readiness %. */
export function latticeDial(value: number, label = "PQC readiness"): string {
  const W = 320, H = 190, cx = 160, cy = 170;
  const cols = 34, rows = [118, 132, 146];
  const lit = Math.round((Math.max(0, Math.min(100, value)) / 100) * (cols - 1));
  let dots = "";
  for (let i = 0; i < cols; i++) {
    const t = i / (cols - 1);
    const a = Math.PI - t * Math.PI;
    const color = i <= lit && value > 0 ? riskRamp(t) : "#243152";
    rows.forEach((r, ri) => {
      const x = cx + r * Math.cos(a);
      const y = cy - r * Math.sin(a);
      const size = ri === 1 ? 4.2 : 3.3;
      dots += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${size}" fill="${color}"${i <= lit && value > 0 ? "" : ' opacity="0.9"'}/>`;
    });
  }
  return `<svg viewBox="0 0 ${W} ${H}" class="w-full max-w-[340px]" role="img" aria-label="${esc(label)}: ${value.toFixed(0)} percent">
    ${dots}
    <text x="${cx}" y="${cy - 30}" text-anchor="middle" class="font-display" font-size="52" font-weight="600" fill="#E4E9F5">${value.toFixed(0)}<tspan font-size="24" fill="#8B96B3">%</tspan></text>
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="13" fill="#8B96B3">${esc(label)}</text>
    <text x="${cx - 146}" y="${cy + 16}" text-anchor="middle" font-size="11" fill="#8B96B3">0</text>
    <text x="${cx + 146}" y="${cy + 16}" text-anchor="middle" font-size="11" fill="#8B96B3">100</text>
  </svg>`;
}

/** Horizontal bars as HTML rows (label, bar, value). */
export function hbars(items: { label: string; value: number; color: string; display?: string; title?: string }[],
                      max?: number, labelCol = "minmax(90px,150px)"): string {
  const m = max ?? Math.max(1, ...items.map((i) => i.value));
  return `<div class="space-y-2.5">${items.map((i) => `
    <div class="grid items-center gap-3 text-[13.5px]" style="grid-template-columns:${labelCol} 1fr auto" title="${esc(i.title ?? "")}">
      <span class="truncate text-fog">${esc(i.label)}</span>
      <div class="bar-track"><div class="h-full rounded-full" style="width:${(100 * i.value / m).toFixed(1)}%;background:${i.color}"></div></div>
      <span class="tabular w-14 text-right">${esc(i.display ?? String(i.value))}</span>
    </div>`).join("")}</div>`;
}

/** One stacked bar per row; segments share a total. */
export function stackedRows(rows: { label: string; parts: { value: number; color: string; name: string }[] }[]): string {
  return `<div class="space-y-3">${rows.map((r) => {
    const total = r.parts.reduce((s, p) => s + p.value, 0) || 1;
    return `<div class="grid grid-cols-[64px_1fr_44px] items-center gap-3 text-[13.5px]">
      <span class="text-fog">${esc(r.label)}</span>
      <div class="flex h-3 overflow-hidden rounded-full bg-ink-3">${r.parts.map((p) =>
        `<div title="${esc(p.name)}: ${p.value}" style="width:${(100 * p.value / total).toFixed(2)}%;background:${p.color}"
          class="h-full border-r-2 border-ink-1 last:border-r-0"></div>`).join("")}</div>
      <span class="tabular text-right">${total}</span></div>`;
  }).join("")}</div>`;
}

export type Series = { name: string; color: string; points: [number, number][]; dashed?: boolean };

/** Line chart with light axes. Optional vertical marker at x = marker. */
// A round tick step (1, 2, 2.5 or 5 times a power of ten) giving about four grid lines.
function niceStep(range: number, n = 4): number {
  const raw = Math.max(range, 1e-9) / n;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

export function lineChart(series: Series[], opts: { yMax?: number; yMin?: number; xLabel?: string; yLabel?: string;
  marker?: number; height?: number; yFormat?: (v: number) => string } = {}): string {
  const W = 640, H = opts.height ?? 240, L = 46, R = 14, T = 14, B = 36;
  const xs = series.flatMap((s) => s.points.map((p) => p[0]));
  const ys = series.flatMap((s) => s.points.map((p) => p[1]));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = opts.yMin ?? 0;
  const step = niceStep((opts.yMax ?? Math.max(...ys) * 1.04) - y0);
  const y1 = opts.yMax ?? y0 + Math.ceil((Math.max(...ys) * 1.04 - y0) / step) * step;
  const X = (x: number) => L + ((x - x0) / Math.max(1e-9, x1 - x0)) * (W - L - R);
  const Y = (y: number) => H - B - ((y - y0) / Math.max(1e-9, y1 - y0)) * (H - T - B);
  const decimals = Number.isInteger(step) ? 0 : Math.min(3, (String(step).split(".")[1] ?? "").length);
  const fmt = opts.yFormat ?? ((v: number) => v.toFixed(decimals));
  let grid = "";
  const ticks = opts.yMax != null ? 4 : Math.round((y1 - y0) / step);
  for (let i = 0; i <= ticks; i++) {
    const v = y0 + ((y1 - y0) * i) / ticks;
    grid += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#243152" stroke-width="1"/>
      <text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="#8B96B3">${esc(fmt(v))}</text>`;
  }
  const xticks = 5;
  for (let i = 0; i <= xticks; i++) {
    const v = x0 + ((x1 - x0) * i) / xticks;
    grid += `<text x="${X(v)}" y="${H - B + 16}" text-anchor="middle" font-size="11" fill="#8B96B3">${Math.round(v)}</text>`;
  }
  const lines = series.map((s) => `<path d="${s.points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("")}"
      fill="none" stroke="${s.color}" stroke-width="2" ${s.dashed ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round"/>`).join("");
  const marker = opts.marker != null ? `<line x1="${X(opts.marker)}" x2="${X(opts.marker)}" y1="${T}" y2="${H - B}" stroke="#9B8CFF" stroke-width="1.5" stroke-dasharray="4 4"/>` : "";
  const legend = series.length > 1 ? `<div class="flex flex-wrap gap-4 text-[12.5px] text-fog mt-1">${series.map((s) =>
    `<span class="inline-flex items-center gap-1.5"><span class="h-0.5 w-4" style="background:${s.color}"></span>${esc(s.name)}</span>`).join("")}</div>` : "";
  return `<svg viewBox="0 0 ${W} ${H}" class="w-full" role="img" aria-label="${esc(series.map((s) => s.name).join(", "))}">
    ${grid}${marker}${lines}
    ${opts.xLabel ? `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle" font-size="11.5" fill="#8B96B3">${esc(opts.xLabel)}</text>` : ""}
    ${opts.yLabel ? `<text x="12" y="${T + (H - T - B) / 2}" transform="rotate(-90 12 ${T + (H - T - B) / 2})" text-anchor="middle" font-size="11.5" fill="#8B96B3">${esc(opts.yLabel)}</text>` : ""}
  </svg>${legend}`;
}

/** Mean ± std as horizontal dots with whiskers; the highlighted row uses the accent. */
export function whiskers(items: { label: string; mean: number; std: number; highlight?: boolean }[], max = 1): string {
  return `<div class="space-y-3">${items.map((i) => {
    const lo = Math.max(0, i.mean - i.std) / max * 100, hi = Math.min(max, i.mean + i.std) / max * 100, m = (i.mean / max) * 100;
    const c = i.highlight ? "#9B8CFF" : "#8B96B3";
    return `<div class="grid grid-cols-[minmax(130px,210px)_1fr_86px] items-center gap-3 text-[13.5px]">
      <span class="${i.highlight ? "text-mist font-medium" : "text-fog"} truncate">${esc(i.label)}</span>
      <div class="relative h-5"><div class="absolute inset-y-[9px] left-0 right-0 bg-ink-3 rounded"></div>
        <div class="absolute top-[9px] h-[2px]" style="left:${lo}%;width:${hi - lo}%;background:${c}"></div>
        <div class="absolute top-[4px] h-3 w-3 -ml-1.5 rounded-full border-2 border-ink-1" style="left:${m}%;background:${c}"></div></div>
      <span class="tabular text-right">${i.mean.toFixed(2)} ± ${i.std.toFixed(2)}</span></div>`;
  }).join("")}</div>`;
}

/** Confusion matrix heatmap (rows = actual, columns = predicted). */
export function heatmap(matrix: number[][], labels: string[]): string {
  const max = Math.max(1, ...matrix.flat());
  const cell = (v: number, diag: boolean) => {
    const a = 0.12 + 0.8 * (v / max);
    const bg = diag ? `rgba(155,140,255,${a.toFixed(2)})` : `rgba(240,80,74,${(a * 0.7).toFixed(2)})`;
    return `<td class="h-11 w-14 text-center tabular border border-ink-1" style="background:${bg}">${v}</td>`;
  };
  return `<table class="text-[13px]"><thead><tr><th></th>${labels.map((l) => `<th class="px-1 pb-1 font-medium text-fog">${esc(l)}</th>`).join("")}</tr></thead>
    <tbody>${matrix.map((row, i) => `<tr><th class="pr-2 text-right font-medium text-fog">${esc(labels[i])}</th>${row.map((v, j) => cell(v, i === j)).join("")}</tr>`).join("")}</tbody></table>
    <p class="muted text-[12.5px] mt-2">Rows: analyst label. Columns: model prediction. Violet = correct, red = wrong.</p>`;
}

/** Before/after paired bars for a few measures. */
export function beforeAfter(rows: { label: string; before: number; after: number; better: "lower" | "higher"; unit?: string }[]): string {
  return `<div class="space-y-4">${rows.map((r) => {
    const m = Math.max(r.before, r.after, 1);
    const improved = r.better === "lower" ? r.after < r.before : r.after > r.before;
    return `<div class="text-[13.5px]"><div class="flex justify-between mb-1.5"><span>${esc(r.label)}</span>
      <span class="tabular ${improved ? "text-risk-safe" : "text-fog"}">${r.before}${r.unit ?? ""} to ${r.after}${r.unit ?? ""}</span></div>
      <div class="space-y-1"><div class="bar-track"><div class="h-full rounded-full bg-fog/50" style="width:${(100 * r.before / m).toFixed(1)}%"></div></div>
      <div class="bar-track"><div class="h-full rounded-full bg-lattice" style="width:${(100 * r.after / m).toFixed(1)}%"></div></div></div></div>`;
  }).join("")}<div class="flex gap-4 text-[12.5px] text-fog"><span class="inline-flex items-center gap-1.5"><span class="h-2 w-4 rounded bg-fog/50"></span>At discovery</span><span class="inline-flex items-center gap-1.5"><span class="h-2 w-4 rounded bg-lattice"></span>Now</span></div></div>`;
}
