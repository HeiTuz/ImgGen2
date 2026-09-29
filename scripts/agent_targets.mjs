import path from "node:path";

export const AGENT_HOST_PRIORITY = Object.freeze(["claude", "codex"]);

const HOST_ALIASES = Object.freeze({ gpt: "codex" });
const HOST_SIGNAL_DIRS = Object.freeze({
  claude: [".claude", path.join(".claude", "skills")],
  codex: [".codex", path.join(".codex", "skills")],
});

export function normalizeAgentHost(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return HOST_ALIASES[normalized] || normalized;
}

export function detectAgentHosts({ homeDir, existsSync, cliSignals = {} }) {
  if (typeof homeDir !== "string" || !homeDir) throw new TypeError("homeDir is required");
  if (typeof existsSync !== "function") throw new TypeError("existsSync is required");
  return AGENT_HOST_PRIORITY.filter((host) =>
    Boolean(cliSignals[host]) || HOST_SIGNAL_DIRS[host].some((relative) => existsSync(path.join(homeDir, relative))));
}

function orderedUniqueHosts(values) {
  const requested = new Set(values.map(normalizeAgentHost));
  return AGENT_HOST_PRIORITY.filter((host) => requested.has(host));
}

export function deterministicAgentHosts(requested, detectedHosts) {
  const target = normalizeAgentHost(requested || "auto");
  const detected = orderedUniqueHosts(detectedHosts || []);
  if (target === "all") return detected.length ? detected : ["codex"];
  if (target === "auto") return [detected[0] || "codex"];
  if (!AGENT_HOST_PRIORITY.includes(target)) throw new Error(`Unsupported agent host: ${requested}`);
  return [target];
}

export function parseInteractiveAgentHosts(answer, detectedHosts) {
  const value = String(answer || "").trim().toLowerCase();
  if (!value) return deterministicAgentHosts("auto", detectedHosts);
  if (value === "all") return deterministicAgentHosts("all", detectedHosts);
  const hosts = value.split(/[\s,]+/u).filter(Boolean).map(normalizeAgentHost);
  const unsupported = hosts.find((host) => !AGENT_HOST_PRIORITY.includes(host));
  if (unsupported) throw new Error(`Unsupported agent host: ${unsupported}`);
  const unique = [...new Set(hosts)];
  if (!unique.length) throw new Error("Choose at least one agent host");
  return unique;
}

export function formatDetectedHosts(detectedHosts) {
  const detected = orderedUniqueHosts(detectedHosts || []);
  return detected.length ? detected.join(", ") : "none (Codex fallback)";
}
