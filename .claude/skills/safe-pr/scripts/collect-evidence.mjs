#!/usr/bin/env node
/**
 * collect-evidence.mjs — gather test evidence into a committed evidence folder and render a
 * Markdown evidence block for a TDD-harness pull request.
 *
 * Two modalities — the harness builds web and non-web apps:
 *   • web     — Playwright artifacts: screenshots + recordings/report.
 *   • generic — terminal transcripts (test-run output + a real endpoint invocation) embedded
 *               as fenced code blocks. No browser required.
 *
 * The modality is auto-detected (Playwright artifacts present → web; otherwise transcripts → generic)
 * and can be forced with --type web|cli|api|service|generic.
 *
 * PRIVATE vs PUBLIC repos:
 *   Inline image embeds (`![](raw.githubusercontent.com/...)`) only render on PUBLIC repos —
 *   raw.githubusercontent 404s for private repos and GitHub won't proxy them. So:
 *     • public  → screenshots embedded inline.
 *     • private → screenshots shown as clickable blob links (render in GitHub's file viewer for
 *                 signed-in reviewers) plus a note; the CI artifact still has the originals.
 *   Visibility is auto-detected via `gh repo view --json isPrivate`; override with --public/--private.
 *
 * TWO-PHASE USE (so embedded URLs point at the commit that actually contains the evidence):
 *   The collector pins URLs to the CURRENT commit. Run it in two phases around the evidence commit:
 *     1) --copy-only : copy artifacts into docs/tdd-evidence/, scan for secrets. No body written.
 *        (then `git add` + commit the evidence)
 *     2) --body-only : regenerate the PR body from the committed evidence, pinned to the new HEAD.
 *   Running with neither flag does copy+body in one shot (back-compat; URLs will pin to the
 *   pre-evidence commit, so prefer the two-phase flow when embedding web screenshots).
 *
 * Cross-platform (Windows/macOS/Linux). Requires Node 18+ and a git repo.
 *
 * Usage (web, two-phase):
 *   node collect-evidence.mjs --feature <slug> --slice <NN-slug> \
 *        --report-dir <dir>/playwright-report --results-dir <dir>/test-results --copy-only
 *   # commit the evidence, then:
 *   node collect-evidence.mjs --feature <slug> --slice <NN-slug> --body-only \
 *        --template path/to/pr-body-template.md --out PR_BODY.md
 *
 * Usage (non-web, two-phase):
 *   node collect-evidence.mjs --feature <slug> --slice <NN-slug> --type cli \
 *        --transcript test-run.txt --transcript cli-demo.txt --copy-only
 *   # commit the evidence, then:
 *   node collect-evidence.mjs --feature <slug> --slice <NN-slug> --type cli --body-only \
 *        --template path/to/pr-body-template.md --out PR_BODY.md
 *
 * Safety:
 *   - RAW traces (*.zip) and HAR captures (*.har) are dropped from the committed evidence by
 *     default (they routinely carry auth tokens / cookies). Opt in with --include-traces.
 *   - Copied text artifacts (transcripts included) are scanned for likely secrets; a match prints
 *     a loud "SECRETS SUSPECTED" report (file + pattern only, never the value) so the human reviews
 *     BEFORE committing.
 *   - --out is never silently clobbered: if the target exists, output goes to <name>.generated.md
 *     unless --force is given.
 */

import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

function parseArgs(argv) {
  const args = {};
  const add = (key, value) => {
    if (key in args) args[key] = [].concat(args[key], value); // repeated flag → array
    else args[key] = value;
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) { add(key, true); }
      else { add(key, next); i++; }
    }
  }
  return args;
}

/** Coerce a possibly-repeated flag value into a list of string values. */
function asList(v) {
  if (v === undefined) return [];
  return [].concat(v).filter((x) => typeof x === 'string');
}

/** Map a free-form --type onto 'web' | 'generic'. Unknown / non-browser kinds → 'generic'. */
function normalizeType(t) {
  if (!t || t === true) return null;
  const s = String(t).toLowerCase();
  return ['web', 'browser', 'playwright', 'e2e', 'ui'].includes(s) ? 'web' : 'generic';
}

function sh(cmd) {
  try { return execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); }
  catch { return ''; }
}

/** Parse owner/repo from a github.com remote URL (https or ssh). Returns null otherwise. */
function parseRepo(remoteUrl) {
  if (!remoteUrl) return null;
  const m = remoteUrl.match(/github\.com[/:]([^/]+)\/(.+?)(?:\.git)?\/?$/i);
  if (!m) return null;
  return { owner: m[1], repo: m[2] };
}

/** Ask gh whether the repo is private. Returns null if gh/visibility is unavailable. */
function detectPrivate(repo) {
  if (!repo) return null;
  const out = sh(`gh repo view ${repo.owner}/${repo.repo} --json isPrivate -q .isPrivate`);
  if (out === 'true') return true;
  if (out === 'false') return false;
  return null; // gh missing / not authed / unknown
}

/** Recursively list files under dir (absolute paths). */
function walk(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

/** OS path -> forward-slash repo-relative path (for URLs and display). */
function toRepoUrlPath(absPath, repoRoot) {
  return path.relative(repoRoot, absPath).split(path.sep).join('/');
}

// High-signal secret patterns. Specific enough to limit false positives on report boilerplate.
const SECRET_PATTERNS = [
  ['Authorization: Bearer', /authorization\s*:\s*bearer\s+\S+/i],
  ['Set-Cookie header', /\bset-cookie\s*:/i],
  ['Cookie header with value', /\bcookie\s*:\s*[^\s;]+=/i],
  ['Bearer token', /\bbearer\s+[A-Za-z0-9._\-]{20,}/i],
  ['AWS access key id', /\bAKIA[0-9A-Z]{16}\b/],
  ['Private key block', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['Slack token', /\bxox[baprs]-[A-Za-z0-9-]{10,}/],
  ['GitHub token', /\bgh[pousr]_[A-Za-z0-9]{20,}/],
  ['Assigned credential', /\b(api[_-]?key|secret|password|passwd|access[_-]?token)\b\s*[=:]\s*['"]?[A-Za-z0-9._\-]{8,}/i],
];

const TEXT_EXT = /\.(json|har|txt|log|xml|md|yaml|yml|csv|html?)$/i;
const TRANSCRIPT_EXT = /\.(txt|log|json|md|csv)$/i;

function scanForSecrets(files) {
  const hits = [];
  for (const f of files) {
    if (!TEXT_EXT.test(f)) continue;
    let stat;
    try { stat = fs.statSync(f); } catch { continue; }
    if (stat.size > 2 * 1024 * 1024) continue; // skip very large bundles
    let content;
    try { content = fs.readFileSync(f, 'utf8'); } catch { continue; }
    for (const [name, re] of SECRET_PATTERNS) {
      if (re.test(content)) hits.push({ file: f, pattern: name });
    }
  }
  return hits;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const feature = args.feature;
  const slice = args.slice;
  if (!feature || !slice || feature === true || slice === true) {
    console.error('ERROR: --feature <slug> and --slice <NN-slug> are required.');
    process.exit(1);
  }

  const reportDir = (typeof args['report-dir'] === 'string' && args['report-dir']) || 'playwright-report';
  const resultsDir = (typeof args['results-dir'] === 'string' && args['results-dir']) || 'test-results';
  const maxShots = parseInt(args['max-screenshots'] || '12', 10);
  const maxTranscriptLines = parseInt(args['max-transcript-lines'] || '200', 10);
  const includeTraces = !!args['include-traces'];
  const force = !!args.force;
  const copyOnly = !!args['copy-only'];
  const bodyOnly = !!args['body-only'];
  let outFile = (typeof args.out === 'string' && args.out) || 'PR_BODY.md';

  if (copyOnly && bodyOnly) {
    console.error('ERROR: --copy-only and --body-only are mutually exclusive.');
    process.exit(1);
  }

  const explicitType = normalizeType(args.type);
  const transcriptInputs = asList(args.transcript);
  const transcriptDir = typeof args['transcript-dir'] === 'string' ? args['transcript-dir'] : null;

  const repoRoot = sh('git rev-parse --show-toplevel') || process.cwd();
  const branch = sh('git rev-parse --abbrev-ref HEAD');
  const sha = sh('git rev-parse HEAD');
  const ref = sha || branch; // pin URLs to the commit so they survive branch deletion
  const remote = sh('git remote get-url origin');
  const repo = parseRepo(remote);

  // Visibility: explicit override wins, else ask gh, else assume public (inline embeds, today's default).
  const isPrivate = args.private ? true : args.public ? false : (detectPrivate(repo) === true);

  if (!branch || branch === 'HEAD') {
    console.warn('WARN: detached HEAD or no branch — checkout the feature branch before collecting evidence.');
  }
  if (!repo) {
    if (remote) console.warn('WARN: origin is not a github.com remote (GitHub Enterprise hosts are not auto-detected) — links will use repo-relative paths and may not render in the PR.');
    else console.warn('WARN: no origin remote — links will use repo-relative paths until the branch is pushed to GitHub.');
  }

  const destRel = path.join('docs', 'tdd-evidence', feature, slice);
  const destAbs = path.join(repoRoot, destRel);
  fs.mkdirSync(destAbs, { recursive: true });

  // Decide modality (uses the resolved report/results dirs).
  const reportAbs = path.isAbsolute(reportDir) ? reportDir : path.join(repoRoot, reportDir);
  const resultsAbs = path.isAbsolute(resultsDir) ? resultsDir : path.join(repoRoot, resultsDir);
  const sourceHasPw = fs.existsSync(reportAbs) || fs.existsSync(resultsAbs);
  const destHasPw = fs.existsSync(path.join(destAbs, 'playwright-report')) || fs.existsSync(path.join(destAbs, 'test-results'));
  const hasPwArtifacts = sourceHasPw || destHasPw;
  const type = explicitType
    || (hasPwArtifacts ? 'web' : ((transcriptInputs.length || transcriptDir || hasTopLevelTranscripts(destAbs)) ? 'generic' : 'web'));

  // ---- COPY PHASE (skipped in --body-only) ----
  if (!bodyOnly) {
    const copied = [];
    for (const [srcAbs, name] of [[reportAbs, 'playwright-report'], [resultsAbs, 'test-results']]) {
      if (fs.existsSync(srcAbs)) {
        fs.cpSync(srcAbs, path.join(destAbs, name), { recursive: true });
        copied.push(name);
      }
    }
    if (type === 'web' && copied.length === 0 && !destHasPw) {
      console.warn(`WARN: neither "${reportDir}" nor "${resultsDir}" exist. Run the Playwright suite first (or pass --type cli/api with --transcript for a non-web slice).`);
    }

    // Copy transcripts (non-web evidence, or extra command output for a web slice).
    const addTranscript = (srcAbs) => {
      if (!fs.existsSync(srcAbs)) { console.warn(`WARN: transcript not found, skipping: ${srcAbs}`); return; }
      if (fs.statSync(srcAbs).isDirectory()) return;
      const dst = path.join(destAbs, path.basename(srcAbs));
      if (path.resolve(srcAbs) !== path.resolve(dst)) fs.cpSync(srcAbs, dst);
    };
    for (const t of transcriptInputs) addTranscript(path.isAbsolute(t) ? t : path.join(process.cwd(), t));
    if (transcriptDir) {
      const dirAbs = path.isAbsolute(transcriptDir) ? transcriptDir : path.join(process.cwd(), transcriptDir);
      for (const f of walk(dirAbs)) addTranscript(f);
    }

    // Drop raw traces (.zip) and HAR captures (.har) from the committed copy unless asked to keep them.
    if (!includeTraces) {
      for (const f of walk(destAbs)) {
        if (/\.(zip|har)$/i.test(f)) { fs.rmSync(f, { force: true }); }
      }
    }
  }

  // ---- CLASSIFY (always, from the committed evidence folder) ----
  const files = walk(destAbs);
  const screenshots = files.filter(f => /\.(png|jpe?g)$/i.test(f)).sort();
  const videos = files.filter(f => /\.(webm|mp4)$/i.test(f)).sort();
  const isTrace = f => /\.zip$/i.test(f) && /(^|[\\/])trace[^\\/]*\.zip$/i.test(f);
  const traces = files.filter(isTrace).sort();
  const reportIndex = files.find(f => /playwright-report[\\/].*index\.html$/i.test(f));
  // Transcripts = top-level text files in the evidence folder (that's where the copy phase puts them).
  const transcriptFiles = topLevelTranscripts(destAbs);
  const droppedSensitive = files.filter(f => /\.(zip|har)$/i.test(f) && !isTrace(f)).length; // informational only

  const secretHits = scanForSecrets(files);

  const rawUrl = (rel) => repo && ref ? `https://raw.githubusercontent.com/${repo.owner}/${repo.repo}/${ref}/${rel}` : rel;
  const blobUrl = (rel) => repo && ref ? `https://github.com/${repo.owner}/${repo.repo}/blob/${ref}/${rel}` : rel;

  // ---- BODY PHASE (skipped in --copy-only) ----
  if (!copyOnly) {
    const lines = [];

    if (type === 'web') {
      lines.push('### Visual evidence', '');
      if (screenshots.length === 0) {
        lines.push("_No screenshots found. Add `await page.screenshot(...)` at the decisive assertion, or set `screenshot: 'on'` in playwright.config._");
      } else if (isPrivate) {
        lines.push('> ℹ️ This repo is **private**, so inline image previews don\'t render in the PR (raw.githubusercontent requires public access). The screenshots are committed — click to open them in GitHub\'s file viewer (signed in), and they\'re also in the e2e CI artifact.', '');
        for (const s of screenshots.slice(0, maxShots)) {
          lines.push(`- 📷 [${path.basename(s)}](${blobUrl(toRepoUrlPath(s, repoRoot))})`);
        }
        lines.push('');
      } else {
        for (const s of screenshots.slice(0, maxShots)) {
          const rel = toRepoUrlPath(s, repoRoot);
          const label = path.basename(s);
          lines.push(`**${label}**`, '', `![${label}](${rawUrl(rel)})`, '');
        }
      }
      if (screenshots.length > maxShots) {
        lines.push(`_…and ${screenshots.length - maxShots} more screenshot(s) in \`${destRel.split(path.sep).join('/')}/\`._`, '');
      }

      lines.push('### Recordings', '');
      if (videos.length) {
        lines.push('_Click to download and view the recording of the run:_', '');
        for (const v of videos) lines.push(`- [${path.basename(v)}](${blobUrl(toRepoUrlPath(v, repoRoot))})`);
        lines.push('');
      } else {
        lines.push('> ⚠️ **No recording was captured.** A web slice requires a video of the passing acceptance run. Set `video: \'on\'`, re-run the e2e suite, and re-collect.', '');
      }

      lines.push('### Reports & traces', '');
      if (reportIndex) {
        const rel = toRepoUrlPath(reportIndex, repoRoot);
        lines.push(`- Playwright HTML report: [\`${rel}\`](${blobUrl(rel)}) (also uploaded as a CI artifact — open locally with \`npx playwright show-report\`).`);
      }
      for (const t of traces) {
        const rel = toRepoUrlPath(t, repoRoot);
        lines.push(`- Trace: [${path.basename(t)}](${blobUrl(rel)}) — open with \`npx playwright show-trace <file>\`.`);
      }
      lines.push('');
    }

    // Transcripts — primary evidence for non-web slices; supplementary for web.
    if (transcriptFiles.length) {
      lines.push('### Test output (transcripts)', '');
      for (const tf of transcriptFiles) {
        const rel = toRepoUrlPath(tf, repoRoot);
        const label = path.basename(tf);
        let content = '';
        try { content = fs.readFileSync(tf, 'utf8'); } catch { /* unreadable */ }
        const allLines = content.replace(/\s+$/, '').split(/\r?\n/);
        const shown = allLines.slice(0, maxTranscriptLines);
        const truncated = allLines.length > maxTranscriptLines;
        const fence = content.includes('```') ? '~~~' : '```';
        const lang = /\.json$/i.test(tf) ? 'json' : '';
        lines.push(`**${label}**`, '');
        lines.push(fence + lang, ...shown, fence, '');
        if (truncated) lines.push(`_…truncated to ${maxTranscriptLines} lines; full transcript (${allLines.length} lines): [\`${rel}\`](${blobUrl(rel)})._`, '');
        else lines.push(`Full transcript: [\`${rel}\`](${blobUrl(rel)})`, '');
      }
    } else if (type !== 'web') {
      lines.push('### Test output (transcripts)', '');
      lines.push('> ⚠️ **No transcript captured.** For a non-web slice, capture the test-run output AND a real endpoint invocation to files and pass them with `--transcript <file>` (repeatable).', '');
    }

    lines.push(`_All evidence committed under \`${destRel.split(path.sep).join('/')}/\`._`, '');

    const block = lines.join('\n');

    const template = typeof args.template === 'string' ? args.template : null;
    if (template && fs.existsSync(template)) {
      let body = fs.readFileSync(template, 'utf8');
      body = body.includes('<!-- EVIDENCE -->') ? body.replace('<!-- EVIDENCE -->', block) : body + '\n\n' + block;
      if (fs.existsSync(outFile) && !force) {
        outFile = outFile.replace(/\.md$/i, '') + '.generated.md';
        console.warn(`WARN: target PR body already exists — wrote to ${outFile} instead (use --force to overwrite).`);
      }
      fs.writeFileSync(outFile, body, 'utf8');
      console.log(`Wrote PR body with evidence to ${outFile}`);
    } else if (args.out) {
      if (fs.existsSync(outFile) && !force) {
        outFile = outFile.replace(/\.md$/i, '') + '.generated.md';
        console.warn(`WARN: target already exists — wrote evidence block to ${outFile} instead (use --force to overwrite).`);
      }
      fs.writeFileSync(outFile, block, 'utf8');
      console.log(`Wrote evidence block to ${outFile}`);
    }

    console.log('\n----- EVIDENCE BLOCK -----\n');
    console.log(block);
  }

  // Loud secret report — the safe-pr skill keys off the "SECRETS SUSPECTED" token.
  if (secretHits.length) {
    console.log('\n==================== SECRETS SUSPECTED ====================');
    console.log('Review and redact these BEFORE committing — committed history is hard to un-publish:');
    for (const h of secretHits) console.log(`  ! ${h.pattern}  in  ${toRepoUrlPath(h.file, repoRoot)}`);
    console.log('==========================================================');
  }

  console.log('\n----- SUMMARY -----');
  console.log(`phase           : ${copyOnly ? 'copy-only' : bodyOnly ? 'body-only' : 'copy+body (single-shot)'}`);
  console.log(`modality        : ${type}${explicitType ? ' (forced)' : ' (auto-detected)'}`);
  console.log(`repo visibility : ${isPrivate ? 'private (screenshots shown as blob links)' : 'public (screenshots embedded inline)'}`);
  console.log(`evidence folder : ${destRel.split(path.sep).join('/')}/`);
  if (type === 'web') {
    console.log(`screenshots     : ${screenshots.length}`);
    console.log(`recordings      : ${videos.length}${videos.length ? '' : '  <-- WARNING: a web slice requires a recording of the acceptance run'}`);
    console.log(`traces          : ${traces.length}${includeTraces ? '' : ' (raw traces/HAR omitted; --include-traces to keep)'}`);
  }
  console.log(`transcripts     : ${transcriptFiles.length}${type !== 'web' && transcriptFiles.length === 0 ? '  <-- WARNING: a non-web slice needs at least one transcript' : ''}`);
  console.log(`secrets         : ${secretHits.length ? secretHits.length + ' SUSPECTED — see report above' : 'none detected (still skim the evidence)'}`);
  console.log(`commit          : ${sha ? sha.slice(0, 12) : '(unknown)'}`);
  console.log(`repo            : ${repo ? repo.owner + '/' + repo.repo : '(no github.com remote)'}`);
  if (copyOnly) {
    console.log('next            : git add the evidence folder, commit it, then re-run with --body-only to pin URLs to that commit.');
  }
  if (!repo || !branch || branch === 'HEAD') {
    console.log('note            : push the feature branch to GitHub so committed-file URLs resolve.');
  }
}

/** Top-level (depth-1) text files in the evidence folder — these are the copied transcripts. */
function topLevelTranscripts(destAbs) {
  if (!fs.existsSync(destAbs)) return [];
  return fs.readdirSync(destAbs, { withFileTypes: true })
    .filter(e => e.isFile() && TRANSCRIPT_EXT.test(e.name))
    .map(e => path.join(destAbs, e.name))
    .sort();
}

function hasTopLevelTranscripts(destAbs) {
  return topLevelTranscripts(destAbs).length > 0;
}

main();
