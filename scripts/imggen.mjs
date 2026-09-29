#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const IMGGEN_REPO = "github:HeiTuz/ImgGen2";
export const MPW_PLUGIN_NOTICE = "MPW is installed as the plugin mpw@heituz, not by ImgGen2. Codex: codex plugin marketplace add HeiTuz/heituz-plugins && codex plugin add mpw@heituz. Claude Code: claude plugin marketplace add HeiTuz/heituz-plugins && claude plugin install mpw@heituz.";

const REPAIR_COMMAND = "bunx --package github:HeiTuz/ImgGen2 imggen-imggen2 -- --component imggen2 --force --register";
export function selectedComponents(installation, requested = null) {
  if (requested !== null && !["imggen2", "mpw", "all"].includes(requested)) throw new Error("--component must be imggen2, mpw, or all");
  const values = requested !== null ? (requested === "all" ? ["imggen2", "mpw"] : [requested]) : (installation.components || ["imggen2"]);
  if (!Array.isArray(values) || !values.length || values.some((value) => !["imggen2", "mpw"].includes(value))) throw new Error("Invalid installation components");
  // MPW moved to the mpw@heituz plugin; a legacy or requested "mpw" component selects nothing here.
  return values.includes("imggen2") ? ["imggen2"] : [];
}

export function mentionsMpw(manifest, requested = null) {
  if (requested === "mpw" || requested === "all") return true;
  return manifestInstallations(manifest).some((installation) => Boolean(installation.mpw_target) || (Array.isArray(installation.components) && installation.components.includes("mpw")));
}

function platform() {
  return process.env.HEITUZ_TEST_PLATFORM || process.platform;
}

export function locations() {
  const home = os.homedir();
  const windows = platform() === "win32";
  const config = windows
    ? path.join(process.env.APPDATA || path.join(home, "AppData", "Roaming"), "ImgGen2")
    : path.join(process.env.XDG_CONFIG_HOME || path.join(home, ".config"), "imggen");
  const bin = windows ? path.join(process.env.LOCALAPPDATA || path.join(home, "AppData", "Local"), "ImgGen2", "bin") : path.join(home, ".local", "bin");
  return { home, windows, config, bin, manifest: path.join(config, "installation.json") };
}

export function isTransientWindowsPath(candidate, env = process.env) {
  if (typeof candidate !== "string" || !candidate) return false;
  const normalized = path.win32.resolve(candidate).toLowerCase().replaceAll("/", "\\");
  const roots = [env.TEMP, env.TMP, env.TMPDIR]
    .filter((value) => typeof value === "string" && /^(?:[A-Za-z]:[\\/]|\\\\)/u.test(value))
    .map((value) => path.win32.resolve(value).toLowerCase().replaceAll("/", "\\"));
  if (roots.some((root) => normalized === root || normalized.startsWith(`${root}\\`))) return true;
  return /\\(?:_npx|npx|bunx|\.bun\\install\\cache|npm-cache)\\|\\_cacache\\tmp\\/iu.test(normalized);
}

export function assertPersistentTargets(manifest, { windows = locations().windows, env = process.env } = {}) {
  if (!windows) return;
  for (const installation of manifestInstallations(manifest)) {
    const selected = selectedComponents(installation);
    for (const [label, candidate] of [["ImgGen2", selected.includes("imggen2") && installation.imggen2_target]]) {
      if (isTransientWindowsPath(candidate, env)) {
        throw new Error(`${label} target is inside a transient TEMP/npx/bunx path: ${candidate}`);
      }
    }
  }
}

function inferredAgentHost(home, installation) {
  const normalized = (value) => path.resolve(value);
  for (const host of ["claude", "codex"]) {
    const imggen = path.join(home, `.${host}`, "skills", "ImgGen2");
    if (normalized(installation.imggen2_target) === normalized(imggen)) return host;
  }
  return null;
}

function withoutMpw(manifest) {
  if (!mentionsMpw(manifest)) return manifest;
  const strip = (entry) => {
    const { mpw_target: _target, mpw_repo: _repo, ...rest } = entry;
    return Array.isArray(rest.components) ? { ...rest, components: rest.components.filter((component) => component !== "mpw") } : rest;
  };
  const repaired = strip(manifest);
  if (Array.isArray(manifest.installations)) repaired.installations = manifest.installations.map(strip);
  return repaired;
}

export function repairLegacyManifest(manifest, options = {}) {
  return withoutMpw(repairV1Manifest(manifest, options));
}

function repairV1Manifest(manifest, { home = locations().home, windows = locations().windows, env = process.env } = {}) {
  if (manifest.version !== 1) return manifest;
  const installations = manifestInstallations(manifest);
  if (installations.length !== 1 || !installations[0].imggen2_target) {
    throw new Error(`Legacy v1 manifest is ambiguous. Repair with: ${REPAIR_COMMAND}`);
  }
  try {
    assertPersistentTargets(manifest, { windows, env });
  } catch (error) {
    throw new Error(`Legacy v1 manifest is transient and cannot be persisted. Repair with: ${REPAIR_COMMAND}. ${error.message}`);
  }
  const host = inferredAgentHost(home, installations[0]);
  if (!host || (installations[0].agent_host && installations[0].agent_host !== host)) {
    throw new Error(`Legacy v1 manifest target is not an unambiguous active agent installation. Repair with: ${REPAIR_COMMAND}`);
  }
  const repaired = { ...manifest, version: 2, agent_host: host };
  repaired.installations = [{ agent_host: host, imggen2_target: manifest.imggen2_target, vision_qc_config: manifest.vision_qc_config }];
  return repaired;
}

function installedVersion(target) {
  try {
    const value = JSON.parse(fs.readFileSync(path.join(target, "package.json"), "utf8")).version;
    return typeof value === "string" && value ? value : null;
  } catch {
    return null;
  }
}

export function writeJsonAtomic(destination, value) {
  const temporary = `${destination}.tmp-${process.pid}-${Date.now()}`;
  try {
    fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + "\n", { mode: 0o600, flag: "wx" });
    fs.renameSync(temporary, destination);
    fs.chmodSync(destination, 0o600);
  } finally {
    fs.rmSync(temporary, { force: true });
  }
}

export function installationHealth(manifest, loc = locations()) {
  const problems = [];
  const installations = manifestInstallations(manifest);
  const target_status = installations.map((installation) => {
    const imggen2_exists = Boolean(installation.imggen2_target && fs.existsSync(installation.imggen2_target));
    const imggen2_version = installation.imggen2_target ? installedVersion(installation.imggen2_target) : null;
    const imageManaged = selectedComponents(installation).includes("imggen2");
    const status = {
      components: selectedComponents(installation),
      agent_host: installation.agent_host || null,
      imggen2_target: installation.imggen2_target || null,
      imggen2_exists,
      imggen2_version,
    };
    if (imageManaged && !installation.imggen2_target) problems.push("manifest target is incomplete");
    if (imageManaged && !imggen2_exists) problems.push(`ImgGen2 target missing: ${installation.imggen2_target}`);
    else if (imageManaged && !fs.existsSync(path.join(installation.imggen2_target, "scripts", "imggen.mjs"))) problems.push(`updater missing from ${installation.imggen2_target}`);
    if (imageManaged && !imggen2_version) problems.push(`ImgGen2 installed version unreadable at ${installation.imggen2_target}`);
    if (installation.agent_host === "hermes") problems.push("Hermes installations are no longer supported; reinstall with --agent codex or --agent claude");
    return status;
  });
  const launcher_surfaces = loc.windows
    ? {
        cmd: path.join(loc.bin, "imggen.cmd"),
        powershell: path.join(loc.bin, "imggen.ps1"),
        git_bash: path.join(loc.home, ".local", "bin", "imggen"),
      }
    : { posix: path.join(loc.bin, "imggen") };
  const launcherExpectations = loc.windows
    ? { cmd: /%APPDATA%\\ImgGen2\\imggen\.mjs/iu, powershell: /\$env:APPDATA\\ImgGen2\\imggen\.mjs/iu, git_bash: /\$appdata\/HeiTuz\/imggen\.mjs/u }
    : { posix: /imggen\.mjs/u };
  for (const [surface, launcher] of (installations.some((installation) => selectedComponents(installation).includes("imggen2")) ? Object.entries(launcher_surfaces) : [])) {
    if (!fs.existsSync(launcher)) {
      problems.push(`${surface} launcher missing: ${launcher}`);
      continue;
    }
    const content = fs.readFileSync(launcher, "utf8");
    if (!launcherExpectations[surface].test(content) || (loc.windows && isTransientWindowsPath(content))) {
      problems.push(`${surface} launcher does not target the persistent updater: ${launcher}`);
    }
  }
  const launcher_paths = Object.values(launcher_surfaces);
  return {
    healthy: problems.length === 0,
    problems,
    repair_recommendation: problems.length ? REPAIR_COMMAND : null,
    selected_launcher_path: launcher_paths[0],
    launcher_surfaces,
    launcher_paths,
    target_status,
    installed_versions: target_status.map(({ agent_host, imggen2_version }) => ({ agent_host, imggen2_version })),
  };
}

export function ensureBun(windows, { run = spawnSync, home = os.homedir(), env = process.env } = {}) {
  if (run("bun", ["--version"], { stdio: "ignore" }).status === 0) return "bun";
  const local = path.join(env.BUN_INSTALL || path.join(home, ".bun"), "bin", windows ? "bun.exe" : "bun");
  if (run(local, ["--version"], { stdio: "ignore" }).status === 0) return local;
  const installer = windows
    ? { command: "powershell.exe", args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://bun.com/install.ps1 | iex"] }
    : { command: "bash", args: ["-c", "curl -fsSL https://bun.com/install | bash"] };
  const result = run(installer.command, installer.args, { stdio: "inherit" });
  if (result.error || result.status !== 0 || run(local, ["--version"], { stdio: "ignore" }).status !== 0) {
    throw new Error("Bun installation failed. See https://bun.com/docs/installation and retry.");
  }
  return local;
}

export function packageInvocation(_windows, args, bunCommand = "bun") {
  return { command: bunCommand, args: ["x", ...args] };
}

export function codexExists(windows) {
  const home = os.homedir();
  const installDir = process.env.CODEX_INSTALL_DIR;
  const canonical = windows
    ? path.join(process.env.LOCALAPPDATA || path.join(home, "AppData", "Local"), "Programs", "OpenAI", "Codex", "bin", "codex.exe")
    : path.join(home, ".local", "bin", "codex");
  const configured = installDir ? path.join(installDir, windows ? "codex.exe" : "codex") : null;
  return [configured, canonical].filter(Boolean).some((candidate) => fs.existsSync(candidate));
}

export function codexInstallCommand(windows) {
  return windows
    ? { command: "powershell.exe", args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://chatgpt.com/codex/install.ps1 | iex"] }
    : { command: "sh", args: ["-c", "curl -fsSL https://chatgpt.com/codex/install.sh | sh"] };
}

function run(command, args, { dryRun = false, label }) {
  const rendered = [command, ...args].map((part) => JSON.stringify(part)).join(" ");
  if (dryRun) {
    console.log(`[dry-run] ${label}: ${rendered}`);
    return;
  }
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.error || result.status !== 0) {
    throw new Error(`${label} failed${result.error ? `: ${result.error.message}` : ` (exit ${result.status})`}`);
  }
}

function usage(code = 0) {
  const out = code === 0 ? console.log : console.error;
  out(`HeiTuz unified updater

Usage:
  imggen update [--component imggen2] [--dry-run] [--codex]
  imggen status
  imggen vision-qc setup
  imggen vision-qc status

Commands:
  update       Refresh the registered ImgGen2 installations.
               Codex updates only when missing or when --codex is supplied.
               MPW is the separate plugin mpw@heituz (github.com/HeiTuz/heituz-plugins).
  status       Print the recorded installation targets.
  vision-qc    Show the host-default Vision QC mode or setup guidance.
`);
  process.exit(code);
}

export function imggenUpdateArgs(manifest, { interactive }) {
  const args = ["--package", IMGGEN_REPO, "imggen-imggen2", "--", "--component", "imggen2"];
  if (manifest.agent_host) args.push("--agent", manifest.agent_host);
  args.push("--target", manifest.imggen2_target, "--force", "--skip-codex", "--no-register");
  // Per-host saved QC settings remain owned by the installed configuration.
  return args;
}

export function manifestInstallations(manifest) {
  if (Array.isArray(manifest.installations) && manifest.installations.length) {
    return manifest.installations.map((installation) => ({ ...manifest, ...installation, installations: undefined }));
  }
  return [manifest];
}

export function update(manifest, { dryRun, forceCodex, component = null, interactive = Boolean(process.stdin.isTTY && process.stdout.isTTY) }) {
  const { windows } = locations();
  if (mentionsMpw(manifest, component)) console.log(MPW_PLUGIN_NOTICE);
  const installations = manifestInstallations(manifest).map((installation) => ({ ...installation, components: selectedComponents(installation, component) }));
  if (installations.some((installation) => installation.agent_host === "hermes")) {
    throw new Error("Hermes installations are no longer supported; reinstall ImgGen2 with --agent codex or --agent claude.");
  }
  assertPersistentTargets({ installations }, { windows });
  if (installations.some((installation) => installation.components.includes("imggen2") && !installation.imggen2_target)) {
    throw new Error("Installation manifest is incomplete; rerun the ImgGen2 installer.");
  }
  if (forceCodex && !installations.some((installation) => installation.components.includes("imggen2"))) throw new Error("--codex requires the ImgGen2 component");
  if (installations.some((installation) => installation.components.includes("imggen2")) && (forceCodex || !codexExists(windows))) {
    const plan = codexInstallCommand(windows);
    run(plan.command, plan.args, { dryRun, label: "official Codex CLI install/update" });
  }
  const bunCommand = dryRun ? "bun" : ensureBun(windows);
  for (const installation of installations) {
    const hostLabel = installation.agent_host ? ` (${installation.agent_host})` : "";
    if (installation.components.includes("imggen2")) {
      const imggen = packageInvocation(windows, imggenUpdateArgs(installation, { interactive }), bunCommand);
      run(imggen.command, imggen.args, { dryRun, label: `ImgGen2 update${hostLabel}` });
    }
  }
  if (!dryRun) {
    const health = installationHealth({ ...manifest, installations });
    if (!health.healthy) throw new Error(`Update completed but installation remains degraded: ${health.problems.join("; ")}`);
  }
}

function main(argv) {
  const command = argv[0] || "help";
  const tail = argv.slice(1);
  let component = null;
  for (let index = 0; index < tail.length; index += 1) {
    if (tail[index] === "--component") { component = tail[index + 1]; if (!component || component.startsWith("--")) throw new Error("--component needs imggen2"); tail.splice(index, 2); index -= 1; }
    else if (tail[index].startsWith("--component=")) { component = tail[index].slice(12); tail.splice(index, 1); index -= 1; }
  }
  if (component !== null) selectedComponents({}, component);
  const flags = new Set(tail);
  if (command === "help" || command === "--help" || command === "-h") usage(0);
  const loc = locations();
  const { manifest } = loc;
  if (!fs.existsSync(manifest)) throw new Error(`HeiTuz installation manifest is missing: ${manifest}`);
  const original = JSON.parse(fs.readFileSync(manifest, "utf8"));
  const data = repairLegacyManifest(original);
  if (data !== original && command === "update" && !flags.has("--dry-run")) writeJsonAtomic(manifest, data);
  if (command !== "update") assertPersistentTargets(data);
  if (command === "status") {
    const health = installationHealth(data, loc);
    console.log(JSON.stringify({
      ...data,
      manifest_path: manifest,
      manifest_version: data.version ?? null,
      codex_present: codexExists(loc.windows),
      ...health,
    }, null, 2));
    if (!health.healthy) process.exitCode = 1;
    return;
  }
  if (command === "vision-qc") {
    const action = argv[1] || "setup";
    if (!new Set(["setup", "status"]).has(action) || argv.length !== 2) usage(2);
    const setup = path.join(data.imggen2_target, "scripts", "vision_qc_setup.mjs");
    if (!fs.existsSync(setup)) throw new Error("Vision-QC setup is unavailable; run imggen update.");
    run(process.execPath, [setup, ...(action === "status" ? ["--status"] : [])], { label: "Vision-QC setup" });
    return;
  }
  if (command !== "update") usage(2);
  for (const flag of flags) {
    if (!new Set(["--dry-run", "--codex"]).has(flag)) usage(2);
  }
  update(data, { dryRun: flags.has("--dry-run"), forceCodex: flags.has("--codex"), component });
  if (!flags.has("--dry-run")) console.log("Selected components are updated.");
}

if (!process.env.HEITUZ_INSTALLER_IMPORT) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`imggen: ${error.message}`);
    process.exitCode = 1;
  }
}
