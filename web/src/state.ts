// Session state shared by all pages.

export type Me = {
  user: { id: string; email: string; name: string; role: string; totp_enabled: boolean; must_change_password: boolean };
  tenant: { id: string; name: string; is_demo: boolean; data_region: string };
  permissions: string[];
  roles: string[];
};

export type PublicConfig = {
  allow_signup: boolean;
  privacy_contact: string;
  demo_accounts: { company: string; logins: string[] }[];
  demo_password: string | null;
  version: string;
};

import { api } from "./api.js";

export const state: { me: Me | null; config: PublicConfig | null; unread: number } = { me: null, config: null, unread: 0 };

export const can = (perm: string): boolean => !!state.me?.permissions.includes(perm);

export function go(path: string): void {
  if (location.hash === "#" + path) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = path;
}

export async function loadMe(): Promise<Me | null> {
  try {
    state.me = await api<Me>("/auth/me");
  } catch {
    state.me = null;
  }
  return state.me;
}

export async function refreshUnread(): Promise<void> {
  try {
    const ov = await api("/overview");
    state.unread = ov.unread_alerts ?? 0;
  } catch {
    return;
  }
  const el = document.querySelector<HTMLElement>("[data-unread]");
  if (el) {
    el.textContent = String(state.unread);
    el.classList.toggle("hidden", state.unread === 0);
  }
}
