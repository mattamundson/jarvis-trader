import type { TapePayload } from "./serialize";

// The ONLY network call the /tape page makes: same-origin GET /api/tape (allow-list serialized).
export async function fetchTape(url: string = "/api/tape"): Promise<TapePayload> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`tape feed ${res.status}`);
  return res.json();
}
