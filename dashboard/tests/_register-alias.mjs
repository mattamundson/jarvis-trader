// Registers the "@/" path-alias resolve hook (./_alias-hooks.mjs) for the
// built-in Node test runner. Loaded via `node --import ./tests/_register-alias.mjs`
// in the test:unit script. Test-infra only.
import { register } from "node:module";

register("./_alias-hooks.mjs", import.meta.url);
