#!/usr/bin/env node
/**
 * classify-branches.mjs — classify LOCAL git branches by merge status and propose safe cleanup.
 *
 * Scope: LOCAL branches only. This script NEVER touches the remote (no push --delete).
 * Default: DRY-RUN — it reports and deletes nothing. Deletion happens only with --apply --yes
 * plus the category flag(s) you approve.
 *
 * Safety guarantees:
 *   - Refuses to run on a detached HEAD (the "current branch" must be well-defined to protect it).
 *   - An OPEN PR always wins — such a branch is never deletable, even if it is an ancestor of the base.
 *   - A branch is only "merged" (safe) if its commits are genuinely in the base: either an ancestor,
 *     or `git cherry` shows every commit is patch-present in the base. A branch whose PR merged but
 *     which carries extra commits not in the base is KEPT ("ahead-of-merged-pr"), never force-deleted —
 *     this defeats branch-name reuse and post-merge commits.
 *   - Force-delete (`-D`) is re-verified at delete time; recovery SHAs are logged to a file BEFORE
 *     any deletion, and deletion aborts if that log cannot be written.
 *
 * Cross-platform (Windows/macOS/Linux). Requires Node 18+ and git. Uses `gh` if available to detect
 * squash/rebase-merged and abandoned (closed-unmerged) PRs; degrades safely without it.
 *
 * Usage:
 *   node ${CLAUDE_SKILL_DIR}/scripts/classify-branches.mjs
 *   node ${CLAUDE_SKILL_DIR}/scripts/classify-branches.mjs --apply --yes --delete-merged
 *   node ${CLAUDE_SKILL_DIR}/scripts/classify-branches.mjs --apply --yes --delete-merged --delete-abandoned
 *
 * Flags:
 *   --base <branch>     base branch to compare against (auto-detected if omitted)
 *   --protected a,b,c   extra branch names to never delete (base/main/master/develop/release always protected)
 *   --apply             actually delete (otherwise dry-run)
 *   --yes               required with --apply as an explicit go-ahead
 *   --delete-merged     in apply mode, delete branches classified "merged"
 *   --delete-abandoned  in apply mode, also delete "abandoned" (closed-unmerged-PR) branches — these carry
 *                       commits NOT in the base; you opt into losing them (recoverable via reflog / the log)
 *   --log <path>        recovery-log path (default: .tdd-branch-cleanup.log at repo root)
 *   --json              also print machine-readable JSON of the classification
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const VALUE_FLAGS = new Set(['base', 'protected', 'log']);

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) args[key] = true;
    else { args[key] = next; i++; }
  }
  return args;
}

function git(gitArgs) {
  try { return execFileSync('git', gitArgs, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim(); }
  catch { return null; }
}
function gitOk(gitArgs) {
  try { execFileSync('git', gitArgs, { stdio: 'ignore' }); return true; } catch { return false; }
}
function gh(ghArgs) {
  try { return execFileSync('gh', ghArgs, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim(); }
  catch { return null; }
}

// Count commits on `branch` that are NOT patch-present in `base` (git cherry '+' lines).
// 0 => everything on the branch is already in the base (safe). null => couldn't determine.
function cherryAhead(branch, base) {
  const out = git(['cherry', base, branch]);
  if (out === null) return null;
  if (out === '') return 0;
  return out.split('\n').filter(l => l.startsWith('+')).length;
}

function detectBase(args) {
  if (typeof args.base === 'string') {
    if (gitOk(['rev-parse', '--verify', 'refs/heads/' + args.base])) return args.base;
    console.error(`ERROR: --base "${args.base}" is not a local branch.`); process.exit(1);
  }
  const sym = git(['symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD']);
  if (sym) { const b = sym.replace('refs/remotes/origin/', ''); if (gitOk(['rev-parse', '--verify', 'refs/heads/' + b])) return b; }
  const cfg = git(['config', '--get', 'init.defaultBranch']);
  if (cfg && gitOk(['rev-parse', '--verify', 'refs/heads/' + cfg])) return cfg;
  const candidates = ['main', 'master', 'develop', 'release'].filter(c => gitOk(['rev-parse', '--verify', 'refs/heads/' + c]));
  if (candidates.length === 1) return candidates[0];
  if (candidates.length > 1) { console.error(`ERROR: multiple candidate base branches (${candidates.join(', ')}) and no origin/HEAD — pass --base <branch>.`); process.exit(1); }
  return null;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  for (const f of VALUE_FLAGS) {
    if (args[f] === true) { console.error(`ERROR: --${f} requires a value.`); process.exit(2); }
  }
  const apply = !!args.apply;
  const yes = !!args.yes;
  const deleteMerged = !!args['delete-merged'];
  const deleteAbandoned = !!args['delete-abandoned'];

  if (!gitOk(['rev-parse', '--is-inside-work-tree'])) { console.error('ERROR: not inside a git repository.'); process.exit(1); }
  const repoRoot = git(['rev-parse', '--show-toplevel']) || process.cwd();

  const base = detectBase(args);
  if (!base) { console.error('ERROR: could not determine a base branch to compare against. Pass --base <branch>.'); process.exit(1); }

  // Detached HEAD breaks "never delete the current branch" — refuse rather than protect the literal "HEAD".
  const current = git(['symbolic-ref', '--quiet', '--short', 'HEAD']);
  if (!current) { console.error('ERROR: detached HEAD — check out a branch before running cleanup.'); process.exit(1); }

  const protectedSet = new Set(['main', 'master', 'develop', 'release', base, current]
    .concat(typeof args.protected === 'string' ? args.protected.split(',').map(s => s.trim()).filter(Boolean) : []));

  const hasRemote = !!git(['remote']);
  let ghAuthed = false;
  try { execFileSync('gh', ['auth', 'status'], { stdio: 'ignore' }); ghAuthed = true; } catch { ghAuthed = false; }
  const prCapable = hasRemote && ghAuthed;

  const prByBranch = {};
  let prTruncated = false;
  if (prCapable) {
    const out = gh(['pr', 'list', '--state', 'all', '--json', 'number,state,headRefName,url,mergedAt', '--limit', '500']);
    if (out) {
      try {
        const list = JSON.parse(out);
        if (list.length >= 500) prTruncated = true;
        for (const pr of list) (prByBranch[pr.headRefName] ||= []).push(pr);
      } catch { /* ignore */ }
    }
  }

  const raw = git(['for-each-ref', '--format=%(refname:short)\t%(objectname)\t%(committerdate:unix)', 'refs/heads']) || '';
  const branches = raw.split('\n').filter(Boolean).map(l => {
    const [name, sha, ts] = l.split('\t');
    return { name, sha, ts: parseInt(ts, 10) };
  }).filter(b => b.name && b.sha);

  const now = Math.floor(Date.now() / 1000);
  const rows = [];
  for (const b of branches) {
    if (protectedSet.has(b.name)) { rows.push({ ...b, status: 'protected', reason: 'protected / current / base' }); continue; }

    const prs = prByBranch[b.name] || [];
    const openPr = prs.find(p => p.state === 'OPEN');
    const mergedPr = prs.find(p => p.state === 'MERGED');
    const closedPr = prs.find(p => p.state === 'CLOSED'); // gh: CLOSED excludes MERGED
    const ancestor = gitOk(['merge-base', '--is-ancestor', b.name, base]);
    const unique = parseInt(git(['rev-list', '--count', `${base}..${b.name}`]) || '0', 10);
    const ageDays = Number.isFinite(b.ts) ? Math.floor((now - b.ts) / 86400) : null;

    let status, delFlag = null, reason = '';
    if (openPr) {
      status = 'open-pr'; reason = `PR #${openPr.number} open — never delete`;
    } else if (ancestor) {
      status = 'merged'; delFlag = '-d'; reason = `commits already in ${base}`;
    } else if (mergedPr) {
      const ahead = cherryAhead(b.name, base);
      if (ahead === 0) { status = 'merged'; delFlag = '-D'; reason = `PR #${mergedPr.number} merged; all commits present in ${base}`; }
      else { status = 'ahead-of-merged-pr'; reason = `PR #${mergedPr.number} merged but ${ahead == null ? 'some' : ahead} commit(s) NOT in ${base} — kept`; }
    } else if (closedPr) {
      status = 'abandoned'; delFlag = '-D'; reason = `PR #${closedPr.number} closed unmerged; ${unique} commit(s) not in ${base}`;
    } else {
      status = 'local-only'; reason = `${unique} commit(s) not in ${base}${prCapable ? ', no PR' : ', PR state unknown (gh/remote unavailable)'}`;
    }
    rows.push({ ...b, status, delFlag, unique, ageDays, pr: prs[0]?.number ?? null, reason });
  }

  // Report
  const self = process.argv[1];
  const fullCmd = `node "${self}"`;
  console.log(`Branch cleanup report — base "${base}", current "${current}"`);
  console.log(`PR detection: ${prCapable ? 'gh + remote available' : 'UNAVAILABLE (squash-merged / abandoned cannot be detected; only ancestor-merged branches are eligible)'}`);
  if (prTruncated) console.log('NOTE: PR list hit the 500 query limit — older PRs may be missing; affected branches fall back to "local-only" (kept).');
  console.log('');
  const pad = (s, n) => String(s).padEnd(n);
  console.log(pad('BRANCH', 40), pad('STATUS', 19), pad('PR', 6), pad('AGE', 6), pad('UNIQ', 5), 'NOTE');
  for (const r of rows) {
    console.log(pad(r.name, 40), pad(r.status, 19), pad(r.pr ?? '-', 6), pad(r.ageDays == null ? '-' : r.ageDays + 'd', 6), pad(r.unique ?? '-', 5), r.reason);
  }
  console.log('');

  const merged = rows.filter(r => r.status === 'merged');
  const abandoned = rows.filter(r => r.status === 'abandoned');
  const aheadPr = rows.filter(r => r.status === 'ahead-of-merged-pr');
  const openPr = rows.filter(r => r.status === 'open-pr');
  const localOnly = rows.filter(r => r.status === 'local-only');
  console.log(`Summary: ${merged.length} merged · ${abandoned.length} abandoned · ${aheadPr.length} ahead-of-merged-pr (kept) · ${openPr.length} open-PR (kept) · ${localOnly.length} local-only/unknown (kept)`);

  if (args.json) console.log('\nJSON ' + JSON.stringify(rows));

  const toDelete = [];
  if (deleteMerged) toDelete.push(...merged);
  if (deleteAbandoned) toDelete.push(...abandoned);

  if (!apply) {
    console.log('\n(DRY-RUN — nothing deleted.)');
    if (merged.length) console.log(`  To delete the ${merged.length} merged branch(es):     ${fullCmd} --apply --yes --delete-merged`);
    if (abandoned.length) console.log(`  To ALSO delete the ${abandoned.length} abandoned branch(es): add --delete-abandoned (these drop commits not in ${base} — recoverable via reflog only)`);
    const kept = aheadPr.length + openPr.length + localOnly.length;
    if (kept) console.log(`  ${kept} branch(es) are never auto-deleted (open PR, unmerged local work, or commits beyond a merged PR).`);
    return;
  }

  // Apply mode.
  if (!yes) { console.error('\nREFUSING: --apply requires --yes as an explicit go-ahead. Nothing deleted.'); process.exit(2); }
  if (!prCapable && deleteAbandoned) console.warn('WARNING: gh/remote unavailable — "abandoned" branches could not be evaluated, so none will be deleted under --delete-abandoned.');
  if (!toDelete.length) { console.log('\nNothing selected for deletion (pass --delete-merged and/or --delete-abandoned). Nothing deleted.'); return; }

  // Recovery log is mandatory when deleting — write it (and abort if we cannot).
  const logPath = typeof args.log === 'string' ? args.log : path.join(repoRoot, '.tdd-branch-cleanup.log');
  const stamp = new Date().toISOString();
  try {
    fs.appendFileSync(logPath, toDelete.map(r => `${stamp} ${r.sha} ${r.name} (${r.status})`).join('\n') + '\n');
  } catch (e) {
    console.error(`ERROR: cannot write recovery log at ${logPath} (${e.code || e.message}) — aborting before any deletion.`); process.exit(3);
  }

  console.log('\n----- RECOVERY (restore any of these with:  git branch <name> <sha>) -----');
  for (const r of toDelete) console.log(`  ${r.sha}  ${r.name}`);
  console.log(`(recovery log written to ${logPath})`);

  console.log('\n----- DELETING (local only) -----');
  let deleted = 0, skipped = 0;
  for (const r of toDelete) {
    if (protectedSet.has(r.name)) { console.log(`  skip   ${r.name} (protected)`); skipped++; continue; }
    if (!['merged', 'abandoned'].includes(r.status)) { console.log(`  skip   ${r.name} (${r.status} — not eligible)`); skipped++; continue; }
    // Re-verify force-deletes at the moment of deletion to catch any drift since classification.
    if (r.delFlag === '-D' && r.status === 'merged') {
      const ahead = cherryAhead(r.name, base);
      if (ahead !== 0) { console.log(`  SKIP   ${r.name} (now has ${ahead == null ? 'undetermined' : ahead} commit(s) not in ${base} — refusing force-delete)`); skipped++; continue; }
    }
    const ok = gitOk(['branch', r.delFlag, r.name]);
    if (ok) { console.log(`  delete ${r.name}  (git branch ${r.delFlag})`); deleted++; }
    else { console.log(`  FAILED ${r.name} (git branch ${r.delFlag} refused — left intact)`); skipped++; }
  }
  console.log(`\nDone. Deleted ${deleted} local branch(es), ${skipped} skipped/failed. Remote was NOT touched. Recovery log: ${logPath}`);
}

main();
