// Step 2: the interactive dependency map (Cytoscape.js) with the live Wave 1 migration.
import { api, post } from "../api.js";
import { can, refreshUnread } from "../state.js";
import { $, RISK, animateNumber, confirmDialog, emptyState, esc, num, riskBadge, toast } from "../ui.js";
const CLOUDS = ["AWS", "Azure", "GCP"];
export async function graphPage(el, params) {
    let data;
    try {
        data = await api("/graph");
    }
    catch (e) {
        el.innerHTML = emptyState("No dependency map yet", esc(e.message), `<a class="btn btn-primary no-underline hover:no-underline" href="#/connect">Connect and discover</a>`);
        return;
    }
    const ov = await api("/overview");
    const timers = [];
    el.innerHTML = `
  <div class="grid gap-3 sm:grid-cols-3 mb-4" aria-live="polite">
    <div class="panel px-5 py-4"><p class="text-[13px] text-fog">Quantum-exposed</p><p class="kpi-value text-risk-critical mt-1" data-k="exposed">${ov.now.quantum_exposed}</p></div>
    <div class="panel px-5 py-4"><p class="text-[13px] text-fog">Quantum-safe coverage</p><p class="kpi-value mt-1"><span data-k="coverage">${ov.now.coverage_pct.toFixed(1)}</span><span class="text-[20px] text-fog">%</span></p></div>
    <div class="panel px-5 py-4"><p class="text-[13px] text-fog">Critical (AI)</p><p class="kpi-value mt-1" data-k="critical">${ov.now.critical}</p></div>
  </div>
  <section class="panel overflow-hidden">
    <div class="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
      <label for="g-search" class="sr-only">Find an asset</label>
      <input id="g-search" class="input max-w-[220px] py-1.5" placeholder="Find an asset ID" list="g-ids" autocomplete="off">
      <datalist id="g-ids">${data.nodes.map((n) => `<option value="${esc(n.id)}">`).join("")}</datalist>
      <div class="flex gap-1.5" role="group" aria-label="Clouds">${CLOUDS.map((c) => `<button class="chip border-lattice/60 text-mist" aria-pressed="true" data-cloud="${c}">${c}</button>`).join("")}</div>
      <button class="btn btn-sm btn-quiet" data-fit>Fit to screen</button>
      <div class="ml-auto flex items-center gap-3 text-[12.5px] text-fog">
        ${["Critical", "High", "Medium", "Low"].map((c) => `<span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full" style="background:${RISK[c].color}"></span>${c}</span>`).join("")}
      </div>
    </div>
    <div class="grid lg:grid-cols-[1fr_360px]">
      <div class="relative">
        <div id="cy" class="h-[560px] lg:h-[640px] bg-ink-0" role="img" aria-label="Dependency map of ${data.nodes.length} assets"></div>
        ${can("migrate") ? `<div class="absolute left-3 top-3 flex gap-2">
          <button class="btn btn-primary btn-sm" data-wave>Migrate Wave 1 live</button>
          <button class="btn btn-sm" data-reset>Reset to discovered state</button></div>` : ""}
        <p class="absolute bottom-2 left-3 text-[12px] text-fog">${num(data.nodes.length)} assets, ${num(data.edges.length)} dependencies. Dot size = number of dependants. Scroll to zoom.</p>
      </div>
      <aside id="g-side" class="border-t border-line p-5 lg:border-l lg:border-t-0 max-h-[640px] overflow-y-auto"></aside>
    </div>
  </section>`;
    const side = $("#g-side", el);
    const hubs = [...data.nodes].sort((a, b) => b.dependents - a.dependents).slice(0, 6);
    const idleSide = () => {
        side.innerHTML = `<h2>Click a key or certificate authority</h2>
      <p class="muted mt-1 text-[13.5px]">Everything that depends on it lights up red: if its algorithm is broken, these assets are exposed too.</p>
      <p class="mt-5 text-[13px] text-fog">Most depended-on assets</p>
      <div class="mt-2 space-y-1.5">${hubs.map((h) => `<button class="flex w-full items-center gap-2 rounded-lg border border-line px-3 py-2 text-left hover:border-lattice" data-pick="${esc(h.id)}">
        <span class="h-2.5 w-2.5 rounded-full" style="background:${RISK[h.ai_class].color}"></span>
        <span class="id">${esc(h.id)}</span><span class="ml-auto text-[12.5px] text-fog tabular">${h.dependents} dependants</span></button>`).join("")}</div>`;
    };
    idleSide();
    const nodes = data.nodes.map((n) => ({
        data: { id: n.id, color: RISK[n.ai_class].color, size: 9 + Math.sqrt(n.dependents) * 3.2, dependents: n.dependents,
            cloud: n.cloud, label: n.dependents >= 12 ? n.id : "" },
        position: { x: n.x * 640, y: n.y * 640 },
    }));
    const edges = data.edges.map((e, i) => ({ data: { id: "e" + i, source: e.source, target: e.target } }));
    const cy = cytoscape({
        container: $("#cy", el), elements: [...nodes, ...edges],
        layout: { name: "preset", fit: true, padding: 30 },
        minZoom: 0.15, maxZoom: 5, wheelSensitivity: 0.3, boxSelectionEnabled: false,
        style: [
            { selector: "node", style: { "background-color": "data(color)", width: "data(size)", height: "data(size)",
                    "border-width": 1, "border-color": "#0A0F1E", label: "data(label)", color: "#8B96B3", "font-size": 9,
                    "font-family": "IBM Plex Mono, monospace", "text-valign": "bottom", "text-margin-y": 3,
                    "transition-property": "background-color, border-width, border-color, opacity", "transition-duration": "300ms" } },
            { selector: "edge", style: { width: 0.7, "line-color": "#33436b", opacity: 0.5, "curve-style": "haystack" } },
            { selector: ".faded", style: { opacity: 0.1 } },
            { selector: "edge.faded", style: { opacity: 0.04 } },
            { selector: "node.dep", style: { "background-color": "#F0504A", "border-color": "#ffb4ae", "border-width": 1.5, opacity: 1 } },
            { selector: "edge.dep", style: { "line-color": "#F0504A", opacity: 0.85, width: 1.3 } },
            { selector: "node.focus", style: { "border-color": "#E4E9F5", "border-width": 4, opacity: 1, label: "data(id)", color: "#E4E9F5", "font-size": 11 } },
            { selector: "node.pulse", style: { "border-color": "#3CCB7F", "border-width": 7 } },
            { selector: ".hidden-cloud", style: { display: "none" } },
        ],
    });
    // Lets the end-to-end tests find a node's position on screen and click it like a person would.
    $("#cy", el)._cy = cy;
    const clear = () => {
        cy.elements().removeClass("faded dep focus");
    };
    const select = async (id) => {
        const node = cy.getElementById(id);
        if (!node || node.empty()) {
            toast(`${id} is not in the map.`, "error");
            return;
        }
        clear();
        const dependents = node.predecessors();
        cy.elements().addClass("faded");
        dependents.removeClass("faded").addClass("dep");
        node.removeClass("faded").addClass("focus");
        cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.1) }, { duration: 350 });
        side.innerHTML = `<div class="skeleton h-40"></div>`;
        try {
            const x = await api(`/assets/${encodeURIComponent(id)}/explain`);
            const a = x.asset;
            side.innerHTML = `
        <div class="flex items-center gap-2"><span class="id text-[15px] text-mist">${esc(id)}</span><button class="btn btn-sm btn-quiet ml-auto" data-clear>Clear</button></div>
        <p class="text-[13.5px] text-fog">${esc(a.service_label)}, ${esc(a.cloud)} ${esc(a.region)}, ${esc(a.application)}</p>
        <div class="mt-3 flex flex-wrap items-center gap-2">${riskBadge(x.ai.class)}<span class="text-[13px] text-fog">AI score ${x.ai.score.toFixed(0)}/100</span></div>
        <dl class="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 text-[13.5px]">
          <dt class="text-fog">Algorithm</dt><dd class="id">${esc(a.algorithm)}</dd>
          <dt class="text-fog">Used for</dt><dd>${esc(a.usage.replace("_", " "))}</dd>
          <dt class="text-fog">Exposure</dt><dd>${esc(a.exposure)}</dd>
          <dt class="text-fog">Depend on it</dt><dd class="text-risk-critical tabular">${x.dependents.all.length} assets (${x.dependents.direct.length} directly)</dd>
        </dl>
        <h3 class="mt-5">Why</h3>
        <ul class="mt-2 space-y-1.5 text-[13.5px] text-fog list-disc pl-5">${x.reasons.slice(0, 4).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
        ${x.recommendation ? `<div class="mt-4 rounded-lg border border-risk-safe/40 p-3 text-[13.5px]">Move to <span class="id text-risk-safe">${esc(x.recommendation.target)}</span> (${esc(x.recommendation.standard)})</div>` : ""}
        <div class="mt-4 flex flex-wrap gap-2">
          <a class="btn btn-sm btn-primary no-underline hover:no-underline" href="#/lab?asset=${encodeURIComponent(id)}">Open in PQC lab</a>
          <a class="btn btn-sm no-underline hover:no-underline" href="#/assets?focus=${encodeURIComponent(id)}">Full explanation</a></div>`;
            $("[data-clear]", side)?.addEventListener("click", () => { clear(); idleSide(); });
        }
        catch (e) {
            side.innerHTML = `<p class="text-risk-critical">${esc(e.message)}</p>`;
        }
    };
    cy.on("tap", "node", (evt) => select(evt.target.id()));
    cy.on("tap", (evt) => { if (evt.target === cy) {
        clear();
        idleSide();
    } });
    side.addEventListener("click", (e) => {
        const id = e.target.closest("[data-pick]")?.dataset.pick;
        if (id)
            select(id);
    });
    $("#g-search", el).addEventListener("change", (e) => {
        const v = e.target.value.trim().toUpperCase();
        if (v)
            select(v);
    });
    $("[data-fit]", el).addEventListener("click", () => cy.animate({ fit: { padding: 30 } }, { duration: 300 }));
    el.querySelectorAll("[data-cloud]").forEach((b) => b.addEventListener("click", () => {
        const on = b.getAttribute("aria-pressed") !== "true";
        b.setAttribute("aria-pressed", String(on));
        b.classList.toggle("border-lattice/60", on);
        b.classList.toggle("text-mist", on);
        b.classList.toggle("border-line", !on);
        b.classList.toggle("text-fog", !on);
        const hidden = new Set(Array.from(el.querySelectorAll("[data-cloud]")).filter((x) => x.getAttribute("aria-pressed") !== "true").map((x) => x.dataset.cloud));
        cy.nodes().forEach((n) => n.toggleClass("hidden-cloud", hidden.has(n.data("cloud"))));
    }));
    const kExposed = $("[data-k=exposed]", el), kCoverage = $("[data-k=coverage]", el), kCritical = $("[data-k=critical]", el);
    const playWave = async () => {
        const ok = await confirmDialog("Migrate Wave 1", `<p>The 20 highest-priority assets move to their recommended post-quantum or hybrid algorithm, one by one.</p>
       <p class="mt-2 text-fog">Every change is recorded in the audit log and can be rolled back in the PQC lab.</p>`, "Migrate Wave 1");
        if (!ok)
            return;
        const btn = $("[data-wave]", el);
        if (btn)
            btn.disabled = true;
        clear();
        let res;
        try {
            res = await post("/migrations/wave", { wave: "Wave 1" });
        }
        catch (e) {
            toast(e.message, "error");
            if (btn)
                btn.disabled = false;
            return;
        }
        side.innerHTML = `<h2>Wave 1 in progress</h2><p class="muted text-[13px] mt-1">Each step changes one asset's algorithm and recomputes the risk of everything that depends on it.</p>
      <ol data-log class="mt-4 space-y-2 text-[13px]"></ol>`;
        const log = $("[data-log]", side);
        const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const delay = reduce ? 0 : 420;
        res.steps.forEach((s, i) => {
            timers.push(window.setTimeout(() => {
                const n = cy.getElementById(s.asset_id);
                n.addClass("pulse");
                timers.push(window.setTimeout(() => n.removeClass("pulse"), 380));
                s.changed.forEach((c) => cy.getElementById(c.id).data("color", RISK[c.ai_class].color));
                animateNumber(kExposed, s.kpis.quantum_exposed, 0, 350);
                animateNumber(kCoverage, s.kpis.coverage_pct, 1, 350);
                animateNumber(kCritical, s.kpis.critical, 0, 350);
                log.insertAdjacentHTML("afterbegin", `<li class="rounded-lg border border-line px-3 py-2">
          <span class="id text-mist">${esc(s.asset_id)}</span><br><span class="id text-risk-critical">${esc(s.from)}</span>
          <span class="text-fog">to</span> <span class="id text-risk-safe">${esc(s.to)}</span>${s.changed.length > 1
                    ? `<br><span class="text-fog">${s.changed.length - 1} ${s.changed.length === 2 ? "dependant" : "dependants"} also safer</span>` : ""}</li>`);
                if (i === res.steps.length - 1) {
                    const title = $("h2", side);
                    if (title)
                        title.textContent = `Wave 1 complete: ${res.steps.length} assets migrated`;
                    toast(`Wave 1 done: quantum-exposed ${res.before.quantum_exposed} to ${s.kpis.quantum_exposed}.`, "ok");
                    if (btn)
                        btn.disabled = false;
                    refreshUnread();
                }
            }, delay * (i + 1)));
        });
    };
    $("[data-wave]", el)?.addEventListener("click", playWave);
    $("[data-reset]", el)?.addEventListener("click", async () => {
        if (!(await confirmDialog("Reset to discovered state", "<p>Every asset returns to the algorithm found at discovery. This is recorded in the audit log.</p>", "Reset")))
            return;
        await post("/migrations/reset");
        toast("All assets are back to their discovered algorithms.", "ok");
        location.hash = "#/graph";
        window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    const focus = params.get("focus");
    if (focus)
        select(focus);
    if (params.get("play") === "wave1" && can("migrate"))
        playWave();
    return () => {
        timers.forEach((t) => clearTimeout(t));
        cy.destroy();
    };
}
