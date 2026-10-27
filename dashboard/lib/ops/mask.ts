/**
 * Account-identifier masking for the private /ops view.
 *
 * Every string that leaves lib/ops goes through `maskDeep`, so a broker account id, a policy number or
 * any long numeric reference can only ever reach the page as "••••" + its last 4 characters.
 * Already-masked forms ("••1804", "•••7225", "x1804") are left alone: they are last-4 by construction.
 */

const DOTS = "••••";

/** Last 4 characters of an identifier, behind a fixed mask. */
export function maskId(raw: string): string {
  const s = raw.replace(/[\s-]/g, "");
  return DOTS + s.slice(-4);
}

// Letter-prefixed broker / policy style ids: U1234567, DU1234567, DUH123456, PA-1234567 ...
const PREFIXED = /\b(?:[A-Z]{1,3}-?\d{6,12}|DU[A-Z]?\d{5,10})\b/g;
// Long digit runs (account numbers, routing-like numbers, policy numbers): 8+ digits, optionally grouped by space/dash.
const GROUPED = /\b\d{4}(?:[ -]\d{4}){2,4}\b/g;
const LONG_DIGITS = /\b\d{8,}\b/g;
// "acct 12345", "account #12345", "acct ending 12345" with a short numeric id of 5+ digits
const LABELLED = /\b(acct|account|a\/c|policy)(\s*(?:no\.?|number|#|id|ending|:)?\s*)([A-Z]{0,3}\d{5,})\b/gi;
// An 8-digit YYYYMMDD date is not an account id.
const DATE8 = /^20[2-3]\d(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$/;

export function maskAccountIds(text: string): string {
  if (!text) return text;
  return text
    .replace(LABELLED, (_m, label: string, sep: string, id: string) => `${label}${sep}${maskId(id)}`)
    .replace(GROUPED, (m) => maskId(m))
    .replace(PREFIXED, (m) => maskId(m))
    .replace(LONG_DIGITS, (m) => (DATE8.test(m) ? m : maskId(m)));
}

/** Deep-copy `value`, masking every string in it. Non-plain values pass through unchanged. */
export function maskDeep<T>(value: T): T {
  if (typeof value === "string") return maskAccountIds(value) as unknown as T;
  if (Array.isArray(value)) return value.map((v) => maskDeep(v)) as unknown as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) out[k] = maskDeep(v);
    return out as T;
  }
  return value;
}
