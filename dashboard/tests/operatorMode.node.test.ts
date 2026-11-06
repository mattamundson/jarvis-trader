import { test } from "node:test";
import assert from "node:assert/strict";
import {
  isScoreboardMode,
  isVercelDeployment,
  scoreboardRejectsMethod,
} from "../lib/operatorMode.ts";

test("scoreboard mode defaults off", () => {
  assert.equal(isScoreboardMode({} as NodeJS.ProcessEnv), false);
});

test("scoreboard mode turns on only for an explicit enable", () => {
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "0" } as NodeJS.ProcessEnv), false);
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "false" } as NodeJS.ProcessEnv), false);
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "1" } as NodeJS.ProcessEnv), true);
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "true" } as NodeJS.ProcessEnv), true);
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "yes" } as NodeJS.ProcessEnv), true);
});

test("scoreboard rejects mutations when enabled", () => {
  const env = { DASHBOARD_SCOREBOARD_MODE: "1" } as NodeJS.ProcessEnv;
  assert.equal(scoreboardRejectsMethod("POST", env), true);
  assert.equal(scoreboardRejectsMethod("PUT", env), true);
  assert.equal(scoreboardRejectsMethod("PATCH", env), true);
  assert.equal(scoreboardRejectsMethod("DELETE", env), true);
  assert.equal(scoreboardRejectsMethod("GET", env), false);
  assert.equal(scoreboardRejectsMethod("HEAD", env), false);
  assert.equal(scoreboardRejectsMethod("OPTIONS", env), false);
});

test("mutations pass through by default", () => {
  const env = {} as NodeJS.ProcessEnv;
  assert.equal(scoreboardRejectsMethod("POST", env), false);
  assert.equal(scoreboardRejectsMethod("PUT", env), false);
});

test("vercel audience is the VERCEL=1 flag", () => {
  assert.equal(isVercelDeployment({} as NodeJS.ProcessEnv), false);
  assert.equal(isVercelDeployment({ VERCEL: "1" } as NodeJS.ProcessEnv), true);
});
