import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyProviderDiagnostic } from "../lib/providerDiagnostic.ts";

test("billing failures become compact HOLD diagnostics", () => {
  const result = classifyProviderDiagnostic(
    "trader LLM call failed: credit balance is too low; request_id=req_secret",
  );

  assert.equal(result?.failureClass, "billing");
  assert.equal(result?.consequence, "Decision defaulted to HOLD");
  assert.equal(result?.title.includes("req_secret"), false);
});

test("ordinary market reasoning is not classified as infrastructure failure", () => {
  assert.equal(classifyProviderDiagnostic("Momentum weakened below VWAP"), null);
});
