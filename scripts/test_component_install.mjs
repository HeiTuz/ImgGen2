import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

process.env.HEITUZ_INSTALLER_IMPORT = "1";
const { parse, selectComponent } = await import("./install.mjs");
const { selectedComponents, installationHealth, mentionsMpw, repairLegacyManifest } = await import("./imggen.mjs");
delete process.env.HEITUZ_INSTALLER_IMPORT;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "imggen-components-"));
try {
  // MPW moved to the mpw@heituz plugin: ImgGen2 never prompts for or installs it.
  assert.equal(await selectComponent(parse([])), "imggen2");
  assert.equal(await selectComponent(parse(["--component", "mpw"])), "mpw");
  assert.equal(await selectComponent(parse(["--component", "all"])), "all");
  assert.throws(() => parse(["--component", "all", "--skip-mpw"]), /conflicts/);
  assert.throws(() => selectedComponents({}, ""), /must be/);
  assert.deepEqual(selectedComponents({}), ["imggen2"]);
  const legacy = repairLegacyManifest({version: 1, imggen2_target: path.join(temp, ".codex/skills/ImgGen2")}, {home: temp, windows: false});
  assert.equal(legacy.version, 2);
  assert.equal(legacy.agent_host, "codex");
  assert.deepEqual(selectedComponents(legacy), ["imggen2"]);
  assert.deepEqual(selectedComponents({ components: ["imggen2", "mpw"] }), ["imggen2"]);
  assert.deepEqual(selectedComponents({ components: ["imggen2", "mpw"] }, "mpw"), []);
  assert.equal(mentionsMpw({ components: ["imggen2"] }), false);
  assert.equal(mentionsMpw({ components: ["imggen2"] }, "all"), true);
  assert.equal(mentionsMpw({ installations: [{ components: ["imggen2", "mpw"] }] }), true);

  if (!fs.existsSync(path.join(root, "agents"))) {
    console.log("component selection: OK (source-only install tests skipped)");
  } else {
    const bin = path.join(temp, "bin"); fs.mkdirSync(bin);
    for (const command of ["python3", "python"]) {
      fs.writeFileSync(path.join(bin, command), "#!/bin/sh\nexit 0\n", { mode: 0o755 });
      fs.writeFileSync(path.join(bin, `${command}.cmd`), "@exit /b 0\r\n");
    }
    for (const component of ["imggen2", "mpw", "all"]) {
      const home = path.join(temp, component); fs.mkdirSync(home);
      const images = path.join(home, "image-skill"), prompts = path.join(home, "prompt-skill");
      const result = spawnSync(process.execPath, [path.join(root, "scripts/install.mjs"), "--component", component, "--agent", "codex", "--target", images, "--mpw-target", prompts, "--skip-codex", "--no-register"], {
        encoding: "utf8", env: { ...process.env, HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: path.join(home, "config"), PATH: bin + path.delimiter + process.env.PATH, CI: "1" },
      });
      assert.equal(result.status, 0, result.stderr + result.stdout);
      assert.equal(fs.existsSync(path.join(images, "SKILL.md")), component !== "mpw");
      assert.equal(fs.existsSync(path.join(images, "vision-qc.json")), component !== "mpw");
      assert.equal(fs.existsSync(prompts), false, "ImgGen2 must not install MPW");
      assert.match(result.stderr, /mpw@heituz/u, "every run with --mpw-target or an MPW component explains the plugin route");
      assert.equal(fs.existsSync(path.join(home, ".config/imggen/installation.json")), false);
    }
    const hermes = spawnSync(process.execPath, [path.join(root, "scripts/install.mjs"), "--agent", "hermes", "--offline", "--target", path.join(temp, "hermes-refused")], { encoding: "utf8" });
    assert.notEqual(hermes.status, 0);
    assert.equal(fs.existsSync(path.join(temp, "hermes-refused")), false);
    const health = installationHealth({ components: ["imggen2"], agent_host: "hermes", imggen2_target: path.join(temp, "imggen2", "image-skill") });
    assert.equal(health.problems.some((problem) => /Hermes installations are no longer supported/u.test(problem)), true);
    console.log("component selection, isolated installs, and MPW plugin guidance: OK");
  }
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
