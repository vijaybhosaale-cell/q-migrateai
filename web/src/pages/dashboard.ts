// Dashboard: readiness dial, KPI tiles, where the risk is, what to migrate first.
import { api, post } from "../api.js";
import { hbars, latticeDial, riskRamp, stackedRows } from "../charts.js";
import { can, go, refreshUnread } from "../state.js";
import { $, RISK, RISK_ORDER, ago, emptyState, esc, num, pct, riskBadge, toast } from "../ui.js";

function delta(now: number, before: number, lowerIsBetter: boolean, unit = ""): string {
  const d = Math.round((now - before) * 10) / 10;
  if (!d) return `<span class="text-fog">no change since discovery</span>`;
  const good = lowerIsBetter ? d < 0 : d > 0;
  return `<span class="${good ? "text-risk-safe" : "text-risk-critical"}">${d > 0 ? "+" : ""}${d}${unit}</span> <span class="text-fog">since discovery</span>`;
}

function tile(label: string, value: string, sub: string, accent = ""): string {
  return `<div class="rounded-xl border border-line bg-ink-0/70 p-4">
    <p class="text-[13.5px] text-fog">${esc(label)}</p>
    <p class="kpi-value mt-2 ${accent}">${value}</p>
    <p class="mt-2 text-[12.5px]">${sub}</p></div>`;
}

export async function dashboardPage(el: HTMLElement): Promise<void | (() => void)> {
  const ov = await api("/overview");
  refreshUnread();
  if (!ov.has_data) {
    const running = ov.last_discovery?.status === "running";
    el.innerHTML = running
      ? emptyState("Discovery is running", "We are scanning your connected cloud, mapping dependencies and training the AI models. This page refreshes by itself.")
      : emptyState("No inventory yet", "Connect a cloud account (or the demo simulator) and run your first discovery. It takes about half a minute.",
          `<a class="btn btn-primary no-underline hover:no-underline" href="#/connect">Connect and discover</a>`);
    if (running) {
      const t = setInterval(async () => {
        const o = await api("/overview").catch(() => null);
        if (o?.has_data || o?.last_discovery?.status !== "running") { clearInterval(t); go("/dashboard"); }
      }, 2500);
      return () => clearInterval(t);
    }
    return;
  }
  const now = ov.now, before = ov.before, rd = ov.readiness;
  const classes = RISK_ORDER.map((c) => ({ label: RISK[c].label, value: now.ai_classes[c] ?? 0, color: RISK[c].color }));
  const clouds = Object.entries(now.by_cloud as Record<string, any>).map(([cloud, s]) => ({
    label: cloud, parts: [
      { name: "Quantum-exposed", value: s.quantum_exposed, color: "#F0504A" },
      { name: "Needs review", value: s.needs_review, color: "#E9C440" },
      { name: "Quantum-safe", value: s.quantum_safe, color: "#3CCB7F" },
    ] }));
  const last = ov.last_discovery;
  el.innerHTML = `
  <section class="panel-hero lattice-bg overflow-hidden">
    <div class="grid gap-6 p-6 lg:grid-cols-[minmax(300px,380px)_1fr] lg:p-8">
      <div class="flex flex-col items-center justify-center text-center">
        ${latticeDial(rd.overall)}
        <p class="mt-1 max-w-[19rem] text-[12.5px] text-fog">Indicative score from six checks aligned with NIST post-quantum guidance. Not a certification.</p>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        ${tile("Cryptographic assets", num(now.total_assets), `${Object.keys(now.by_cloud).length} clouds, ${num(Object.values(now.by_algorithm as Record<string, number>).length)} algorithms in use`)}
        ${tile("Quantum-exposed", num(now.quantum_exposed), delta(now.quantum_exposed, before.quantum_exposed, true), "text-risk-critical")}
        ${tile("Quantum-safe coverage", `<span style="color:${riskRamp(now.coverage_pct / 100)}">${pct(now.coverage_pct)}</span>`, delta(now.coverage_pct, before.coverage_pct, false, " pts"))}
        ${tile("Critical (AI)", num(now.critical), delta(now.critical, before.critical, true), "text-risk-critical")}
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-3 border-t border-line bg-ink-1/80 px-6 py-3 text-[13.5px] lg:px-8">
      <span class="text-fog">Last discovery ${esc(ago(last?.finished_at))}${last?.assets_found ? `, ${num(last.assets_found)} assets` : ""}</span>
      <span class="ml-auto"></span>
      ${can("discover") ? `<button class="btn btn-sm" data-rescan>Run discovery again</button>` : ""}
      <a class="btn btn-sm btn-primary no-underline hover:no-underline" href="#/graph">Open dependency map</a>
    </div>
  </section>

  <div class="mt-5 grid gap-5 xl:grid-cols-3">
    <section class="panel panel-pad">
      <h2>Risk according to the AI model</h2>
      <p class="muted text-[13px] mb-4">Neural network with dependency-graph features.</p>
      ${hbars(classes)}
    </section>
    <section class="panel panel-pad">
      <h2>Readiness by cloud</h2>
      <p class="muted text-[13px] mb-4">Exposed means RSA, ECC or DH is used directly or by a key it depends on.</p>
      ${stackedRows(clouds)}
      <div class="mt-4 flex flex-wrap gap-4 text-[12.5px] text-fog">
        <span class="inline-flex items-center gap-1.5"><span class="h-2 w-3 rounded bg-risk-critical"></span>Exposed</span>
        <span class="inline-flex items-center gap-1.5"><span class="h-2 w-3 rounded bg-risk-medium"></span>Needs review</span>
        <span class="inline-flex items-center gap-1.5"><span class="h-2 w-3 rounded bg-risk-safe"></span>Quantum-safe</span>
      </div>
    </section>
    <section class="panel panel-pad">
      <h2>Readiness checks</h2>
      <p class="muted text-[13px] mb-4">What moves the dial.</p>
      <ul class="space-y-3">${rd.items.map((i: any) => `
        <li class="text-[13.5px]" title="${esc(i.detail)}">
          <div class="flex justify-between gap-3"><span>${esc(i.title)}</span><span class="tabular text-fog">${i.score == null ? "n/a" : pct(i.score, 0)}</span></div>
          <div class="bar-track mt-1.5"><div class="h-full rounded-full" style="width:${i.score ?? 0}%;background:${(i.score ?? 0) >= 80 ? "#3CCB7F" : (i.score ?? 0) >= 40 ? "#E9C440" : "#F0504A"}"></div></div>
        </li>`).join("")}</ul>
    </section>
  </div>

  <section class="panel mt-5">
    <div class="flex flex-wrap items-center gap-3 px-5 pt-5">
      <div><h2>Migrate first</h2><p class="muted text-[13px]">Highest priority today. Shared keys and certificate authorities protect many assets at once.</p></div>
      <a class="btn btn-sm ml-auto no-underline hover:no-underline" href="#/plan">See the full plan</a>
    </div>
    <div class="overflow-x-auto mt-3"><table class="tbl">
      <thead><tr><th>#</th><th>Asset</th><th>Service</th><th>Now</th><th>Move to</th><th>AI risk</th><th class="text-right">Dependants</th><th></th></tr></thead>
      <tbody>${ov.top_queue.map((q: any) => `<tr>
        <td class="tabular text-fog">${q.rank}</td><td class="id">${esc(q.asset_id)}</td><td>${esc(q.service_label)}</td>
        <td class="id text-risk-critical">${esc(q.algorithm)}</td><td class="id text-risk-safe">${esc(q.target)}</td>
        <td>${riskBadge(q.ai_class)}</td><td class="text-right tabular">${q.dependents}</td>
        <td class="text-right"><a class="btn btn-sm no-underline hover:no-underline" href="#/lab?asset=${encodeURIComponent(q.asset_id)}">Open in lab</a></td></tr>`).join("")}</tbody>
    </table></div>
  </section>`;
  $("[data-rescan]", el)?.addEventListener("click", async () => {
    await post("/discovery/run", {});
    toast("Discovery started. New assets will raise alerts.", "ok");
    go("/connect");
  });
}
