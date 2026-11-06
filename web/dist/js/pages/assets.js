// Step 3: assess risk. Inventory with filters, and a plain-language explanation for every asset.
import { api } from "../api.js";
import { hbars } from "../charts.js";
import { $, RISK, RISK_ORDER, downloadText, emptyState, esc, icon, num, riskBadge, statusBadge } from "../ui.js";
export async function assetsPage(el, params) {
    let rows;
    try {
        rows = await api("/assets");
    }
    catch (e) {
        el.innerHTML = emptyState("No inventory yet", esc(e.message), `<a class="btn btn-primary no-underline hover:no-underline" href="#/connect">Connect and discover</a>`);
        return;
    }
    let shown = 100;
    el.innerHTML = `
  <section class="panel">
    <div class="flex flex-wrap items-end gap-3 border-b border-line p-4">
      <div><label class="label" for="a-q">Search</label><input id="a-q" class="input w-56" placeholder="Asset, application or service"></div>
      <div><label class="label" for="a-cloud">Cloud</label><select id="a-cloud" class="input w-32"><option value="">All</option><option>AWS</option><option>Azure</option><option>GCP</option></select></div>
      <div><label class="label" for="a-risk">AI risk</label><select id="a-risk" class="input w-36"><option value="">All</option>${RISK_ORDER.map((c) => `<option>${c}</option>`).join("")}</select></div>
      <div><label class="label" for="a-status">Quantum status</label><select id="a-status" class="input w-44"><option value="">All</option>
        <option value="exposed">Quantum-exposed</option><option value="review">Review</option><option value="safe">Quantum-safe</option></select></div>
      <p class="ml-auto text-[13.5px] text-fog" data-count></p>
      <button class="btn btn-sm" data-csv>Export CSV</button>
    </div>
    <div class="overflow-x-auto"><table class="tbl">
      <thead><tr><th>Asset</th><th>Service</th><th>Cloud</th><th>Application</th><th>Algorithm</th><th>Status</th><th>AI risk</th>
        <th class="text-right">AI score</th><th class="text-right">Dependants</th></tr></thead>
      <tbody data-body></tbody></table></div>
    <div class="p-4 text-center"><button class="btn btn-sm hidden" data-more>Show more</button></div>
  </section>
  <div data-drawer></div>`;
    const filtered = () => {
        const q = ($("#a-q", el)).value.trim().toLowerCase();
        const cloud = ($("#a-cloud", el)).value;
        const risk = ($("#a-risk", el)).value;
        const status = ($("#a-status", el)).value;
        return rows.filter((r) => (!q || `${r.asset_id} ${r.application} ${r.service_label}`.toLowerCase().includes(q))
            && (!cloud || r.cloud === cloud) && (!risk || r.ai_class === risk)
            && (!status || (status === "exposed" ? r.quantum_exposed : status === "safe" ? r.quantum_safe : !r.quantum_exposed && !r.quantum_safe)))
            .sort((a, b) => b.ai_score - a.ai_score);
    };
    const draw = () => {
        const list = filtered();
        $("[data-count]", el).textContent = `${num(list.length)} of ${num(rows.length)} assets`;
        $("[data-body]", el).innerHTML = list.slice(0, shown).map((r) => `<tr class="cursor-pointer" data-id="${esc(r.asset_id)}" tabindex="0">
      <td class="id">${esc(r.asset_id)}</td><td>${esc(r.service_label)}</td><td>${esc(r.cloud)}</td><td class="text-fog">${esc(r.application)}</td>
      <td class="id">${esc(r.algorithm)}</td><td>${statusBadge(r)}</td><td>${riskBadge(r.ai_class)}</td>
      <td class="text-right tabular">${r.ai_score.toFixed(0)}</td><td class="text-right tabular">${r.dependents}</td></tr>`).join("");
        $("[data-more]", el).classList.toggle("hidden", list.length <= shown);
    };
    ["#a-q", "#a-cloud", "#a-risk", "#a-status"].forEach((s) => $(s, el).addEventListener("input", () => { shown = 100; draw(); }));
    $("[data-more]", el).addEventListener("click", () => { shown += 100; draw(); });
    $("[data-csv]", el).addEventListener("click", () => {
        const cols = ["asset_id", "cloud", "region", "application", "service_label", "usage", "algorithm", "algorithm_discovered", "exposure",
            "data_sensitivity", "retention_years", "business_criticality", "quantum_exposed", "quantum_safe", "ai_class", "ai_score", "rule_score", "dependents"];
        const csv = [cols.join(","), ...filtered().map((r) => cols.map((c) => `"${String(r[c]).replace(/"/g, '""')}"`).join(","))].join("\n");
        downloadText("q-migrateai-inventory.csv", csv);
    });
    const body = $("[data-body]", el);
    body.addEventListener("click", (e) => {
        const id = e.target.closest("[data-id]")?.dataset.id;
        if (id)
            openDrawer(el, id);
    });
    body.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            const id = e.target.closest("[data-id]")?.dataset.id;
            if (id)
                openDrawer(el, id);
        }
    });
    draw();
    const focus = params.get("focus");
    if (focus)
        openDrawer(el, focus);
}
async function openDrawer(el, id) {
    const host = $("[data-drawer]", el);
    host.innerHTML = `<div class="fixed inset-0 z-40 bg-black/50" data-close-drawer></div>
    <aside class="fixed inset-y-0 right-0 z-50 w-full max-w-[540px] overflow-y-auto border-l border-line bg-ink-1 p-6" role="dialog" aria-label="Why this risk score">
      <div class="skeleton h-48"></div></aside>`;
    const panel = $("aside", host);
    const close = () => { host.innerHTML = ""; };
    host.querySelector("[data-close-drawer]").addEventListener("click", close);
    try {
        const x = await api(`/assets/${encodeURIComponent(id)}/explain`);
        const a = x.asset;
        const contrib = [...x.rule.contributions].sort((p, q) => q.points - p.points)
            .map((c) => ({ label: c.label, value: c.points, color: "#9B8CFF", display: c.points.toFixed(1), title: `value ${c.value} × weight ${c.weight}` }));
        const maxImpact = Math.max(0.01, ...x.ai.attributions.map((t) => Math.abs(t.impact)));
        panel.innerHTML = `
      <div class="flex items-start gap-3">
        <div><p class="id text-[16px] text-mist">${esc(id)}</p><p class="text-[13.5px] text-fog">${esc(a.service_label)}, ${esc(a.cloud)} ${esc(a.region)}, ${esc(a.application)}</p></div>
        <button class="btn btn-quiet ml-auto" data-x aria-label="Close">${icon("close")}</button>
      </div>
      <div class="mt-4 grid grid-cols-3 gap-3">
        <div class="rounded-lg border border-line p-3"><p class="text-[12.5px] text-fog">AI risk</p><div class="mt-1">${riskBadge(x.ai.class)}</div><p class="mt-1 text-[12px] text-fog">${Math.round(100 * x.ai.confidence)}% confident</p></div>
        <div class="rounded-lg border border-line p-3"><p class="text-[12.5px] text-fog">Formula score</p><p class="font-display text-[22px] tabular">${x.rule.score.toFixed(0)}<span class="text-[13px] text-fog">/100</span></p></div>
        <div class="rounded-lg border border-line p-3"><p class="text-[12.5px] text-fog">Depend on it</p><p class="font-display text-[22px] tabular">${x.dependents.all.length}</p></div>
      </div>
      <h3 class="mt-6">In plain words</h3>
      <ul class="mt-2 space-y-2 text-[14px] list-disc pl-5">${x.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${x.recommendation ? `<div class="mt-5 rounded-lg border border-risk-safe/40 p-4"><p class="text-[13.5px]">Recommended: <span class="id text-risk-safe">${esc(x.recommendation.target)}</span> (${esc(x.recommendation.standard)})</p>
        <p class="mt-1 text-[13px] text-fog">${esc(x.recommendation.reason)}</p></div>` : `<p class="mt-5 rounded-lg border border-line p-3 text-[13.5px] text-fog">${esc(a.algorithm)} is already quantum-safe.</p>`}
      <h3 class="mt-6">Formula breakdown</h3>
      <p class="text-[12.5px] text-fog mb-3">Points each factor adds to the 0–100 score.</p>
      ${hbars(contrib)}
      <h3 class="mt-6">What the neural network relied on</h3>
      <p class="text-[12.5px] text-fog mb-3">How much the predicted class's probability drops when the feature is hidden. Violet supports the prediction, red argues against it.</p>
      <div class="space-y-2">${x.ai.attributions.map((t) => `<div class="grid grid-cols-[1fr_120px_48px] items-center gap-2 text-[13px]">
        <span class="text-fog truncate" title="${esc(t.label)}">${esc(t.label)}</span>
        <div class="relative h-2 rounded-full bg-ink-3"><div class="absolute h-2 rounded-full" style="left:${t.impact >= 0 ? 50 : 50 - 50 * Math.abs(t.impact) / maxImpact}%;width:${50 * Math.abs(t.impact) / maxImpact}%;background:${t.impact >= 0 ? "#9B8CFF" : "#F0504A"}"></div></div>
        <span class="tabular text-right">${t.impact >= 0 ? "+" : ""}${t.impact.toFixed(2)}</span></div>`).join("")}</div>
      <h3 class="mt-6">Class probabilities</h3>
      <div class="mt-2">${hbars(RISK_ORDER.map((c) => ({ label: c, value: x.ai.probabilities[c], color: RISK[c].color, display: `${Math.round(100 * x.ai.probabilities[c])}%` })), 1)}</div>
      <div class="mt-6 flex flex-wrap gap-2">
        ${x.recommendation ? `<a class="btn btn-primary no-underline hover:no-underline" href="#/lab?asset=${encodeURIComponent(id)}">Open in PQC lab</a>` : ""}
        <a class="btn no-underline hover:no-underline" href="#/graph?focus=${encodeURIComponent(id)}">Show on map</a></div>`;
        $("[data-x]", panel).addEventListener("click", close);
        $("[data-x]", panel).focus();
    }
    catch (e) {
        panel.innerHTML = `<p class="text-risk-critical">${esc(e.message)}</p><button class="btn mt-4" data-x>Close</button>`;
        $("[data-x]", panel).addEventListener("click", close);
    }
    const onKey = (e) => { if (e.key === "Escape") {
        close();
        document.removeEventListener("keydown", onKey);
    } };
    document.addEventListener("keydown", onKey);
}
