export type ProviderFailureClass =
  | "billing"
  | "authentication"
  | "rate-limit"
  | "timeout"
  | "capacity"
  | "provider";

export interface ProviderDiagnostic {
  title: string;
  consequence: string;
  failureClass: ProviderFailureClass;
  provider: string | null;
  detail: string;
}

const PROVIDERS: Array<[RegExp, string]> = [
  [/\b(?:anthropic|claude)\b/i, "Anthropic"],
  [/\bopenai\b/i, "OpenAI"],
  [/\b(?:google|gemini)\b/i, "Gemini"],
  [/\bvertex\b/i, "Vertex AI"],
  [/\b(?:moonshot|kimi)\b/i, "Kimi"],
  [/\bollama\b/i, "Ollama"],
];

const FAILURE_PATTERNS: Array<{
  failureClass: ProviderFailureClass;
  pattern: RegExp;
  label: string;
}> = [
  {
    failureClass: "billing",
    pattern: /credit balance|insufficient (?:credit|funds)|billing|payment required/i,
    label: "billing unavailable",
  },
  {
    failureClass: "authentication",
    pattern: /authentication|unauthorized|invalid api key|api key.*(?:invalid|missing)|forbidden/i,
    label: "authentication failed",
  },
  {
    failureClass: "rate-limit",
    pattern: /rate.?limit|too many requests|\b429\b/i,
    label: "rate limit reached",
  },
  {
    failureClass: "timeout",
    pattern: /timed? ?out|timeout|deadline exceeded/i,
    label: "request timed out",
  },
  {
    failureClass: "capacity",
    pattern: /overloaded|capacity|temporarily unavailable|service unavailable|\b503\b/i,
    label: "capacity unavailable",
  },
  {
    failureClass: "provider",
    pattern: /(?:llm|provider|model) (?:call |request )?(?:failed|error)|provider error/i,
    label: "provider failure",
  },
];

export function classifyProviderDiagnostic(
  text: string | null | undefined,
): ProviderDiagnostic | null {
  const detail = text?.trim();
  if (!detail) return null;

  const failure = FAILURE_PATTERNS.find(({ pattern }) => pattern.test(detail));
  if (!failure) return null;

  const provider = PROVIDERS.find(([pattern]) => pattern.test(detail))?.[1] ?? null;
  return {
    title: `${provider ?? "LLM provider"} ${failure.label}`,
    consequence: "Decision defaulted to HOLD",
    failureClass: failure.failureClass,
    provider,
    detail,
  };
}
