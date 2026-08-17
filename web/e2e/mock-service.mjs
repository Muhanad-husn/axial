/** A stand-in for `axial.service.api`, for the end-to-end spec only.
 *
 * It speaks the routes the app uses -- `POST /asks`, `GET /asks`, `GET
 * /asks/{id}`, `GET /asks/{id}/events`, `GET /asks/{id}/paper`, `GET
 * /asks/{id}/export`, `GET`/`PUT /me/profile`, `GET /me/usage` -- with the
 * same shapes and the same SSE framing (`id:` line, `{"message", "detail"}`
 * payload, stream closes at a terminal state). Four things it does
 * deliberately: it drops the first event connection halfway, so a resume
 * through `Last-Event-ID` is exercised for real; `POST /__kill` makes it
 * stop answering, which is what "the API died mid-ask" looks like from a
 * browser; `POST /__revive` brings it back WITHOUT clearing any job -- an
 * API restart loses no job state because the worker that runs the ask is a
 * separate process (issue #760), and this is the mock's stand-in for that;
 * and the case `quiet` holds the stream open and silent mid-ask, which is
 * what a real fourteen-minute ask looks like and the only way a buffering
 * hop between the browser and the service is visible at all.
 *
 * **The auth surface (issue #764):** every route below except `/__reset`,
 * `/__revive`, `/__health` and `/__kill` requires `Authorization: Bearer
 * <token>` and `401`s without one. The token's own `sub` claim is read
 * without a signature check -- verifying JWKS/RSA is `src/axial/service/
 * auth.py`'s job and is already proven there against a real key set (issue
 * #763); this mock only needs to know WHICH principal is asking, so it can
 * scope jobs and profiles the way the real service's `current_principal` +
 * `can_access` do. A job or profile another principal owns is invisible --
 * `GET /asks` filters to it, and a single-job route 404s exactly as
 * `_require_own_job` does, never leaking a name from an existence check.
 *
 * `/paper` renders one of two fixed §7.3 records, picked by the ask's own
 * `case` (`paperFor`) -- the default is shaped like `locator` citation mode
 * (no `citation.quote`), and the case `"Aleppo"` is shaped like `passage`
 * mode (`citation.quote` present on every resolved chunk ground). The real
 * mode is a deployment setting the client never sees or chooses (#690);
 * this mock picks a fixture by case only because it has no deployment
 * setting of its own to read -- the client under test is exercised against
 * both shapes exactly as it would be against two real deployments. A
 * cached job (`job.cached`) renders its cost as `0`, not the usual `0.13`
 * -- the real worker persists `cost_usd = 0.0` for a cache hit
 * (`axial.service.worker`), and issue #746's own bar is that this reads as
 * zero, not as unknown and not as a repeat charge.
 *
 * `/__reset` also seeds three fixed history rows (issue #746) so `GET
 * /asks` and reopening have something to show without driving a live ask
 * through the SSE flow first: a plain `done` row, a `cached` (free) one,
 * and a `failed` one carrying the service's own error text.
 */

import { createServer } from "node:http";

const PORT = Number(process.env.MOCK_PORT ?? 8099);

const MESSAGES = [
  "Interrogated the question against the corpus -- one fork resolved",
  "French Mandate -- 55 notes across 8 sources",
  "Walked the relations -- 48 notes retrieved from 5 books",
  "Checked every claim against the passage it rests on",
];

/** How long a `quiet` job says nothing between its second and third event.
 * Longer than the spec's patience for the early events, so an assertion that
 * they are on screen can only pass while the stream is still open and silent. */
const QUIET_MS = 10_000;

/** The signed-in principal `web/e2e/fixtures.ts` seeds by default for every
 * spec that doesn't ask for a different one -- must match its own
 * `DEFAULT_USER_ID`. The seeded history rows (`seedHistory` below) belong to
 * this principal, so the pre-existing specs (`ask.spec.ts`,
 * `history-usage.spec.ts`, `paper.spec.ts`) see exactly what they did before
 * this issue made every route require a token. */
const DEFAULT_USER_ID = "a0000000-0000-4000-8000-000000000001";

const jobs = new Map();
const profiles = new Map();
let nextId = 1;
let dead = false;
// Set by `POST /__expire` -- every bearer token is refused from that point
// on, regardless of whose `sub` it carries, standing in for a real token
// that expired mid-walk (issue #764's fourth "done when" bullet: the app
// must show a sign-in prompt, not a stuck screen).
let forceUnauthorized = false;
const openSockets = new Set();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The caller's own principal, read off the bearer token's `sub` claim with
 * no signature check (module docstring) -- `null` for a missing header or a
 * token this mock cannot even parse, both of which the real service also
 * refuses at its edge. */
function principalFor(req) {
  const header = req.headers.authorization;
  if (!header || !header.startsWith("Bearer ")) return null;
  const token = header.slice("Bearer ".length);
  const [, payloadPart] = token.split(".");
  if (!payloadPart) return null;
  try {
    const payload = JSON.parse(Buffer.from(payloadPart, "base64url").toString("utf8"));
    return typeof payload.sub === "string" && payload.sub.length > 0 ? payload.sub : null;
  } catch {
    return null;
  }
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => resolve(raw ? JSON.parse(raw) : {}));
  });
}

// One resolved-citation ground, in whichever mode `passageMode` asks for --
// `quote` only exists on the object at all in passage mode, mirroring how
// `axial.service.citation._resolve_chunk_citation` only ever adds the key
// in that mode rather than sending it `null` in the other.
function chunkGround(refId, { source_id, author, date, chapter, section, quote }, passageMode) {
  const citation = { source_id, author, title: null, date, chapter, section };
  // `display` is the citation as the server formatted it (`axial.cite.
  // format_citation`, issue #783). Both modes carry it; the client prints
  // it rather than composing a second version of the same string.
  citation.display = [author ? `${author} (${date})` : source_id, chapter, section]
    .filter(Boolean)
    .join(", ");
  if (passageMode) citation.quote = quote;
  return { ref_type: "chunk", ref_id: refId, citation };
}

function paperFor(job) {
  const passageMode = job.case === "Aleppo";
  const claims = [
    {
      claim_id: "c1",
      text:
        "Batatu records that Mandate recruitment into the Troupes Spéciales drew disproportionately from the Alawi highlands, and that the practice was administrative convenience before it was policy.",
      kind: "a",
      grounds: [
        chunkGround(
          "batatu-1999_08_troupes-speciales_003",
          {
            source_id: "batatu-1999",
            author: "Batatu",
            date: "1999",
            chapter: "8",
            section: "Troupes Spéciales recruitment",
            quote: "Recruitment followed administrative convenience, not a stated policy.",
          },
          passageMode,
        ),
      ],
      confidence: "high",
      names_touched: ["Troupes Spéciales"],
    },
    {
      claim_id: "c2",
      text:
        "Read together, Batatu and Vignal describe the same pattern but disagree on what it explains: one treats it as a residue the Ba'th inherited, the other as a structure it reproduced.",
      kind: "b",
      grounds: [
        chunkGround(
          "batatu-1999_08_troupes-speciales_004",
          { source_id: "batatu-1999", author: "Batatu", date: "1999", chapter: "8", section: null, quote: "A residue, not a design." },
          passageMode,
        ),
        chunkGround(
          "vignal-2022_03_state-formation_012",
          { source_id: "vignal-2022", author: "Vignal", date: "2022", chapter: "3", section: null, quote: "A structure the party reproduced deliberately." },
          passageMode,
        ),
        chunkGround(
          "hinnebusch-2001_05_continuity_002",
          { source_id: "hinnebusch-2001", author: "Hinnebusch", date: "2001", chapter: "5", section: null, quote: "The continuity is of outcome, not institution." },
          passageMode,
        ),
      ],
      confidence: "medium",
      names_touched: ["Ba'th Party"],
    },
    {
      claim_id: "c3",
      text:
        "Whether the same mechanism operated in the officer corps after 1963 is not settled by anything in this corpus.",
      kind: "c",
      grounds: [],
      confidence: "low",
      names_touched: [],
    },
  ];

  const record = {
    brief_id: job.id,
    brief: { case: job.case, request: job.request ?? "" },
    interrogation: { disposition: "answer" },
    claims,
  };

  // A cache hit made no model call, so its own record's cost reads as a
  // real zero -- never the fixture's usual $0.13, and never "unknown".
  const metrics = {
    cost: job.cached
      ? { by_pass: {}, total_usd: 0 }
      : {
          by_pass: {
            interrogate: { prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500, usd: 0.02 },
            retrieve: { prompt_tokens: 4000, completion_tokens: 900, total_tokens: 4900, usd: 0.06 },
            synthesize: { prompt_tokens: 3000, completion_tokens: 1100, total_tokens: 4100, usd: 0.05 },
          },
          total_usd: 0.13,
        },
    model_by_pass: {
      interrogate: "glm-5.2",
      retrieve: "glm-5.2",
      synthesize: "gpt-5.6-luna",
    },
    coverage_map: {
      "Ba'th Party": { corpus_note_count: 126, evidence_note_count: 3, coverage_band: "dense" },
      "Troupes Spéciales": { corpus_note_count: 9, evidence_note_count: 1, coverage_band: "thin" },
    },
    confidence: {
      overall_band: "medium",
      rationale: "4 evidence note(s), median note band 'moderate'; capped at 'medium' because coverage_map discloses a thin name.",
    },
  };

  return { record, metrics };
}

function exportContentFor(job, format) {
  const { record, metrics } = paperFor(job);
  const markdown =
    `# Analysis answer: ${record.brief_id}\n\n**Case:** ${record.brief.case}\n\n` +
    record.claims.map((c) => `- (${c.kind}) ${c.text}`).join("\n") +
    `\n\n## Metrics\n\n**Total cost (USD):** ${metrics.cost.total_usd}\n`;
  if (format === "md") return { content: markdown, contentType: "text/markdown; charset=utf-8" };
  if (format === "docx") {
    return {
      content: `docx:${markdown}`,
      contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    };
  }
  return { content: `odt:${markdown}`, contentType: "application/vnd.oasis.opendocument.text" };
}

async function streamEvents(req, res, job) {
  const lastSeq = Number.parseInt(req.headers["last-event-id"] ?? "0", 10) || 0;
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  // The first connection is cut halfway through, with the job still running.
  // A quiet job keeps its one connection instead: it is here to go silent.
  const stopAfter = job.quiet || job.connections > 0 ? MESSAGES.length : 2;
  job.connections += 1;

  for (let seq = lastSeq + 1; seq <= stopAfter; seq += 1) {
    await sleep(job.quiet && seq === 3 ? QUIET_MS : 120);
    if (res.writableEnded || dead) return;
    res.write(`id: ${seq}\ndata: ${JSON.stringify({ message: MESSAGES[seq - 1], detail: {} })}\n\n`);
  }
  if (stopAfter === MESSAGES.length) job.state = "done";
  res.end();
}

// One `AskStatus` row (`src/axial/service/api.py`) for `job`. Shared by the
// list route and the single-job route so the two can never disagree about
// what a row looks like.
function askStatusFor(job) {
  return {
    id: job.id,
    state: job.state,
    case: job.case ?? null,
    question: job.request ?? null,
    corpus_pin: "3c49f2e5aa11bb22",
    cached: Boolean(job.cached),
    created_at: job.created_at ?? new Date().toISOString(),
    claimed_at: job.claimed_at ?? null,
    finished_at:
      job.finished_at ??
      (job.state === "done" || job.state === "failed" ? new Date().toISOString() : null),
    result_ref: null,
    error: job.error ?? null,
  };
}

// Three fixed history rows (issue #746): a plain finished ask, a cached one
// that cost nothing, and a failed one -- so `GET /asks` and reopening have
// something to show without a live ask first.
function seedHistory() {
  jobs.set("hist-done", {
    id: "hist-done",
    state: "done",
    connections: 0,
    quiet: false,
    cached: false,
    case: "Damascus",
    request: "Did Mandate recruitment shape later rule?",
    created_at: "2026-08-01T09:00:00.000Z",
    finished_at: "2026-08-01T09:03:12.000Z",
    principal: DEFAULT_USER_ID,
  });
  jobs.set("hist-cached", {
    id: "hist-cached",
    state: "done",
    connections: 0,
    quiet: false,
    cached: true,
    case: "Aleppo",
    request: "The same question, asked a second time",
    created_at: "2026-08-02T10:00:00.000Z",
    finished_at: "2026-08-02T10:00:01.000Z",
    principal: DEFAULT_USER_ID,
  });
  jobs.set("hist-failed", {
    id: "hist-failed",
    state: "failed",
    connections: 0,
    quiet: false,
    cached: false,
    case: "Homs",
    request: "A question the corpus could not answer",
    created_at: "2026-08-03T11:00:00.000Z",
    finished_at: "2026-08-03T11:01:00.000Z",
    error: "The corpus snapshot could not be bound.",
    principal: DEFAULT_USER_ID,
  });
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const path = url.pathname;

  // Reviving has to answer even while dead; nothing else does. `__revive`
  // is the same revival `__reset` does, minus `jobs.clear()` -- an API
  // restart in the real deployment loses no job state, since the worker
  // that runs the ask is a separate process the restart never touches
  // (issue #760).
  if (path === "/__reset") {
    dead = false;
    forceUnauthorized = false;
    jobs.clear();
    profiles.clear();
    seedHistory();
    return json(res, 200, { dead });
  }
  if (path === "/__revive") {
    dead = false;
    return json(res, 200, { dead });
  }
  if (dead) {
    req.socket.destroy();
    return;
  }
  if (path === "/__health") return json(res, 200, { ok: true });
  if (path === "/__kill") {
    dead = true;
    json(res, 200, { dead });
    for (const socket of openSockets) socket.destroy();
    return;
  }
  if (path === "/__expire") {
    forceUnauthorized = true;
    return json(res, 200, { forceUnauthorized });
  }

  // Everything past here is the auth surface (module docstring): no bearer
  // token, one this mock cannot parse a `sub` out of, or a token forced
  // stale by `POST /__expire`, is `401` -- before any route below runs,
  // matching `current_principal`'s own place in the real service.
  const principal = forceUnauthorized ? null : principalFor(req);
  if (!principal) return json(res, 401, { detail: "invalid or missing bearer token" });

  if (req.method === "GET" && path === "/asks") {
    return json(
      res,
      200,
      [...jobs.values()].filter((job) => job.principal === principal).map(askStatusFor),
    );
  }

  if (req.method === "GET" && path === "/me/profile") {
    return json(res, 200, { theme: profiles.get(principal) ?? "system" });
  }

  if (req.method === "PUT" && path === "/me/profile") {
    const body = await readBody(req);
    if (!["light", "dark", "system"].includes(body.theme)) {
      return json(res, 422, { detail: `theme must be one of ('light', 'dark', 'system')` });
    }
    profiles.set(principal, body.theme);
    return json(res, 200, { theme: body.theme });
  }

  if (req.method === "GET" && path === "/me/usage") {
    // The session window is `null` here only when the client sends no
    // `session_id` at all -- the app under test always does
    // (`currentSessionId()`), so this exercises the "present" branch and
    // uses a `null` cost/tokens pair to prove unknown never renders as
    // `$0.00`. `month_to_date` carries a real estimate with `asks_charged`
    // short of `asks_made`, the cache-hit exclusion the issue names.
    const sessionId = url.searchParams.get("session_id");
    return json(res, 200, {
      principal,
      session: sessionId
        ? { cost_usd: null, tokens: null, asks_made: 2, asks_charged: 1 }
        : null,
      month_to_date: { cost_usd: 4.82, tokens: 128000, asks_made: 9, asks_charged: 7 },
      quota: {
        day: { limit: 20, used: 3, reset_at: "2026-08-12T00:00:00+00:00" },
        month: { limit: 300, used: 7, reset_at: "2026-09-01T00:00:00+00:00" },
      },
    });
  }

  if (req.method === "POST" && path === "/asks") {
    const ask = await readBody(req);
    if (ask.case === "over quota") {
      return json(res, 429, {
        detail: {
          message: "You've reached your daily limit of 20 ask(s). It resets at 2026-08-12T00:00:00+00:00 (UTC).",
          window: "day",
          limit: 20,
          reset_at: "2026-08-12T00:00:00+00:00",
        },
      });
    }
    const id = `ask-${nextId++}`;
    jobs.set(id, {
      id,
      state: "running",
      connections: 0,
      quiet: ask.case === "quiet",
      case: ask.case,
      request: ask.request,
      principal,
    });
    return json(res, 202, { id, state: "queued" });
  }

  const match = /^\/asks\/([^/]+)(\/events|\/paper|\/export)?$/.exec(path);
  const job = match ? jobs.get(match[1]) : undefined;
  // A job owned by someone else is refused exactly as if it did not exist
  // (`_require_own_job`'s own rule, `src/axial/service/api.py`) -- guessing
  // another analyst's ask id correctly proves nothing.
  if (!job || job.principal !== principal) return json(res, 404, { detail: `no ask with id ${path}` });

  if (match[2] === "/events") return streamEvents(req, res, job);

  if (match[2] === "/paper") {
    if (job.state !== "done") {
      return json(res, 409, { detail: `ask ${job.id} is ${job.state}, not finished` });
    }
    return json(res, 200, paperFor(job));
  }

  if (match[2] === "/export") {
    if (job.state !== "done") {
      return json(res, 409, { detail: `ask ${job.id} is ${job.state}, not finished` });
    }
    const format = url.searchParams.get("format") ?? "md";
    if (!["md", "docx", "odt"].includes(format)) {
      return json(res, 422, { detail: `format must be one of ('md', 'docx', 'odt'), got '${format}'` });
    }
    const { content, contentType } = exportContentFor(job, format);
    res.writeHead(200, {
      "Content-Type": contentType,
      "Content-Disposition": `attachment; filename="${job.id}.${format}"`,
    });
    return res.end(content);
  }

  return json(res, 200, askStatusFor(job));
});

server.on("connection", (socket) => {
  openSockets.add(socket);
  socket.on("close", () => openSockets.delete(socket));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`mock axial service on http://127.0.0.1:${PORT}`);
});
