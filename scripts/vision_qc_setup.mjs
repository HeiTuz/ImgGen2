#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const status = process.argv.includes("--status");

if (status) {
  const configIndex = process.argv.indexOf("--config");
  const configPath = configIndex < 0
    ? path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "vision-qc.json")
    : process.argv[configIndex + 1];
  try {
    if (!configPath || configPath.startsWith("--")) throw new Error("missing config path");
    const config = fs.existsSync(configPath) ? JSON.parse(fs.readFileSync(configPath, "utf8")) : { qc_mode: "auto" };
    if (!["auto", "off"].includes(config?.qc_mode)) throw new Error("invalid QC mode");
    console.log(JSON.stringify({ vision_qc: config.qc_mode, reviewer: "host-default-vision" }));
  } catch {
    console.error("Cannot read saved QC mode; repair vision-qc.json with the installer.");
    process.exit(1);
  }
  process.exit(0);
}

console.log(`Vision-QC setup

ImgGen2 uses the host's default Vision model in auto mode.

Hermes configuration:
  auxiliary.vision.provider: auto
  auxiliary.vision.model: ""

Inspect or change the active host model with:
  hermes config
  hermes config set auxiliary.vision.provider auto
  hermes config set auxiliary.vision.model ""

No separate QC API key or pinned reviewer model is required.`);
