/** The wire contract, mirrored from `src/axial/service/api.py`.
 *
 * Every field below is one of that module's pydantic models. Nothing is
 * invented here and nothing is derived: this client posts an ask, reads a job
 * row, and renders what comes back.
 *
 * Requests go to `/api/...` on this origin and Next rewrites them onto the
 * service (`next.config.ts`, `AXIAL_API_BASE`). Same-origin on purpose: the
 * FastAPI app installs no CORS middleware, and a rewrite also means the API's
 * address is a deployment setting rather than something baked into the
 * browser bundle at build time.
 */

export const API_BASE = "/api";

/** `AskRequest`. `weights` is the analyst's own instruction and is never
 * inferred (DEC-61). `session_id` is this browser's session
 * (`src/lib/session.ts`) -- never a value read back off a served record,
 * which on a cache hit belongs to whoever asked first (#686). */
export interface AskRequest {
  case: string;
  request: string;
  weights?: Record<string, number> | null;
  lens?: string | null;
  session_id?: string | null;
}

/** `AskAccepted` -- the 202 from `POST /asks`. */
export interface AskAccepted {
  id: string;
  state: string;
}

/** `AskStatus` -- one job row. `cached` is true when the worker served the
 * paper from the content-keyed cache and the ask cost nothing. */
export interface AskStatus {
  id: string;
  state: string;
  corpus_pin: string | null;
  cached: boolean;
  created_at: string;
  claimed_at: string | null;
  finished_at: string | null;
  result_ref: string | null;
  error: string | null;
}

/** `UsageWindow`. `cost_usd`/`tokens` are null-preserving: unknown is never
 * rendered as a zero. `asks_made` counts every ask, `asks_charged` excludes a
 * cache hit. #746 renders these; the shapes live here with the rest. */
export interface UsageWindow {
  cost_usd: number | null;
  tokens: number | null;
  asks_made: number;
  asks_charged: number;
}

/** `QuotaWindowStatus`. */
export interface QuotaWindowStatus {
  limit: number;
  used: number;
  reset_at: string;
}

/** `UsageResponse` -- `GET /me/usage`. */
export interface UsageResponse {
  principal: string;
  session: UsageWindow | null;
  month_to_date: UsageWindow;
  quota: Record<string, QuotaWindowStatus>;
}

/** A refusal from the service. `message` is what to show: on a `429` the
 * service already words it for an academic to read, so it is rendered
 * verbatim rather than replaced with wording of our own. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function messageFor(response: Response): Promise<string> {
  let detail: unknown;
  try {
    detail = (await response.json())?.detail;
  } catch {
    detail = undefined;
  }
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  return `The service refused the request (HTTP ${response.status}).`;
}

async function expectOk(response: Response): Promise<Response> {
  if (!response.ok) throw new ApiError(response.status, await messageFor(response));
  return response;
}

export async function submitAsk(ask: AskRequest, signal?: AbortSignal): Promise<AskAccepted> {
  const response = await fetch(`${API_BASE}/asks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ask),
    signal,
  });
  return (await expectOk(response)).json();
}

export async function getAsk(id: string, signal?: AbortSignal): Promise<AskStatus> {
  const response = await fetch(`${API_BASE}/asks/${encodeURIComponent(id)}`, { signal });
  return (await expectOk(response)).json();
}

/** Open the event stream, resuming after `lastSeq` when reconnecting.
 * `Last-Event-ID` is SSE's own reconnect header and the service honours it,
 * so a resume misses nothing and repeats nothing. */
export async function openEventStream(
  id: string,
  lastSeq: number,
  signal?: AbortSignal,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (lastSeq > 0) headers["Last-Event-ID"] = String(lastSeq);
  const response = await fetch(`${API_BASE}/asks/${encodeURIComponent(id)}/events`, {
    headers,
    signal,
  });
  return expectOk(response);
}
