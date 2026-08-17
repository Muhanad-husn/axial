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
 *
 * **One fetch path** (issue #764): every call below goes through
 * `authorizedFetch`, which attaches `Authorization: Bearer <token>`
 * (`@/lib/auth`'s own seam) and, on a `401`, tells `useSession` the token is
 * no longer good for anything (`notifyUnauthorized`) -- so a token expiring
 * mid-walk surfaces as a sign-in prompt from whichever call noticed first,
 * never a silently-broken screen.
 */

import { getAccessToken, notifyUnauthorized } from "@/lib/auth";

export const API_BASE = "/api";

async function authorizedFetch(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<Response> {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, signal });
  if (response.status === 401) notifyUnauthorized();
  return response;
}

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
 * paper from the content-keyed cache and the ask cost nothing. `case`/
 * `question` (issue #759) are the brief that produced this row, read off
 * the job's own payload server-side -- present for every state, not just
 * `done`. */
export interface AskStatus {
  id: string;
  state: string;
  case: string | null;
  question: string | null;
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
  const response = await authorizedFetch(
    "/asks",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ask) },
    signal,
  );
  return (await expectOk(response)).json();
}

export async function getAsk(id: string, signal?: AbortSignal): Promise<AskStatus> {
  const response = await authorizedFetch(`/asks/${encodeURIComponent(id)}`, {}, signal);
  return (await expectOk(response)).json();
}

/** `GET /asks` -- every ask this caller has made, in the store's own order.
 * The service already filters on the identity seam (`current_principal`),
 * so this is this analyst's own list with nothing further to ask for. */
export async function listAsks(signal?: AbortSignal): Promise<AskStatus[]> {
  const response = await authorizedFetch("/asks", {}, signal);
  return (await expectOk(response)).json();
}

/** `GET /me/usage`. `sessionId` is this browser's own session
 * (`src/lib/session.ts`) -- omitted, the server sends no `session` window at
 * all, since it holds no notion of a "current" session (#724/#746). */
export async function getUsage(
  sessionId: string | null,
  signal?: AbortSignal,
): Promise<UsageResponse> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const response = await authorizedFetch(`/me/usage${query}`, {}, signal);
  return (await expectOk(response)).json();
}

/** `GET`/`PUT /me/profile` (issue #763) -- the caller's own theme.
 * `src/lib/theme.ts`'s `loadThemeChoice`/`saveThemeChoice` are the seam that
 * calls these; nothing else in the client reads or writes a profile. */
export interface ProfileResponse {
  theme: string;
}

export async function getProfile(signal?: AbortSignal): Promise<ProfileResponse> {
  const response = await authorizedFetch("/me/profile", {}, signal);
  return (await expectOk(response)).json();
}

export async function putProfile(theme: string, signal?: AbortSignal): Promise<ProfileResponse> {
  const response = await authorizedFetch(
    "/me/profile",
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ theme }) },
    signal,
  );
  return (await expectOk(response)).json();
}

/** `note_locator` (`axial.query.store`) plus, in `passage` citation mode
 * only, the resolved `quote` (`axial.service.citation`). Attached to a
 * `chunk` ground when it resolves; absent otherwise -- never a placeholder
 * full of nulls. The citation mode itself is a deployment setting this
 * client never sees or branches on (#690): whatever keys are present here
 * are whatever this deployment chose to send. */
export interface Citation {
  source_id: string;
  author: string | null;
  title: string | null;
  date: string | null;
  chapter: string | null;
  section: string | null;
  quote?: string;
  /** The citation as it reads on a page, formatted server-side by
   * `axial.cite.format_citation` (issue #783). One formatter for the
   * markdown renders and this client, so the same ground can never cite
   * two different ways in a download and on the screen. */
  display?: string;
}

/** One claim's evidence pointer (`axial.answer.record._claim_to_dict`).
 * `citation` is present only when the server resolved it. */
export interface Ground {
  ref_type: string;
  ref_id: string;
  citation?: Citation;
}

/** One §7.4 claim. `kind` is `"a"` (a source states it), `"b"` (Axial
 * concluded it across sources) or `"c"` (Axial's own judgment, past the
 * books) -- the marker text and accent for each live in `src/lib/paper.ts`,
 * a lookup table, never a decision made here. */
export interface Claim {
  claim_id: string;
  text: string;
  kind: string;
  grounds: Ground[];
  confidence: string | null;
  names_touched: string[];
}

export interface CoverageEntry {
  corpus_note_count: number | null;
  evidence_note_count: number;
  coverage_band: string;
}

export interface ConfidenceBlock {
  overall_band: string;
  rationale: string;
}

export interface CostByPass {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  usd: number | null;
}

export interface CostBlock {
  by_pass: Record<string, CostByPass>;
  total_usd: number | null;
}

/** The §7.3 analysis record, as `GET /asks/{id}/paper` serves it. This
 * client reads `brief`, `interrogation` and `claims` to render the paper;
 * every other key (`trajectory`, `source_usage`, `counter_position`, ...)
 * rides along untouched -- nothing here re-derives what the record already
 * states. */
export interface AnalysisRecord {
  brief_id: string;
  brief: { case: string; request: string };
  interrogation: { disposition: string; refusal?: { reason?: string } | null };
  claims: Claim[];
  [key: string]: unknown;
}

/** The metrics sibling (issue #724): exactly `cost`, `model_by_pass`,
 * `coverage_map`, `confidence` -- never merged into `record`, never
 * `retries` or a shape band, which this endpoint does not send. */
export interface Metrics {
  cost: CostBlock | null;
  model_by_pass: Record<string, string> | null;
  coverage_map: Record<string, CoverageEntry> | null;
  confidence: ConfidenceBlock | null;
}

export interface PaperResponse {
  record: AnalysisRecord;
  metrics: Metrics;
}

export async function getPaper(id: string, signal?: AbortSignal): Promise<PaperResponse> {
  const response = await authorizedFetch(`/asks/${encodeURIComponent(id)}/paper`, {}, signal);
  return (await expectOk(response)).json();
}

/** `GET /asks/{id}/export`'s three formats, verbatim. */
export const EXPORT_FORMATS = ["md", "docx", "odt"] as const;
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

export const EXPORT_FORMAT_LABELS: Record<ExportFormat, string> = {
  md: "Markdown (.md)",
  docx: "Word (.docx)",
  odt: "OpenDocument (.odt)",
};

/** The export route's own URL, for display/copy only (`ExportControl`'s
 * `href`) -- every route now requires a bearer token (issue #764), which a
 * plain navigated anchor can never carry, so the actual download goes
 * through `downloadExport` below instead. */
export function exportUrl(id: string, format: ExportFormat): string {
  return `${API_BASE}/asks/${encodeURIComponent(id)}/export?format=${format}`;
}

/** Fetch the export with the caller's own bearer token, then hand it to the
 * browser's download manager as a blob URL -- the server still does all the
 * rendering and sets `Content-Disposition`; this is the least mechanism that
 * can still attach `Authorization`, which a plain `<a href download>` cannot
 * (issue #764's own constraint, once every route requires a token). */
export async function downloadExport(
  id: string,
  format: ExportFormat,
  signal?: AbortSignal,
): Promise<void> {
  const response = await expectOk(
    await authorizedFetch(`/asks/${encodeURIComponent(id)}/export?format=${format}`, {}, signal),
  );
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${id}.${format}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
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
  const response = await authorizedFetch(`/asks/${encodeURIComponent(id)}/events`, { headers }, signal);
  return expectOk(response);
}
