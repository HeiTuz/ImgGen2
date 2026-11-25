#!/usr/bin/env node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(os.tmpdir(), `HeiTuz-install-smoke-${process.pid}`);
try {
  const result = spawnSync(process.execPath, [
    path.join(root, "scripts", "install.mjs"),
    "--offline", "--no-register", "--force", "--target", target,
  ], { cwd: root, encoding: "utf8" });
  if (result.error || result.status !== 0) {
    throw new Error(result.error?.message || result.stderr || result.stdout || `installer exited ${result.status}`);
  }
  if (!fs.existsSync(path.join(target, "SKILL.md"))) throw new Error("installed SKILL.md is missing");
  console.log(`cross-platform install smoke: OK (${target})`);
} finally {
  fs.rmSync(target, { recursive: true, force: true });
}
