#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import {
  AGENT_HOST_PRIORITY,
  detectAgentHosts,
  deterministicAgentHosts,
  formatDetectedHosts,
  normalizeAgentHost,
  parseInteractiveAgentHosts,
} from "./agent_targets.mjs";


const source = fs.realpathSync(path.join(path.dirname(fileURLToPath(import.meta.url)), ".."));
const args = process.argv.slice(2);
export const ALLOWED_ROOTS = new Set(["SKILL.md", "README.md", "LICENSE", "package.json", "agents", "contracts", "examples", "references", "scripts"]);
export const COMPONENTS = new Set(["imggen2", "mpw", "all"]);
const VISION_QC_MODES = new Set(["auto", "off"]);
const AGENT_TARGETS = new Set(["auto", "all", ...AGENT_HOST_PRIORITY, "gpt"]);

export function normalizeInstallerPath(value, platform = process.platform, cwd = process.cwd()) {
  if (typeof value !== "string" || !value || value.includes("\0")) throw new Error("Install path must be a non-empty path without NUL bytes.");
  let candidate = value;
  if (/^file:/iu.test(candidate)) {
    const parsed = new URL(candidate);
    if (parsed.username || parsed.password) throw new Error("Install path file URI must not contain credentials.");
    if (platform === "win32" && parsed.hostname && parsed.hostname !== "localhost") {
      candidate = `\\\\${parsed.hostname}${decodeURIComponent(parsed.pathname).replaceAll("/", "\\")}`;
    } else {
      if (parsed.hostname && parsed.hostname !== "localhost") throw new Error("Remote file URI is not a local install path.");
      candidate = decodeURIComponent(parsed.pathname);
      if (platform === "win32" && /^\/[A-Za-z]:\//u.test(candidate)) candidate = candidate.slice(1).replaceAll("/", "\\");
    }
  }
  if (platform === "win32") {
    if (/^\/(?:Users|Volumes|Applications|System|Library)(?:\/|$)/u.test(candidate)) {
      throw new Error("Install path belongs to macOS and cannot be guessed on Windows; provide a real Windows/UNC path.");
    }
    const wsl = candidate.match(/^\/mnt\/([A-Za-z])(?:\/(.*))?$/u);
    if (wsl) candidate = `${wsl[1].toUpperCase()}:\\${(wsl[2] || "").replaceAll("/", "\\")}`.replace(/\\$/u, "");
    else if (/^\//u.test(candidate)) throw new Error("Install path is POSIX syntax and cannot be guessed on Windows; provide a real Windows/UNC path.");
    const resolved = path.win32.resolve(cwd, candidate);
    if (resolved.length >= 240 && !resolved.startsWith("\\\\?\\")) {
      return resolved.startsWith("\\\\") ? `\\\\?\\UNC\\${resolved.slice(2)}` : `\\\\?\\${resolved}`;
    }
    return resolved;
  }
  if (/^[A-Za-z]:[\\/]/u.test(candidate) || /^\\\\/u.test(candidate)) {
    throw new Error("Install path belongs to Windows and cannot be guessed on this host; provide its real local path.");
  }
  return path.resolve(cwd, candidate);
}

function usage(code = 0) {
  const out = code === 0 ? console.log : console.error;
  out(`ImgGen2 unified installer

Usage:
  npx --yes --package github:HeiTuz/ImgGen2 imggen-imggen2 -- [options]
  bunx --package github:HeiTuz/ImgGen2 imggen-imggen2 -- [options]

Options:
  --component <choice>   imggen2, mpw, or all; prompts in a terminal, defaults to imggen2 otherwise
  --agent <host>         Agent host: auto (default), all, hermes, claude, or codex
  --target <directory>   Explicit ImgGen2 installation directory
  --mpw-target <dir>     Explicit MPW installation directory
  --force                Replace existing destinations for the selected components
  --skip-codex           Do not install/update the official Codex CLI
  --skip-mpw             Compatibility alias for --component imggen2
  --vision-qc <mode>     Configure QC: auto (host default Vision model) or off
  --dry-run              Print the platform plan without writing or downloading
  --offline              Copy ImgGen2 locally; MPW requires online installation
  --register             Also register the global imggen launcher/manifest (default for non-offline installs)
  --no-register          Copy files only; leave the global launcher, manifest, and shell profiles untouched
  -h, --help             Show this help

After ImgGen2 install: imggen update [--component imggen2|mpw|all] [--dry-run] [--codex]
`);
  process.exit(code);
}

export function parse(argv) {
  const options = { component: null, agent: "auto", agentExplicit: false, target: null, mpwTarget: null, force: false, skipCodex: false, skipMpw: false, dryRun: false, offline: false, register: null, visionQc: null, visionQcExplicit: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "-h" || arg === "--help") usage(0);
    if (arg === "--") continue;
    if (arg === "--force") { options.force = true; continue; }
    if (arg === "--skip-codex") { options.skipCodex = true; continue; }
    if (arg === "--skip-mpw") { options.skipMpw = true; continue; }
    if (arg === "--dry-run") { options.dryRun = true; continue; }
    if (arg === "--offline") { options.offline = true; continue; }
    if (arg === "--register") { options.register = true; continue; }
    if (arg === "--no-register") { options.register = false; continue; }
    if (arg === "--component") { options.component = argv[++i]; if (!COMPONENTS.has(options.component)) usage(2); continue; }
    if (arg.startsWith("--component=")) { options.component = arg.slice("--component=".length); if (!COMPONENTS.has(options.component)) usage(2); continue; }
    if (arg === "--agent" || arg === "--target" || arg === "--mpw-target" || arg === "--vision-qc") {
      const value = argv[++i];
      if (!value) usage(2);
      if (arg === "--vision-qc") {
        if (!VISION_QC_MODES.has(value)) usage(2);
        options.visionQc = value;
        options.visionQcExplicit = true;
      } else if (arg === "--agent") {
        options.agent = value.toLowerCase();
        options.agentExplicit = true;
      } else {
        options[arg === "--target" ? "target" : "mpwTarget"] = value;
      }
      continue;
    }
    if (arg.startsWith("--agent=")) {
      options.agent = arg.slice("--agent=".length).toLowerCase();
      options.agentExplicit = true;
      continue;
    }
    if (arg.startsWith("--target=")) { options.target = arg.slice("--target=".length); continue; }
    if (arg.startsWith("--mpw-target=")) { options.mpwTarget = arg.slice("--mpw-target=".length); continue; }
    if (arg.startsWith("--vision-qc=")) {
      const value = arg.slice("--vision-qc=".length);
      if (!VISION_QC_MODES.has(value)) usage(2);
      options.visionQc = value;
      options.visionQcExplicit = true;
      continue;
    }
    usage(2);
  }
  if (!AGENT_TARGETS.has(options.agent)) usage(2);
  if (options.skipMpw && options.component && options.component !== "imggen2") throw new Error("--skip-mpw conflicts with --component; choose imggen2 or remove --skip-mpw.");
  if (options.offline) options.skipCodex = true;
  return options;
}

export async function selectComponent(options, { interactive = Boolean(process.stdin.isTTY && process.stdout.isTTY && !process.env.CI), ask } = {}) {
  if (options.component) return options.component;
  if (options.skipMpw || options.offline || options.dryRun || !interactive) return "imggen2";
  const prompt = "\nChoose what to install:\n  1  ImgGen2 — image production\n  2  MPW     — prompt writing\n  3  Both    — same agent host\nSelection [1]: ";
  let terminal;
  try {
    const question = ask || ((text) => {
      terminal = readline.createInterface({ input: process.stdin, output: process.stdout });
      return terminal.question(text);
    });
    const answer = (await question(prompt)).trim().toLowerCase();
    const selected = ({ "": "imggen2", "1": "imggen2", "2": "mpw", "3": "all" })[answer] || answer;
    if (!COMPONENTS.has(selected)) throw new Error("Choose 1 (ImgGen2), 2 (MPW), or 3 (both).");
    return selected;
  } finally { terminal?.close(); }
}

export function mpwInstallArgs(plan, { force = false } = {}) {
  const args = ["--yes", "--package", "github:HeiTuz/MPW", "heituzmpw", "--"];
  if (plan.host) args.push("--target", plan.host);
  args.push("--dest", plan.mpwTarget, "--quiet");
  if (force) args.push("--force");
  return args;
}

const EXCLUDED_PARTS = new Set([".git", ".gjc", ".omx", "node_modules", "docs-internal", "__pycache__"]);

export function shouldCopy(rel, { includeAgents = false } = {}) {
  const parts = rel.split(/[/\\]/u);
  if (!ALLOWED_ROOTS.has(parts[0])) return false;
  if (!includeAgents && parts[0] === "agents") return false;
  return !parts.some((part) => EXCLUDED_PARTS.has(part)) &&
    !path.basename(rel).startsWith(".") && !rel.endsWith(".pyc") && !rel.endsWith(".bak") && !rel.endsWith(".local.md");
}

function copyTree(current, destination, sourceRoot) {
  for (const entry of fs.readdirSync(current)) {
    const from = path.join(current, entry);
    const rel = path.relative(sourceRoot, from);
    if (!shouldCopy(rel)) continue;
    const to = path.join(destination, rel);
    const stat = fs.lstatSync(from);
    if (stat.isDirectory()) {
      fs.mkdirSync(to, { recursive: true });
      copyTree(from, destination, sourceRoot);
    } else if (stat.isFile()) {
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.copyFileSync(from, to, fs.constants.COPYFILE_EXCL);
      fs.chmodSync(to, stat.mode & 0o777);
    }
  }
}

function overlayEntryIsSafe(relative) {
  const parts = relative.split(/[/\\]/u);
  return !parts.some((part) => EXCLUDED_PARTS.has(part)) &&
    !path.basename(relative).startsWith(".") &&
    !relative.endsWith(".pyc") &&
    !relative.endsWith(".bak") &&
    !relative.endsWith(".local.md");
}

function copyOverlayTree(current, destination, overlayRoot) {
  for (const entry of fs.readdirSync(current)) {
    const from = path.join(current, entry);
    const rel = path.relative(overlayRoot, from);
    if (!overlayEntryIsSafe(rel)) continue;
    const to = path.join(destination, rel);
    const stat = fs.lstatSync(from);
    if (stat.isDirectory()) {
      fs.mkdirSync(to, { recursive: true });
      copyOverlayTree(from, destination, overlayRoot);
    } else if (stat.isFile()) {
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.copyFileSync(from, to);
      fs.chmodSync(to, stat.mode & 0o777);
    }
  }
}

function preserveLocalOverlays(current, destination, currentRoot = current) {
  for (const entry of fs.readdirSync(current)) {
    const from = path.join(current, entry);
    const stat = fs.lstatSync(from);
    if (stat.isDirectory()) {
      preserveLocalOverlays(from, destination, currentRoot);
    } else if (stat.isFile() && entry.endsWith(".local.md")) {
      const rel = path.relative(currentRoot, from);
      const to = path.join(destination, rel);
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.copyFileSync(from, to);
      fs.chmodSync(to, stat.mode & 0o777);
    }
  }
}

function validateHostOverlay(sourceRoot, host) {
  const normalized = normalizeAgentHost(host);
  const overlay = path.join(sourceRoot, "agents", normalized);
  if (!fs.existsSync(overlay) || !fs.statSync(overlay).isDirectory()) {
    throw new Error(`Install source is missing the ${normalized} agent overlay`);
  }
  if (normalized !== "hermes" && !fs.existsSync(path.join(overlay, "SKILL.md"))) {
    throw new Error(`Install source is missing agents/${normalized}/SKILL.md`);
  }
  const allowed = new Set(["AGENTS.md", "README.md", "SKILL.md"]);
  for (const entry of fs.readdirSync(overlay)) {
    if (!allowed.has(entry)) throw new Error(`Unsupported ${normalized} overlay entry: ${entry}`);
  }
  return overlay;
}

function countSkillEntries(directory) {
  let count = 0;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) count += countSkillEntries(candidate);
    else if (entry.isFile() && entry.name === "SKILL.md") count += 1;
  }
  return count;
}

export function installPayload({ sourceRoot = source, destination, host = null }) {
  fs.mkdirSync(destination, { recursive: true });
  copyTree(sourceRoot, destination, sourceRoot);
  const overlay = host ? validateHostOverlay(sourceRoot, host) : null;
  if (overlay) copyOverlayTree(overlay, destination, overlay);
  if (fs.existsSync(path.join(destination, "agents"))) {
    throw new Error(`Install verification failed: agents/ must not appear in ${destination}`);
  }
  if (!fs.existsSync(path.join(destination, "SKILL.md"))) {
    throw new Error(`Install verification failed: SKILL.md missing in ${destination}`);
  }
  if (countSkillEntries(destination) !== 1) {
    throw new Error(`Install verification failed: expected exactly one SKILL.md in ${destination}`);
  }
}

function run(command, commandArgs, { dryRun, label }) {
  if (dryRun) { console.log(`[dry-run] ${label}: ${[command, ...commandArgs].map(JSON.stringify).join(" ")}`); return; }
  const result = spawnSync(command, commandArgs, { stdio: "inherit" });
  if (result.error || result.status !== 0) throw new Error(`${label} failed${result.error ? `: ${result.error.message}` : ` (exit ${result.status})`}`);
}

function ensurePillow(loc, options) {
  if (options.offline || options.dryRun) return;
  const python = loc.windows ? "python" : "python3";
  const probe = spawnSync(python, ["-c", "from PIL import Image"], { stdio: "ignore" });
  if (!probe.error && probe.status === 0) return;
  const install = spawnSync(python, ["-m", "pip", "install", "--user", "Pillow>=10,<13"], { stdio: "inherit" });
  if (install.error || install.status !== 0) {
    console.warn(
      "Pillow could not be installed automatically (for example on a PEP 668 externally-managed Python). " +
      "Reference/edit/product-photo Vision-QC thumbnails require Pillow; install it later via a virtual environment, pipx, or your package manager. " +
      "Continuing the installation without it; simple text-only generation remains available.",
    );
  }
}
async function selectVisionQc(options) {
  const requested = options.visionQc || "auto";
  return { requested, effective: requested };
}

function configureVisionQc(destination, selection) {
  const config = path.join(destination, "vision-qc.json");
  fs.writeFileSync(config, JSON.stringify({ version: 2, requested_mode: selection.requested, qc_mode: selection.effective, reviewer: "host-default-vision" }, null, 2) + "\n", { mode: 0o600 });
  return config;
}

function migrateLegacyPath(from, to, label, dryRun = false) {
  if (!fs.existsSync(from)) return false;
  if (path.resolve(from) === path.resolve(to)) return false;
  if (fs.existsSync(to)) {
    throw new Error(`Legacy ${label} exists at ${from}, but the new destination already exists at ${to}; reconcile the two explicitly instead of overwriting either.`);
  }
  if (dryRun) return true;
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.renameSync(from, to);
  return true;
}

export function migrateLegacyInstallPaths(home, loc, { dryRun = false, component = "imggen2" } = {}) {
  const legacyConfig = loc.windows
    ? path.join(process.env.APPDATA || path.join(home, "AppData", "Roaming"), "HeiTuz")
    : path.join(process.env.XDG_CONFIG_HOME || path.join(home, ".config"), "heituz");
  const legacyImgGen = path.join(home, ".hermes", "skills", "HeiTuzImgGen2");
  const legacyImgGenLower = path.join(home, ".hermes", "skills", "HeiTuzimgGen2");
  const legacyMpw = path.join(home, ".hermes", "skills", "prompt-writing", "HeiTuzMPW");
  const moves = [
    [legacyConfig, loc.config, "ImgGen2 config"],
    [legacyImgGen, path.join(home, ".hermes", "skills", "ImgGen2"), "ImgGen2 skill"],
    [legacyImgGenLower, path.join(home, ".hermes", "skills", "ImgGen2"), "ImgGen2 skill"],
    [legacyMpw, path.join(home, ".hermes", "skills", "prompt-writing", "MPW"), "MPW skill"],
  ];
  const seen = new Set();
  return moves.filter(([, , label]) => label === "MPW skill" ? component !== "imggen2" : component !== "mpw").filter(([from, to, label]) => {
    if (!fs.existsSync(from)) return false;
    const info = fs.statSync(from);
    const identity = `${info.dev}:${info.ino}`;
    if (seen.has(identity)) return false;
    seen.add(identity);
    return migrateLegacyPath(from, to, label, dryRun);
  }).map(([from, to]) => ({ from, to }));
}


export function hostInstallPlan(homeDir, host) {
  const normalized = normalizeAgentHost(host);
  if (!AGENT_HOST_PRIORITY.includes(normalized)) throw new Error(`Unsupported agent host: ${host}`);
  if (normalized === "hermes") {
    return {
      host: normalized,
      destination: path.resolve(path.join(homeDir, ".hermes", "skills", "ImgGen2")),
      mpwTarget: path.resolve(path.join(homeDir, ".hermes", "skills", "prompt-writing", "MPW")),
    };
  }
  return {
    host: normalized,
    destination: path.resolve(path.join(homeDir, `.${normalized}`, "skills", "ImgGen2")),
    mpwTarget: path.resolve(path.join(homeDir, `.${normalized}`, "skills", "MPW")),
  };
}

function inferHostFromDestinations(homeDir, destination, mpwTarget) {
  for (const host of AGENT_HOST_PRIORITY) {
    const known = hostInstallPlan(homeDir, host);
    const imgMatches = path.normalize(destination) === path.normalize(known.destination);
    const mpwMatches = path.normalize(mpwTarget) === path.normalize(known.mpwTarget);
    if (imgMatches && mpwMatches) return host;
  }
  return null;
}

function inferHostFromProvidedDestinations(homeDir, destination, mpwTarget) {
  const matches = [];
  for (const host of AGENT_HOST_PRIORITY) {
    const known = hostInstallPlan(homeDir, host);
    if ((destination && path.normalize(destination) === path.normalize(known.destination)) ||
        (mpwTarget && path.normalize(mpwTarget) === path.normalize(known.mpwTarget))) {
      matches.push(host);
    }
  }
  const unique = [...new Set(matches)];
  if (unique.length > 1) throw new Error("Explicit ImgGen2 and MPW targets select different agent hosts");
  return unique[0] || null;
}

async function chooseInteractiveHosts(detected) {
  console.log(`Detected agent environments: ${formatDetectedHosts(detected)}`);
  const recommended = deterministicAgentHosts("auto", detected)[0];
  const prompt = `Install target(s) [${recommended}] (comma-separated ${AGENT_HOST_PRIORITY.join(", ")}; all = every detected): `;
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    return parseInteractiveAgentHosts(await terminal.question(prompt), detected);
  } finally {
    terminal.close();
  }
}

async function resolveInstallPlans(options, homeDir) {
  if (options.target || options.mpwTarget) {
    const explicitHost = options.agentExplicit && !["auto", "all"].includes(options.agent)
      ? normalizeAgentHost(options.agent)
      : null;
    const providedDestination = options.target ? normalizeInstallerPath(options.target) : null;
    const providedMpwTarget = options.mpwTarget ? normalizeInstallerPath(options.mpwTarget) : null;
    const inferredHost = inferHostFromProvidedDestinations(homeDir, providedDestination, providedMpwTarget);
    if (explicitHost && inferredHost && explicitHost !== inferredHost) {
      throw new Error("Explicit --agent conflicts with the supplied installation directory");
    }
    const host = explicitHost || inferredHost;
    const defaults = hostInstallPlan(homeDir, host || "hermes");
    const destination = providedDestination || defaults.destination;
    const mpwTarget = providedMpwTarget || defaults.mpwTarget;
    return [{ host: host || inferHostFromDestinations(homeDir, destination, mpwTarget), destination, mpwTarget }];
  }
  const detected = detectAgentHosts({ homeDir, existsSync: fs.existsSync });
  const interactive = options.agent === "auto" && process.stdin.isTTY && process.stdout.isTTY && !process.env.CI;
  const hosts = interactive
    ? await chooseInteractiveHosts(detected)
    : deterministicAgentHosts(options.agent, detected);
  return hosts.map((host) => hostInstallPlan(homeDir, host));
}

function pathsOverlap(left, right) {
  const a = path.resolve(left);
  const b = path.resolve(right);
  return a === b || a.startsWith(b + path.sep) || b.startsWith(a + path.sep);
}

function validateDestination(destination, loc) {
  const resolved = path.resolve(destination);
  const filesystemRoot = path.parse(resolved).root;
  const protectedContainers = [
    ".hermes",
    path.join(".hermes", "skills"),
    ".claude",
    path.join(".claude", "skills"),
    ".codex",
    path.join(".codex", "skills"),
  ].map((relative) => path.resolve(loc.home, relative));
  if (resolved === filesystemRoot || path.dirname(resolved) === filesystemRoot ||
      resolved === path.resolve(loc.home) || protectedContainers.includes(resolved)) {
    throw new Error(`Refusing unsafe install destination: ${resolved}`);
  }
  for (const protectedPath of [source, loc.config, loc.bin]) {
    if (pathsOverlap(resolved, protectedPath)) throw new Error(`Refusing unsafe install destination: ${resolved}`);
  }
}

function prepareInstallPlans(plans, force, loc, components = ["imggen2"]) {
  const destinations = plans.flatMap((plan) => components.map((component) => component === "mpw" ? plan.mpwTarget : plan.destination));
  for (let index = 0; index < destinations.length; index += 1) {
    const destination = destinations[index];
    validateDestination(destination, loc);
    if (destinations.slice(index + 1).some((other) => pathsOverlap(destination, other))) {
      throw new Error("Selected install destinations must not overlap");
    }
    if (fs.existsSync(destination) && !force) {
      throw new Error(`Refusing to overwrite existing installation: ${destination}; rerun with --force.`);
    }
  }
}

export function installPlansTransaction(plans, visionQc, { sourceRoot = source } = {}) {
  const staged = [];
  try {
    for (const plan of plans) {
      const parent = path.dirname(plan.destination);
      fs.mkdirSync(parent, { recursive: true });
      const stageRoot = fs.mkdtempSync(path.join(parent, ".imggenimggen2-stage-"));
      const payload = path.join(stageRoot, "payload");
      staged.push({ ...plan, stageRoot, payload });
      installPayload({ sourceRoot, destination: payload, host: plan.host });
      configureVisionQc(payload, plan.visionQc || visionQc);
      if (fs.existsSync(plan.destination)) preserveLocalOverlays(plan.destination, payload);
    }
    const applied = [];
    try {
      for (let index = 0; index < staged.length; index += 1) {
        const item = staged[index];
        const backup = `${item.destination}.imggenimggen2-backup-${process.pid}-${Date.now()}-${index}`;
        const hadDestination = fs.existsSync(item.destination);
        if (hadDestination) fs.renameSync(item.destination, backup);
        try {
          fs.renameSync(item.payload, item.destination);
        } catch (error) {
          if (hadDestination) fs.renameSync(backup, item.destination);
          throw error;
        }
        applied.push({ destination: item.destination, backup: hadDestination ? backup : null });
      }
    } catch (error) {
      for (const item of applied.reverse()) {
        fs.rmSync(item.destination, { recursive: true, force: true });
        if (item.backup && fs.existsSync(item.backup)) fs.renameSync(item.backup, item.destination);
      }
      throw error;
    }
    for (const item of applied) {
      if (item.backup) fs.rmSync(item.backup, { recursive: true, force: true });
    }
  } finally {
    for (const item of staged) fs.rmSync(item.stageRoot, { recursive: true, force: true });
  }
  return plans.map((plan) => path.join(plan.destination, "vision-qc.json"));
}

export async function main(argv = args) {
  const options = parse(argv);
  const component = await selectComponent(options);
  const components = component === "all" ? ["imggen2", "mpw"] : [component];
  const installImages = components.includes("imggen2");
  const installPrompts = components.includes("mpw");
  if (!installImages && options.target && !options.mpwTarget) throw new Error("MPW destination uses --mpw-target; --target selects an ImgGen2 directory.");
  if (options.offline && installPrompts && !options.dryRun) throw new Error("MPW requires an online install; remove --offline or use --component imggen2. No components were installed.");
  process.env.HEITUZ_INSTALLER_IMPORT = "1";
  const helper = await import(pathToFileURL(path.join(source, "scripts", "imggen.mjs")).href);
  delete process.env.HEITUZ_INSTALLER_IMPORT;
  const loc = helper.locations();
  const migratedLegacyPaths = migrateLegacyInstallPaths(loc.home, loc, { dryRun: options.dryRun, component });
  const plans = await resolveInstallPlans(options, loc.home);
  const primary = plans[0];
  const visionQc = installImages ? await selectVisionQc(options) : { requested: "off", effective: "off" };
  for (const plan of plans) {
    plan.visionQc = visionQc;
    const migration = options.dryRun && migratedLegacyPaths.find((move) => path.resolve(move.to) === path.resolve(plan.destination));
    const previous = path.join(migration ? migration.from : plan.destination, "vision-qc.json");
    if (installImages && !options.visionQcExplicit && fs.existsSync(previous)) {
      let saved;
      try { saved = JSON.parse(fs.readFileSync(previous, "utf8")); }
      catch { throw new Error(`Cannot read existing QC config: ${previous}; use --vision-qc auto or --vision-qc off to explicitly repair it.`); }
      if (!VISION_QC_MODES.has(saved.qc_mode)) throw new Error(`Invalid existing QC config: ${previous}`);
      plan.visionQc = { requested: VISION_QC_MODES.has(saved.requested_mode) ? saved.requested_mode : saved.qc_mode, effective: saved.qc_mode };
    }
  }
  const register = installImages && (options.register ?? !options.offline);

  if (options.dryRun) {
    console.log(JSON.stringify({
      components,
      will_install_codex: installImages && !options.skipCodex && !helper.codexExists(loc.windows),
      mpw_commands: installPrompts ? plans.map((plan) => mpwInstallArgs(plan, options)) : [],
      agent_targets: plans.map((plan) => plan.host).filter(Boolean),
      installs: plans.map((plan) => ({
        agent: plan.host,
        imggen2_target: plan.destination,
        mpw_target: plan.mpwTarget,
        vision_qc: installImages ? { requested_mode: plan.visionQc.requested, mode: plan.visionQc.effective } : null,
      })),
      imggen2_target: primary.destination,
      mpw_target: primary.mpwTarget,
      codex: helper.codexInstallCommand(loc.windows),
      platform: loc.windows ? "windows" : "posix",
      register,
      migrated_legacy_paths: migratedLegacyPaths,
      vision_qc: installImages ? {
        requested_mode: primary.visionQc.requested,
        mode: primary.visionQc.effective,
        config: path.join(primary.destination, "vision-qc.json"),
      } : null,
    }, null, 2));
    return;
  }

  prepareInstallPlans(plans, options.force, loc, components);
  if (installImages) ensurePillow(loc, options);
  if (register) {
    helper.assertPersistentTargets({
      installations: plans.map((plan) => ({
        components,
        agent_host: plan.host,
        imggen2_target: plan.destination,
        mpw_target: plan.mpwTarget,
        vision_qc: installImages ? { requested_mode: plan.visionQc.requested, mode: plan.visionQc.effective } : null,
      })),
    }, { windows: loc.windows });
  }
  const visionQcConfigs = installImages ? installPlansTransaction(plans, visionQc) : [];

  if (installImages && !options.skipCodex && !helper.codexExists(loc.windows)) {
    const codexPlan = helper.codexInstallCommand(loc.windows);
    run(codexPlan.command, codexPlan.args, { dryRun: false, label: "official Codex CLI install" });
  }
  if (installPrompts) {
    for (const plan of plans) {
      const invocation = helper.npxInvocation(loc.windows, mpwInstallArgs(plan, options));
      run(invocation.command, invocation.args, { dryRun: false, label: `MPW install${plan.host ? ` (${plan.host})` : ""}` });
      const manifest = JSON.parse(fs.readFileSync(path.join(plan.mpwTarget, "package.json"), "utf8"));
      if (manifest.name !== "heituzmpw" || !fs.existsSync(path.join(plan.mpwTarget, "SKILL.md"))) throw new Error("MPW installer did not materialize the expected skill.");
      console.log(`Installed MPW${plan.host ? ` (${plan.host})` : ""} to ${plan.mpwTarget}`);
    }
  }
  if (!installImages) return;

  if (!register) {
    for (const plan of plans) console.log(`Installed ImgGen2${plan.host ? ` (${plan.host})` : ""} to ${plan.destination}`);
    console.log("Global launcher and manifest were not registered (offline/test install); rerun with --register to make the first target active.");
    return;
  }

  fs.mkdirSync(loc.config, { recursive: true });
  fs.copyFileSync(path.join(primary.destination, "scripts", "imggen.mjs"), path.join(loc.config, "imggen.mjs"));
  fs.writeFileSync(loc.manifest, JSON.stringify({
    version: 2,
    components,
    agent_host: primary.host,
    imggen2_target: primary.destination,
    mpw_target: primary.mpwTarget,
    imggen2_repo: "github:HeiTuz/ImgGen2",
    mpw_repo: "github:HeiTuz/MPW",
    vision_qc_requested: primary.visionQc.requested,
    vision_qc_mode: primary.visionQc.effective,
    vision_qc_config: visionQcConfigs[0],
    installations: plans.map((plan, index) => ({
      agent_host: plan.host,
      imggen2_target: plan.destination,
      mpw_target: plan.mpwTarget,
      components,
      vision_qc_config: visionQcConfigs[index],
      vision_qc_requested: plan.visionQc.requested,
      vision_qc_mode: plan.visionQc.effective,
    })),
  }, null, 2) + "\n", { mode: 0o600 });
  fs.mkdirSync(loc.bin, { recursive: true });
  if (loc.windows) {
    const cmdLauncher = path.join(loc.bin, "imggen.cmd");
    const psLauncher = path.join(loc.bin, "imggen.ps1");
    const gitBashLauncher = path.join(loc.home, ".local", "bin", "imggen");
    for (const stale of [path.join(loc.bin, "imggen"), path.join(loc.bin, "imggen.mjs")]) {
      fs.rmSync(stale, { force: true });
    }
    fs.writeFileSync(cmdLauncher, `@echo off\r\nnode "%APPDATA%\\ImgGen2\\imggen.mjs" %*\r\n`);
    fs.writeFileSync(psLauncher, `& node "$env:APPDATA\\ImgGen2\\imggen.mjs" @args\r\nexit $LASTEXITCODE\r\n`);
    fs.mkdirSync(path.dirname(gitBashLauncher), { recursive: true });
    fs.writeFileSync(gitBashLauncher, `#!/bin/sh\nappdata="$APPDATA"\ncase "$appdata" in\n  [A-Za-z]:\\\\*) appdata="$(cygpath -u "$appdata")" ;;\nesac\nexec node "$appdata/ImgGen2/imggen.mjs" "$@"\n`, { mode: 0o755 });
    fs.chmodSync(gitBashLauncher, 0o755);
    const begin = "# >>> imggen user bin >>>";
    const end = "# <<< imggen user bin <<<";
    for (const profile of [path.join(loc.home, ".profile"), path.join(loc.home, ".zprofile"), path.join(loc.home, ".bash_profile"), path.join(loc.home, ".bashrc")]) {
      if (!fs.existsSync(profile)) continue;
      const existing = fs.readFileSync(profile, "utf8");
      const marker = new RegExp(`${begin}[^]*?${end}\\r?\\n?`, "gu");
      const repaired = existing.replace(marker, "");
      if (repaired !== existing) fs.writeFileSync(profile, repaired);
    }
    if (process.platform === "win32") {
      const escapedBin = loc.bin.replace(/'/g, "''");
      const escapedConfig = loc.config.replace(/'/g, "''");
      const pathScript = [
        "$p = [Environment]::GetEnvironmentVariable('Path', 'User')",
        "$parts = @($p -split ';' | Where-Object { $_ })",
        `$parts = @($parts | Where-Object { -not ($_.TrimEnd('\\') -ieq '${escapedBin}'.TrimEnd('\\')) -and -not ($_.TrimEnd('\\') -ieq '${escapedConfig}'.TrimEnd('\\')) })`,
        `[Environment]::SetEnvironmentVariable('Path', (('${escapedBin}', $parts) | ForEach-Object { $_ } | Where-Object { $_ }) -join ';', 'User')`,
      ].join("; ");
      run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", pathScript], { dryRun: false, label: "Windows user PATH repair" });
    }
  } else {
    const launcher = path.join(loc.bin, "imggen");
    fs.writeFileSync(launcher, `#!/bin/sh\nexec node "${path.join(loc.config, "imggen.mjs")}" "$@"\n`, { mode: 0o755 });
    fs.chmodSync(launcher, 0o755);
    const begin = "# >>> imggen user bin >>>";
    const end = "# <<< imggen user bin <<<";
    for (const profile of [path.join(loc.home, ".profile"), path.join(loc.home, ".zprofile")]) {
      const existing = fs.existsSync(profile) ? fs.readFileSync(profile, "utf8") : "";
      if (!existing.includes(begin)) {
        fs.appendFileSync(profile, `${existing.endsWith("\n") || !existing ? "" : "\n"}${begin}\nexport PATH="$HOME/.local/bin:$PATH"\n${end}\n`);
      }
    }
  }
  for (const plan of plans) console.log(`Installed ImgGen2${plan.host ? ` (${plan.host})` : ""} to ${plan.destination}`);
  console.log("Open a new terminal, then run: imggen update");
}

function isMainModule() {
  if (!process.argv[1]) return false;
  try {
    return fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
  }
}

if (isMainModule()) {
  main().catch((error) => { console.error(`ImgGen2 installer: ${error.message}`); process.exitCode = 1; });
}
