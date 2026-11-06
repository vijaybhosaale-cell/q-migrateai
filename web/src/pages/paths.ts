// Data paths (P7): a request or record crosses several assets, and is only as quantum-safe as its weakest hop.
import { api } from "../api.js";
import { $, emptyState, esc, num } from "../ui.js";

function tile(label: string, value: string, sub: string, accent = ""): string {
  return `<div class="rounded-xl border border-line bg-ink-0/70 p-4">
    <p class="text-[13.5px] text-fog">${esc(label)}</p>
    <p class="kpi-value mt-2 ${accent}">${value}</p>
    <p class="mt-2 text-[12.5px] text-fog">${sub}</p></div>`;
}

function hop(h: any, weakest: boolean): string {
  const cls = h.safe ? "border-risk-safe/50 text-risk-safe" : weakest ? "border-risk-critical text-risk-critical" : "border-risk-high/40 text-mist";
  return `<a href="#/assets?focus=${encodeURIComponent(h.asset_id)}" class="chip no-underline hover:no-underline ${cls}" title="${esc(h.service_label)}, ${esc(h.algorithm)}">${esc(h.asset_id)}</a>`;
}

function chain(p: any): string {
  return `<div class="flex flex-wrap items-center gap-1">${p.hops.map((h: any) => hop(h, h.asset_id === p.weakest_hop))
    .join(`<span class="text-fog" aria-hidden="true">›</span>`)}</div>`;
}

function compareTable(rows: any[], wave1: number): string {
  const line = (label: string, key: string, unit = "") =>
    `<tr><td>${label}</td>${rows.map((r) => `<td class="tabular">${num(r.per_asset[key])}${unit}</td><td class="tabular text-mist">${num(r.path_first[key])}${unit}</td>`).join("")}</tr>`;
  return `<div class="overflow-x-auto"><table class="tbl">
    <thead><tr><th></th>${rows.map((r) => `<th colspan="2">${r.budget === wave1 ? `Wave 1 (${r.budget} migrations)` : `${r.budget} migrations`}</th>`).join("")}</tr>
      <tr><th></th>${rows.map(() => `<th>Asset queue</th><th>Path-first</th>`).join("")}</tr></thead>
    <tbody>
      ${line("Paths safe end to end", "safe_paths")}
      ${line("Share of path value safe", "safe_value_pct", "%")}
      ${line("Assets quantum-safe", "asset_coverage_pct", "%")}
      ${line("False assurance (assets)", "false_assurance")}
    </tbody></table></div>`;
}

export async function pathsPage(el: HTMLElement): Promise<void> {
  const r = await api("/paths");
  if (!r.has_paths) {
    el.innerHTML = emptyState("No data paths in this workspace",
      "Data paths need links that show where data travels: load balancer to gateway, gateway to backend, backend to database or queue, database to backup. Public websites only show their certificate chain, and the cloud connectors read keys and certificates, so there is nothing to chain together yet.");
    return;
  }
  const now = r.now;
  const w1 = r.comparison.find((c: any) => c.budget === r.wave1_size) ?? r.comparison[0];
  el.innerHTML = `
  <div class="space-y-5">
    <section class="panel panel-pad">
      <h2>Is the data safe end to end?</h2>
      <p class="mt-2 max-w-[75ch] text-[13.5px] text-fog">A request or a record crosses several assets. Harvest-now-decrypt-later needs only one readable hop, so a path is only as quantum-safe as its weakest hop. An asset can be quantum-safe on its own and still carry data that is recorded in the clear one hop later.</p>
      <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        ${tile("Assets quantum-safe", `${num(now.asset_coverage_pct)}%`, "the per-asset view")}
        ${tile("Data paths safe end to end", `${num(now.safe_paths)} of ${num(now.paths)}`, `${num(now.sensitive_paths)} paths carry sensitivity 4–5 data`, now.safe_paths ? "" : "text-risk-critical")}
        ${tile("False assurance", num(now.false_assurance), "assets safe on their own, on a path still readable elsewhere", "text-risk-high")}
        ${tile("Path value at risk", `${num(now.harvestable_value_pct)}%`, "weighted by data sensitivity and secrecy lifetime")}
      </div>
    </section>

    <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section class="panel min-w-0">
        <div class="px-5 pt-5"><h2>Same number of migrations, two orders</h2>
          <p class="mt-2 text-[13.5px] text-fog">The asset queue (the waves on the plan page) picks the riskiest single assets. Path-first picks the migrations that close whole paths, most valuable first.
          With Wave 1 the queue makes <span class="text-mist">${num(w1.per_asset.safe_paths)}</span> paths safe end to end; path-first makes <span class="text-mist">${num(w1.path_first.safe_paths)}</span>.</p></div>
        <div class="mt-3">${compareTable(r.comparison, r.wave1_size)}</div>
      </section>
      <section class="panel panel-pad min-w-0">
        <h2>Hops that block the most paths</h2>
        <p class="mt-2 text-[13px] text-fog">Migrating these, or the key behind them, unblocks the most path value.</p>
        <ol class="mt-3 space-y-2 text-[13.5px]">${r.bottlenecks.slice(0, 8).map((b: any) => `
          <li class="flex items-baseline gap-2"><a class="id shrink-0 whitespace-nowrap" href="#/assets?focus=${encodeURIComponent(b.asset_id)}">${esc(b.asset_id)}</a>
            <span class="min-w-0 truncate text-fog" title="${esc(b.service_label)}, ${esc(b.algorithm)}">${esc(b.algorithm)}</span><span class="ml-auto shrink-0 whitespace-nowrap tabular text-fog">${num(b.paths)} paths</span></li>`).join("")}</ol>
      </section>
    </div>

    <section class="panel">
      <div class="flex flex-wrap items-end gap-3 px-5 pt-5">
        <div><h2>Paths</h2><p class="mt-1 text-[13px] text-fog">Weakest hop in red, safe hops in green. Most valuable unsafe paths first.</p></div>
        <label class="ml-auto flex items-center gap-2 text-[13px] text-fog"><input type="checkbox" data-sens> Sensitivity 4–5 only</label>
      </div>
      <div class="mt-3 overflow-x-auto"><table class="tbl">
        <thead><tr><th>Path</th><th>Weakest hop</th><th>Safe hops</th><th>Data</th></tr></thead>
        <tbody data-body></tbody></table></div>
    </section>

    ${r.path_first_wave.length ? `<section class="panel">
      <div class="px-5 pt-5"><h2>A path-first Wave 1</h2>
        <p class="mt-1 text-[13px] text-fog">The ${num(r.path_first_wave.length)} migrations that close the most valuable paths. Compare it with Wave 1 on the plan page before you choose.</p></div>
      <div class="mt-3 overflow-x-auto"><table class="tbl"><thead><tr><th>#</th><th>Asset</th><th>Now</th><th>Move to</th></tr></thead>
        <tbody>${r.path_first_wave.map((x: any, i: number) => `<tr><td class="tabular">${i + 1}</td>
          <td><a class="id" href="#/assets?focus=${encodeURIComponent(x.asset_id)}">${esc(x.asset_id)}</a> <span class="text-fog">${esc(x.service_label)}</span></td>
          <td>${esc(x.algorithm)}</td><td>${esc(x.target)}</td></tr>`).join("")}</tbody></table></div>
    </section>` : ""}
  </div>`;

  const body = $("[data-body]", el)!;
  const draw = () => {
    const sensOnly = ($<HTMLInputElement>("[data-sens]", el)!).checked;
    const list = r.paths.filter((p: any) => !sensOnly || p.max_sensitivity >= 4).slice(0, 80);
    body.innerHTML = list.map((p: any) => `<tr>
      <td class="min-w-[320px]">${chain(p)}</td>
      <td>${p.weakest_hop ? `<span class="id">${esc(p.weakest_hop)}</span><div class="text-[12.5px] text-fog">${esc(p.weakest_reason ?? "")}</div>` : `<span class="text-risk-safe">none</span>`}</td>
      <td class="tabular">${num(p.safe_hops)} of ${num(p.hops.length)}</td>
      <td class="tabular">sensitivity ${num(p.max_sensitivity)}</td></tr>`).join("");
  };
  $("[data-sens]", el)!.addEventListener("change", draw);
  draw();
}
