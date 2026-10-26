import { chromium } from "@playwright/test";

const user = process.env.MC_USER;
const pass = process.env.MC_PASS;
if (!user || !pass) {
  throw new Error("Missing required environment variable MC_USER or MC_PASS");
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({
  httpCredentials: { username: user, password: pass },
});
await page.goto("http://127.0.0.1:3010/mission-control", {
  waitUntil: "domcontentloaded",
  timeout: 60000,
});
await page.waitForTimeout(9000);
const text = await page.locator("body").innerText();
const lines = text
  .split(/\n/)
  .map((line) => line.trim())
  .filter(Boolean);
const keep = lines.filter((line) =>
  /Current DD|Halt|Avg Loss|Equity|trades|Drawdown|No contracts|Loading chain|OFFLINE|DATA|SPX|Health|Engine online|Options|OPRA/i.test(
    line,
  ),
);
console.log(keep.slice(0, 50).join("\n"));
console.log("HAS_6_42=" + /6\.42/.test(text));
console.log("HAS_6_41=" + /6\.41/.test(text));
console.log("HAS_6_48=" + /6\.48/.test(text));
console.log("HAS_12_08=" + /12\.08/.test(text));
console.log("NO_CONTRACTS=" + text.includes("No contracts"));
console.log("LOADING_CHAIN=" + text.includes("Loading chain"));
console.log("PAGE_LEN=" + text.length);
await browser.close();
