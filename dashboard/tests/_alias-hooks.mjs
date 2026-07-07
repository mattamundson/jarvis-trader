// Node ESM resolve hook: map the dashboard's "@/..." path alias (defined in
// tsconfig paths, "@/*" -> "./*") to real files so the built-in `node --test`
// runner can load modules that use it. tsc/next understand "@/"; plain Node does
// not. Registered by tests/_register-alias.mjs via module.register(), loaded by
// the test:unit script with `--import`. Test-infra only — never imported by app code.
import { fileURLToPath, pathToFileURL } from "node:url";
import { existsSync } from "node:fs";
import path from "node:path";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) {
    let target = path.join(projectRoot, specifier.slice(2));
    if (!path.extname(target)) {
      for (const ext of [".ts", ".tsx", ".js", ".mjs"]) {
        if (existsSync(target + ext)) {
          target += ext;
          break;
        }
      }
    }
    return nextResolve(pathToFileURL(target).href, context);
  }
  return nextResolve(specifier, context);
}
