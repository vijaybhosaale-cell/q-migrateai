// Step 5: PQC lab. Choose an asset and a target algorithm, validate, migrate, roll back.
import { api, post } from "../api.js";
import { can, go, refreshUnread } from "../state.js";
import { $, $$, emptyState, esc, num, pct, riskBadge, toast, when } from "../ui.js";

const RESULT_STYLE: Record<string, string> = {
  PASS: "border-risk-safe/50 text-risk-safe", WARN: "border-risk-medium/50 text-risk-medium", FAIL: "border-risk-critical/50 text-risk-critical",
};

function size(n: number | undefined | null): string {
  return n == null ? "–" : `${num(n)} B`;
}

export async function labPage(el: HTMLElement, params: URLSearchParams): Promise<void> {
  let assets: any[], plan: any;
  try {
    [assets, plan] = await Promise.all([api("/assets"), api("/plan")]);
  } catch (e: any) {
    el.innerHTML = emptyState("Nothing to migrate yet", esc(e.message), `<a class="btn btn-primary no-underline hover:no-underline" href="#/connect">Connect and discover</a>`);
    return;
  }
  const assetId = params.get("asset") || plan.queue[0]?.asset_id || assets[0].asset_id;
  const order = [...plan.queue.map((q: any) => q.asset_id), ...assets.map((a) => a.asset_id).filter((id: string) => !plan.queue.some((q: any) => q.asset_id === id))];
  let lab: any;
  try {
    lab = await api(`/lab/${encodeURIComponent(assetId)}`);
  } catch (e: any) {
    el.innerHTML = emptyState("Asset not found", esc(e.message), `<a class="btn no-underline hover:no-underline" href="#/lab">Open the lab</a>`);
    return;
  }
  const a = lab.asset;
  el.innerHTML = `
  <div class="flex flex-wrap items-end gap-3 mb-5">
    <div><label class="label" for="lab-asset">Asset</label>
      <input id="lab-asset" class="input w-64 id" list="lab-ids" value="${esc(assetId)}" autocomplete="off">
      <datalist id="lab-ids">${order.map((id) => `<option value="${esc(id)}">`).join("")}</datalist></div>
    <button class="btn" data-load>Load asset</button>
    <p class="text-[13px] text-fog max-w-xl">Nothing moves: only the asset's cryptographic policy changes. Every change keeps the previous policy, so one click rolls it back.</p>
  </div>
  <div class="grid gap-5 xl:grid-cols-[minmax(300px,380px)_1fr]">
    <section class="panel panel-pad">
      <h2>Current policy</h2>
      <p class="id mt-3 text-[15px] text-mist">${esc(a.asset_id)}</p>
      <p class="text-[13.5px] text-fog">${esc(a.service_label)}, ${esc(a.cloud)} ${esc(a.region)}</p>
      <dl class="mt-4 grid grid-cols-[120px_1fr] gap-y-2 text-[13.5px]">
        <dt class="text-fog">Algorithm</dt><dd class="id ${a.quantum_vulnerable ? "text-risk-critical" : "text-risk-safe"}">${esc(a.algorithm)}</dd>
        <dt class="text-fog">Discovered as</dt><dd class="id">${esc(a.algorithm_discovered)}</dd>
        <dt class="text-fog">Used for</dt><dd>${esc(a.usage.replace("_", " "))} (${esc(a.protocol)})</dd>
        <dt class="text-fog">Exposure</dt><dd>${esc(a.exposure)}</dd>
        <dt class="text-fog">AI risk</dt><dd>${riskBadge(a.ai_class)}</dd>
        <dt class="text-fog">Dependants</dt><dd class="tabular">${a.dependents}</dd>
        <dt class="text-fog">Last change</dt><dd>${lab.last_change ? `${esc(lab.last_change.action)} ${esc(when(lab.last_change.created_at))}` : "none"}</dd>
      </dl>
      ${lab.can_rollback && can("migrate") ? `<button class="btn btn-danger mt-5" data-rollback>Roll back to ${esc(lab.last_change.from_alg)}</button>` : ""}
    </section>
    <section class="panel panel-pad">
      <h2>Choose the target algorithm</h2>
      ${lab.recommendation ? "" : `<p class="mt-1 text-[13.5px] text-fog">${esc(a.algorithm)} is already quantum-safe. You can still test other options.</p>`}
      <fieldset class="mt-4 grid gap-3 md:grid-cols-2"><legend class="sr-only">Target algorithm</legend>${lab.targets.map((t: any, i: number) => `
        <label class="flex cursor-pointer gap-3 rounded-xl border border-line p-4 hover:border-lattice has-[:checked]:border-lattice has-[:checked]:bg-lattice-soft/40">
          <input type="radio" name="target" value="${esc(t.algorithm)}" class="mt-1 accent-[#9B8CFF]" ${i === 0 ? "checked" : ""}>
          <span class="flex-1"><span class="id text-mist">${esc(t.algorithm)}</span>
            ${i === 0 && lab.recommendation ? `<span class="chip ml-1 border-risk-safe/50 text-risk-safe">Recommended</span>` : ""}
            <span class="block text-[12.5px] text-fog mt-1">${esc(t.standard)}${t.facts?.nist_category ? `, NIST category ${t.facts.nist_category}` : ""}${t.status === "hybrid" ? ", hybrid" : ""}</span>
            ${t.facts ? `<span class="block text-[12.5px] text-fog">Public key ${size(t.facts.public_key_bytes)}, ${t.facts.kind === "kem" ? `ciphertext ${size(t.facts.ciphertext_bytes)}` : `signature ${size(t.facts.signature_bytes)}`}</span>` : ""}
          </span></label>`).join("")}</fieldset>
      ${lab.current_facts ? `<p class="mt-3 text-[12.5px] text-fog">Today: ${esc(a.algorithm)} public key ${size(lab.current_facts.public_key_bytes)}${lab.current_facts.signature_bytes ? `, signature ${size(lab.current_facts.signature_bytes)}` : ""}${lab.current_facts.ciphertext_bytes ? `, key share ${size(lab.current_facts.ciphertext_bytes)}` : ""}. Post-quantum keys are larger; the checks flag sizes that may matter.</p>` : ""}
      <div class="mt-5 flex flex-wrap gap-2">
        ${can("validate") ? `<button class="btn" data-validate>Run validation checks</button>` : ""}
        ${can("migrate") ? `<button class="btn btn-primary" data-migrate disabled title="Run the validation checks first">Migrate</button>` : ""}
        ${!can("validate") ? `<p class="text-[13.5px] text-fog">Your role can view the lab but not run checks or migrations.</p>` : ""}
      </div>
      <div data-result class="mt-6"></div>
    </section>
  </div>`;

  const target = () => ($<HTMLInputElement>("input[name=target]:checked", el)!).value;
  const migrateBtn = $<HTMLButtonElement>("[data-migrate]", el);
  $$("input[name=target]", el).forEach((r) => r.addEventListener("change", () => {
    if (migrateBtn) migrateBtn.disabled = true;
    $("[data-result]", el)!.innerHTML = "";
  }));
  $("[data-load]", el)!.addEventListener("click", () => go(`/lab?asset=${encodeURIComponent(($<HTMLInputElement>("#lab-asset", el)!).value.trim().toUpperCase())}`));
  $("#lab-asset", el)!.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") $<HTMLButtonElement>("[data-load]", el)!.click(); });

  $("[data-validate]", el)?.addEventListener("click", async () => {
    const out = $("[data-result]", el)!;
    out.innerHTML = `<div class="skeleton h-40"></div>`;
    try {
      const v = await post("/lab/validate", { asset_id: assetId, target: target() });
      const k0 = v.kpis_before, k1 = v.kpis_after;
      out.innerHTML = `
        <h3>Validation checks <span class="text-[12.5px] text-fog font-normal">(policy checks; a live handshake test comes in a later version)</span></h3>
        <ul class="mt-3 space-y-2">${v.checks.map((c: any) => `<li class="flex items-start gap-3 text-[13.5px]">
          <span class="chip ${RESULT_STYLE[c.result]} w-14 justify-center">${c.result}</span><span><span class="text-mist">${esc(c.check)}</span><br><span class="text-fog">${esc(c.detail)}</span></span></li>`).join("")}</ul>
        <h3 class="mt-6">Projected effect</h3>
        <div class="mt-3 grid gap-3 sm:grid-cols-4 text-[13.5px]">
          <div class="rounded-lg border border-line p-3"><p class="text-fog text-[12.5px]">This asset</p><p class="mt-1">${riskBadge(v.class_before)} <span class="text-fog">to</span> ${riskBadge(v.class_after)}</p></div>
          <div class="rounded-lg border border-line p-3"><p class="text-fog text-[12.5px]">Quantum-exposed</p><p class="mt-1 font-display text-[18px] tabular">${k0.quantum_exposed} <span class="text-fog text-[13px]">to</span> ${k1.quantum_exposed}</p></div>
          <div class="rounded-lg border border-line p-3"><p class="text-fog text-[12.5px]">Coverage</p><p class="mt-1 font-display text-[18px] tabular">${pct(k0.coverage_pct)} <span class="text-fog text-[13px]">to</span> ${pct(k1.coverage_pct)}</p></div>
          <div class="rounded-lg border border-line p-3"><p class="text-fog text-[12.5px]">Assets that also improve</p><p class="mt-1 font-display text-[18px] tabular">${v.ripple.filter((r: any) => r.score_after < r.score_before).length}</p></div>
        </div>
        ${v.ripple.length ? `<details class="mt-3"><summary class="cursor-pointer text-[13.5px] text-lattice">Show dependants whose risk changes</summary>
          <table class="tbl mt-2"><thead><tr><th>Asset</th><th>Service</th><th>AI risk</th><th>Quantum-safe after</th></tr></thead><tbody>
          ${v.ripple.slice(0, 25).map((r: any) => `<tr><td class="id">${esc(r.asset_id)}</td><td>${esc(r.service_label)}</td>
            <td>${riskBadge(r.class_before)} <span class="text-fog">to</span> ${riskBadge(r.class_after)}</td><td>${r.now_quantum_safe ? "yes" : "no"}</td></tr>`).join("")}</tbody></table></details>` : ""}
        ${!v.valid ? `<p class="mt-4 text-risk-critical text-[13.5px]">This target fails a check, so it cannot be applied.</p>` : ""}`;
      if (migrateBtn) { migrateBtn.disabled = !v.valid; migrateBtn.title = v.valid ? "" : "Fix the failed check first"; }
    } catch (e: any) {
      out.innerHTML = `<p class="text-risk-critical">${esc(e.message)}</p>`;
    }
  });

  migrateBtn?.addEventListener("click", async () => {
    migrateBtn.disabled = true;
    try {
      const r = await post("/lab/migrate", { asset_id: assetId, target: target() });
      toast(`Migrated ${assetId}: ${r.from} to ${r.to}.`, "ok");
      refreshUnread();
      go(`/lab?asset=${encodeURIComponent(assetId)}&done=1`);
    } catch (e: any) {
      toast(e.message, "error");
      migrateBtn.disabled = false;
    }
  });

  $("[data-rollback]", el)?.addEventListener("click", async () => {
    try {
      const r = await post("/lab/rollback", { asset_id: assetId });
      toast(`Rolled back ${assetId} to ${r.to}.`, "ok");
      go(`/lab?asset=${encodeURIComponent(assetId)}`);
    } catch (e: any) {
      toast(e.message, "error");
    }
  });
}
