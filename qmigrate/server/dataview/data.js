// Project data page: what was collected for each project, its migration status, corrections and downloads.
"use strict";
(function () {
  const main = document.getElementById("main");
  const state = { projects: [], canEdit: false, pid: null, data: null, status: "all", target: "", q: "" };

  // ------------------------------------------------------------ helpers
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const dash = (v) => (v === null || v === undefined || v === "" ? '<span class="muted">-</span>' : esc(v));
  const when = (iso) => { if (!iso) return "never"; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString(); };

  async function api(path, opts = {}) {
    const res = await fetch("/api" + path, {
      credentials: "same-origin", ...opts,
      headers: { "Content-Type": "application/json", "X-QM-Request": "1", ...(opts.headers || {}) },
    });
    if (res.status === 401) { const e = new Error("login"); e.login = true; throw e; }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Request failed (" + res.status + ").");
    return body;
  }

  function toast(text, kind) {
    const el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.textContent = text;
    document.getElementById("toasts").appendChild(el);
    setTimeout(() => el.remove(), 3800);
  }

  const statusChip = (r) => `<span class="chip st-${esc(r.status)}">${esc(r.status_text)}</span>`;
  const riskChip = (c) => (c ? `<span class="chip plain rk-${esc(c)}">${esc(c)}</span>` : '<span class="muted">-</span>');

  // ------------------------------------------------------------ boot
  async function boot() {
    try {
      const r = await api("/projects");
      state.projects = r.projects;
      state.canEdit = r.can_edit;
      document.getElementById("who").textContent = `${r.tenant} · ${r.user}`;
    } catch (e) {
      if (e.login) {
        main.innerHTML = `<div class="panel panel-pad"><h1>Please log in first</h1>
          <p class="muted">Log in on the dashboard, then come back to this page.</p>
          <p><a class="btn btn-primary" href="/">Go to the login page</a></p></div>`;
        return;
      }
      main.innerHTML = `<div class="panel panel-pad"><h1>Could not load projects</h1><p class="muted">${esc(e.message)}</p></div>`;
      return;
    }
    const wanted = new URLSearchParams(location.search).get("project");
    if (!state.projects.length) {
      main.innerHTML = `<div class="panel panel-pad"><h1>No projects yet</h1>
        <p class="muted">Add a connection on the dashboard's <a href="/#/connect">Connect</a> page (for example "Public websites" with your own domains), run a discovery, then come back here.</p></div>`;
      return;
    }
    state.pid = state.projects.some((p) => p.id === wanted) ? wanted : state.projects[0].id;
    await load();
  }

  async function load() {
    main.innerHTML = renderPicker() + `<p class="muted pad">Loading the project data…</p>`;
    bindPicker();
    try {
      state.data = await api(`/projects/${encodeURIComponent(state.pid)}/data`);
    } catch (e) {
      if (e.login) return boot();
      main.innerHTML = renderPicker() + `<div class="panel panel-pad"><p>${esc(e.message)}</p></div>`;
      bindPicker();
      return;
    }
    history.replaceState(null, "", `?project=${encodeURIComponent(state.pid)}`);
    render();
  }

  // ------------------------------------------------------------ project picker
  function renderPicker() {
    return `<section class="stack"><div><h1>Project data</h1>
      <p class="muted">Choose a project to see exactly what data was collected for it, what was used in the analysis, what is migrated and what still needs migration. You can correct entries and download the data.</p></div>
      <div class="projects" role="group" aria-label="Projects">${state.projects.map((p) => `
        <button class="proj" data-pid="${esc(p.id)}" aria-pressed="${p.id === state.pid}">
          <div class="t">${esc(p.name)}</div>
          <div class="s" title="${esc(p.targets)}">${esc(p.targets)}</div>
          <div class="c">
            <span class="chip plain">${p.assets} assets</span>
            ${p.counts.needs_migration ? `<span class="chip st-needs_migration">${p.counts.needs_migration} to migrate</span>` : ""}
            ${p.counts.migrated ? `<span class="chip st-migrated">${p.counts.migrated} migrated</span>` : ""}
          </div>
        </button>`).join("")}</div></section>`;
  }

  function bindPicker() {
    main.querySelectorAll("[data-pid]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.pid === state.pid) return;
      state.pid = b.dataset.pid; state.status = "all"; state.target = ""; state.q = "";
      load();
    }));
  }

  // ------------------------------------------------------------ main view
  function filtered() {
    const q = state.q.trim().toLowerCase();
    return state.data.rows.filter((r) =>
      (state.status === "all" || (state.status === "corrected" ? Object.keys(r.corrections || {}).length || r.note : r.status === state.status)) &&
      (!state.target || r.target === state.target) &&
      (!q || [r.asset_id, r.target, r.algorithm_discovered, r.algorithm_current, r.kind, r.cloud, r.owner_team, r.cert_issuer, r.note]
        .some((v) => String(v || "").toLowerCase().includes(q))));
  }

  function render() {
    const d = state.data, s = d.summary, p = d.project;
    const exp = (f) => `/api/projects/${encodeURIComponent(p.id)}/export?format=${f}`;
    const tile = (key, value, label, cls) => `<button class="tile ${cls || ""}" data-status="${key}" aria-pressed="${state.status === key}">
        <div class="v">${value}</div><div class="k">${label}</div></button>`;
    main.innerHTML = renderPicker() + `
    <section class="stack" style="margin-top:28px">
      <div class="panel panel-pad">
        <div class="row" style="align-items:flex-start">
          <div style="flex:1;min-width:260px">
            <h2>${esc(p.name)}</h2>
            <p class="muted" style="margin:4px 0 0">Targets: <span style="color:var(--mist)">${esc(p.targets)}</span></p>
            <p class="muted" style="margin:2px 0 0">Last discovery: ${esc(when(p.last_sync_at))}${s.targets_requested ? ` · ${s.targets_reached} of ${s.targets_requested} websites reached` : ""}</p>
          </div>
          <div class="row">
            <a class="btn btn-primary" href="${exp("xlsx")}" download>Download Excel</a>
            <a class="btn" href="${exp("csv")}" download>CSV</a>
            <a class="btn" href="${exp("json")}" download>JSON</a>
          </div>
        </div>
        ${d.analysis_ready ? "" : `<p class="why">This data is stored but not analysed yet: the AI needs at least 20 assets in the workspace. Run discovery on more websites or add another project.</p>`}
      </div>

      <div class="tiles">
        ${tile("all", s.assets, "Data rows collected")}
        <div class="tile"><div class="v">${s.used_in_analysis}</div><div class="k">Used in the analysis</div></div>
        ${tile("needs_migration", s.needs_migration, "Need migration", "needs")}
        ${tile("migrated", s.migrated, "Migrated", "migrated")}
        ${tile("safe", s.safe, "Already quantum-safe", "safe")}
        ${tile("corrected", s.corrected, "Corrected by you")}
        ${s.not_reached ? `<a class="tile" href="#not-reached"><div class="v" style="color:var(--med)">${s.not_reached}</div><div class="k">Not reached (not used)</div></a>` : ""}
      </div>

      <div class="panel">
        <div class="panel-pad" style="padding-bottom:6px"><h2>By target</h2>
          <p class="muted" style="margin:2px 0 0;font-size:13px">Each website (or cloud resource) you put in this project. Click one to see only its data.</p></div>
        <div class="tbl-wrap"><table class="tbl" id="targets">
          <thead><tr><th>Target</th><th class="num">Data rows</th><th class="num">Need migration</th><th class="num">Migrated</th><th class="num">Already safe</th></tr></thead>
          <tbody>${d.targets.map((t) => `<tr data-target="${esc(t.target)}" ${state.target === t.target ? 'style="background:var(--lattice-soft)"' : ""}>
            <td>${esc(t.target)}</td><td class="num">${t.assets}</td>
            <td class="num" style="color:${t.needs_migration ? "var(--crit)" : "inherit"}">${t.needs_migration}</td>
            <td class="num" style="color:${t.migrated ? "var(--safe)" : "inherit"}">${t.migrated}</td><td class="num">${t.safe}</td></tr>`).join("")
            || `<tr><td colspan="5" class="muted">No data yet. Run discovery for this project on the Connect page.</td></tr>`}</tbody>
        </table></div>
      </div>

      <div class="panel">
        <div class="panel-pad">
          <div class="row" style="justify-content:space-between"><h2>Collected data</h2>
            <span class="muted" id="count"></span></div>
          <div class="filters" style="margin-top:12px">
            <div class="f"><label class="label" for="f-status">Status</label>
              <select id="f-status" class="input">
                ${[["all", "All"], ["needs_migration", "Needs migration"], ["migrated", "Migrated"], ["safe", "Already quantum-safe"], ["corrected", "Corrected / with note"]]
                  .map(([k, v]) => `<option value="${k}" ${state.status === k ? "selected" : ""}>${v}</option>`).join("")}
              </select></div>
            <div class="f"><label class="label" for="f-target">Target</label>
              <select id="f-target" class="input"><option value="">All targets</option>
                ${d.targets.map((t) => `<option ${state.target === t.target ? "selected" : ""}>${esc(t.target)}</option>`).join("")}</select></div>
            <div class="grow"><label class="label" for="f-q">Search</label>
              <input id="f-q" class="input" placeholder="Algorithm, issuer, cloud, note…" value="${esc(state.q)}"></div>
          </div>
        </div>
        <div class="tbl-wrap"><table class="tbl" id="rows">
          <thead><tr><th>Target</th><th>Data (asset)</th><th>Kind</th><th>Algorithm found → now</th><th>Status</th>
            <th>AI risk</th><th class="num">Upgrade by</th><th>Hosting</th><th class="num">Sensitivity</th><th class="num">Secret for (yrs)</th><th>Used</th></tr></thead>
          <tbody></tbody>
        </table></div>
        <p class="muted" style="padding:10px 20px;font-size:13px;margin:0">Click a row to see everything measured for it${state.canEdit ? " and to correct it" : ""}. A yellow bar marks rows corrected by a user.</p>
      </div>

      ${d.not_reached.length ? `<div class="panel panel-pad" id="not-reached"><h2>Not reached (not used)</h2>
        <p class="muted" style="margin:2px 0 8px;font-size:13px">These targets were in the project, but the website did not answer, so no data from them is used.</p>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Target</th><th>Reason</th></tr></thead><tbody>
        ${d.not_reached.map((f) => `<tr><td>${esc(f.domain)}</td><td class="mono">${esc((f.errors || []).join("; "))}</td></tr>`).join("")}
        </tbody></table></div></div>` : ""}

      <details class="panel panel-pad guide"><summary>Where each piece of data comes from and what it is used for</summary>
        <div class="tbl-wrap" style="margin-top:10px"><table class="tbl"><thead><tr><th>Data</th><th>Comes from</th><th>Used for</th></tr></thead><tbody>
        ${d.field_guide.map((g) => `<tr style="cursor:default"><td class="nowrap">${esc(g.label)}</td><td>${esc(g.source)}</td><td>${esc(g.used_for)}</td></tr>`).join("")}
        </tbody></table></div>
      </details>
    </section>`;
    bindPicker();
    renderRows();

    main.querySelectorAll("button.tile[data-status]").forEach((b) => b.addEventListener("click", () => { state.status = b.dataset.status; render(); }));
    main.querySelectorAll("#targets [data-target]").forEach((tr) => tr.addEventListener("click", () => {
      state.target = state.target === tr.dataset.target ? "" : tr.dataset.target; render();
    }));
    main.querySelector("#f-status").addEventListener("change", (e) => { state.status = e.target.value; render(); });
    main.querySelector("#f-target").addEventListener("change", (e) => { state.target = e.target.value; render(); });
    main.querySelector("#f-q").addEventListener("input", (e) => { state.q = e.target.value; renderRows(); });
  }

  function renderRows() {
    const rows = filtered();
    main.querySelector("#count").textContent = `${rows.length} of ${state.data.rows.length} rows`;
    main.querySelector("#rows tbody").innerHTML = rows.map((r) => `
      <tr data-asset="${esc(r.asset_id)}" class="${Object.keys(r.corrections || {}).length || r.note ? "edited" : ""}">
        <td>${esc(r.target)}</td>
        <td class="mono nowrap">${esc(r.asset_id)}</td>
        <td>${esc(r.kind)}</td>
        <td class="nowrap">${esc(r.algorithm_discovered)}${r.algorithm_current !== r.algorithm_discovered ? `<span class="arrow">→</span><span style="color:var(--safe)">${esc(r.algorithm_current)}</span>` : ""}</td>
        <td>${statusChip(r)}</td>
        <td>${riskChip(r.risk_class)}</td>
        <td class="num">${dash(r.upgrade_by)}</td>
        <td>${dash(r.cloud)}</td>
        <td class="num">${dash(r.data_sensitivity)}</td>
        <td class="num">${dash(r.retention_years)}</td>
        <td>${r.used_in_analysis ? "Yes" : '<span class="muted">Not yet</span>'}</td>
      </tr>`).join("") || `<tr><td colspan="11" class="muted" style="cursor:default">No rows match these filters.</td></tr>`;
    main.querySelectorAll("#rows [data-asset]").forEach((tr) => tr.addEventListener("click", () => openRow(tr.dataset.asset)));
  }

  // ------------------------------------------------------------ row drawer (details + corrections)
  function openRow(assetId) {
    const d = state.data, r = d.rows.find((x) => x.asset_id === assetId);
    if (!r) return;
    const root = document.getElementById("drawer-root");
    const fixes = r.corrections || {};
    const was = (f) => fixes[f] ? `<div class="was">Corrected by ${esc(fixes[f].by)} (measured: ${esc(fixes[f].original)})
        ${state.canEdit ? `· <button type="button" data-revert="${f}">use measured value</button>` : ""}</div>` : "";
    const input = (f) => {
      const v = r[f];
      const dis = state.canEdit ? "" : "disabled";
      if (f === "exposure") return `<select class="input" data-f="${f}" ${dis}>${d.exposures.map((x) => `<option ${x === v ? "selected" : ""}>${x}</option>`).join("")}</select>`;
      if (f === "clients_support_pqc") return `<select class="input" data-f="${f}" ${dis}><option value="true" ${v ? "selected" : ""}>yes</option><option value="false" ${v ? "" : "selected"}>no</option></select>`;
      if (f === "data_sensitivity" || f === "business_criticality") return `<input class="input" type="number" min="1" max="5" step="1" data-f="${f}" value="${esc(v)}" ${dis}>`;
      if (f === "retention_years") return `<input class="input" type="number" min="0" max="100" step="0.1" data-f="${f}" value="${esc(v)}" ${dis}>`;
      return `<input class="input" data-f="${f}" value="${esc(v)}" maxlength="120" ${dis}>`;
    };
    const ev = r.evidence || {};
    const measured = [
      ["Protocol", r.protocol], ["TLS version", r.tls_version], ["Cipher suite", r.cipher],
      ["Post-quantum test", r.pq_group ? `${r.pq_group}${r.pq_note ? " (" + r.pq_note + ")" : ""}` : null],
      ["IP address", r.ip], ["Hosting", ev.hosting || (r.cloud ? `${r.cloud} (${r.region || "-"})` : null)],
      ["Certificate subject", r.cert_subject], ["Certificate issuer", r.cert_issuer], ["Certificate expires", r.cert_expires],
      ["Measured at", ev.measured_at], ["First seen", r.first_seen], ["Last seen", r.last_seen],
    ].filter(([, v]) => v !== null && v !== undefined && v !== "");

    root.innerHTML = `<div class="scrim" data-close></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="dr-title">
      <header><div style="flex:1"><h2 id="dr-title" class="mono" style="font-size:15px">${esc(r.asset_id)}</h2>
        <p class="muted" style="margin:2px 0 0">${esc(r.kind)} · ${esc(r.target)}</p></div>
        <button class="btn btn-quiet btn-sm" data-close aria-label="Close">Close</button></header>
      <div class="body">
        <div class="row">${statusChip(r)} ${riskChip(r.risk_class)} ${r.used_in_analysis ? '<span class="chip plain">Used in analysis</span>' : '<span class="chip plain muted">Not analysed yet</span>'}</div>
        <dl class="kv">
          <dt>Algorithm found</dt><dd>${esc(r.algorithm_discovered)}</dd>
          <dt>Algorithm now</dt><dd>${esc(r.algorithm_current)}</dd>
          ${r.migrated_at ? `<dt>Migrated</dt><dd>${esc(when(r.migrated_at))} by ${esc(r.migrated_by || "-")}</dd>` : ""}
          <dt>AI risk score</dt><dd>${dash(r.ai_score)} <span class="muted">(formula: ${dash(r.rule_score)})</span></dd>
          <dt>Upgrade by</dt><dd>${dash(r.upgrade_by)}</dd>
        </dl>
        ${r.why ? `<p class="why">${esc(r.why)}</p>` : ""}
        <h3 style="margin-top:20px">Measured</h3>
        <dl class="kv">${measured.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="${/Cipher|IP|subject|issuer/.test(k) ? "mono" : ""}">${esc(v)}</dd>`).join("") || "<dd class='muted'>No extra measurements stored for this row (run discovery again to collect them).</dd>"}</dl>
        <h3 style="margin-top:20px">${state.canEdit ? "Correct this data" : "Business data"}</h3>
        <p class="muted" style="margin:2px 0 0;font-size:13px">${state.canEdit ? "Fix anything that is wrong. Corrections are kept when discovery runs again, and risk scores are recalculated." : "Your role can view but not change this data."}</p>
        <div class="form-grid">
          ${Object.entries(d.editable).map(([f, label]) => `<div class="${f === "application" || f === "owner_team" ? "full" : ""}">
            <label class="label">${esc(label)}</label>${input(f)}${was(f)}</div>`).join("")}
          <div class="full"><label class="label" for="dr-note">Note</label>
            <textarea id="dr-note" class="input" rows="3" maxlength="1000" ${state.canEdit ? "" : "disabled"} placeholder="For example: checked with the bank's IT team">${esc(r.note)}</textarea></div>
        </div>
      </div>
      <footer>${state.canEdit ? `<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-save>Save corrections</button>` : `<button class="btn" data-close>Close</button>`}</footer>
    </aside>`;
    const close = () => { root.innerHTML = ""; document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    root.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
    root.querySelector(".drawer input, .drawer select, .drawer textarea, .drawer button")?.focus();

    const send = async (body, okText) => {
      try {
        const res = await api(`/projects/${encodeURIComponent(state.pid)}/assets/${encodeURIComponent(assetId)}`, { method: "PATCH", body: JSON.stringify(body) });
        close();
        toast(Object.keys(res.changed || {}).length ? okText : "Nothing changed.", "ok");
        state.data = await api(`/projects/${encodeURIComponent(state.pid)}/data`);
        const pr = await api("/projects"); state.projects = pr.projects;
        render();
      } catch (e) { toast(e.message, "error"); }
    };
    root.querySelectorAll("[data-revert]").forEach((b) => b.addEventListener("click", () => send({ revert: [b.dataset.revert] }, "Measured value restored.")));
    root.querySelector("[data-save]")?.addEventListener("click", () => {
      const changes = {};
      root.querySelectorAll("[data-f]").forEach((i) => {
        const f = i.dataset.f;
        let v = i.value;
        if (f === "clients_support_pqc") v = v === "true";
        else if (i.type === "number") { if (v === "") return; v = Number(v); }
        const old = r[f];
        if (String(v) !== String(old ?? "")) changes[f] = v;
      });
      const note = root.querySelector("#dr-note").value;
      send({ changes, note: note !== (r.note || "") ? note : null }, "Corrections saved. Risk scores were recalculated.");
    });
  }

  boot();
})();
