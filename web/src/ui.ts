// Small UI toolkit: escaping, formatting, toasts, modals, badges, icons and the GDPR notice.

export function esc(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export const $ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) =>
  root.querySelector(sel) as T | null;
export const $$ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) =>
  Array.from(root.querySelectorAll(sel)) as T[];

export const num = (n: number | null | undefined) => (n == null ? "–" : Number(n).toLocaleString("en-GB"));
export const pct = (n: number | null | undefined, digits = 1) => (n == null ? "n/a" : `${Number(n).toFixed(digits)}%`);
export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export const RISK: Record<string, { color: string; text: string; label: string }> = {
  Critical: { color: "#F0504A", text: "text-risk-critical", label: "Critical" },
  High: { color: "#F58A34", text: "text-risk-high", label: "High" },
  Medium: { color: "#E9C440", text: "text-risk-medium", label: "Medium" },
  Low: { color: "#3CCB7F", text: "text-risk-safe", label: "Low" },
};
export const RISK_ORDER = ["Critical", "High", "Medium", "Low"];

export function riskBadge(cls: string): string {
  const r = RISK[cls] ?? RISK.Low;
  return `<span class="chip border-transparent" style="background:${r.color}1f;color:${r.color}">
    <span class="h-2 w-2 rounded-full" style="background:${r.color}"></span>${esc(r.label)}</span>`;
}

export function statusBadge(row: { quantum_safe?: boolean; quantum_exposed?: boolean }): string {
  if (row.quantum_safe) return `<span class="chip border-risk-safe/40 text-risk-safe">Quantum-safe</span>`;
  if (row.quantum_exposed) return `<span class="chip border-risk-critical/40 text-risk-critical">Quantum-exposed</span>`;
  return `<span class="chip border-risk-medium/40 text-risk-medium">Review</span>`;
}

// Tiny, safe Markdown subset for assistant answers: **bold**, "- " lists, "1. " lists, line breaks.
export function md(text: string): string {
  const lines = esc(text).split("\n");
  let out = "";
  let list: "ul" | "ol" | null = null;
  const close = () => { if (list) { out += `</${list}>`; list = null; } };
  for (const raw of lines) {
    const line = raw.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    const bullet = line.match(/^- (.*)/);
    const numbered = line.match(/^\d+\. (.*)/);
    if (bullet) {
      if (list !== "ul") { close(); out += `<ul class="list-disc pl-5 space-y-1">`; list = "ul"; }
      out += `<li>${bullet[1]}</li>`;
    } else if (numbered) {
      if (list !== "ol") { close(); out += `<ol class="list-decimal pl-5 space-y-1">`; list = "ol"; }
      out += `<li>${numbered[1]}</li>`;
    } else {
      close();
      out += line.trim() ? `<p>${line}</p>` : "";
    }
  }
  close();
  return out;
}

export function toast(message: string, kind: "ok" | "error" | "info" = "info"): void {
  const root = document.getElementById("toasts");
  if (!root) return;
  const el = document.createElement("div");
  const tone = kind === "error" ? "border-risk-critical/60" : kind === "ok" ? "border-risk-safe/60" : "border-line";
  el.className = `pointer-events-auto panel ${tone} px-4 py-2.5 text-[14px] shadow-lg max-w-[90vw]`;
  el.setAttribute("role", kind === "error" ? "alert" : "status");
  el.textContent = message;
  root.appendChild(el);
  while (root.children.length > 3) root.firstElementChild?.remove();
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 3500);
}

export function modal(title: string, body: string, actions = `<button class="btn" data-close>Close</button>`): {
  el: HTMLElement; close: () => void;
} {
  const root = document.getElementById("modal-root")!;
  const wrap = document.createElement("div");
  wrap.className = "fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4";
  wrap.innerHTML = `<div role="dialog" aria-modal="true" aria-labelledby="modal-title"
      class="panel w-full max-w-lg max-h-[90vh] overflow-auto p-6">
      <h2 id="modal-title" class="mb-3">${esc(title)}</h2>
      <div class="text-[14px] leading-relaxed">${body}</div>
      <div class="mt-5 flex justify-end gap-2">${actions}</div></div>`;
  const prev = document.activeElement as HTMLElement | null;
  const close = () => { wrap.remove(); document.removeEventListener("keydown", onKey); prev?.focus(); };
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
  wrap.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    if (t === wrap || t.closest("[data-close]")) close();
  });
  document.addEventListener("keydown", onKey);
  root.appendChild(wrap);
  (wrap.querySelector("button, input, select, textarea") as HTMLElement | null)?.focus();
  return { el: wrap, close };
}

export function confirmDialog(title: string, body: string, confirmLabel: string, danger = false): Promise<boolean> {
  return new Promise((resolve) => {
    const m = modal(title, body,
      `<button class="btn" data-close>Cancel</button>
       <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-ok>${esc(confirmLabel)}</button>`);
    let done = false;
    m.el.querySelector("[data-ok]")!.addEventListener("click", () => { done = true; m.close(); resolve(true); });
    const obs = new MutationObserver(() => { if (!document.body.contains(m.el)) { obs.disconnect(); if (!done) resolve(false); } });
    obs.observe(document.getElementById("modal-root")!, { childList: true });
  });
}

// ---------------------------------------------------------------- GDPR notice
let privacyContact = "privacy@awhlle.com";
export function setPrivacyContact(email: string): void { privacyContact = email; }

export function gdprButton(extraClass = ""): string {
  return `<button type="button" data-gdpr class="inline-flex h-6 w-6 items-center justify-center rounded-full border border-line
    text-[13px] font-semibold text-fog hover:text-mist hover:border-lattice ${extraClass}"
    aria-label="Your data and GDPR" title="Your data and GDPR">i</button>`;
}

export function openGdpr(): void {
  modal("Your data and GDPR", `
    <ul class="space-y-2.5">
      <li>We only read cryptographic metadata (key types, algorithms, certificates), never your files or customer data.</li>
      <li>Access is read-only and can be removed at any time.</li>
      <li>Data is stored in the EU and encrypted.</li>
      <li>Never shared with other customers or third parties.</li>
      <li>You can export or delete all your data at any time.</li>
      <li>Contact: <a href="mailto:${esc(privacyContact)}">${esc(privacyContact)}</a></li>
    </ul>
    <p class="mt-4 muted text-[13px]">Read the full <a href="#/privacy" data-close>privacy policy</a>.</p>`);
}

document.addEventListener("click", (e) => {
  if ((e.target as HTMLElement).closest("[data-gdpr]")) openGdpr();
});

// ---------------------------------------------------------------------- icons
const ICONS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z",
  plug: "M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4",
  graph: "M5 6a2 2 0 1 0 0 .1M19 6a2 2 0 1 0 0 .1M12 19a2 2 0 1 0 0 .1M6.5 7.5l4.5 9.5M17.5 7.5 13 17M7 6h10",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  brain: "M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 5 3 3 0 0 0 3 4 3 3 0 0 0 5 1V5a3 3 0 0 0-3-1zM15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 5 3 3 0 0 1-3 4 3 3 0 0 1-5 1",
  route: "M4 19h4a4 4 0 0 0 0-8H8a4 4 0 0 1 0-8h12M18 1l3 2-3 2",
  flask: "M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7.5 14h9",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4",
  scroll: "M6 4h11a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H7M6 4a2 2 0 0 0-2 2v2h4M6 4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2M11 9h5M11 13h5",
  cog: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  chat: "M4 5h16v11H9l-5 4z",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "M6 6l12 12M18 6 6 18",
  shield: "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z",
};

export function icon(name: string, cls = "h-[18px] w-[18px]"): string {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICONS[name] ?? ""}"/></svg>`;
}

export function emptyState(title: string, body: string, action = ""): string {
  return `<div class="panel panel-pad text-center py-12">
    <h2 class="mb-2">${esc(title)}</h2><p class="muted max-w-md mx-auto">${body}</p>
    ${action ? `<div class="mt-5">${action}</div>` : ""}</div>`;
}

export function errorBox(message: string): string {
  return `<div class="panel panel-pad border-risk-critical/50 text-risk-critical" role="alert">${esc(message)}</div>`;
}

export function downloadText(filename: string, text: string, type = "text/csv"): void {
  const blob = new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function animateNumber(el: HTMLElement, to: number, decimals = 0, ms = 500, suffix = ""): void {
  const from = Number(el.dataset.value ?? el.textContent?.replace(/[^\d.-]/g, "") ?? 0) || 0;
  el.dataset.value = String(to);
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || from === to) { el.textContent = to.toFixed(decimals) + suffix; return; }
  const t0 = performance.now();
  const step = (t: number) => {
    const k = Math.min(1, (t - t0) / ms);
    const v = from + (to - from) * (1 - Math.pow(1 - k, 3));
    el.textContent = v.toFixed(decimals) + suffix;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
