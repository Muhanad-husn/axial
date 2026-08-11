/** Formatting for the two spend meters (issue #746, `GET /me/usage`).
 *
 * `cost_usd` and `tokens` are `None`-preserving on the wire -- unknown is
 * never the same value as a real zero (a cache hit costs nothing and is a
 * genuine `0`, not a missing figure). Everything here is a lookup or a
 * `toFixed`/`toLocaleString` call over a number the server already sent;
 * nothing sums across windows, computes a month boundary or re-derives
 * `asks_charged` from `asks_made` -- the one rule the issue states by name.
 */

const UNKNOWN = "—"; // em dash: unknown, never a bare "$0.00" or "0".

/** `null` renders as an em dash. A real `0` (a cached ask, or a window with
 * no asks yet) renders as `$0.00` -- that is the honest reading of a cache
 * hit, not a missing value. The service's own price table runs ~14% high
 * (`llm.py`), which is why every caller of this pairs it with the word
 * "estimate" rather than showing it as a bill. */
export function formatCostUsd(value: number | null): string {
  return value == null ? UNKNOWN : `$${value.toFixed(2)}`;
}

export function formatTokens(value: number | null): string {
  return value == null ? UNKNOWN : value.toLocaleString();
}
