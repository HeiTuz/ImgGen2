#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const npmCli = process.env.npm_execpath;
assert.ok(npmCli, "npm_execpath is required for packaged helper smoke");

function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, encoding: "utf8" });
  assert.equal(result.status, 0, `${command} ${args.join(" ")} failed: ${result.stderr || result.stdout}`);
  return result.stdout;
}

const candidates = process.platform === "win32"
  ? [["python", []], ["py", ["-3"]], ["python3", []]]
  : [["python3", []], ["python", []]];
let python = null;
for (const [command, prefix] of candidates) {
  const probe = spawnSync(command, [...prefix, "--version"], { encoding: "utf8" });
  if (!probe.error && probe.status === 0) {
    python = [command, prefix];
    break;
  }
}
assert.ok(python, "Python 3 was not found on PATH");

const temp = fs.mkdtempSync(path.join(os.tmpdir(), "imggenimggen2-packaged-helper-"));
try {
  const dryRunReport = JSON.parse(run(process.execPath, [npmCli, "pack", "--dry-run", "--json"]));
  // npm <= 11 reports an array of packages; npm 12 keys the report by package name.
  const dryRun = Array.isArray(dryRunReport) ? dryRunReport[0] : Object.values(dryRunReport)[0];
  const names = dryRun.files.map((file) => file.path);
  for (const required of [
    "scripts/folder_batch_prepare.py",
    "scripts/test_folder_batch_prepare.py",
    "examples/dint-shared-folder-apparel-batch.md",
  ]) assert.equal(names.includes(required), true, `npm package omits ${required}`);

  const packDestination = path.join(temp, "pack");
  fs.mkdirSync(packDestination);
  run(process.execPath, [npmCli, "pack", "--silent", "--pack-destination", packDestination]);
  const tarballs = fs.readdirSync(packDestination).filter((name) => name.endsWith(".tgz"));
  assert.equal(tarballs.length, 1, "npm pack did not produce exactly one tarball");
  const consumer = path.join(temp, "consumer");
  fs.mkdirSync(consumer);
  run(process.execPath, [npmCli, "install", "--ignore-scripts", "--no-audit", "--no-fund", path.join(packDestination, tarballs[0])], consumer);

  const installed = path.join(consumer, "node_modules", "imggen-imggen2-skill");
  const [command, prefix] = python;
  run(command, [...prefix, path.join(installed, "scripts", "folder_batch_prepare.py"), "--help"], consumer);
  const source = path.join(temp, "source");
  fs.mkdirSync(source);
  for (const name of ["f1.jpg", "b1.jpg", "d1_원단.jpg"]) fs.writeFileSync(path.join(source, name), name);
  const stdout = run(command, [...prefix, path.join(installed, "scripts", "folder_batch_prepare.py"), "--input-dir", source, "--work-root", path.join(temp, "work"), "--dry-run"], consumer);
  const result = JSON.parse(stdout);
  assert.equal(result.dry_run, true);
  assert.equal(result.counts.sources, 3);
  assert.equal(result.runner, null);
  console.log("packaged helper: OK");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
