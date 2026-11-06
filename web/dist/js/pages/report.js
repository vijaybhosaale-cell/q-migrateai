// Step 6: measure before and after, and download the PDF report.
import { api } from "../api.js";
import { beforeAfter, hbars, riskRamp } from "../charts.js";
import { RISK_ORDER, emptyState, esc, num, pct, riskBadge, when } from "../ui.js";
export async function reportPage(el) {
    let data, history;
    try {
        [data, history] = await Promise.all([api("/report"), api("/migrations")]);
    }
    catch (e) {
        el.innerHTML = emptyState("Nothing to report yet", esc(e.message), `<a class="btn btn-primary no-underline hover:no-underline" href="#/connect">Connect and discover</a>`);
        return;
    }
    const { before: b, after: a, changes, top_risks } = data.report;
    const rd = data.readiness;
    const direct = changes.filter((c) => c.directly_migrated).length;
    const ripple = changes.length - direct;
    el.innerHTML = `
  <section class="panel panel-pad flex flex-wrap items-center gap-4">
    <div class="max-w-2xl">
      <h2>Before and after migration</h2>
      <p class="mt-1 text-[14px] text-fog">"Before" is the estate as the last discovery found it; "after" is the estate with every migration applied since.
        ${direct ? `${direct} assets were migrated directly and ${ripple} more improved because what they depend on became quantum-safe.` : "No migration has been applied yet, so both columns match."}</p>
    </div>
    <a class="btn btn-primary ml-auto no-underline hover:no-underline" href="/api/report.pdf" data-pdf download>Download PDF report</a>
  </section>

  <div class="mt-5 grid gap-5 xl:grid-cols-[1.1fr_1fr]">
    <section class="panel panel-pad">
      <h2 class="mb-4">Key figures</h2>
      ${beforeAfter([
        { label: "Quantum-exposed assets", before: b.quantum_exposed, after: a.quantum_exposed, better: "lower" },
        { label: "Quantum-safe assets", before: b.quantum_safe, after: a.quantum_safe, better: "higher" },
        { label: "Quantum-safe coverage", before: Math.round(b.coverage_pct * 10) / 10, after: Math.round(a.coverage_pct * 10) / 10, better: "higher", unit: "%" },
        { label: "Critical (AI)", before: b.critical, after: a.critical, better: "lower" },
        { label: "High or Critical (AI)", before: b.high_critical, after: a.high_critical, better: "lower" },
        { label: "Mean AI risk score", before: Math.round(b.mean_ai_score), after: Math.round(a.mean_ai_score), better: "lower" },
    ])}
    </section>
    <section class="panel panel-pad">
      <div class="flex items-baseline gap-3"><h2>NIST readiness</h2>
        <span class="ml-auto font-display text-[28px] font-semibold tabular" style="color:${riskRamp(rd.overall / 100)}">${pct(rd.overall, 0)}</span></div>
      <p class="muted text-[12.5px] mb-4">${esc(rd.note)}</p>
      ${hbars(rd.items.map((i) => ({ label: i.title, value: i.score ?? 0, color: i.score == null ? "#243152" : riskRamp((i.score ?? 0) / 100),
        display: i.score == null ? "n/a" : pct(i.score, 0), title: i.detail })), 100, "minmax(150px,1.4fr)")}
    </section>
  </div>

  <div class="mt-5 grid gap-5 xl:grid-cols-2">
    <section class="panel panel-pad">
      <h2 class="mb-4">AI risk classes</h2>
      <table class="tbl"><thead><tr><th>Class</th><th class="text-right">Before</th><th class="text-right">After</th><th class="text-right">Change</th></tr></thead>
        <tbody>${RISK_ORDER.map((c) => {
        const d = a.ai_classes[c] - b.ai_classes[c];
        return `<tr><td>${riskBadge(c)}</td><td class="text-right tabular">${b.ai_classes[c]}</td><td class="text-right tabular">${a.ai_classes[c]}</td>
            <td class="text-right tabular ${d === 0 ? "text-fog" : (c === "Low" ? d > 0 : d < 0) ? "text-risk-safe" : "text-risk-critical"}">${d > 0 ? "+" : ""}${d}</td></tr>`;
    }).join("")}</tbody></table>
    </section>
    <section class="panel panel-pad">
      <h2 class="mb-4">By cloud</h2>
      <table class="tbl"><thead><tr><th>Cloud</th><th class="text-right">Assets</th><th class="text-right">Exposed before</th><th class="text-right">Exposed after</th><th class="text-right">Safe after</th></tr></thead>
        <tbody>${Object.keys(a.by_cloud).map((c) => `<tr><td>${esc(c)}</td><td class="text-right tabular">${a.by_cloud[c].assets}</td>
          <td class="text-right tabular">${b.by_cloud[c]?.quantum_exposed ?? "–"}</td><td class="text-right tabular">${a.by_cloud[c].quantum_exposed}</td>
          <td class="text-right tabular text-risk-safe">${a.by_cloud[c].quantum_safe}</td></tr>`).join("")}</tbody></table>
    </section>
  </div>

  <section class="panel mt-5">
    <div class="px-5 pt-5"><h2>Assets that changed</h2><p class="muted text-[13px]">Largest risk reduction first.</p></div>
    ${changes.length ? `<div class="overflow-x-auto mt-2"><table class="tbl">
      <thead><tr><th>Asset</th><th>Service</th><th>Algorithm</th><th>AI risk</th><th class="text-right">Score</th><th>How</th></tr></thead>
      <tbody>${changes.slice(0, 60).map((c) => `<tr><td class="id">${esc(c.asset_id)}</td><td>${esc(c.service_label)}</td>
        <td class="id">${c.directly_migrated ? `<span class="text-risk-critical">${esc(c.algorithm_before)}</span> <span class="text-fog">to</span> <span class="text-risk-safe">${esc(c.algorithm_after)}</span>` : esc(c.algorithm_after)}</td>
        <td>${riskBadge(c.class_before)} <span class="text-fog">to</span> ${riskBadge(c.class_after)}</td>
        <td class="text-right tabular">${c.score_before.toFixed(0)} to ${c.score_after.toFixed(0)}</td>
        <td class="text-fog text-[12.5px]">${c.directly_migrated ? "migrated" : "dependency became safe"}</td></tr>`).join("")}</tbody></table></div>
      ${changes.length > 60 ? `<p class="px-5 pb-4 text-[13px] text-fog">Showing 60 of ${num(changes.length)}. The PDF lists them all.</p>` : ""}`
        : `<p class="p-5 text-fog">No changes yet. Migrate Wave 1 from the <a href="#/plan">plan</a> or try one asset in the <a href="#/lab">PQC lab</a>.</p>`}
  </section>

  <div class="mt-5 grid gap-5 2xl:grid-cols-2">
    <section class="panel">
      <div class="px-5 pt-5"><h2>Top 10 remaining risks</h2></div>
      <div class="overflow-x-auto mt-2"><table class="tbl"><thead><tr><th>Asset</th><th>Service</th><th>Algorithm</th><th>AI risk</th><th class="text-right">Dependants</th></tr></thead>
        <tbody>${top_risks.map((r) => `<tr><td class="id"><a href="#/assets?focus=${encodeURIComponent(r.asset_id)}">${esc(r.asset_id)}</a></td><td>${esc(r.service_label)}</td>
          <td class="id">${esc(r.algorithm)}</td><td>${riskBadge(r.ai_class)}</td><td class="text-right tabular">${r.dependents}</td></tr>`).join("")}</tbody></table></div>
    </section>
    <section class="panel">
      <div class="px-5 pt-5"><h2>Migration history</h2></div>
      ${history.length ? `<div class="overflow-x-auto mt-2 max-h-[420px] overflow-y-auto"><table class="tbl"><thead><tr><th>When</th><th>Asset</th><th>Change</th><th>By</th></tr></thead>
        <tbody>${history.map((h) => `<tr><td class="text-fog whitespace-nowrap">${esc(when(h.created_at))}</td><td class="id">${esc(h.asset_id)}</td>
          <td class="text-[13px]">${h.action === "rollback" ? `<span class="chip border-risk-medium/50 text-risk-medium">rollback</span> ` : ""}<span class="id">${esc(h.from_alg)}</span> <span class="text-fog">to</span> <span class="id">${esc(h.to_alg)}</span>${h.wave ? ` <span class="text-fog">(${esc(h.wave)})</span>` : ""}</td>
          <td class="text-fog text-[12.5px]">${esc(h.user_email)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="p-5 text-fog">No migrations yet.</p>`}
    </section>
  </div>`;
}
