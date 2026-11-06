// Public privacy policy. A template that must be reviewed by a lawyer before real customers use the service.
import { state } from "../state.js";
import { esc } from "../ui.js";

export async function privacyPage(el: HTMLElement): Promise<void> {
  const contact = state.config?.privacy_contact ?? "privacy@awhlle.com";
  const back = state.me ? "#/dashboard" : "#/login";
  const mail = `<a href="mailto:${esc(contact)}">${esc(contact)}</a>`;
  const sections: [string, string][] = [
    ["Who we are", `<p>Q-MigrateAI is operated by AWHLLE ("we"), the data controller for account data and the data processor for the
      cryptographic metadata a customer connects. For any privacy question, write to ${mail}.</p>`],
    ["What we collect", `<ul>
      <li><strong>Cryptographic metadata</strong> from the cloud accounts you connect: key types and sizes, algorithms, certificate details,
        TLS settings, service names and how services depend on each other.</li>
      <li><strong>Account data</strong>: your company name, the names, work e-mail addresses and roles of your users, login times and IP addresses.</li>
      <li><strong>Activity data</strong>: migrations, alerts and an audit log of actions in the app.</li></ul>
      <p>We never read files, databases, messages, customer records, secrets or private keys. Cloud access is read-only.</p>`],
    ["Why we use it, and on what legal basis", `<ul>
      <li>To provide the service you signed up for: discovery, risk scoring, migration planning and reports (contract, GDPR Art. 6(1)(b)).</li>
      <li>To keep the service secure, for example the audit log and login protection (legitimate interest, Art. 6(1)(f)).</li>
      <li>To meet legal obligations such as invoicing (Art. 6(1)(c)).</li></ul>
      <p>We do not sell data, show advertising or use your data to train models for other customers. Each company's models are trained only on its own data.</p>`],
    ["Where it is stored", `<p>Data is hosted in the European Union (Hetzner Online, data centres in Germany or Finland) and encrypted in transit (TLS)
      and at rest. Each company's data is isolated at database level. We do not transfer data outside the EU/EEA.</p>`],
    ["Who can see it", `<p>Only the users your admin adds to your company account, and a small number of our staff when needed for support or security,
      under confidentiality. Our hosting provider acts as a sub-processor under a data processing agreement. Data is never shared with other customers or third parties.</p>`],
    ["How long we keep it", `<p>For as long as your account is active. When an admin deletes the company account, all of its data is deleted at once;
      encrypted backups are overwritten within 14 days.</p>`],
    ["Your rights", `<p>You can access, correct, export or delete your data, object to or restrict its use, and withdraw consent at any time.
      Admins can export all company data or delete it from Settings, Privacy and data. Anyone can write to ${mail}; we answer within one month.
      You also have the right to complain to the French data protection authority, the CNIL (<a href="https://www.cnil.fr" rel="noopener" target="_blank">cnil.fr</a>), or the authority where you live.</p>`],
    ["Cookies", `<p>We use one strictly necessary cookie to keep you signed in. It is HttpOnly, sent only to this site, and deleted when you log out.
      There are no analytics, advertising or tracking cookies.</p>`],
    ["Security", `<p>Passwords are stored as scrypt hashes, two-factor authentication is available for every user, sessions expire,
      and every sensitive action is written to the audit log.</p>`],
    ["Changes to this policy", `<p>If we change this policy we will update the date below and tell admins by e-mail before the change takes effect.</p>`],
  ];
  el.innerHTML = `
  <div class="lattice-bg min-h-screen px-4 py-10">
    <article class="mx-auto max-w-[720px]">
      <a href="${back}" class="text-[14px]">Back to Q-MigrateAI</a>
      <h1 class="mt-6 font-display text-[34px] font-semibold leading-tight">Privacy policy</h1>
      <p class="mt-3 rounded-lg border border-risk-medium/50 bg-risk-medium/10 p-3 text-[14px] text-risk-medium">
        Template, to be reviewed by a lawyer before the service is offered to real customers.</p>
      <p class="mt-3 text-[13.5px] text-fog">Last updated 31 October 2026</p>
      <div class="policy mt-8 space-y-8 text-[15px] leading-relaxed">
        ${sections.map(([h, body]) => `<section><h2 class="text-[19px] font-semibold text-mist">${esc(h)}</h2><div class="mt-2 space-y-3 text-mist/90">${body}</div></section>`).join("")}
      </div>
    </article>
  </div>`;
}
