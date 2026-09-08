#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const script = path.join(root, "scripts", "vision_qc_setup.mjs");

const setup = spawnSync(process.execPath, [script], { cwd: root, encoding: "utf8" });
assert.equal(setup.status, 0, setup.stderr || setup.stdout);
assert.match(setup.stdout, /host's default Vision model/);
assert.match(setup.stdout, /auxiliary\.vision\.provider: auto/);
assert.match(setup.stdout, /auxiliary\.vision\.model: ""/);
assert.doesNotMatch(setup.stdout, /GOOGLE_API_KEY|GEMINI_API_KEY/);

const status = spawnSync(process.execPath, [script, "--status"], { cwd: root, encoding: "utf8" });
assert.equal(status.status, 0, status.stderr || status.stdout);
assert.deepEqual(JSON.parse(status.stdout), { vision_qc: "auto", reviewer: "host-default-vision" });

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "imggen-qc-status-"));
try {
  const config = path.join(temporary, "vision-qc.json");
  fs.writeFileSync(config, JSON.stringify({ version: 2, qc_mode: "off" }));
  const off = spawnSync(process.execPath, [script, "--status", "--config", config], { encoding: "utf8" });
  assert.equal(off.status, 0);
  assert.equal(JSON.parse(off.stdout).vision_qc, "off");
  fs.writeFileSync(config, "invalid");
  const invalid = spawnSync(process.execPath, [script, "--status", "--config", config], { encoding: "utf8" });
  assert.equal(invalid.status, 1);
  assert.equal(invalid.stdout, "");
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}

console.log("Vision-QC setup: OK");
