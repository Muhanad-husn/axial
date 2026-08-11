/** A stand-in for `axial.service.api`, for the end-to-end spec only.
 *
 * It speaks exactly the three routes the app uses -- `POST /asks`,
 * `GET /asks/{id}`, `GET /asks/{id}/events` -- with the same shapes and the
 * same SSE framing (`id:` line, `{"message", "detail"}` payload, stream closes
 * at a terminal state). Three things it does deliberately: it drops the first
 * event connection halfway, so a resume through `Last-Event-ID` is exercised
 * for real; `POST /__kill` makes it stop answering, which is what "the API
 * died mid-ask" looks like from a browser; and the case `quiet` holds the
 * stream open and silent mid-ask, which is what a real fourteen-minute ask
 * looks like and the only way a buffering hop between the browser and the
 * service is visible at all.
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
    jobs.set(id, { id, state: "running", connections: 0, quiet: ask.case === "quiet" });
    return json(res, 202, { id, state: "queued" });
  }

  const match = /^\/asks\/([^/]+)(\/events)?$/.exec(path);
  const job = match ? jobs.get(match[1]) : undefined;
  if (!job) return json(res, 404, { detail: `no ask with id ${path}` });

  if (match[2]) return streamEvents(req, res, job);

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
