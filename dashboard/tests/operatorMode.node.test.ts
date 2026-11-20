import { test } from "node:test";
import assert from "node:assert/strict";
import {
  isScoreboardMode,
  isVercelDeployment,
  scoreboardRejectsMethod,
} from "../lib/operatorMode.ts";

test("scoreboard mode defaults on", () => {
  assert.equal(isScoreboardMode({} as NodeJS.ProcessEnv), true);
});

test("scoreboard mode turns off only for an explicit disable", () => {
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "0" } as NodeJS.ProcessEnv), false);
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "false" } as NodeJS.ProcessEnv), false);
  assert.equal(isScoreboardMode({ DASHBOARD_SCOREBOARD_MODE: "1" } as NodeJS.ProcessEnv), true);
});

test("scoreboard rejects mutations and allows reads", () => {
  const env = {} as NodeJS.ProcessEnv;
  assert.equal(scoreboardRejectsMethod("POST", env), true);
  assert.equal(scoreboardRejectsMethod("PUT", env), true);
  assert.equal(scoreboardRejectsMethod("PATCH", env), true);
  assert.equal(scoreboardRejectsMethod("DELETE", env), true);
  assert.equal(scoreboardRejectsMethod("GET", env), false);
  assert.equal(scoreboardRejectsMethod("HEAD", env), false);
  assert.equal(scoreboardRejectsMethod("OPTIONS", env), false);
});

test("an explicit disable lets mutations through the helper", () => {
  const env = { DASHBOARD_SCOREBOARD_MODE: "off" } as NodeJS.ProcessEnv;
  assert.equal(scoreboardRejectsMethod("POST", env), false);
});

test("vercel audience is the VERCEL=1 flag", () => {
  assert.equal(isVercelDeployment({} as NodeJS.ProcessEnv), false);
  assert.equal(isVercelDeployment({ VERCEL: "1" } as NodeJS.ProcessEnv), true);
});
