// Config check (P8): paste or upload TLS configuration and see whether post-quantum key exchange is on.
import { api, post } from "../api.js";
import { can } from "../state.js";
import { $, downloadText, emptyState, esc, num, toast, when } from "../ui.js";
const OUTCOME = {
    off_pinned: { label: "Off: pinned", cls: "border-risk-critical/60 text-risk-critical" },
    off_draft: { label: "Off: draft only", cls: "border-risk-critical/60 text-risk-critical" },
    off_default: { label: "Off: default", cls: "border-risk-high/60 text-risk-high" },
    unknown: { label: "Unknown", cls: "border-line text-fog" },
    depends_library: { label: "Depends on OpenSSL", cls: "border-risk-medium/60 text-risk-medium" },
    on_if_go124: { label: "On with Go 1.24+", cls: "border-risk-medium/60 text-risk-medium" },
    on: { label: "On", cls: "border-risk-safe/60 text-risk-safe" },
};
const VERDICT = {
    pq_off: "Post-quantum key exchange is switched off on at least one endpoint.",
    pq_on: "Every endpoint found offers hybrid post-quantum key exchange.",
    depends: "Nothing is pinned off, but the result depends on library versions or templates.",
    nothing_found: "No TLS key-exchange settings or TLS listeners were found in this text.",
};
const EXAMPLE = `# nginx
server {
  listen 443 ssl;
  ssl_ecdh_curve X25519:prime256v1:secp384r1;
}`;
function chip(outcome) {
    const o = OUTCOME[outcome] ?? { label: outcome, cls: "border-line text-fog" };
    return `<span class="chip whitespace-nowrap ${o.cls}">${esc(o.label)}</span>`;
}
function findingsTable(findings) {
    if (!findings.length)
        return `<p class="p-5 text-[13.5px] text-fog">${esc(VERDICT.nothing_found)}</p>`;
    return `<div class="overflow-x-auto"><table class="tbl">
    <thead><tr><th>File and line</th><th>Product</th><th>Setting</th><th>Result</th><th>What to change</th></tr></thead>
    <tbody>${findings.map((f) => `<tr>
      <td class="id">${esc(f.file)}:${esc(f.line)}</td>
      <td>${esc(f.product)}</td>
      <td><span class="id">${esc(f.setting)}</span>${f.values?.length ? `<div class="mt-1 text-[12.5px] text-fog id">${esc(f.values.join(" "))}</div>` : ""}</td>
      <td>${chip(f.outcome)}</td>
      <td class="text-[13px] min-w-[240px] [overflow-wrap:anywhere]">${esc(f.advice)}${f.default_source ? ` <a href="${esc(f.default_source)}" target="_blank" rel="noopener">Source</a>` : ""}</td>
    </tr>`).join("")}</tbody></table></div>`;
}
function resultPanel(check) {
    const s = check.summary;
    return `<section class="panel" data-result>
    <div class="flex flex-wrap items-center gap-3 px-5 pt-5">
      <h2>Result</h2>
      <span class="text-[13px] text-fog">${esc(check.files.join(", "))}${check.created_at ? ` · ${esc(when(check.created_at))}` : ""}</span>
      ${check.findings?.length ? `<button class="btn btn-sm ml-auto" data-csv>Export CSV</button>` : ""}
    </div>
    <p class="px-5 pt-2 text-mist">${esc(VERDICT[s.verdict] ?? "")}</p>
    ${s.breakage_risk ? `<p class="px-5 pt-1 text-[13.5px] text-risk-high">${num(s.breakage_risk)} setting(s) name ML-KEM in an OpenSSL-based server. On older OpenSSL that server will not start, so check the OpenSSL version before you deploy.</p>` : ""}
    <div class="mt-3">${findingsTable(check.findings ?? [])}</div>
  </section>`;
}
function studyPanel(st) {
    if (!st)
        return "";
    const g = st.groups ?? {};
    const row = (name, v) => v ? `<tr><td>${name}</td><td class="tabular">${num(v.readable)}</td><td class="tabular">${num(v.pq_excluded)}</td><td class="tabular">${num(v.pq_enabled)}</td></tr>` : "";
    return `<section class="panel panel-pad">
    <h2>What public repositories ship</h2>
    <p class="mt-2 text-[13.5px] text-fog">${num(st.repositories_scanned)} public repositories (proxies, meshes, ingress controllers, Helm charts, config templates, Go infrastructure, AWS load-balancer code), ${num(st.files_scanned)} files, scanned ${esc(st.generated)}.
      Of ${num(st.explicit_deployable_readable)} readable key-exchange settings outside tests and docs, <span class="text-mist">${num(st.pinned_classical_deployable)}</span> pin a classical-only list.</p>
    <div class="mt-3 overflow-x-auto"><table class="tbl"><thead><tr><th>Where</th><th>Readable</th><th>Pinned</th><th>PQ on</th></tr></thead>
      <tbody>${row("Configs, charts, examples", g.copied_config)}${row("Shipped Go code", g.shipped_code)}${row("Tests and docs", g.tests_docs)}</tbody></table></div>
    <p class="mt-3 text-[12.5px] text-fog">Every finding links to its line at a pinned commit in <span class="id">qmigrate/research/p8_config_pqc/results/</span>.</p>
  </section>`;
}
function defaultsPanel(st) {
    const d = st?.defaults ?? {};
    return `<section class="panel panel-pad">
    <h2>Without a setting</h2>
    <p class="mt-2 text-[13.5px] text-fog">When nothing is configured, the product default decides.</p>
    <ul class="mt-3 space-y-2 text-[13px]">${Object.entries(d).map(([p, v]) => `
      <li class="flex gap-2"><span class="w-28 shrink-0 text-mist">${esc(p)}</span><span class="text-fog">${esc(v.pq_default)} · <a href="${esc(v.source)}" target="_blank" rel="noopener">source</a></span></li>`).join("")}</ul>
  </section>`;
}
export async function configCheckPage(el) {
    const data = await api("/config-check");
    const latest = data.checks[0];
    const allowed = can("validate");
    el.innerHTML = `
  <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
    <div class="min-w-0 space-y-5">
      <section class="panel panel-pad">
        <h2>Check TLS configuration</h2>
        <p class="mt-2 max-w-[70ch] text-[13.5px] text-fog">Software that supports post-quantum key exchange does not use it when its configuration pins a classical list, or when its default leaves it out.
          Paste nginx, Apache, HAProxy, Envoy, Istio, Envoy Gateway, Traefik, Caddy, Go, Kubernetes or Terraform configuration.
          The text is read, never run, and is not stored: only the findings are kept.</p>
        ${allowed ? `
        <label class="label mt-4" for="cc-name">File name</label>
        <input id="cc-name" class="input w-full max-w-72" value="nginx.conf" maxlength="200">
        <label class="label mt-3" for="cc-text">Configuration</label>
        <textarea id="cc-text" class="input id h-56 w-full" spellcheck="false" placeholder="${esc(EXAMPLE)}"></textarea>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <button class="btn btn-primary" data-run>Check configuration</button>
          <label class="btn" for="cc-files">Upload files</label>
          <input id="cc-files" type="file" multiple class="sr-only">
          <button class="btn btn-quiet" data-example>Use an example</button>
          <span class="text-[12.5px] text-fog">Up to ${num(data.limits.files)} files, ${num(Math.round(data.limits.file_chars / 1000))} KB each.</span>
        </div>` : `<p class="mt-4 text-[13.5px] text-fog">Your role can view results but not run a check.</p>`}
      </section>
      <div data-out>${latest ? resultPanel(latest) : emptyState("No check yet", "Paste a configuration above to see whether its TLS endpoints negotiate post-quantum key exchange.")}</div>
    </div>
    <aside class="min-w-0 space-y-5">${studyPanel(data.study)}${defaultsPanel(data.study)}</aside>
  </div>`;
    const out = $("[data-out]", el);
    const show = (check) => {
        out.innerHTML = resultPanel(check);
        $("[data-csv]", out)?.addEventListener("click", () => {
            const head = ["file", "line", "product", "setting", "values", "outcome", "advice"];
            const lines = check.findings.map((f) => [f.file, f.line, f.product, f.setting, f.values.join(" "), f.outcome, f.advice]
                .map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","));
            downloadText("config-check.csv", [head.join(","), ...lines].join("\n"));
        });
    };
    if (latest)
        show(latest);
    if (!allowed)
        return;
    const run = async (files) => {
        const btn = $("[data-run]", el);
        btn.disabled = true;
        try {
            show(await post("/config-check", { files }));
            out.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        catch (e) {
            toast(e.message ?? "The check failed.", "error");
        }
        finally {
            btn.disabled = false;
        }
    };
    $("[data-run]", el).addEventListener("click", () => {
        const text = ($("#cc-text", el)).value;
        if (!text.trim()) {
            toast("Paste some configuration first.", "info");
            return;
        }
        void run([{ name: ($("#cc-name", el)).value || "config", text }]);
    });
    $("[data-example]", el).addEventListener("click", () => {
        ($("#cc-text", el)).value = EXAMPLE;
        ($("#cc-name", el)).value = "nginx.conf";
    });
    $("#cc-files", el).addEventListener("change", async (ev) => {
        const list = Array.from(ev.target.files ?? []).slice(0, data.limits.files);
        const tooBig = list.find((f) => f.size > data.limits.file_chars);
        if (tooBig) {
            toast(`${tooBig.name} is larger than ${Math.round(data.limits.file_chars / 1000)} KB.`, "error");
            return;
        }
        const files = await Promise.all(list.map(async (f) => ({ name: f.name, text: await f.text() })));
        if (files.length)
            void run(files);
    });
}
