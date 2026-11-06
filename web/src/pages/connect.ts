// Step 1: connect a cloud (read-only) and run discovery.
import { api, del, post } from "../api.js";
import { can, refreshUnread } from "../state.js";
import { ago, confirmDialog, esc, gdprButton, modal, num, toast, when } from "../ui.js";

const PHASES = ["scanning", "mapping", "training", "done"];
const PHASE_TEXT: Record<string, string> = {
  scanning: "Reading keys, certificates and TLS settings", mapping: "Building the dependency map",
  training: "Training the AI risk models", done: "Finished", failed: "Failed",
};

function statusChip(status: string): string {
  const map: Record<string, string> = {
    connected: "border-risk-safe/50 text-risk-safe", not_implemented: "border-risk-medium/50 text-risk-medium",
    completed: "border-risk-safe/50 text-risk-safe", running: "border-lattice/60 text-lattice", failed: "border-risk-critical/50 text-risk-critical",
  };
  const text: Record<string, string> = { not_implemented: "Scanning not built yet", connected: "Connected", completed: "Completed",
    running: "Running", failed: "Failed" };
  return `<span class="chip ${map[status] ?? "border-line text-fog"}">${esc(text[status] ?? status)}</span>`;
}

function runRow(r: any): string {
  const idx = PHASES.indexOf(r.phase);
  const progress = r.status === "running" ? `<div class="mt-2 flex gap-1" aria-label="Progress">${PHASES.slice(0, 3).map((_, i) =>
    `<span class="h-1.5 flex-1 rounded-full ${i < idx ? "bg-lattice" : i === idx ? "bg-lattice/60 animate-pulse" : "bg-ink-3"}"></span>`).join("")}</div>
    <p class="mt-1 text-[12.5px] text-fog">${esc(PHASE_TEXT[r.phase] ?? r.phase)}</p>` : "";
  return `<li class="py-3 border-b border-line/60 last:border-0">
    <div class="flex flex-wrap items-center gap-3 text-[13.5px]">
      ${statusChip(r.status)}<span>${esc(r.connection ?? "Connection removed")}</span>
      <span class="text-fog">${esc(when(r.started_at))}${r.triggered_by === "monitor" ? ", scheduled check" : r.triggered_by === "seed" ? ", initial demo setup" : ""}</span>
      ${r.status === "completed" ? `<span class="ml-auto tabular">${num(r.assets_found)} assets${r.new_assets ? `, <span class="${r.new_vulnerable ? "text-risk-critical" : ""}">${r.new_assets} new (${r.new_vulnerable} quantum-vulnerable)</span>` : ""}</span>` : ""}
    </div>
    ${r.message ? `<p class="mt-1.5 text-[13px] ${r.status === "failed" ? "text-risk-medium" : "text-fog"}">${esc(r.message)}</p>` : ""}
    ${progress}</li>`;
}

export async function connectPage(el: HTMLElement, params: URLSearchParams): Promise<void | (() => void)> {
  let timer: number | undefined;
  const render = async () => {
    const [data, runs] = await Promise.all([api("/connections"), api("/discovery/runs")]);
    const running = runs.some((r: any) => r.status === "running");
    const providers = data.providers as Record<string, any>;
    el.innerHTML = `
    ${params.get("welcome") ? `<div class="panel panel-pad mb-5 border-lattice/60"><h2>Your account is ready</h2>
      <p class="mt-1 text-fog">Start with the demo cloud below: run a discovery to see your first dependency map, risk scores and migration plan. Real cloud connectors use read-only access only.</p></div>` : ""}
    <div class="flex flex-wrap items-start gap-3 mb-5">
      <p class="max-w-3xl text-fog">Q-MigrateAI needs <span class="text-mist">read-only</span> access. It lists keys, certificates and TLS settings, and never reads files or customer data. You can remove access at any time from your cloud console.</p>
      ${gdprButton("ml-auto")}
    </div>
    <section class="panel">
      <div class="px-5 pt-5"><h2>Your connections</h2></div>
      <div class="overflow-x-auto mt-2"><table class="tbl">
        <thead><tr><th>Name</th><th>Provider</th><th>Status</th><th>Last discovery</th><th></th></tr></thead>
        <tbody>${data.connections.length ? data.connections.map((c: any) => `<tr>
          <td>${esc(c.display_name)}</td><td>${esc(providers[c.provider]?.title ?? c.provider)}${c.provider === "simulator" ? ` <span class="text-fog text-[12.5px]">(${esc(c.config.profile)}, seed ${esc(c.config.seed)})</span>` : ""}</td>
          <td>${statusChip(c.status)}</td><td class="text-fog">${esc(ago(c.last_sync_at))}</td>
          <td class="text-right whitespace-nowrap">
            ${can("discover") ? `<button class="btn btn-sm btn-primary" data-run="${c.id}" ${running ? "disabled" : ""}>Run discovery</button>` : ""}
            ${can("connections") ? `<button class="btn btn-sm" data-test="${c.id}">Test</button>
            <button class="btn btn-sm btn-quiet" data-remove="${c.id}" data-name="${esc(c.display_name)}">Remove</button>` : ""}
          </td></tr>`).join("") : `<tr><td colspan="5" class="text-fog py-6 text-center">No connections yet. Add one below.</td></tr>`}</tbody>
      </table></div>
    </section>

    <section class="panel panel-pad mt-5">
      <h2>Discovery runs</h2>
      <p class="muted text-[13px]">Each run reads the inventory, rebuilds the dependency map and retrains the AI models. New quantum-vulnerable assets raise alerts.</p>
      <ul class="mt-2">${runs.length ? runs.map(runRow).join("") : `<li class="py-4 text-fog">No discovery has run yet.</li>`}</ul>
    </section>

    <section class="mt-5">
      <h2 class="mb-3">Add a connection</h2>
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">${Object.entries(providers).map(([key, p]) => `
        <article class="panel panel-pad flex flex-col">
          <div class="flex items-center gap-2"><h3>${esc(p.title)}</h3></div>
          <p class="mt-1">${p.status === "available" ? `<span class="chip border-risk-safe/50 text-risk-safe">Available</span>`
            : `<span class="chip border-risk-medium/50 text-risk-medium" title="The read-only access design is ready; automatic scanning is not built in this version">Access design ready</span>`}</p>
          <p class="mt-3 text-[13.5px] text-fog flex-1">${esc(p.summary)}</p>
          ${can("connections") ? `<button class="btn btn-sm mt-4 self-start" data-setup="${key}">Set up</button>` : ""}
        </article>`).join("")}</div>
    </section>`;

    el.querySelectorAll<HTMLElement>("[data-run]").forEach((b) => b.addEventListener("click", async () => {
      await post("/discovery/run", { connection_id: b.dataset.run });
      toast("Discovery started.", "ok");
      await render();
    }));
    el.querySelectorAll<HTMLElement>("[data-test]").forEach((b) => b.addEventListener("click", async () => {
      const r = await post(`/connections/${b.dataset.test}/test`);
      toast(r.message, r.ok ? "ok" : "info");
    }));
    el.querySelectorAll<HTMLElement>("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
      if (await confirmDialog("Remove connection", `<p>Remove <strong>${esc(b.dataset.name)}</strong>? Discovered assets stay until the next discovery.</p>`, "Remove", true)) {
        await del(`/connections/${b.dataset.remove}`);
        await render();
      }
    }));
    el.querySelectorAll<HTMLElement>("[data-setup]").forEach((b) => b.addEventListener("click", () => setup(b.dataset.setup!, providers[b.dataset.setup!], data.external_id, render)));

    clearInterval(timer);
    if (running) {
      timer = window.setInterval(async () => {
        const rs = await api("/discovery/runs").catch(() => []);
        if (!rs.some((r: any) => r.status === "running")) {
          clearInterval(timer);
          await render();
          refreshUnread();
          const latest = rs[0];
          if (latest?.status === "completed") toast(`Discovery finished: ${latest.assets_found} assets${latest.new_vulnerable ? `, ${latest.new_vulnerable} new quantum-vulnerable` : ""}.`, "ok");
        } else {
          const list = el.querySelector("section.panel.panel-pad ul");
          if (list) list.innerHTML = rs.map(runRow).join("");
        }
      }, 2000);
    }
  };
  await render();
  return () => clearInterval(timer);
}

function setup(key: string, p: any, externalId: string, after: () => Promise<void>): void {
  const fields = (p.fields as any[]).map((f) => {
    if (f.type === "readonly") return `<label class="label mt-3">${esc(f.label)}</label><input class="input id" value="${esc(externalId)}" readonly>`;
    if (f.type === "select") return `<label class="label mt-3" for="f-${f.key}">${esc(f.label)}</label>
      <select id="f-${f.key}" data-field="${f.key}" class="input">${f.options.map((o: string) => `<option>${esc(o)}</option>`).join("")}</select>`;
    return `<label class="label mt-3" for="f-${f.key}">${esc(f.label)}</label>
      <input id="f-${f.key}" data-field="${f.key}" class="input" ${f.type === "number" ? 'type="number"' : ""} placeholder="${esc(f.placeholder ?? "")}">`;
  }).join("");
  const body = `
    ${p.status !== "available" ? `<p class="mb-3 rounded-lg border border-risk-medium/40 bg-risk-medium/10 p-3 text-[13.5px] text-risk-medium">
      This version stores the connection and shows the read-only access needed, but does not scan ${esc(p.title)} yet. Discovery uses the demo simulator meanwhile.</p>` : ""}
    <ol class="list-decimal space-y-1.5 pl-5 text-[13.5px]">${(p.access as string[]).map((a) => `<li>${esc(a)}</li>`).join("")}</ol>
    ${p.policy ? `<details class="mt-3"><summary class="cursor-pointer text-[13.5px] text-lattice">Show the read-only IAM policy</summary>
      <pre class="mt-2 max-h-56 overflow-auto rounded-lg bg-ink-0 p-3 text-[12px] id">${esc(JSON.stringify(p.policy, null, 2))}</pre></details>` : ""}
    <label class="label mt-4" for="f-name">Connection name</label>
    <input id="f-name" class="input" value="${esc(p.title)}">
    ${fields}`;
  const m = modal(`Connect ${p.title}`, body, `<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-save>Save connection</button>`);
  m.el.querySelector("[data-save]")!.addEventListener("click", async () => {
    const config: Record<string, unknown> = {};
    m.el.querySelectorAll<HTMLInputElement>("[data-field]").forEach((i) => {
      if (i.value) config[i.dataset.field!] = i.type === "number" ? Number(i.value) : i.value;
    });
    try {
      const r = await post("/connections", { provider: key, display_name: (m.el.querySelector<HTMLInputElement>("#f-name")!).value, config });
      m.close();
      toast(r.status === "connected" ? "Connection saved." : "Connection saved. Scanning for this provider is not built yet.", "ok");
      await after();
    } catch (e: any) {
      toast(e.message, "error");
    }
  });
}
