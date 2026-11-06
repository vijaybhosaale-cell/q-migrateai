// Thin wrapper around the platform API. Every state-changing request carries the
// X-QM-Request header, which the server requires as CSRF protection.
export class ApiError extends Error {
    constructor(status, message) {
        super(message);
        this.status = status;
    }
}
let onUnauthorized = () => { };
export function setUnauthorizedHandler(fn) {
    onUnauthorized = fn;
}
export async function api(path, opts = {}) {
    const method = opts.method ?? (opts.body !== undefined ? "POST" : "GET");
    const res = await fetch("/api" + path, {
        method,
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-QM-Request": "1" },
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
    let data = null;
    const text = await res.text();
    try {
        data = text ? JSON.parse(text) : null;
    }
    catch {
        data = { detail: text };
    }
    if (!res.ok) {
        const detail = typeof data?.detail === "string" ? data.detail : `Request failed (${res.status}).`;
        if (res.status === 401 && !path.startsWith("/auth/"))
            onUnauthorized();
        throw new ApiError(res.status, detail);
    }
    return data;
}
export const post = (path, body = {}) => api(path, { method: "POST", body });
export const put = (path, body) => api(path, { method: "PUT", body });
export const patch = (path, body) => api(path, { method: "PATCH", body });
export const del = (path) => api(path, { method: "DELETE" });
