/** This browser session's id, sent with every ask.
 *
 * It is generated here and never read back off a served record. On a cache hit
 * the service returns the FIRST asker's analysis record byte-identically
 * (#686), so the `session_id` inside it belongs to a stranger -- taking the
 * session from anywhere but here would tag an analyst's follow-up with someone
 * else's session.
 */

const SESSION_STORAGE_KEY = "axial.session";

export function currentSessionId(): string {
  try {
    const existing = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) return existing;
    const fresh = crypto.randomUUID();
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, fresh);
    return fresh;
  } catch {
    return crypto.randomUUID();
  }
}

/** The id of the ask this tab is currently watching, if any (issue #760).
 *
 * Only an id is kept -- never events, progress or a paper. A reload reads it
 * back and asks the service what state that id is in now; the walk resumes
 * or the paper loads from there, both driven by the service's own answer,
 * never reconstructed from anything stored here. `useAsk` clears the key the
 * moment the ask settles (`done`/`failed`), so a later reload never reattaches
 * to something that finished long ago -- but leaves it alone on a lost
 * connection, since the ask may still be running on a service that is only
 * temporarily unreachable.
 */

const LIVE_ASK_STORAGE_KEY = "axial.liveAsk";

export function currentLiveAskId(): string | null {
  try {
    return window.sessionStorage.getItem(LIVE_ASK_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function rememberLiveAskId(id: string): void {
  try {
    window.sessionStorage.setItem(LIVE_ASK_STORAGE_KEY, id);
  } catch {
    // No storage, no reattachment on reload -- the ask itself is unaffected.
  }
}

export function clearLiveAskId(): void {
  try {
    window.sessionStorage.removeItem(LIVE_ASK_STORAGE_KEY);
  } catch {
    // Nothing to clear if nothing could be stored.
  }
}
