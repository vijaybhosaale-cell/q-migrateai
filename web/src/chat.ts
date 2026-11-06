// AI assistant side panel. Answers come from /api/assistant, which builds them from the
// platform's own explanation, plan, what-if and readiness data.
import { post } from "./api.js";
import { go } from "./state.js";
import { $, esc, icon, md } from "./ui.js";

const STARTERS = ["Why is the riskiest asset critical?", "What should we migrate first?", "What if we migrate the top 10?",
  "What is our NIST readiness?", "What is ML-KEM?"];

export function mountAssistant(): void {
  if ($("#assistant")) return;
  const root = document.createElement("div");
  root.id = "assistant";
  root.innerHTML = `
    <button data-open class="btn btn-primary fixed bottom-5 right-5 z-40 rounded-full px-4 py-2.5 shadow-lg" aria-expanded="false" aria-controls="assistant-panel">
      ${icon("chat")}<span>Ask the assistant</span></button>
    <section id="assistant-panel" class="hidden fixed bottom-0 right-0 z-50 flex h-[min(620px,100vh)] w-full flex-col border border-line bg-ink-1 sm:bottom-5 sm:right-5 sm:w-[400px] sm:rounded-[14px]"
      aria-label="AI assistant">
      <header class="flex items-center gap-2 border-b border-line px-4 py-3">
        <div><h2 class="text-[15px]">Assistant</h2><p class="text-[12px] text-fog">Answers from your own inventory, never invented</p></div>
        <button data-close class="btn btn-quiet ml-auto" aria-label="Close assistant">${icon("close")}</button>
      </header>
      <div data-log class="flex-1 space-y-3 overflow-y-auto p-4 text-[14px]">
        <div class="rounded-xl bg-ink-2 p-3">Ask me about any asset, the migration plan, what-if scenarios or post-quantum terms.</div>
        <div class="flex flex-wrap gap-2" data-starters>${STARTERS.map((s) => `<button class="chip border-line text-fog hover:text-mist" data-q="${esc(s)}">${esc(s)}</button>`).join("")}</div>
      </div>
      <form data-form class="flex gap-2 border-t border-line p-3">
        <label for="assistant-input" class="sr-only">Your question</label>
        <input id="assistant-input" class="input" maxlength="500" placeholder="For example: why is AWS-KMS-004 critical?" autocomplete="off">
        <button class="btn btn-primary" type="submit">Ask</button>
      </form>
    </section>`;
  document.body.appendChild(root);
  const panel = $("#assistant-panel")!;
  const open = $("[data-open]", root)!;
  const log = $("[data-log]", root)!;
  const input = $<HTMLInputElement>("#assistant-input")!;
  const toggle = (show: boolean) => {
    panel.classList.toggle("hidden", !show);
    open.classList.toggle("hidden", show);
    open.setAttribute("aria-expanded", String(show));
    if (show) input.focus();
  };
  open.addEventListener("click", () => toggle(true));
  $("[data-close]", root)!.addEventListener("click", () => toggle(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.classList.contains("hidden")) toggle(false); });

  const ask = async (q: string) => {
    if (!q.trim()) return;
    log.insertAdjacentHTML("beforeend", `<div class="ml-10 rounded-xl bg-lattice-soft p-3">${esc(q)}</div>`);
    const pending = document.createElement("div");
    pending.className = "rounded-xl bg-ink-2 p-3 text-fog";
    pending.textContent = "Looking at your inventory…";
    log.appendChild(pending);
    log.scrollTop = log.scrollHeight;
    try {
      const a = await post("/assistant", { message: q });
      pending.className = "rounded-xl bg-ink-2 p-3 space-y-2 leading-relaxed";
      pending.innerHTML = md(a.answer) +
        (a.references?.length ? `<div class="flex flex-wrap gap-1.5 pt-1">${a.references.map((r: string) =>
          `<button class="chip border-line id text-lattice" data-ref="${esc(r)}">${esc(r)}</button>`).join("")}</div>` : "") +
        (a.suggestions?.length ? `<div class="flex flex-wrap gap-1.5 pt-1">${a.suggestions.map((s: string) =>
          `<button class="chip border-line text-fog hover:text-mist" data-q="${esc(s)}">${esc(s)}</button>`).join("")}</div>` : "");
    } catch (err: any) {
      pending.className = "rounded-xl border border-risk-critical/50 p-3 text-risk-critical";
      pending.textContent = err.message;
    }
    log.scrollTop = log.scrollHeight;
  };
  $("[data-form]", root)!.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value;
    input.value = "";
    void ask(q);
  });
  log.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    const q = t.closest<HTMLElement>("[data-q]")?.dataset.q;
    const ref = t.closest<HTMLElement>("[data-ref]")?.dataset.ref;
    if (q) void ask(q);
    if (ref) { toggle(false); go(`/assets?focus=${encodeURIComponent(ref)}`); }
  });
}
