#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (!fs.existsSync(path.join(root, "agents", "codex", "SKILL.md"))) {
  console.log("unified install/update dry-run: SKIP (install artifact has no source overlays)");
  process.exit(0);
}
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "heituz-skill-unified-"));
process.env.HEITUZ_INSTALLER_IMPORT = "1";
const { ensureBun, skillUpdateArgs, isTransientWindowsPath, packageInvocation, repairLegacyManifest } = await import("./heituz-skill.mjs");
delete process.env.HEITUZ_INSTALLER_IMPORT;

function invoke(args, env = {}, command = process.execPath) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, HOME: temp, USERPROFILE: temp, XDG_CONFIG_HOME: path.join(temp, "config"), ...env },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return result.stdout;
}

function hostDestination(home, host) {
  return path.join(home, `.${host}`, "skills", "HeiTuz");
}

try {
  const updateManifest = { imggen2_target: "/tmp/heituz-skill", vision_qc_requested: "auto" };
  const interactiveUpdate = skillUpdateArgs(updateManifest, { interactive: true });
  assert.equal(interactiveUpdate.includes("--vision-qc"), false);
  const automatedUpdate = skillUpdateArgs(updateManifest, { interactive: false });
  assert.equal(automatedUpdate.includes("--vision-qc"), false);
  const packageArgs = ["--package", "github:HeiTuz/heituz-skill", "heituz-skill", "--", "--agent", "codex"];
  assert.deepEqual(packageInvocation(false, packageArgs), { command: "bun", args: ["x", ...packageArgs] });
  assert.deepEqual(packageInvocation(true, packageArgs, "C:\\Users\\alice\\.bun\\bin\\bun.exe"), { command: "C:\\Users\\alice\\.bun\\bin\\bun.exe", args: ["x", ...packageArgs] });
  for (const windows of [false, true]) {
    const calls = [];
    let localChecks = 0;
    const home = windows ? "C:\\Users\\alice" : "/tmp/alice";
    const installed = ensureBun(windows, { home, env: {}, run(command, args) {
      calls.push([command, args]);
      if (command === "bun") return { status: 1 };
      if (command === "bash" || command === "powershell.exe") return { status: 0 };
      localChecks += 1;
      return { status: localChecks === 1 ? 1 : 0 };
    } });
    assert.match(installed, /\.bun[/\\]bin[/\\]bun(?:\.exe)?$/u);
    assert.equal(calls.length, 4);
    assert.match(calls[2][1].at(-1), /bun\.com\/install/u);
  }
  assert.throws(() => ensureBun(false, { home: "/tmp/alice", env: {}, run: () => ({ status: 1 }) }), /Bun installation failed/u);
  const customBunRoot = path.join(temp, "custom-bun");
  const customBunBin = path.join(customBunRoot, "bin", "bun");
  assert.equal(ensureBun(false, { home: temp, env: { BUN_INSTALL: customBunRoot }, run: (command) => ({ status: command === customBunBin ? 0 : 1 }) }), customBunBin);
  assert.equal(isTransientWindowsPath("C:\\Users\\alice\\AppData\\Local\\Temp\\_npx\\123\\package", { TEMP: "C:\\Users\\alice\\AppData\\Local\\Temp" }), true);
  assert.equal(isTransientWindowsPath("C:\\Users\\alice\\.codex\\skills\\HeiTuz", { TEMP: "C:\\Users\\alice\\AppData\\Local\\Temp" }), false);
  const repairHome = path.join(temp, "repair-home");
  const legacy = {
    version: 1,
    imggen2_target: path.join(repairHome, ".codex", "skills", "HeiTuz"),
    mpw_target: path.join(repairHome, ".codex", "skills", "MPW"),
  };
  const repairedLegacy = repairLegacyManifest(legacy, { home: repairHome, windows: false });
  assert.equal(repairedLegacy.installations[0].agent_host, "codex");
  assert.equal("mpw_target" in repairedLegacy, false);
  assert.equal("mpw_target" in repairedLegacy.installations[0], false);
  const v2WithMpw = repairLegacyManifest({ version: 2, components: ["heituz", "mpw"], imggen2_target: legacy.imggen2_target, mpw_target: legacy.mpw_target, mpw_repo: "github:HeiTuz/MPW", installations: [{ agent_host: "codex", components: ["heituz", "mpw"], imggen2_target: legacy.imggen2_target, mpw_target: legacy.mpw_target }] }, { home: repairHome, windows: false });
  assert.deepEqual(v2WithMpw.components, ["heituz"]);
  assert.deepEqual(v2WithMpw.installations[0].components, ["heituz"]);
  assert.equal("mpw_repo" in v2WithMpw, false);
  assert.throws(() => repairLegacyManifest({ version: 1, imggen2_target: path.join(repairHome, ".hermes", "skills", "HeiTuz") }, { home: repairHome, windows: false }), /Repair with: bunx/u);
  assert.throws(
    () => repairLegacyManifest({ ...legacy, imggen2_target: path.join(repairHome, "custom") }, { home: repairHome, windows: false }),
    /Repair with: bunx/u,
  );
  assert.throws(
    () => repairLegacyManifest({
      version: 1,
      imggen2_target: "C:\\Users\\alice\\AppData\\Local\\Temp\\_npx\\123\\package",
      mpw_target: "C:\\Users\\alice\\.codex\\skills\\MPW",
    }, { home: "C:\\Users\\alice", windows: true, env: { TEMP: "C:\\Users\\alice\\AppData\\Local\\Temp" } }),
    /transient.*Repair with: bunx --package github:HeiTuz\/heituz-skill heituz-skill/iu,
  );
  const plan = invoke(["scripts/install.mjs", "--dry-run"], { HEITUZ_TEST_PLATFORM: "win32", LOCALAPPDATA: path.join(temp, "local"), APPDATA: path.join(temp, "roaming") });
  assert.match(plan, /powershell\.exe/);
  assert.match(plan, /install\.ps1/);
  assert.doesNotMatch(plan, /mpw_target|mpw_commands/u);
  const offlineVisionPlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--vision-qc", "auto", "--offline"], { HEITUZ_TEST_PLATFORM: "linux" }));
  assert.equal(offlineVisionPlan.vision_qc.requested_mode, "auto");
  assert.equal(offlineVisionPlan.vision_qc.mode, "auto");
  assert.match(offlineVisionPlan.vision_qc.config, /vision-qc\.json$/);
  const forwardedPlan = JSON.parse(invoke(["scripts/install.mjs", "--", "--dry-run", "--offline", "--agent", "claude"], { HEITUZ_TEST_PLATFORM: "linux" }));
  assert.deepEqual(forwardedPlan.agent_targets, ["claude"]);
  const updateHome = path.join(temp, "home-update-claude");
  const updatePlan = JSON.parse(invoke([
    "scripts/install.mjs", "--dry-run", "--offline",
    "--target", path.join(updateHome, ".claude", "skills", "HeiTuz"),
    "--mpw-target", path.join(updateHome, ".claude", "skills", "MPW"),
  ], { HOME: updateHome, USERPROFILE: updateHome, HEITUZ_TEST_PLATFORM: "linux", CI: "1" }));
  assert.deepEqual(updatePlan.agent_targets, ["claude"]);
  const partialOverridePlan = JSON.parse(invoke([
    "scripts/install.mjs", "--dry-run", "--offline", "--agent", "codex",
    "--target", path.join(updateHome, "custom-heituz"),
  ], { HOME: updateHome, USERPROFILE: updateHome, HEITUZ_TEST_PLATFORM: "linux", CI: "1" }));
  assert.equal(partialOverridePlan.imggen2_target, path.join(updateHome, "custom-heituz"));
  assert.equal("mpw_target" in partialOverridePlan, false);

  for (const host of ["claude", "codex"]) {
    const hostHome = path.join(temp, `home-${host}`);
    fs.mkdirSync(path.join(hostHome, `.${host}`), { recursive: true });
    const hostPlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--offline"], {
      HOME: hostHome, USERPROFILE: hostHome, XDG_CONFIG_HOME: path.join(hostHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
    }));
    assert.deepEqual(hostPlan.agent_targets, [host]);
    assert.match(hostPlan.imggen2_target, new RegExp(`\\.${host}[/\\\\]skills[/\\\\]HeiTuz$`, "u"));
    invoke(["scripts/install.mjs", "--offline", "--no-register", "--force"], {
      HOME: hostHome, USERPROFILE: hostHome, XDG_CONFIG_HOME: path.join(hostHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
    });
    const installed = hostDestination(hostHome, host);
    assert.equal(fs.existsSync(path.join(installed, "SKILL.md")), true);
    assert.equal(fs.existsSync(path.join(installed, "agents")), false);
    const overlaySkill = path.join(root, "agents", host, "SKILL.md");
    if (fs.existsSync(overlaySkill)) {
      const installedSkill = fs.readFileSync(path.join(installed, "SKILL.md"), "utf8");
      assert.equal(installedSkill, fs.readFileSync(overlaySkill, "utf8"));
      assert.notEqual(installedSkill, fs.readFileSync(path.join(root, "SKILL.md"), "utf8"));
    }
  }

  const noDetectedHome = path.join(temp, "home-none");
  fs.mkdirSync(noDetectedHome, { recursive: true });
  invoke(["scripts/install.mjs", "--offline", "--no-register", "--force"], {
    HOME: noDetectedHome, USERPROFILE: noDetectedHome, XDG_CONFIG_HOME: path.join(noDetectedHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  });
  assert.equal(fs.existsSync(path.join(hostDestination(noDetectedHome, "codex"), "SKILL.md")), true);

  const multipleHome = path.join(temp, "home-multiple");
  for (const host of ["hermes", "claude", "codex"]) fs.mkdirSync(path.join(multipleHome, `.${host}`), { recursive: true });
  const multiplePlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--offline"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  }));
  assert.deepEqual(multiplePlan.agent_targets, ["claude"]);
  const allPlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--offline", "--agent", "all"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  }));
  assert.deepEqual(allPlan.agent_targets, ["claude", "codex"]);
  for (const install of allPlan.installs) {
    assert.equal(install.imggen2_target.includes(`.${install.agent}`), true);
    assert.equal("mpw_target" in install, false);
  }
  invoke(["scripts/install.mjs", "--offline", "--register", "--force", "--agent", "all"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  });
  for (const host of ["claude", "codex"]) {
    assert.equal(fs.existsSync(path.join(hostDestination(multipleHome, host), "SKILL.md")), true);
  }
  assert.equal(fs.existsSync(hostDestination(multipleHome, "hermes")), false);
  const multipleManifest = path.join(multipleHome, "config", "heituz-skill", "installation.json");
  const multipleManifestData = JSON.parse(fs.readFileSync(multipleManifest, "utf8"));
  assert.equal(multipleManifestData.version, 2);
  assert.deepEqual(multipleManifestData.installations.map((installation) => installation.agent_host), ["claude", "codex"]);
  assert.equal(JSON.stringify(multipleManifestData).includes("mpw"), false);
  const multipleManifestBeforeUpdate = fs.readFileSync(multipleManifest, "utf8");
  const multipleCli = path.join(multipleHome, "config", "heituz-skill", "heituz-skill.mjs");
  const multipleUpdate = invoke([multipleCli, "update", "--dry-run"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  });
  assert.match(multipleUpdate, /--no-register/u);
  assert.equal(fs.readFileSync(multipleManifest, "utf8"), multipleManifestBeforeUpdate);
  for (const host of ["claude", "codex"]) {
    assert.equal(multipleUpdate.includes(`HeiTuz update (${host})`), true);
    assert.equal(multipleUpdate.includes(`MPW update (${host})`), false);
  }

  const target = path.join(temp, "heituz");
  // The desktop app owns <config>/heituz (Windows: %APPDATA%\\HeiTuz); the installer must never move it into the skill config.
  const desktopConfig = path.join(temp, "config", "heituz");
  fs.mkdirSync(desktopConfig, { recursive: true });
  fs.writeFileSync(path.join(desktopConfig, "app-data.txt"), "desktop");
  invoke(["scripts/install.mjs", "--target", target, "--offline", "--register", "--vision-qc", "auto"], { HEITUZ_TEST_PLATFORM: "linux" });
  assert.equal(fs.readFileSync(path.join(desktopConfig, "app-data.txt"), "utf8"), "desktop");
  const manifest = path.join(temp, "config", "heituz-skill", "installation.json");
  const launcher = path.join(temp, ".local", "bin", "heituz-skill");
  assert.equal(fs.existsSync(manifest), true);
  assert.equal(fs.existsSync(launcher), true);
  assert.match(fs.readFileSync(path.join(temp, ".profile"), "utf8"), /heituz-skill user bin/);
  assert.match(fs.readFileSync(path.join(temp, ".zprofile"), "utf8"), /heituz-skill user bin/);
  const visionQcConfig = path.join(target, "vision-qc.json");
  assert.deepEqual(JSON.parse(fs.readFileSync(visionQcConfig, "utf8")), { version: 2, requested_mode: "auto", qc_mode: "auto", reviewer: "host-default-vision" });
  const manifestData = JSON.parse(fs.readFileSync(manifest, "utf8"));
  assert.equal(manifestData.vision_qc_requested, "auto");
  assert.equal(manifestData.vision_qc_mode, "auto");
  const installedCli = path.join(temp, "config", "heituz-skill", "heituz-skill.mjs");
  const invokeInstalled = (cliArgs) => process.platform === "win32"
    ? invoke([installedCli, ...cliArgs], { HEITUZ_TEST_PLATFORM: "linux" }, process.execPath)
    : invoke(cliArgs, { HEITUZ_TEST_PLATFORM: "linux" }, launcher);
  const updater = invokeInstalled(["update", "--dry-run"]);
  assert.match(updater, /HeiTuz update/);
  assert.doesNotMatch(updater, /--vision-qc/);
  assert.doesNotMatch(updater, /MPW update/);
  const bothUpdater = invokeInstalled(["update", "--component", "all", "--dry-run"]);
  assert.match(bothUpdater, /mpw@heituz/u);
  assert.match(bothUpdater, /HeiTuz update/u);
  assert.doesNotMatch(bothUpdater, /MPW update/u);
  const promptUpdater = invokeInstalled(["update", "--component", "mpw", "--dry-run"]);
  assert.match(promptUpdater, /mpw@heituz/u);
  assert.doesNotMatch(promptUpdater, /HeiTuz update|Codex CLI install|MPW update/u);
  assert.equal(JSON.parse(invokeInstalled(["status"])).healthy, true);
  assert.equal(updater.includes(os.homedir()), false, "update dry-run leaked the developer home directory");
  const visionQcSetup = invokeInstalled(["vision-qc", "setup"]);
  assert.match(visionQcSetup, /host's default Vision model/);
  const visionQcStatus = invokeInstalled(["vision-qc", "status"]);
  assert.deepEqual(JSON.parse(visionQcStatus), { vision_qc: "auto", reviewer: "host-default-vision" });
  // Offline/test installs without --register must not touch global state.
  const manifestBefore = fs.readFileSync(manifest, "utf8");
  const isolatedTarget = path.join(temp, "heituz-isolated");
  const isolated = invoke(["scripts/install.mjs", "--target", isolatedTarget, "--offline", "--vision-qc", "off"], { HEITUZ_TEST_PLATFORM: "linux" });
  assert.match(isolated, /not registered/);
  assert.equal(fs.existsSync(path.join(isolatedTarget, "SKILL.md")), true);
  assert.equal(fs.readFileSync(manifest, "utf8"), manifestBefore);

  // A failing Pillow provisioning (e.g. PEP 668 externally-managed Python) must not abort the install.
  const brokenPythonBin = path.join(temp, "broken-python-bin");
  fs.mkdirSync(brokenPythonBin, { recursive: true });
  fs.writeFileSync(path.join(brokenPythonBin, "python3"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
  const pillowTarget = path.join(temp, "heituz-pillowless");
  const pillowResult = spawnSync(process.execPath, ["scripts/install.mjs", "--target", pillowTarget, "--skip-codex", "--skip-mpw", "--no-register", "--vision-qc", "off"], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, HOME: temp, XDG_CONFIG_HOME: path.join(temp, "config"), HEITUZ_TEST_PLATFORM: "linux", PATH: `${brokenPythonBin}:/usr/bin:/bin` },
  });
  assert.equal(pillowResult.status, 0, pillowResult.stderr || pillowResult.stdout);
  assert.match(pillowResult.stderr, /Pillow could not be installed automatically/);
  assert.equal(fs.existsSync(path.join(pillowTarget, "SKILL.md")), true);

  const windowsTarget = path.join(temp, "windows-heituz");
  const localAppData = path.join(temp, "local-app-data");
  const appData = path.join(temp, "app-data");
  const windowsBin = path.join(localAppData, "heituz-skill", "bin");
  fs.mkdirSync(windowsBin, { recursive: true });
  fs.writeFileSync(path.join(windowsBin, "heituz-skill"), "stale extensionless launcher");
  fs.writeFileSync(path.join(windowsBin, "heituz-skill.mjs"), "stale mjs launcher");
  const gitBashLauncher = path.join(temp, ".local", "bin", "heituz-skill");
  fs.mkdirSync(path.dirname(gitBashLauncher), { recursive: true });
  fs.writeFileSync(gitBashLauncher, "#!/bin/sh\nexec node /tmp/_npx/stale/heituz-skill.mjs \"$@\"\n");
  invoke(["scripts/install.mjs", "--target", windowsTarget, "--offline", "--register", "--vision-qc", "off"], {
    HEITUZ_TEST_PLATFORM: "win32", LOCALAPPDATA: localAppData, APPDATA: appData,
    TEMP: path.join(temp, "declared-windows-temp"), TMP: path.join(temp, "declared-windows-temp"),
  });
  const windowsLauncher = path.join(localAppData, "heituz-skill", "bin", "heituz-skill.cmd");
  const windowsPowerShellLauncher = path.join(localAppData, "heituz-skill", "bin", "heituz-skill.ps1");
  assert.equal(fs.existsSync(windowsLauncher), true);
  assert.equal(fs.existsSync(windowsPowerShellLauncher), true);
  assert.match(fs.readFileSync(windowsLauncher, "utf8"), /%APPDATA%\\heituz-skill\\heituz-skill\.mjs/);
  assert.match(fs.readFileSync(windowsPowerShellLauncher, "utf8"), /\$env:APPDATA\\heituz-skill\\heituz-skill\.mjs/);
  assert.equal(fs.existsSync(path.join(windowsBin, "heituz-skill")), false);
  assert.equal(fs.existsSync(path.join(windowsBin, "heituz-skill.mjs")), false);
  assert.equal(fs.existsSync(gitBashLauncher), true);
  const gitBashContent = fs.readFileSync(gitBashLauncher, "utf8");
  assert.match(gitBashContent, /\$appdata\/heituz-skill\/heituz-skill\.mjs/u);
  assert.equal(gitBashContent.includes("_npx"), false);
  assert.equal(JSON.parse(spawnSync(process.execPath, [path.join(appData, "heituz-skill", "heituz-skill.mjs"), "status"], {
    cwd: root, encoding: "utf8",
    env: { ...process.env, HOME: temp, USERPROFILE: temp, HEITUZ_TEST_PLATFORM: "win32", LOCALAPPDATA: localAppData, APPDATA: appData, TEMP: path.join(temp, "declared-windows-temp"), TMP: path.join(temp, "declared-windows-temp") },
  }).stdout).healthy, true, "a fresh Windows install reports healthy");
  // Point the Git Bash launcher back at a transient npx copy: status must report the installation as degraded.
  fs.writeFileSync(gitBashLauncher, "#!/bin/sh\nexec node /tmp/_npx/stale/heituz-skill.mjs \"$@\"\n");
  const degraded = spawnSync(process.execPath, [path.join(appData, "heituz-skill", "heituz-skill.mjs"), "status"], {
    cwd: root,
    encoding: "utf8",
    env: {
      ...process.env,
      HOME: temp,
      USERPROFILE: temp,
      HEITUZ_TEST_PLATFORM: "win32",
      LOCALAPPDATA: localAppData,
      APPDATA: appData,
      TEMP: path.join(temp, "declared-windows-temp"),
      TMP: path.join(temp, "declared-windows-temp"),
    },
  });
  assert.notEqual(degraded.status, 0);
  assert.equal(JSON.parse(degraded.stdout).healthy, false);
  const degradedStatus = JSON.parse(degraded.stdout);
  assert.equal(degradedStatus.problems.some((problem) => problem.startsWith("git_bash launcher does not target the persistent updater")), true);
  assert.equal(degradedStatus.manifest_path, path.join(appData, "heituz-skill", "installation.json"));
  assert.equal(degradedStatus.manifest_version, 2);
  assert.equal(degradedStatus.selected_launcher_path, windowsLauncher);
  assert.equal(degradedStatus.target_status.length, 1);
  assert.equal(degradedStatus.target_status[0].imggen2_exists, true);
  assert.equal(typeof degradedStatus.target_status[0].imggen2_version, "string");
  assert.equal("mpw_version" in degradedStatus.target_status[0], false);
  assert.equal("active_hermes" in degradedStatus, false);
  assert.match(degradedStatus.repair_recommendation, /^bunx --package /u);
  assert.equal(degradedStatus.launcher_surfaces.cmd, windowsLauncher);
  assert.equal(degradedStatus.launcher_surfaces.powershell, windowsPowerShellLauncher);
  assert.equal(degradedStatus.launcher_surfaces.git_bash, gitBashLauncher);

  const migrationHome = path.join(temp, "migration-home");
  const migrationSkill = path.join(migrationHome, ".codex", "skills", "HeiTuz");
  const migrationMpw = path.join(migrationHome, ".codex", "skills", "MPW");
  const migrationConfig = path.join(migrationHome, "config", "heituz-skill");
  fs.mkdirSync(path.join(migrationSkill, "scripts"), { recursive: true });
  fs.mkdirSync(migrationMpw, { recursive: true });
  fs.mkdirSync(migrationConfig, { recursive: true });
  fs.writeFileSync(path.join(migrationSkill, "scripts", "heituz-skill.mjs"), "");
  fs.writeFileSync(path.join(migrationSkill, "SKILL.md"), "");
  fs.writeFileSync(path.join(migrationSkill, "package.json"), JSON.stringify({ version: "1.9.1" }));
  fs.writeFileSync(path.join(migrationMpw, "package.json"), JSON.stringify({ version: "1.2.3" }));
  const migrationManifest = path.join(migrationConfig, "installation.json");
  fs.writeFileSync(migrationManifest, JSON.stringify({ version: 1, imggen2_target: migrationSkill, mpw_target: migrationMpw }));
  const migration = spawnSync(process.execPath, ["scripts/heituz-skill.mjs", "status"], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, HOME: migrationHome, USERPROFILE: migrationHome, XDG_CONFIG_HOME: path.join(migrationHome, "config"), HEITUZ_TEST_PLATFORM: "linux" },
  });
  assert.notEqual(migration.status, 0, "migration status remains degraded until launchers exist");
  assert.equal(JSON.parse(fs.readFileSync(migrationManifest, "utf8")).version, 1, "status must not rewrite the manifest");
  assert.deepEqual(fs.readdirSync(migrationConfig).filter((name) => name.includes(".tmp-")), []);
  assert.equal(fs.existsSync(path.join(appData, "heituz-skill", "installation.json")), true);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(windowsTarget, "vision-qc.json"), "utf8")), { version: 2, requested_mode: "off", qc_mode: "off", reviewer: "host-default-vision" });
  const savedQc = path.join(windowsTarget, "vision-qc.json");
  const preserved = JSON.parse(invoke(["scripts/install.mjs", "--agent", "codex", "--target", windowsTarget, "--offline", "--force", "--no-register", "--dry-run"]));
  assert.equal(preserved.vision_qc.mode, "off");
  assert.equal(preserved.installs[0].vision_qc.mode, "off");
  invoke(["scripts/install.mjs", "--agent", "codex", "--target", windowsTarget, "--offline", "--force", "--no-register"]);
  assert.equal(JSON.parse(fs.readFileSync(savedQc, "utf8")).qc_mode, "off");
  invoke(["scripts/install.mjs", "--agent", "codex", "--target", windowsTarget, "--offline", "--force", "--no-register", "--vision-qc", "auto"]);
  assert.equal(JSON.parse(fs.readFileSync(savedQc, "utf8")).qc_mode, "auto");
  console.log("unified install/update dry-run: OK");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
