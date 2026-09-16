#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "imggenimggen2-install-"));

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, encoding: "utf8" });
  assert.equal(result.status, 0, `${command} failed: ${result.stderr || result.stdout}`);
  return result.stdout;
}

function hasExcludedPath(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const name = entry.name;
    if (name.startsWith(".") || ["docs-internal", "node_modules", "__pycache__"].includes(name) || name.endsWith(".pyc") || name.includes(".bak")) return true;
    if (entry.isDirectory() && hasExcludedPath(path.join(dir, name))) return true;
  }
  return false;
}

try {
  const destination = path.join(temp, "installed");
  run(process.execPath, ["scripts/install.mjs", "--target", destination, "--offline"]);
  assert.equal(fs.existsSync(path.join(destination, "SKILL.md")), true);
  assert.equal(fs.existsSync(path.join(destination, "contracts", "v1", "image-production-handoff.schema.json")), true);
  assert.equal(hasExcludedPath(destination), false, "installer copied excluded local state");
  assert.equal(fs.existsSync(path.join(destination, "agents")), false, "installer leaked distribution overlays");

  const npmCli = process.env.npm_execpath;
  assert.ok(npmCli, "npm_execpath is required for package privacy smoke");
  const packedReport = JSON.parse(run(process.execPath, [npmCli, "pack", "--dry-run", "--json"]));
  // npm <= 11 reports an array of packages; npm 12 keys the report by package name.
  const packed = Array.isArray(packedReport) ? packedReport[0] : Object.values(packedReport)[0];
  const names = packed.files.map((file) => file.path);
  const packageFiles = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).files;
  assert.equal(packageFiles.includes("agents/**"), true, "npm files allowlist omits agent overlays");
  if (fs.existsSync(path.join(root, "agents"))) {
    assert.equal(names.some((name) => name.startsWith("agents/")), true, "npm package omits agent overlays");
  }
  assert.equal(names.includes("contracts/v1/image-production-handoff.schema.json"), true,
    "npm package omits the public handoff schema");
  assert.equal(names.includes("examples/batch_100_variations.py"), true,
    "npm package omits the reusable bulk-variation entrypoint");
  for (const example of [
    "examples/preset_runner.py",
    "examples/indie_editorial_100.py",
    "examples/fashion_moodboard_80.py",
    "examples/album_cover_directions_40.py",
    "examples/character_silhouettes_64.py",
    "examples/package_concepts_50.py",
    "examples/interior_directions_48.py",
    "examples/single_mpw_enhanced.py",
  ]) {
    assert.equal(names.includes(example), true, `npm package omits ${example}`);
  }
  assert.equal(names.some((name) => /(^|\/)\.[^/]+|(^|\/)(?:docs-internal|node_modules|__pycache__)(?:\/|$)|\.pyc$|\.bak/u.test(name)), false,
    "npm package includes excluded local state");
  console.log("installer/package privacy allowlist: OK");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
