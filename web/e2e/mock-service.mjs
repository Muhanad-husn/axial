/** A stand-in for `axial.service.api`, for the end-to-end spec only.
 *
 * It speaks the routes the app uses -- `POST /asks`, `GET /asks/{id}`,
 * `GET /asks/{id}/events`, `GET /asks/{id}/paper`, `GET /asks/{id}/export`
 * -- with the same shapes and the same SSE framing (`id:` line,
 * `{"message", "detail"}` payload, stream closes at a terminal state).
 * Three things it does deliberately: it drops the first event connection
 * halfway, so a resume through `Last-Event-ID` is exercised for real;
 * `POST /__kill` makes it stop answering, which is what "the API died
 * mid-ask" looks like from a browser; and the case `quiet` holds the
 * stream open and silent mid-ask, which is what a real fourteen-minute ask
 * looks like and the only way a buffering hop between the browser and the
 * service is visible at all.
 *
 * `/paper` renders one of two fixed §7.3 records, picked by the ask's own
 * `case` (`paperFor`) -- the default is shaped like `locator` citation mode
 * (no `citation.quote`), and the case `"Aleppo"` is shaped like `passage`
 * mode (`citation.quote` present on every resolved chunk ground). The real
 * mode is a deployment setting the client never sees or chooses (#690);
 * this mock picks a fixture by case only because it has no deployment
 * setting of its own to read -- the client under test is exercised against
 * both shapes exactly as it would be against two real deployments.
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

const jobs = new Map();
let nextId = 1;
let dead = false;
const openSockets = new Set();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

  const metrics = {
    cost: {
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

const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const path = url.pathname;

  // Reviving has to answer even while dead; nothing else does.
  if (path === "/__reset") {
    dead = false;
    jobs.clear();
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
    });
    return json(res, 202, { id, state: "queued" });
  }

  const match = /^\/asks\/([^/]+)(\/events|\/paper|\/export)?$/.exec(path);
  const job = match ? jobs.get(match[1]) : undefined;
  if (!job) return json(res, 404, { detail: `no ask with id ${path}` });

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

  return json(res, 200, {
    id: job.id,
    state: job.state,
    corpus_pin: "3c49f2e5aa11bb22",
    cached: false,
    created_at: new Date().toISOString(),
    claimed_at: null,
    finished_at: job.state === "done" ? new Date().toISOString() : null,
    result_ref: null,
    error: null,
  });
});

server.on("connection", (socket) => {
  openSockets.add(socket);
  socket.on("close", () => openSockets.delete(socket));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`mock axial service on http://127.0.0.1:${PORT}`);
});
