/**
 * Browser API client. Same-origin requests to /api/v1 (proxied to FastAPI),
 * httpOnly session cookies, double-submit CSRF header and a single
 * transparent refresh on 401.
 */

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
  /** Plan-gated feature (HTTP 402) - detail carries the required plan. */
  get upgrade(): { feature?: string; required_plan?: string; message?: string } | null {
    if (this.status !== 402) return null;
    const d = this.detail as { detail?: unknown } | undefined;
    return (d?.detail as { feature?: string; required_plan?: string; message?: string }) ?? null;
  }
}

const BASE = "/api/v1";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": readCookie("pf_csrf") ?? "" },
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        setTimeout(() => (refreshing = null), 0);
      });
  }
  return refreshing;
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  if (body && typeof body === "object" && "errors" in body) {
    const errs = (body as { errors: { field: string; message: string }[] }).errors;
    if (errs?.length) return errs.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join("; ");
  }
  return status === 0 ? "Network error - is the API running?" : `Request failed (${status})`;
}

export type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function buildQuery(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; retry?: boolean } = {},
): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = readCookie("pf_csrf") ?? "";
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${buildQuery(opts.query)}`, {
      method,
      headers,
      credentials: "include",
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, messageFrom(null, 0));
  }
  if (res.status === 401 && opts.retry !== false && !path.startsWith("/auth/")) {
    if (await tryRefresh()) return api<T>(path, { ...opts, retry: false });
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, messageFrom(body, res.status), body);
  return body as T;
}
