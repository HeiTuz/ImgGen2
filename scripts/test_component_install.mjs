import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

process.env.HEITUZ_INSTALLER_IMPORT = "1";
const { parse, selectComponent } = await import("./install.mjs");
const { selectedComponents, installationHealth, repairLegacyManifest } = await import("./imggen.mjs");
delete process.env.HEITUZ_INSTALLER_IMPORT;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "imggen-components-"));
try {
  for (const [answer, expected] of [["1", "imggen2"], ["2", "mpw"], ["3", "all"], ["", "imggen2"]]) {
    let asked = 0;
    assert.equal(await selectComponent(parse([]), { interactive: true, ask: async () => { asked++; return answer; } }), expected);
    assert.equal(asked, 1);
  }
  const noAsk = async () => { throw new Error("Must not prompt"); };
  assert.equal(await selectComponent(parse([]), { interactive: false, ask: noAsk }), "imggen2");
  assert.equal(await selectComponent(parse(["--dry-run"]), { interactive: true, ask: noAsk }), "imggen2");
  assert.equal(await selectComponent(parse(["--component", "mpw"]), { interactive: true, ask: noAsk }), "mpw");
  assert.throws(() => parse(["--component", "all", "--skip-mpw"]), /conflicts/);
  assert.throws(() => selectedComponents({}, ""), /must be/);
  assert.deepEqual(selectedComponents({}), ["imggen2"]);
  const legacy = repairLegacyManifest({version: 1, imggen2_target: path.join(temp, ".codex/skills/ImgGen2")}, {home: temp, windows: false});
  assert.equal(legacy.version, 2);
  assert.equal(legacy.agent_host, "codex");
  assert.deepEqual(selectedComponents(legacy), ["imggen2"]);
  assert.deepEqual(selectedComponents({ components: ["imggen2", "mpw"] }), ["imggen2", "mpw"]);
  assert.deepEqual(selectedComponents({ components: ["imggen2", "mpw"] }, "mpw"), ["mpw"]);

  if (!fs.existsSync(path.join(root, "agents"))) {
    console.log("component selection: OK (source-only install tests skipped)");
  } else {
    const bin = path.join(temp, "bin"); fs.mkdirSync(bin);
    const fake = path.join(bin, "fake-mpw.cjs");
    fs.writeFileSync(fake, `const fs=require('node:fs'),path=require('node:path');
const args=process.argv.slice(2),dest=args[args.indexOf('--dest')+1];
fs.appendFileSync(process.env.IMGGEN_TEST_CALLS,JSON.stringify(args)+'\\n');
if(!dest)process.exit(2);
fs.mkdirSync(dest,{recursive:true});
fs.writeFileSync(path.join(dest,'package.json'),JSON.stringify({name:'heituzmpw',version:'2.28.0'}));
fs.writeFileSync(path.join(dest,'SKILL.md'),'---\\nname: mpw\\n---\\n');
`);
    for (const command of ["npx", "python3", "python"]) {
      const isNpx = command === "npx";
      fs.writeFileSync(path.join(bin, command), `#!/bin/sh\n${isNpx ? 'exec "$IMGGEN_TEST_NODE" "$IMGGEN_TEST_MPW" "$@"' : 'exit 0'}\n`, { mode: 0o755 });
      fs.writeFileSync(path.join(bin, `${command}.cmd`), isNpx ? '@"%IMGGEN_TEST_NODE%" "%IMGGEN_TEST_MPW%" %*\r\n' : '@exit /b 0\r\n');
    }
    for (const component of ["imggen2", "mpw", "all"]) {
      const home = path.join(temp, component); fs.mkdirSync(home);
      const images = path.join(home, "image-skill"), prompts = path.join(home, "prompt-skill"), calls = path.join(home, "calls.jsonl");
      const result = spawnSync(process.execPath, [path.join(root, "scripts/install.mjs"), "--component", component, "--agent", "codex", "--target", images, "--mpw-target", prompts, "--skip-codex", "--no-register"], {
        encoding: "utf8", env: { ...process.env, HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: path.join(home, "config"), PATH: bin + path.delimiter + process.env.PATH,
          IMGGEN_TEST_NODE: process.execPath, IMGGEN_TEST_MPW: fake, IMGGEN_TEST_CALLS: calls, CI: "1" },
      });
      assert.equal(result.status, 0, result.stderr + result.stdout);
      assert.equal(fs.existsSync(path.join(images, "SKILL.md")), component !== "mpw");
      assert.equal(fs.existsSync(path.join(images, "vision-qc.json")), component !== "mpw");
      assert.equal(fs.existsSync(path.join(prompts, "SKILL.md")), component !== "imggen2");
      assert.equal(fs.existsSync(calls), component !== "imggen2");
      assert.equal(fs.existsSync(path.join(home, ".config/imggen/installation.json")), false);
      if (component !== "imggen2") {
        const call = JSON.parse(fs.readFileSync(calls, "utf8").trim());
        assert.deepEqual(call.slice(0, 6), ["--yes", "--allow-git=all", "--package", "github:HeiTuz/MPW", "heituzmpw", "--"]);
        assert.equal(call.includes("--force"), false);
        const health = installationHealth({ components: ["mpw"], imggen2_target: images, mpw_target: prompts });
        assert.equal(health.healthy, true, health.problems.join(", "));
      }
    }
    const offlineRoot = path.join(temp, "offline-refused");
    const refused = spawnSync(process.execPath, [path.join(root, "scripts/install.mjs"), "--component", "all", "--offline", "--target", offlineRoot], { encoding: "utf8" });
    assert.notEqual(refused.status, 0);
    assert.match(refused.stderr, /No components were installed/);
    assert.equal(fs.existsSync(offlineRoot), false);
    console.log("component selection, isolated installs, and optional MPW health: OK");
  }
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
