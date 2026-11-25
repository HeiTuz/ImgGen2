#!/usr/bin/env node
import assert from "node:assert/strict";
import { normalizeInstallerPath } from "./install.mjs";

assert.throws(
  () => normalizeInstallerPath("/Users/alice/.hermes/skills/HeiTuz", "win32", "C:\\work"),
  /belongs to macOS/u,
);
assert.throws(
  () => normalizeInstallerPath("/home/alice/HeiTuz", "win32", "C:\\work"),
  /POSIX syntax/u,
);
assert.throws(
  () => normalizeInstallerPath("C:\\Users\\alice\\HeiTuz", "darwin", "/tmp"),
  /belongs to Windows/u,
);
assert.equal(
  normalizeInstallerPath("/mnt/c/Users/alice/HeiTuz", "win32", "C:\\work"),
  "C:\\Users\\alice\\HeiTuz",
);
assert.equal(
  normalizeInstallerPath("file:///C:/Users/Alice/My%20Skills/HeiTuz", "win32", "C:\\work"),
  "C:\\Users\\Alice\\My Skills\\HeiTuz",
);
assert.equal(
  normalizeInstallerPath("file://server/share/HeiTuz", "win32", "C:\\work"),
  "\\\\server\\share\\HeiTuz",
);
const longPath = `C:\\work\\${"nested\\".repeat(40)}HeiTuz`;
assert.match(normalizeInstallerPath(longPath, "win32", "C:\\work"), /^\\\\\?\\C:\\/u);

console.log("Windows and cross-OS installer paths: OK");
