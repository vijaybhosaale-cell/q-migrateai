// Log in, sign up (with GDPR consent) and the two-factor step.
import { api, post } from "../api.js";
import { state, go, loadMe } from "../state.js";
import { $, esc, gdprButton, modal } from "../ui.js";

function frame(inner: string): string {
  return `<div class="min-h-screen grid lg:grid-cols-[1.05fr_1fr]">
    <section class="relative hidden lg:flex flex-col justify-between overflow-hidden border-r border-line bg-ink-1 p-12 lattice-bg">
      <div class="flex items-center gap-3">
        <img src="/favicon.svg" alt="" class="h-9 w-9"><span class="font-display text-[22px] font-semibold">Q-MigrateAI</span>
      </div>
      <div class="max-w-[30rem]">
        <p class="font-display text-[40px] font-semibold leading-[1.08] tracking-[-0.02em]">Find the keys a quantum computer would break first.</p>
        <p class="mt-5 text-[16px] text-fog leading-relaxed">Q-MigrateAI maps every key, certificate and TLS endpoint across AWS, Azure and GCP,
          ranks them with AI, and moves them to NIST post-quantum algorithms with a rollback for every change.</p>
      </div>
      <p class="text-[13px] text-fog">ML-KEM (FIPS 203), ML-DSA (FIPS 204) and SLH-DSA (FIPS 205). Read-only access to your clouds.</p>
    </section>
    <section class="flex items-center justify-center p-6 sm:p-10">${inner}</section>
  </div>`;
}

export async function loginPage(el: HTMLElement): Promise<void> {
  if (await loadMe()) { go("/dashboard"); return; }
  const cfg = state.config;
  const demo = cfg?.demo_accounts?.length ? `
    <div class="mt-6 rounded-xl border border-line p-4">
      <p class="text-[13.5px] font-medium">Demo accounts</p>
      <p class="text-[12.5px] text-fog mb-3">Fictional companies show that each customer only sees its own data. Password: <span class="id text-mist">${esc(cfg.demo_password ?? "")}</span></p>
      ${cfg.demo_accounts.map((t) => `<p class="text-[12.5px] text-fog mt-2 mb-1">${esc(t.company)}</p>
        <div class="flex flex-wrap gap-1.5">${t.logins.map((l) => `<button type="button" class="chip border-line text-mist hover:border-lattice" data-demo="${esc(l)}">${esc(l.split("@")[0])}</button>`).join("")}</div>`).join("")}
    </div>` : "";
  el.innerHTML = frame(`
    <form class="w-full max-w-sm" novalidate>
      <div class="flex items-center gap-2 mb-1"><h1>Log in</h1>${gdprButton()}</div>
      <p class="muted mb-6">Use your work e-mail.</p>
      <label class="label" for="email">E-mail</label>
      <input id="email" name="email" type="email" autocomplete="username" class="input mb-4" required>
      <label class="label" for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" class="input mb-2" required>
      <p data-error class="hidden text-[13.5px] text-risk-critical mb-2" role="alert"></p>
      <button class="btn btn-primary w-full mt-3" type="submit">Log in</button>
      <button class="btn w-full mt-3" type="button" data-ms>
        <svg viewBox="0 0 20 20" class="h-4 w-4" aria-hidden="true"><path fill="#F25022" d="M1 1h8.5v8.5H1z"/><path fill="#7FBA00" d="M10.5 1H19v8.5h-8.5z"/><path fill="#00A4EF" d="M1 10.5h8.5V19H1z"/><path fill="#FFB900" d="M10.5 10.5H19V19h-8.5z"/></svg>
        Log in with Microsoft</button>
      ${cfg?.allow_signup ? `<p class="mt-6 text-[14px] text-fog">New company? <a href="#/signup">Create an account</a></p>` : ""}
      <p class="mt-2 text-[13px]"><a href="#/privacy">Privacy policy</a></p>
      ${demo}
    </form>`);
  const form = $<HTMLFormElement>("form", el)!;
  const err = $("[data-error]", el)!;
  form.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>("[data-demo]");
    if (b) {
      ($<HTMLInputElement>("#email", el)!).value = b.dataset.demo!;
      ($<HTMLInputElement>("#password", el)!).value = cfg?.demo_password ?? "";
    }
  });
  $("[data-ms]", el)!.addEventListener("click", async () => {
    let detail = "Login with Microsoft is not configured yet.";
    try { await api("/auth/microsoft"); } catch (e: any) { detail = e.message; }
    modal("Log in with Microsoft", `<p>${esc(detail)}</p><p class="mt-3 muted">When it is switched on, your company's Microsoft Entra ID will
      handle the login (OpenID Connect) and Q-MigrateAI will receive only your name and e-mail.</p>`);
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.classList.add("hidden");
    const btn = $<HTMLButtonElement>("button[type=submit]", form)!;
    btn.disabled = true;
    try {
      const r = await post("/auth/login", { email: ($<HTMLInputElement>("#email", el)!).value, password: ($<HTMLInputElement>("#password", el)!).value });
      if (r.mfa_required) { go("/login-2fa"); return; }
      await loadMe();
      go("/dashboard");
    } catch (ex: any) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
    } finally {
      btn.disabled = false;
    }
  });
}

export async function twoFactorPage(el: HTMLElement): Promise<void> {
  el.innerHTML = frame(`
    <form class="w-full max-w-sm" novalidate>
      <h1 class="mb-1">Two-factor check</h1>
      <p class="muted mb-6">Enter the 6-digit code from your authenticator app.</p>
      <label class="label" for="code">Code</label>
      <input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" class="input mb-2 tabular text-[20px] tracking-[0.3em]" required>
      <p data-error class="hidden text-[13.5px] text-risk-critical mb-2" role="alert"></p>
      <button class="btn btn-primary w-full mt-3" type="submit">Verify and continue</button>
      <p class="mt-5 text-[14px]"><a href="#/login">Back to log in</a></p>
    </form>`);
  const input = $<HTMLInputElement>("#code", el)!;
  input.focus();
  $("form", el)!.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("[data-error]", el)!;
    try {
      await post("/auth/login/2fa", { code: input.value });
      await loadMe();
      go("/dashboard");
    } catch (ex: any) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
    }
  });
}

export async function signupPage(el: HTMLElement): Promise<void> {
  el.innerHTML = frame(`
    <form class="w-full max-w-sm" novalidate>
      <div class="flex items-center gap-2 mb-1"><h1>Create your company account</h1>${gdprButton()}</div>
      <p class="muted mb-6">You become the administrator. You can invite your team afterwards.</p>
      <label class="label" for="company">Company name</label>
      <input id="company" class="input mb-4" autocomplete="organization" required>
      <label class="label" for="name">Your name</label>
      <input id="name" class="input mb-4" autocomplete="name" required>
      <label class="label" for="email">Work e-mail</label>
      <input id="email" type="email" class="input mb-4" autocomplete="email" required>
      <label class="label" for="password">Password</label>
      <input id="password" type="password" class="input mb-1" autocomplete="new-password" required>
      <p class="text-[12.5px] text-fog mb-4">At least 10 characters, with upper- and lower-case letters and a digit.</p>
      <label class="flex items-start gap-2.5 text-[13.5px] mb-2">
        <input id="consent" type="checkbox" class="mt-1 h-4 w-4 accent-[#9B8CFF]">
        <span>I agree that Q-MigrateAI stores my account details and my company's cryptographic metadata as described in the
          <a href="#/privacy">privacy policy</a>.</span></label>
      <p data-error class="hidden text-[13.5px] text-risk-critical mb-2" role="alert"></p>
      <button class="btn btn-primary w-full mt-3" type="submit">Create account</button>
      <p class="mt-5 text-[14px] text-fog">Already have an account? <a href="#/login">Log in</a></p>
    </form>`);
  $("form", el)!.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("[data-error]", el)!;
    const v = (id: string) => ($<HTMLInputElement>("#" + id, el)!).value;
    const consent = ($<HTMLInputElement>("#consent", el)!).checked;
    if (!consent) {
      err.textContent = "Please accept the privacy notice to create an account.";
      err.classList.remove("hidden");
      return;
    }
    try {
      await post("/auth/signup", { company: v("company"), name: v("name"), email: v("email"), password: v("password"), consent });
      await loadMe();
      go("/connect?welcome=1");
    } catch (ex: any) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
    }
  });
}
