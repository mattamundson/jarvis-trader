import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEEP_TOOL_GROUPS,
  PRIMARY_NAV_GROUPS,
  routeOwner,
} from "../lib/navigation.ts";

test("command-center and mission-control have distinct ownership", () => {
  assert.equal(routeOwner("/command-center"), "operate");
  assert.equal(routeOwner("/mission-control"), "system");
});

test("primary navigation contains at most twelve destinations", () => {
  assert.ok(PRIMARY_NAV_GROUPS.flatMap((group) => group.items).length <= 12);
});

test("primary and deep-tool destinations do not overlap", () => {
  const primary = PRIMARY_NAV_GROUPS.flatMap((group) => group.items).map((item) => item.href);
  const deep = DEEP_TOOL_GROUPS.flatMap((group) => group.items).map((item) => item.href);

  assert.deepEqual(primary.filter((href) => deep.includes(href)), []);
});
