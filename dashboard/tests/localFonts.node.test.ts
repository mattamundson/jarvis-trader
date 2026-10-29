import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

const appDir = new URL("../app/", import.meta.url);

test("app fonts do not depend on the Google font loader", () => {
  for (const file of readdirSync(appDir, { recursive: true })) {
    if (!/\.[jt]sx?$/.test(file)) continue;
    const source = readFileSync(new URL(file, appDir), "utf8");
    assert.doesNotMatch(source, /["']next\/font\/google["']/, file);
  }
});

test("local font sources are checked-in WOFF2 files with redistribution licenses", () => {
  for (const file of ["layout.tsx", "command-center/page.tsx"]) {
    const fileUrl = new URL(file, appDir);
    const source = readFileSync(fileUrl, "utf8");
    const sources = [...source.matchAll(/src:\s*["']([^"']+\.woff2)["']/g)];
    assert.equal(sources.length, 2, `${file} must load both font families locally`);
    for (const [, src] of sources) {
      const font = readFileSync(new URL(src, fileUrl));
      assert.equal(font.toString("ascii", 0, 4), "wOF2", src);
    }
  }
  for (const name of ["Inter", "JetBrainsMono", "Orbitron"]) {
    const license = readFileSync(new URL(`fonts/${name}-OFL.txt`, appDir), "utf8");
    assert.match(license, /SIL OPEN FONT LICENSE/);
  }
});
