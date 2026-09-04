import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const envCandidates = [
  path.resolve(__dirname, ".env.local"),
  path.resolve(__dirname, "..", "..", "jarvis-trader", "dashboard", ".env.local"),
];

for (const envPath of envCandidates) {
  if (!fs.existsSync(envPath)) continue;
  for (const raw of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    const value = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
    if (!(key in process.env)) {
      process.env[key] = value;
    }
  }
}

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:3010",
    httpCredentials:
      process.env.DASHBOARD_AUTH_USER && process.env.DASHBOARD_AUTH_PASS
        ? {
            username: process.env.DASHBOARD_AUTH_USER,
            password: process.env.DASHBOARD_AUTH_PASS,
          }
        : undefined,
    launchOptions: {
      executablePath: process.env.PW_CHROME || undefined,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
  },
});
