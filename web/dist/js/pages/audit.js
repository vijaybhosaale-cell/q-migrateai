// Audit log: who did what, when, from where.
import { api } from "../api.js";
import { $, downloadText, emptyState, esc, when } from "../ui.js";
const LABEL = {
    "user.login": "Logged in", "tenant.created": "Created the company account",
    "user.created": "Added a user", "user.deleted": "Removed a user", "user.role_changed": "Changed a role",
    "user.2fa_enabled": "Turned on two-factor", "user.2fa_disabled": "Turned off two-factor", "user.password_changed": "Changed password",
    "connection.created": "Added a connection", "connection.deleted": "Removed a connection",
    "discovery.started": "Started discovery", "discovery.completed": "Discovery finished", "discovery.failed": "Discovery failed",
    "models.retrained": "Retrained the models", "migration.applied": "Migrated an asset", "migration.wave": "Migrated a wave",
    "migration.rolled_back": "Rolled back an asset", "migration.reset": "Reset to discovered state",
    "settings.updated": "Changed alert settings", "report.downloaded": "Downloaded the PDF report", "gdpr.export": "Exported all data",
};
function details(d) {
    return Object.entries(d).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(", ");
}
export async function auditPage(el) {
    const rows = await api("/audit");
    if (!rows.length) {
        el.innerHTML = emptyState("No activity yet", "Logins, migrations, setting changes and data exports are recorded here.");
        return;
    }
    el.innerHTML = `
  <section class="panel">
    <div class="flex flex-wrap items-end gap-3 border-b border-line p-4">
      <div><label class="label" for="au-q">Filter</label><input id="au-q" class="input w-64" placeholder="User, action or asset"></div>
      <p class="text-[13px] text-fog max-w-md">The last 300 events for your company. Entries cannot be edited or removed from the app.</p>
      <button class="btn btn-sm ml-auto" data-csv>Export CSV</button>
    </div>
    <div class="overflow-x-auto"><table class="tbl">
      <thead><tr><th>When</th><th>User</th><th>Action</th><th>Target</th><th>Details</th><th>IP address</th></tr></thead>
      <tbody data-body></tbody></table></div>
  </section>`;
    const body = $("[data-body]", el);
    const draw = () => {
        const q = ($("#au-q", el)).value.trim().toLowerCase();
        body.innerHTML = rows.filter((r) => !q || `${r.user_email} ${r.action} ${LABEL[r.action] ?? ""} ${r.target}`.toLowerCase().includes(q))
            .map((r) => `<tr><td class="whitespace-nowrap text-fog">${esc(when(r.created_at))}</td><td>${esc(r.user_email ?? "system")}</td>
        <td>${esc(LABEL[r.action] ?? r.action)}</td><td class="id">${esc(r.target ?? "")}</td>
        <td class="text-fog text-[12.5px] max-w-[320px] truncate" title="${esc(details(r.details))}">${esc(details(r.details))}</td>
        <td class="id text-fog">${esc(r.ip ?? "")}</td></tr>`).join("");
    };
    $("#au-q", el).addEventListener("input", draw);
    $("[data-csv]", el).addEventListener("click", () => {
        const csv = ["created_at,user_email,action,target,details,ip",
            ...rows.map((r) => [r.created_at, r.user_email, r.action, r.target, JSON.stringify(r.details), r.ip]
                .map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");
        downloadText("q-migrateai-audit-log.csv", csv);
    });
    draw();
}
