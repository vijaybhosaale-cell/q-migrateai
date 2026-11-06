// App entry: router, application shell and session handling.
import { api, post, setUnauthorizedHandler } from "./api.js";
import { mountAssistant } from "./chat.js";
import { state, go, can, loadMe, refreshUnread, type PublicConfig } from "./state.js";
import { $, $$, esc, icon, setPrivacyContact, toast } from "./ui.js";
import { loginPage, signupPage, twoFactorPage } from "./pages/auth.js";
import { dashboardPage } from "./pages/dashboard.js";
import { connectPage } from "./pages/connect.js";
import { graphPage } from "./pages/graph.js";
import { assetsPage } from "./pages/assets.js";
import { modelsPage } from "./pages/models.js";
import { planPage } from "./pages/plan.js";
import { labPage } from "./pages/lab.js";
import { reportPage } from "./pages/report.js";
import { alertsPage } from "./pages/alerts.js";
import { auditPage } from "./pages/audit.js";
import { settingsPage } from "./pages/settings.js";
import { privacyPage } from "./pages/privacy.js";

export type Cleanup = void | (() => void);
export type Page = {
  title: string;
  render: (el: HTMLElement, params: URLSearchParams) => Promise<Cleanup>;
  public?: boolean;
  perm?: string;
};

const routes: Record<string, Page> = {
  login: { title: "Log in", render: loginPage, public: true },
  signup: { title: "Create account", render: signupPage, public: true },
  "login-2fa": { title: "Two-factor check", render: twoFactorPage, public: true },
  privacy: { title: "Privacy policy", render: privacyPage, public: true },
  dashboard: { title: "Dashboard", render: dashboardPage },
  connect: { title: "Connect and discover", render: connectPage },
  graph: { title: "Dependency map", render: graphPage },
  assets: { title: "Assess risk", render: assetsPage },
  models: { title: "AI models", render: modelsPage },
  plan: { title: "Migration plan", render: planPage },
  lab: { title: "PQC lab", render: labPage },
  report: { title: "Measure and report", render: reportPage },
  alerts: { title: "Alerts", render: alertsPage },
  audit: { title: "Audit log", render: auditPage, perm: "audit" },
  settings: { title: "Settings", render: settingsPage },
};

const NAV: { group: string; items: { route: string; label: string; icon: string; step?: number; perm?: string; href?: string }[] }[] = [
  { group: "", items: [{ route: "dashboard", label: "Dashboard", icon: "home" }] },
  { group: "Migration journey", items: [
    { route: "connect", label: "Connect and discover", icon: "plug", step: 1 },
    { route: "graph", label: "Map dependencies", icon: "graph", step: 2 },
    { route: "assets", label: "Assess risk", icon: "list", step: 3 },
    { route: "plan", label: "Plan waves", icon: "route", step: 4 },
    { route: "lab", label: "Migrate in PQC lab", icon: "flask", step: 5 },
    { route: "report", label: "Measure and report", icon: "doc", step: 6 },
  ] },
  { group: "Insight and operations", items: [
    { route: "project-data", label: "Project data", icon: "list", href: "/project-data/" },
    { route: "models", label: "AI models", icon: "brain" },
    { route: "alerts", label: "Alerts", icon: "bell" },
    { route: "audit", label: "Audit log", icon: "scroll", perm: "audit" },
    { route: "settings", label: "Settings", icon: "cog" },
  ] },
];

let cleanup: Cleanup;
let shellMounted = false;
let menuCloser = false;

function parseHash(): { name: string; params: URLSearchParams } {
  const raw = location.hash.replace(/^#\/?/, "");
  const [name, query] = raw.split("?");
  return { name: name || "dashboard", params: new URLSearchParams(query || "") };
}

function shell(): string {
  const me = state.me!;
  const nav = NAV.map((g) => `
    ${g.group ? `<p class="px-3 pt-5 pb-1.5 text-[12px] text-fog/80">${esc(g.group)}</p>` : ""}
    ${g.items.filter((i) => !i.perm || can(i.perm)).map((i) => `
      <a href="${i.href ?? `#/${i.route}`}" data-nav="${i.route}" class="nav-link">
        ${i.step ? `<span class="nav-step">${i.step}</span>` : icon(i.icon)}
        <span class="flex-1">${esc(i.label)}</span>
        ${i.route === "alerts" ? `<span data-unread class="hidden rounded-full bg-risk-critical px-1.5 text-[11px] font-semibold text-white tabular"></span>` : ""}
      </a>`).join("")}`).join("");
  return `
  <div class="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
    <aside id="sidebar" class="fixed inset-y-0 left-0 z-40 w-[248px] -translate-x-full border-r border-line bg-ink-1 transition-transform lg:static lg:translate-x-0 flex flex-col">
      <a href="#/dashboard" class="flex items-center gap-2.5 px-5 h-16 border-b border-line no-underline hover:no-underline">
        <img src="/favicon.svg" alt="" class="h-7 w-7">
        <span class="font-display text-[18px] font-semibold text-mist">Q-MigrateAI</span>
      </a>
      <nav class="flex-1 overflow-y-auto px-3 pb-4" aria-label="Main">${nav}</nav>
      <div class="border-t border-line p-4 text-[12.5px] text-fog">
        <p class="truncate text-mist">${esc(me.tenant.name)}</p>
        <p>Data stored in the ${esc(me.tenant.data_region)}</p>
      </div>
    </aside>
    <div class="min-w-0">
      <header class="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-ink-0/90 px-4 backdrop-blur lg:px-8">
        <button class="btn btn-quiet lg:hidden" data-menu aria-label="Open menu">${icon("menu")}</button>
        <h1 id="page-title" class="text-[19px] font-semibold"></h1>
        ${me.tenant.is_demo ? `<span class="chip border-lattice/50 text-lattice" title="This company uses synthetic demo data">Demo data</span>` : ""}
        <div class="ml-auto flex items-center gap-2">
          <div class="hidden text-right sm:block">
            <p class="text-[13.5px] leading-tight">${esc(me.user.name)}</p>
            <p class="text-[12px] leading-tight text-fog">${esc(me.user.role.toUpperCase() === "CISO" ? "CISO" : me.user.role[0].toUpperCase() + me.user.role.slice(1))}</p>
          </div>
          <button class="btn btn-quiet" data-logout title="Log out" aria-label="Log out">${icon("logout")}</button>
        </div>
      </header>
      ${me.user.must_change_password ? `<div class="border-b border-risk-medium/40 bg-risk-medium/10 px-8 py-2 text-[13.5px] text-risk-medium">You are using a temporary password. <a href="#/settings">Choose your own password</a>.</div>` : ""}
      <main id="page" class="mx-auto max-w-[1400px] px-4 py-6 lg:px-8"></main>
    </div>
  </div>`;
}

function mountShell(): void {
  const app = $("#app")!;
  app.innerHTML = shell();
  shellMounted = true;
  $("[data-logout]")!.addEventListener("click", async () => {
    await post("/auth/logout").catch(() => undefined);
    state.me = null;
    shellMounted = false;
    go("/login");
  });
  $("[data-menu]")!.addEventListener("click", (e) => { e.stopPropagation(); $("#sidebar")!.classList.toggle("-translate-x-full"); });
  // On small screens, a tap outside the open menu closes it (listener added once; #app itself is never replaced).
  if (!menuCloser) $("#app")!.addEventListener("click", (e) => {
    const side = $("#sidebar");
    if (side && !side.classList.contains("-translate-x-full") && !side.contains(e.target as Node)) side.classList.add("-translate-x-full");
  });
  menuCloser = true;
  mountAssistant();
  refreshUnread();
}

let routeSeq = 0;

// Each navigation renders into a fresh container. If the person navigates again before a slow page
// finishes loading, the old page keeps writing into its detached container and never overwrites the new one.
async function settle(seq: number, render: Promise<Cleanup>): Promise<void> {
  const c = await render;
  if (seq !== routeSeq) { if (typeof c === "function") c(); return; }
  cleanup = c;
}

async function route(): Promise<void> {
  const seq = ++routeSeq;
  const { name, params } = parseHash();
  const page = routes[name] ?? routes.dashboard;
  if (typeof cleanup === "function") cleanup();
  cleanup = undefined;
  document.title = `${page.title} · Q-MigrateAI`;
  if (page.public) {
    shellMounted = false;
    $("#assistant")?.remove();
    const el = document.createElement("div");
    $("#app")!.replaceChildren(el);
    await settle(seq, page.render(el, params));
    return;
  }
  if (!state.me && !(await loadMe())) {
    go("/login");
    return;
  }
  if (seq !== routeSeq) return;
  if (!shellMounted) mountShell();
  if (page.perm && !can(page.perm)) {
    go("/dashboard");
    return;
  }
  $("#page-title")!.textContent = page.title;
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
  $("#sidebar")!.classList.add("-translate-x-full");
  const el = document.createElement("div");
  el.innerHTML = `<div class="space-y-4"><div class="skeleton h-28"></div><div class="skeleton h-64"></div></div>`;
  $("#page")!.replaceChildren(el);
  try {
    await settle(seq, page.render(el, params));
  } catch (err: any) {
    el.innerHTML = `<div class="panel panel-pad border-risk-critical/50" role="alert">${esc(err?.message ?? "Something went wrong.")}</div>`;
  }
}

async function boot(): Promise<void> {
  setUnauthorizedHandler(() => {
    if (state.me) toast("Your session ended. Please log in again.", "info");
    state.me = null;
    shellMounted = false;
    go("/login");
  });
  try {
    state.config = await api<PublicConfig>("/public/config");
    setPrivacyContact(state.config.privacy_contact);
  } catch {
    state.config = null;
  }
  window.addEventListener("hashchange", () => { void route(); });
  // Pages fire this after a change to the signed-in user (password, two-factor) so the shell redraws.
  window.addEventListener("qm:remount", () => { shellMounted = false; void route(); });
  await route();
}

void boot();
