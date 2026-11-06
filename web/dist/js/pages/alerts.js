// Alerts raised by discovery and monitoring, with the delivery log for e-mail and Slack.
import { api, post } from "../api.js";
import { refreshUnread } from "../state.js";
import { $, $$, emptyState, esc, when } from "../ui.js";
const SEVERITY = {
    critical: "border-risk-critical/60 text-risk-critical", high: "border-risk-high/60 text-risk-high",
    warning: "border-risk-medium/60 text-risk-medium", info: "border-lattice/60 text-lattice",
};
const DELIVERY = {
    sent: "border-risk-safe/50 text-risk-safe", pending: "border-lattice/60 text-lattice",
    skipped: "border-line text-fog", failed: "border-risk-critical/50 text-risk-critical",
};
export async function alertsPage(el) {
    const data = await api("/alerts");
    const unread = data.alerts.filter((a) => !a.read_at).length;
    el.innerHTML = `
  <div class="grid gap-5 xl:grid-cols-[1fr_380px]">
    <section class="panel">
      <div class="flex flex-wrap items-center gap-3 px-5 pt-5">
        <h2>Alerts</h2><span class="text-[13px] text-fog">${unread} unread</span>
        ${unread ? `<button class="btn btn-sm ml-auto" data-all>Mark all as read</button>` : ""}
      </div>
      ${data.alerts.length ? `<ul class="mt-3">${data.alerts.map((a) => `
        <li class="flex gap-3 border-t border-line/60 px-5 py-4 ${a.read_at ? "opacity-70" : ""}">
          <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full ${a.read_at ? "bg-transparent" : "bg-lattice"}" aria-hidden="true"></span>
          <div class="flex-1 min-w-0">
            <div class="flex flex-wrap items-center gap-2"><span class="chip ${SEVERITY[a.severity] ?? SEVERITY.info}">${esc(a.severity)}</span>
              <span class="text-mist font-medium">${esc(a.title)}</span><span class="text-[12.5px] text-fog ml-auto">${esc(when(a.created_at))}</span></div>
            ${a.body ? `<p class="mt-1.5 text-[13.5px] text-fog">${esc(a.body)}</p>` : ""}
            <div class="mt-2 flex gap-2">
              ${a.asset_id ? `<a class="btn btn-sm no-underline hover:no-underline" href="#/assets?focus=${encodeURIComponent(a.asset_id)}">Open ${esc(a.asset_id)}</a>` : ""}
              ${a.read_at ? "" : `<button class="btn btn-sm btn-quiet" data-read="${esc(a.id)}">Mark as read</button>`}
            </div>
          </div></li>`).join("")}</ul>`
        : `<div class="p-5">${emptyState("No alerts", "Alerts appear when a new discovery finds quantum-vulnerable assets, or when you send a test alert from Settings.")}</div>`}
    </section>
    <aside class="space-y-5">
      <section class="panel panel-pad">
        <h2>How alerts reach you</h2>
        <p class="mt-2 text-[13.5px] text-fog">Every alert shows here. Copies go to the e-mail address and Slack channel set in <a href="#/settings">Settings</a>.</p>
        <ul class="mt-3 space-y-2 text-[13px] text-fog list-disc pl-5">
          <li>E-mail is sent only when the server has SMTP details. Without them the delivery is logged as skipped.</li>
          <li>Slack uses an incoming webhook. Only <span class="id">hooks.slack.com</span> addresses are accepted.</li>
          <li>Scheduled monitoring re-runs discovery at the interval you choose and raises an alert for each new quantum-vulnerable asset.</li>
        </ul>
      </section>
      <section class="panel">
        <div class="px-5 pt-5"><h2>Delivery log</h2></div>
        ${data.deliveries.length ? `<ul class="mt-2">${data.deliveries.map((d) => `<li class="border-t border-line/60 px-5 py-3 text-[13px]">
          <div class="flex items-center gap-2"><span class="chip ${DELIVERY[d.status] ?? DELIVERY.skipped}">${esc(d.status)}</span>
            <span>${esc(d.channel)}</span><span class="ml-auto text-fog">${esc(when(d.created_at))}</span></div>
          <p class="mt-1 text-fog truncate" title="${esc(d.subject)}">${esc(d.subject)}</p>
          ${d.error ? `<p class="mt-0.5 text-[12.5px] text-fog">${esc(d.error)}</p>` : ""}</li>`).join("")}</ul>`
        : `<p class="p-5 pt-2 text-[13.5px] text-fog">Nothing sent yet.</p>`}
      </section>
    </aside>
  </div>`;
    $$("[data-read]", el).forEach((b) => b.addEventListener("click", async () => {
        await post(`/alerts/${b.dataset.read}/read`);
        await refreshUnread();
        await alertsPage(el);
    }));
    $("[data-all]", el)?.addEventListener("click", async () => {
        await post("/alerts/read-all");
        await refreshUnread();
        await alertsPage(el);
    });
}
