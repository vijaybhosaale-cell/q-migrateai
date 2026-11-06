// Session state shared by all pages.
import { api } from "./api.js";
export const state = { me: null, config: null, unread: 0 };
export const can = (perm) => !!state.me?.permissions.includes(perm);
export function go(path) {
    if (location.hash === "#" + path)
        window.dispatchEvent(new HashChangeEvent("hashchange"));
    else
        location.hash = path;
}
export async function loadMe() {
    try {
        state.me = await api("/auth/me");
    }
    catch {
        state.me = null;
    }
    return state.me;
}
export async function refreshUnread() {
    try {
        const ov = await api("/overview");
        state.unread = ov.unread_alerts ?? 0;
    }
    catch {
        return;
    }
    const el = document.querySelector("[data-unread]");
    if (el) {
        el.textContent = String(state.unread);
        el.classList.toggle("hidden", state.unread === 0);
    }
}
