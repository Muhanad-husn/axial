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
