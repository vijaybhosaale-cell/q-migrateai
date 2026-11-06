// Step 4: plan the migration in waves, with a what-if slider.
import { api } from "../api.js";
import { lineChart } from "../charts.js";
import { can } from "../state.js";
import { $, emptyState, esc, num, pct, riskBadge } from "../ui.js";
export async function planPage(el) {
    let plan, curve;
    try {
        [plan, curve] = await Promise.all([api("/plan"), api("/whatif?max_n=60")]);
    }
    catch (e) {
        el.innerHTML = emptyState("No plan yet", esc(e.message), `<a class="btn btn-primary no-underline hover:no-underline" href="#/connect">Connect and discover</a>`);
        return;
    }
    if (!plan.queue.length) {
        el.innerHTML = emptyState("Nothing left to migrate", "Every asset already uses a quantum-safe or hybrid algorithm.");
        return;
    }
    const maxN = curve.length - 1;
    const start = Math.min(20, maxN);
    el.innerHTML = `
  <div class="grid gap-4 md:grid-cols-3">${plan.waves.map((w, i) => `
    <section class="panel panel-pad ${i === 0 ? "border-lattice/60" : ""}">
      <div class="flex items-center gap-2"><h2>${esc(w.name)}</h2><span class="text-[13px] text-fog">${["now", "next quarter", "planned"][i]}</span></div>
      <p class="mt-3 font-display text-[30px] font-semibold tabular leading-none">${num(w.assets)} <span class="text-[15px] text-fog font-normal">assets</span></p>
      <p class="mt-2 text-[13.5px] text-fog">${num(w.effort_points)} effort points, about ${num(w.person_days)} person-days</p>
      ${i === 0 && can("migrate") ? `<a class="btn btn-primary btn-sm mt-4 no-underline hover:no-underline" href="#/graph?play=wave1">Migrate Wave 1 live on the map</a>` : ""}
    </section>`).join("")}</div>

  <section class="panel panel-pad mt-5">
    <div class="flex flex-wrap items-start gap-3">
      <div><h2>What if we migrate the top N?</h2>
        <p class="muted text-[13px] max-w-2xl">Projected effect of moving the first N assets of today's plan to their recommended algorithm. Nothing changes until you migrate.</p></div>
    </div>
    <div class="mt-5 grid gap-6 lg:grid-cols-[minmax(260px,340px)_1fr]">
      <div>
        <label for="w-n" class="label">Assets to migrate: <span class="text-mist tabular" data-n>${start}</span></label>
        <input id="w-n" type="range" min="0" max="${maxN}" value="${start}" class="w-full accent-[#9B8CFF]">
        <dl class="mt-5 grid grid-cols-2 gap-3 text-[13.5px]" data-proj></dl>
        <p class="mt-4 text-[12.5px] text-fog">Effort assumes ${plan.points_per_person_day} effort points per person-day. It is a planning estimate by service type.</p>
      </div>
      <div data-chart></div>
    </div>
  </section>

  <section class="panel mt-5">
    <div class="px-5 pt-5"><h2>Migration queue</h2><p class="muted text-[13px]">Priority = 0.40 × formula risk + 0.35 × AI risk + 15 × dependency impact + 0.10 × (100 − effort).</p></div>
    <div class="overflow-x-auto mt-3"><table class="tbl">
      <thead><tr><th>#</th><th>Wave</th><th>Asset</th><th>Service</th><th>Now</th><th>Move to</th><th>Standard</th><th>AI risk</th>
        <th class="text-right">Dependants</th><th class="text-right">Effort</th><th class="text-right">Priority</th><th></th></tr></thead>
      <tbody>${plan.queue.slice(0, 120).map((q) => `<tr>
        <td class="tabular text-fog">${q.rank}</td><td class="text-fog whitespace-nowrap">${esc(q.wave)}</td><td class="id">${esc(q.asset_id)}</td>
        <td>${esc(q.service_label)}</td><td class="id text-risk-critical">${esc(q.algorithm)}</td><td class="id text-risk-safe">${esc(q.target)}</td>
        <td class="text-fog text-[12.5px]">${esc(q.standard)}</td><td>${riskBadge(q.ai_class)}</td>
        <td class="text-right tabular">${q.dependents}</td><td class="text-right tabular">${q.effort}</td><td class="text-right tabular">${q.priority.toFixed(1)}</td>
        <td><a class="btn btn-sm no-underline hover:no-underline" href="#/lab?asset=${encodeURIComponent(q.asset_id)}">Lab</a></td></tr>`).join("")}</tbody>
    </table></div>
    ${plan.queue.length > 120 ? `<p class="p-4 text-[13px] text-fog">Showing the first 120 of ${num(plan.queue.length)} assets. The full plan is in the PDF report.</p>` : ""}
  </section>`;
    const base = curve[0];
    const slider = $("#w-n", el);
    const update = () => {
        const n = Number(slider.value);
        const p = curve[n];
        $("[data-n]", el).textContent = String(n);
        const cell = (label, now, then, good) => `<div class="rounded-lg border border-line p-3">
      <dt class="text-fog text-[12.5px]">${label}</dt><dd class="mt-1 font-display text-[20px] tabular ${good ? "text-risk-safe" : ""}">${then}</dd>
      <dd class="text-[12px] text-fog">today ${now}</dd></div>`;
        $("[data-proj]", el).innerHTML =
            cell("Quantum-exposed", num(base.quantum_exposed), num(p.quantum_exposed), p.quantum_exposed < base.quantum_exposed) +
                cell("Quantum-safe coverage", pct(base.coverage_pct), pct(p.coverage_pct), p.coverage_pct > base.coverage_pct) +
                cell("Critical (AI)", num(base.critical), num(p.critical), p.critical < base.critical) +
                cell("Effort", "0", `${num(p.person_days)} person-days`, false);
        $("[data-chart]", el).innerHTML = lineChart([
            { name: "Quantum-exposed assets", color: "#F0504A", points: curve.map((c) => [c.n, c.quantum_exposed]) },
            { name: "Critical (AI)", color: "#E9C440", points: curve.map((c) => [c.n, c.critical]) },
            { name: "Quantum-safe assets", color: "#3CCB7F", points: curve.map((c) => [c.n, c.quantum_safe]) },
        ], { marker: n, xLabel: "Assets migrated, in plan order", yLabel: "Assets", height: 260 });
    };
    slider.addEventListener("input", update);
    update();
}
