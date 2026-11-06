// Settings: account security, team, alerts and monitoring, privacy and data.
import { api, del, patch, post, put } from "../api.js";
import { can, go, loadMe, state } from "../state.js";
import { $, $$, confirmDialog, esc, gdprButton, modal, toast, when } from "../ui.js";
async function refreshMe() {
    await loadMe();
    window.dispatchEvent(new Event("qm:remount"));
}
const ROLE_TEXT = {
    admin: "Admin: everything, including users and company data",
    ciso: "CISO: migrations, connections, alerts and audit log",
    analyst: "Analyst: discovery, validation and the assistant",
    viewer: "Viewer: read-only",
};
export async function settingsPage(el, params) {
    const me = state.me;
    const [settings, users] = await Promise.all([api("/settings"), can("users") ? api("/users") : Promise.resolve(null)]);
    const tab = params.get("tab") || "account";
    const tabs = [
        { key: "account", label: "Your account" },
        ...(can("users") ? [{ key: "team", label: "Team" }] : []),
        { key: "alerts", label: "Alerts and monitoring" },
        { key: "privacy", label: "Privacy and data" },
    ];
    el.innerHTML = `
  <div class="flex flex-wrap items-center gap-2 mb-5" role="tablist">
    ${tabs.map((t) => `<a role="tab" aria-selected="${t.key === tab}" href="#/settings?tab=${t.key}"
      class="btn btn-sm no-underline hover:no-underline ${t.key === tab ? "border-lattice text-mist bg-lattice-soft/50" : "btn-quiet"}">${esc(t.label)}</a>`).join("")}
    ${gdprButton("ml-auto")}
  </div>
  <div data-tab></div>`;
    const host = $("[data-tab]", el);
    if (tab === "team" && users)
        team(host, users, el, params);
    else if (tab === "alerts")
        alerts(host, settings);
    else if (tab === "privacy")
        privacy(host);
    else
        account(host, me);
}
// ------------------------------------------------------------ account
function account(host, me) {
    const u = me.user;
    host.innerHTML = `
  <div class="grid gap-5 xl:grid-cols-2">
    <section class="panel panel-pad">
      <h2>Profile</h2>
      <dl class="mt-4 grid grid-cols-[110px_1fr] gap-y-2 text-[14px]">
        <dt class="text-fog">Name</dt><dd>${esc(u.name)}</dd>
        <dt class="text-fog">E-mail</dt><dd>${esc(u.email)}</dd>
        <dt class="text-fog">Role</dt><dd>${esc(ROLE_TEXT[u.role] ?? u.role)}</dd>
        <dt class="text-fog">Company</dt><dd>${esc(me.tenant.name)}</dd>
        <dt class="text-fog">Data region</dt><dd>${esc(me.tenant.data_region)}</dd>
      </dl>
    </section>
    <section class="panel panel-pad" data-2fa>
      <h2>Two-factor authentication</h2>
      <p class="mt-1 text-[13.5px] text-fog">A six-digit code from an authenticator app (Microsoft Authenticator, Google Authenticator, 1Password and others) is asked for after your password.</p>
      <div class="mt-4" data-2fa-body>
        ${u.totp_enabled
        ? `<p class="text-[14px]"><span class="chip border-risk-safe/50 text-risk-safe">On</span> Your account asks for a code at every login.</p>
             <div class="mt-4 flex items-end gap-2"><div><label class="label" for="tf-off">Code from your app</label>
               <input id="tf-off" class="input w-36 id" inputmode="numeric" autocomplete="one-time-code" maxlength="6"></div>
               <button class="btn btn-danger" data-2fa-off>Turn off</button></div>`
        : `<p class="text-[14px]"><span class="chip border-risk-medium/50 text-risk-medium">Off</span> Turn it on to protect migrations and company data.</p>
             <button class="btn btn-primary mt-4" data-2fa-setup>Set up two-factor</button>`}
      </div>
    </section>
    <section class="panel panel-pad xl:col-span-2">
      <h2>Change password</h2>
      <form class="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end" data-pw>
        <div><label class="label" for="pw-cur">Current password</label><input id="pw-cur" type="password" class="input" autocomplete="current-password" required></div>
        <div><label class="label" for="pw-new">New password</label><input id="pw-new" type="password" class="input" autocomplete="new-password" required></div>
        <div><label class="label" for="pw-rep">Repeat new password</label><input id="pw-rep" type="password" class="input" autocomplete="new-password" required></div>
        <button class="btn btn-primary">Change password</button>
      </form>
      <p class="mt-2 text-[12.5px] text-fog">At least 10 characters with upper case, lower case and a digit. Your other sessions are signed out.</p>
    </section>
  </div>`;
    $("[data-2fa-setup]", host)?.addEventListener("click", async () => {
        const r = await post("/auth/2fa/setup");
        let qr = "";
        try {
            const q = qrcode(0, "M");
            q.addData(r.otpauth_uri);
            q.make();
            qr = q.createSvgTag({ cellSize: 5, margin: 4, scalable: true, title: "QR code for your authenticator app" });
        }
        catch {
            qr = "";
        }
        $("[data-2fa-body]", host).innerHTML = `
      <ol class="list-decimal pl-5 space-y-1.5 text-[13.5px]"><li>Scan the code with your authenticator app.</li>
        <li>Enter the six-digit code it shows to finish.</li></ol>
      <div class="mt-4 flex flex-wrap items-start gap-5">
        <div class="w-44 rounded-lg bg-white p-2" data-qr>${qr}</div>
        <div class="flex-1 min-w-[200px]">
          <p class="text-[12.5px] text-fog">Cannot scan? Enter this key by hand:</p>
          <p class="id mt-1 break-all text-[13px] text-mist" data-secret>${esc(r.secret)}</p>
          <label class="label mt-4" for="tf-on">Six-digit code</label>
          <div class="flex gap-2"><input id="tf-on" class="input w-36 id" inputmode="numeric" autocomplete="one-time-code" maxlength="6">
            <button class="btn btn-primary" data-2fa-on>Turn on</button></div>
        </div>
      </div>`;
        $("[data-2fa-on]", host).addEventListener("click", async () => {
            try {
                await post("/auth/2fa/enable", { code: ($("#tf-on", host)).value.trim() });
                toast("Two-factor authentication is on.", "ok");
                await refreshMe();
            }
            catch (e) {
                toast(e.message, "error");
            }
        });
    });
    $("[data-2fa-off]", host)?.addEventListener("click", async () => {
        try {
            await post("/auth/2fa/disable", { code: ($("#tf-off", host)).value.trim() });
            toast("Two-factor authentication is off.", "info");
            await refreshMe();
        }
        catch (e) {
            toast(e.message, "error");
        }
    });
    $("[data-pw]", host).addEventListener("submit", async (e) => {
        e.preventDefault();
        const cur = ($("#pw-cur", host)).value, nw = ($("#pw-new", host)).value;
        if (nw !== ($("#pw-rep", host)).value) {
            toast("The new passwords do not match.", "error");
            return;
        }
        try {
            await post("/auth/password", { current: cur, new: nw });
            toast("Password changed.", "ok");
            await refreshMe();
        }
        catch (err) {
            toast(err.message, "error");
        }
    });
}
// --------------------------------------------------------------- team
function team(host, users, el, params) {
    const me = state.me;
    host.innerHTML = `
  <section class="panel">
    <div class="flex flex-wrap items-center gap-3 px-5 pt-5"><h2>Team</h2>
      <p class="text-[13px] text-fog">${users.length} people in ${esc(me.tenant.name)}</p>
      <button class="btn btn-primary btn-sm ml-auto" data-add>Add a person</button></div>
    <div class="overflow-x-auto mt-3"><table class="tbl">
      <thead><tr><th>Name</th><th>E-mail</th><th>Role</th><th>Two-factor</th><th>Last login</th><th></th></tr></thead>
      <tbody>${users.map((u) => `<tr>
        <td>${esc(u.name)}${u.id === me.user.id ? ` <span class="text-fog text-[12.5px]">(you)</span>` : ""}</td><td>${esc(u.email)}</td>
        <td>${u.id === me.user.id ? esc(u.role) : `<select class="input py-1 w-32" data-role="${esc(u.id)}" aria-label="Role for ${esc(u.name)}">
          ${me.roles.map((r) => `<option value="${r}" ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select>`}</td>
        <td>${u.totp_enabled ? `<span class="chip border-risk-safe/50 text-risk-safe">On</span>` : `<span class="chip border-line text-fog">Off</span>`}</td>
        <td class="text-fog">${esc(u.last_login_at ? when(u.last_login_at) : "never")}</td>
        <td class="text-right">${u.id === me.user.id ? "" : `<button class="btn btn-sm btn-quiet" data-del="${esc(u.id)}" data-name="${esc(u.name)}">Remove</button>`}</td></tr>`).join("")}</tbody>
    </table></div>
    <dl class="grid gap-2 p-5 text-[13px] text-fog md:grid-cols-2">${Object.values(ROLE_TEXT).map((t) => `<dd>${esc(t)}</dd>`).join("")}</dl>
  </section>`;
    const reload = () => settingsPage(el, params);
    $$("[data-role]", host).forEach((s) => s.addEventListener("change", async () => {
        try {
            await patch(`/users/${s.dataset.role}`, { role: s.value });
            toast("Role changed.", "ok");
        }
        catch (e) {
            toast(e.message, "error");
            await reload();
        }
    }));
    $$("[data-del]", host).forEach((b) => b.addEventListener("click", async () => {
        if (await confirmDialog("Remove person", `<p>Remove <strong>${esc(b.dataset.name)}</strong>? They are signed out at once.</p>`, "Remove", true)) {
            try {
                await del(`/users/${b.dataset.del}`);
                toast("Person removed.", "ok");
                await reload();
            }
            catch (e) {
                toast(e.message, "error");
            }
        }
    }));
    $("[data-add]", host).addEventListener("click", () => {
        const m = modal("Add a person", `
      <label class="label" for="nu-name">Name</label><input id="nu-name" class="input">
      <label class="label mt-3" for="nu-email">Work e-mail</label><input id="nu-email" type="email" class="input">
      <label class="label mt-3" for="nu-role">Role</label>
      <select id="nu-role" class="input">${me.roles.map((r) => `<option value="${r}" ${r === "analyst" ? "selected" : ""}>${esc(ROLE_TEXT[r])}</option>`).join("")}</select>
      <p class="mt-3 text-[12.5px] text-fog">You get a temporary password to pass on securely. They must change it at first login.</p>`, `<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-save>Add person</button>`);
        m.el.querySelector("[data-save]").addEventListener("click", async () => {
            try {
                const r = await post("/users", { name: (m.el.querySelector("#nu-name")).value.trim(),
                    email: (m.el.querySelector("#nu-email")).value.trim(), role: (m.el.querySelector("#nu-role")).value });
                m.close();
                modal("Person added", `<p>Temporary password:</p><p class="id mt-2 rounded-lg bg-ink-0 p-3 text-[15px] text-mist select-all" data-temp>${esc(r.temporary_password)}</p>
          <p class="mt-3 text-[13px] text-fog">It is shown only once. Share it by a separate channel, not in the same e-mail as the login address.</p>`);
                await reload();
            }
            catch (e) {
                toast(e.message, "error");
            }
        });
    });
}
// ------------------------------------------------------------- alerts
function alerts(host, s) {
    const edit = can("alerts");
    host.innerHTML = `
  <section class="panel panel-pad max-w-3xl">
    <h2>Alerts and monitoring</h2>
    <p class="mt-1 text-[13.5px] text-fog">Scheduled monitoring re-runs discovery and raises an alert for each new quantum-vulnerable asset. Alerts always appear in the app; copies go to e-mail and Slack.</p>
    <form class="mt-5 grid gap-4" data-form>
      <div><label class="label" for="s-email">Alert e-mail</label>
        <input id="s-email" type="email" class="input" value="${esc(s.alert_email ?? "")}" placeholder="security-team@yourcompany.com" ${edit ? "" : "disabled"}>
        ${s.smtp_configured ? "" : `<p class="mt-1 text-[12.5px] text-risk-medium">The server has no SMTP details yet, so e-mails are logged as skipped. Add SMTP_HOST and related values to the .env file to send them.</p>`}</div>
      <div><label class="label" for="s-slack">Slack incoming webhook</label>
        <input id="s-slack" class="input id" value="${esc(s.slack_webhook ?? "")}" placeholder="https://hooks.slack.com/services/…" ${edit ? "" : "disabled"}>
        <p class="mt-1 text-[12.5px] text-fog">Create one in Slack under Apps, Incoming Webhooks. Only hooks.slack.com addresses are accepted.</p></div>
      <div><label class="label" for="s-int">Re-run discovery every</label>
        <select id="s-int" class="input w-48" ${edit ? "" : "disabled"}>${[[0, "Off"], [6, "6 hours"], [12, "12 hours"], [24, "24 hours"], [168, "7 days"]].map(([v, t]) => `<option value="${v}" ${Number(s.monitor_interval_hours) === v ? "selected" : ""}>${t}</option>`).join("")}</select></div>
      ${edit ? `<div class="flex gap-2"><button class="btn btn-primary">Save alert settings</button><button type="button" class="btn" data-test>Send a test alert</button></div>`
        : `<p class="text-[13px] text-fog">Your role can view these settings but not change them.</p>`}
    </form>
  </section>`;
    $("[data-form]", host).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
            await put("/settings", { alert_email: ($("#s-email", host)).value.trim() || null,
                slack_webhook: ($("#s-slack", host)).value.trim() || null,
                monitor_interval_hours: Number(($("#s-int", host)).value) });
            toast("Alert settings saved.", "ok");
        }
        catch (err) {
            toast(err.message, "error");
        }
    });
    $("[data-test]", host)?.addEventListener("click", async () => {
        try {
            const r = await post("/settings/test-alert");
            const lines = r.deliveries.map((d) => `${d.channel}: ${d.status}${d.error ? ` (${d.error})` : ""}`).join("; ");
            toast(`Test alert created. ${lines || "No copies to send."}`, "ok");
        }
        catch (err) {
            toast(err.message, "error");
        }
    });
}
// ------------------------------------------------------------ privacy
function privacy(host) {
    const me = state.me;
    const admin = can("gdpr");
    host.innerHTML = `
  <div class="grid gap-5 xl:grid-cols-2">
    <section class="panel panel-pad">
      <h2>What we store</h2>
      <ul class="mt-3 space-y-2 text-[14px] list-disc pl-5">
        <li>Cryptographic metadata: key types, algorithms, certificates, TLS settings and how services depend on each other.</li>
        <li>Your team's names, work e-mails, roles and login times.</li>
        <li>Migrations, alerts and the audit log.</li>
      </ul>
      <p class="mt-3 text-[13.5px] text-fog">No files, no customer data, no secrets or private keys. Data is kept in ${esc(me.tenant.data_region)} and is encrypted in transit and at rest.</p>
      <p class="mt-3"><a href="#/privacy">Read the privacy policy</a></p>
    </section>
    <section class="panel panel-pad">
      <h2>Export or delete your data</h2>
      ${admin ? `
      <p class="mt-1 text-[13.5px] text-fog">Download everything stored for ${esc(me.tenant.name)} as one JSON file, or delete the company account and all of its data.</p>
      <div class="mt-4 flex flex-wrap gap-2">
        <a class="btn no-underline hover:no-underline" href="/api/gdpr/export" data-export download>Export my data</a>
        <button class="btn btn-danger" data-delete>Delete my data</button>
      </div>
      <p class="mt-3 text-[12.5px] text-fog">Password hashes and two-factor secrets are never included in the export.</p>`
        : `<p class="mt-1 text-[13.5px] text-fog">Only an admin of ${esc(me.tenant.name)} can export or delete company data. Ask your admin, or write to the privacy contact in the "i" panel.</p>`}
    </section>
  </div>`;
    $("[data-delete]", host)?.addEventListener("click", () => {
        const m = modal("Delete all company data", `
      <p>This permanently deletes <strong>${esc(me.tenant.name)}</strong>: every user, connection, discovered asset, migration, alert and audit entry. It cannot be undone.</p>
      <p class="mt-3 text-[13.5px] text-fog">Export your data first if you may need it.</p>
      <label class="label mt-4" for="del-confirm">Type the company name to confirm</label>
      <input id="del-confirm" class="input" autocomplete="off" placeholder="${esc(me.tenant.name)}">`, `<button class="btn" data-close>Cancel</button><button class="btn btn-danger" data-go disabled>Delete everything</button>`);
        const input = m.el.querySelector("#del-confirm");
        const btn = m.el.querySelector("[data-go]");
        input.addEventListener("input", () => { btn.disabled = input.value.trim() !== me.tenant.name; });
        btn.addEventListener("click", async () => {
            try {
                await post("/gdpr/delete", { confirm: input.value.trim() });
                m.close();
                state.me = null;
                toast("Your company data has been deleted.", "ok");
                go("/login");
            }
            catch (e) {
                toast(e.message, "error");
            }
        });
    });
}
