#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (!fs.existsSync(path.join(root, "agents", "hermes", "README.md"))) {
  console.log("unified install/update dry-run: SKIP (install artifact has no source overlays)");
  process.exit(0);
}
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "imggen-unified-"));
process.env.HEITUZ_INSTALLER_IMPORT = "1";
const { imggenUpdateArgs, isTransientWindowsPath, npxInvocation, repairLegacyManifest } = await import("./imggen.mjs");
const { migrateLegacyInstallPaths } = await import("./install.mjs");
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
  return path.join(home, `.${host}`, "skills", "ImgGen2");
}

try {
  const migrationRenameHome = path.join(temp, "legacy-rename-home");
  const previousXdg = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = path.join(migrationRenameHome, "config");
  const legacyConfig = path.join(process.env.XDG_CONFIG_HOME, "heituz");
  const legacyImg = path.join(migrationRenameHome, ".hermes", "skills", "HeiTuzImgGen2");
  const legacyMpw = path.join(migrationRenameHome, ".hermes", "skills", "prompt-writing", "HeiTuzMPW");
  fs.mkdirSync(legacyConfig, { recursive: true }); fs.writeFileSync(path.join(legacyConfig, "installation.json"), "{}");
  fs.mkdirSync(legacyImg, { recursive: true }); fs.mkdirSync(legacyMpw, { recursive: true });
  const planned = migrateLegacyInstallPaths(migrationRenameHome, { windows: false, config: path.join(process.env.XDG_CONFIG_HOME, "imggen") }, { dryRun: true, component: "all" });
  assert.equal(planned.length, 3);
  assert.equal(fs.existsSync(legacyImg), true);
  assert.equal(fs.existsSync(legacyConfig), true);
  assert.equal(fs.existsSync(path.join(migrationRenameHome, ".hermes", "skills", "ImgGen2")), false);
  const renamed = migrateLegacyInstallPaths(migrationRenameHome, { windows: false, config: path.join(process.env.XDG_CONFIG_HOME, "imggen") }, { component: "all" });
  assert.equal(renamed.length, 3);
  assert.equal(fs.existsSync(path.join(process.env.XDG_CONFIG_HOME, "imggen", "installation.json")), true);
  assert.equal(fs.existsSync(path.join(migrationRenameHome, ".hermes", "skills", "ImgGen2")), true);
  assert.equal(fs.existsSync(path.join(migrationRenameHome, ".hermes", "skills", "prompt-writing", "MPW")), true);
  if (previousXdg === undefined) delete process.env.XDG_CONFIG_HOME; else process.env.XDG_CONFIG_HOME = previousXdg;
  const updateManifest = { imggen2_target: "/tmp/imggen", vision_qc_requested: "auto" };
  const interactiveUpdate = imggenUpdateArgs(updateManifest, { interactive: true });
  assert.equal(interactiveUpdate.includes("--vision-qc"), false);
  const automatedUpdate = imggenUpdateArgs(updateManifest, { interactive: false });
  assert.equal(automatedUpdate.includes("--vision-qc"), false);
  // Windows cannot spawn npx.cmd without a shell; the invocation must route through cmd.exe /c.
  assert.deepEqual(npxInvocation(true, ["--yes", "pkg"]), { command: "cmd.exe", args: ["/d", "/s", "/c", "npx", "--yes", "pkg"] });
  assert.deepEqual(npxInvocation(false, ["--yes", "pkg"]), { command: "npx", args: ["--yes", "pkg"] });
  assert.equal(isTransientWindowsPath("C:\\Users\\alice\\AppData\\Local\\Temp\\_npx\\123\\package", { TEMP: "C:\\Users\\alice\\AppData\\Local\\Temp" }), true);
  assert.equal(isTransientWindowsPath("C:\\Users\\alice\\.hermes\\skills\\ImgGen2", { TEMP: "C:\\Users\\alice\\AppData\\Local\\Temp" }), false);
  const repairHome = path.join(temp, "repair-home");
  const legacy = {
    version: 1,
    imggen2_target: path.join(repairHome, ".hermes", "skills", "ImgGen2"),
    mpw_target: path.join(repairHome, ".hermes", "skills", "prompt-writing", "MPW"),
  };
  assert.equal(repairLegacyManifest(legacy, { home: repairHome, windows: false }).installations[0].agent_host, "hermes");
  assert.throws(
    () => repairLegacyManifest({ ...legacy, imggen2_target: path.join(repairHome, "custom") }, { home: repairHome, windows: false }),
    /Repair with: npx/u,
  );
  assert.throws(
    () => repairLegacyManifest({
      version: 1,
      imggen2_target: "C:\\Users\\alice\\AppData\\Local\\Temp\\_npx\\123\\package",
      mpw_target: "C:\\Users\\alice\\.hermes\\skills\\prompt-writing\\MPW",
    }, { home: "C:\\Users\\alice", windows: true, env: { TEMP: "C:\\Users\\alice\\AppData\\Local\\Temp" } }),
    /transient.*Repair with: npx --yes --allow-git=all --package github:HeiTuz\/ImgGen2 imggen-imggen2/iu,
  );
  const plan = invoke(["scripts/install.mjs", "--dry-run"], { HEITUZ_TEST_PLATFORM: "win32", LOCALAPPDATA: path.join(temp, "local"), APPDATA: path.join(temp, "roaming") });
  assert.match(plan, /powershell\.exe/);
  assert.match(plan, /install\.ps1/);
  assert.match(plan, /MPW/);
  const offlineVisionPlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--vision-qc", "auto", "--offline"], { HEITUZ_TEST_PLATFORM: "linux" }));
  assert.equal(offlineVisionPlan.vision_qc.requested_mode, "auto");
  assert.equal(offlineVisionPlan.vision_qc.mode, "auto");
  assert.match(offlineVisionPlan.vision_qc.config, /vision-qc\.json$/);
  const forwardedPlan = JSON.parse(invoke(["scripts/install.mjs", "--", "--dry-run", "--offline", "--agent", "claude"], { HEITUZ_TEST_PLATFORM: "linux" }));
  assert.deepEqual(forwardedPlan.agent_targets, ["claude"]);
  const updateHome = path.join(temp, "home-update-claude");
  const updatePlan = JSON.parse(invoke([
    "scripts/install.mjs", "--dry-run", "--offline",
    "--target", path.join(updateHome, ".claude", "skills", "ImgGen2"),
    "--mpw-target", path.join(updateHome, ".claude", "skills", "MPW"),
  ], { HOME: updateHome, USERPROFILE: updateHome, HEITUZ_TEST_PLATFORM: "linux", CI: "1" }));
  assert.deepEqual(updatePlan.agent_targets, ["claude"]);
  const partialOverridePlan = JSON.parse(invoke([
    "scripts/install.mjs", "--dry-run", "--offline", "--agent", "codex",
    "--target", path.join(updateHome, "custom-imggen2"),
  ], { HOME: updateHome, USERPROFILE: updateHome, HEITUZ_TEST_PLATFORM: "linux", CI: "1" }));
  assert.equal(partialOverridePlan.imggen2_target, path.join(updateHome, "custom-imggen2"));
  assert.equal(partialOverridePlan.mpw_target, path.join(updateHome, ".codex", "skills", "MPW"));

  for (const host of ["hermes", "claude", "codex"]) {
    const hostHome = path.join(temp, `home-${host}`);
    fs.mkdirSync(path.join(hostHome, `.${host}`), { recursive: true });
    const hostPlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--offline"], {
      HOME: hostHome, USERPROFILE: hostHome, XDG_CONFIG_HOME: path.join(hostHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
    }));
    assert.deepEqual(hostPlan.agent_targets, [host]);
    assert.match(hostPlan.imggen2_target, new RegExp(`\\.${host}[/\\\\]skills[/\\\\]ImgGen2$`, "u"));
    assert.match(hostPlan.mpw_target, new RegExp(`\\.${host}[/\\\\]skills[/\\\\](?:prompt-writing[/\\\\])?MPW$`, "u"));
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
  assert.equal(fs.existsSync(path.join(hostDestination(noDetectedHome, "hermes"), "SKILL.md")), true);

  const multipleHome = path.join(temp, "home-multiple");
  for (const host of ["hermes", "claude", "codex"]) fs.mkdirSync(path.join(multipleHome, `.${host}`), { recursive: true });
  const multiplePlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--offline"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  }));
  assert.deepEqual(multiplePlan.agent_targets, ["hermes"]);
  const allPlan = JSON.parse(invoke(["scripts/install.mjs", "--dry-run", "--offline", "--agent", "all"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  }));
  assert.deepEqual(allPlan.agent_targets, ["hermes", "claude", "codex"]);
  for (const install of allPlan.installs) {
    const hostDir = install.agent === "hermes" ? ".hermes" : `.${install.agent}`;
    assert.equal(install.imggen2_target.includes(hostDir), true);
    assert.equal(install.mpw_target.includes(hostDir), true);
  }
  invoke(["scripts/install.mjs", "--offline", "--register", "--force", "--agent", "all"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  });
  for (const host of ["hermes", "claude", "codex"]) {
    assert.equal(fs.existsSync(path.join(hostDestination(multipleHome, host), "SKILL.md")), true);
  }
  const multipleManifest = path.join(multipleHome, "config", "imggen", "installation.json");
  const multipleManifestData = JSON.parse(fs.readFileSync(multipleManifest, "utf8"));
  assert.equal(multipleManifestData.version, 2);
  assert.deepEqual(multipleManifestData.installations.map((installation) => installation.agent_host), ["hermes", "claude", "codex"]);
  const multipleManifestBeforeUpdate = fs.readFileSync(multipleManifest, "utf8");
  const multipleCli = path.join(multipleHome, "config", "imggen", "imggen.mjs");
  const multipleUpdate = invoke([multipleCli, "update", "--dry-run"], {
    HOME: multipleHome, USERPROFILE: multipleHome, XDG_CONFIG_HOME: path.join(multipleHome, "config"), HEITUZ_TEST_PLATFORM: "linux", CI: "1",
  });
  assert.match(multipleUpdate, /--no-register/u);
  assert.equal(fs.readFileSync(multipleManifest, "utf8"), multipleManifestBeforeUpdate);
  for (const host of ["hermes", "claude", "codex"]) {
    assert.equal(multipleUpdate.includes(`ImgGen2 update (${host})`), true);
    assert.equal(multipleUpdate.includes(`MPW update (${host})`), false);
  }

  const target = path.join(temp, "imggen2");
  invoke(["scripts/install.mjs", "--target", target, "--offline", "--register", "--vision-qc", "auto"], { HEITUZ_TEST_PLATFORM: "linux" });
  const manifest = path.join(temp, "config", "imggen", "installation.json");
  const launcher = path.join(temp, ".local", "bin", "imggen");
  assert.equal(fs.existsSync(manifest), true);
  assert.equal(fs.existsSync(launcher), true);
  assert.match(fs.readFileSync(path.join(temp, ".profile"), "utf8"), /imggen user bin/);
  assert.match(fs.readFileSync(path.join(temp, ".zprofile"), "utf8"), /imggen user bin/);
  const visionQcConfig = path.join(target, "vision-qc.json");
  assert.deepEqual(JSON.parse(fs.readFileSync(visionQcConfig, "utf8")), { version: 2, requested_mode: "auto", qc_mode: "auto", reviewer: "host-default-vision" });
  const manifestData = JSON.parse(fs.readFileSync(manifest, "utf8"));
  assert.equal(manifestData.vision_qc_requested, "auto");
  assert.equal(manifestData.vision_qc_mode, "auto");
  const installedCli = path.join(temp, "config", "imggen", "imggen.mjs");
  const invokeInstalled = (cliArgs) => process.platform === "win32"
    ? invoke([installedCli, ...cliArgs], { HEITUZ_TEST_PLATFORM: "linux" }, process.execPath)
    : invoke(cliArgs, { HEITUZ_TEST_PLATFORM: "linux" }, launcher);
  const updater = invokeInstalled(["update", "--dry-run"]);
  assert.match(updater, /ImgGen2 update/);
  assert.doesNotMatch(updater, /--vision-qc/);
  assert.doesNotMatch(updater, /MPW update/);
  const bothUpdater = invokeInstalled(["update", "--component", "all", "--dry-run"]);
  assert.match(bothUpdater, /MPW update/);
  const promptUpdater = invokeInstalled(["update", "--component", "mpw", "--dry-run"]);
  assert.match(promptUpdater, /MPW update/);
  assert.doesNotMatch(promptUpdater, /ImgGen2 update|Codex CLI install/);
  assert.equal(JSON.parse(invokeInstalled(["status"])).healthy, true);
  assert.equal(updater.includes(os.homedir()), false, "update dry-run leaked the developer home directory");
  const visionQcSetup = invokeInstalled(["vision-qc", "setup"]);
  assert.match(visionQcSetup, /host's default Vision model/);
  const visionQcStatus = invokeInstalled(["vision-qc", "status"]);
  assert.deepEqual(JSON.parse(visionQcStatus), { vision_qc: "auto", reviewer: "host-default-vision" });
  // Offline/test installs without --register must not touch global state.
  const manifestBefore = fs.readFileSync(manifest, "utf8");
  const isolatedTarget = path.join(temp, "imggen2-isolated");
  const isolated = invoke(["scripts/install.mjs", "--target", isolatedTarget, "--offline", "--vision-qc", "off"], { HEITUZ_TEST_PLATFORM: "linux" });
  assert.match(isolated, /not registered/);
  assert.equal(fs.existsSync(path.join(isolatedTarget, "SKILL.md")), true);
  assert.equal(fs.readFileSync(manifest, "utf8"), manifestBefore);

  // A failing Pillow provisioning (e.g. PEP 668 externally-managed Python) must not abort the install.
  const brokenPythonBin = path.join(temp, "broken-python-bin");
  fs.mkdirSync(brokenPythonBin, { recursive: true });
  fs.writeFileSync(path.join(brokenPythonBin, "python3"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
  const pillowTarget = path.join(temp, "imggen2-pillowless");
  const pillowResult = spawnSync(process.execPath, ["scripts/install.mjs", "--target", pillowTarget, "--skip-codex", "--skip-mpw", "--no-register", "--vision-qc", "off"], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, HOME: temp, XDG_CONFIG_HOME: path.join(temp, "config"), HEITUZ_TEST_PLATFORM: "linux", PATH: `${brokenPythonBin}:/usr/bin:/bin` },
  });
  assert.equal(pillowResult.status, 0, pillowResult.stderr || pillowResult.stdout);
  assert.match(pillowResult.stderr, /Pillow could not be installed automatically/);
  assert.equal(fs.existsSync(path.join(pillowTarget, "SKILL.md")), true);

  const windowsTarget = path.join(temp, "windows-imggen2");
  const localAppData = path.join(temp, "local-app-data");
  const appData = path.join(temp, "app-data");
  const windowsBin = path.join(localAppData, "ImgGen2", "bin");
  fs.mkdirSync(windowsBin, { recursive: true });
  fs.writeFileSync(path.join(windowsBin, "imggen"), "stale extensionless launcher");
  fs.writeFileSync(path.join(windowsBin, "imggen.mjs"), "stale mjs launcher");
  const gitBashLauncher = path.join(temp, ".local", "bin", "imggen");
  fs.mkdirSync(path.dirname(gitBashLauncher), { recursive: true });
  fs.writeFileSync(gitBashLauncher, "#!/bin/sh\nexec node /tmp/_npx/stale/imggen.mjs \"$@\"\n");
  invoke(["scripts/install.mjs", "--target", windowsTarget, "--offline", "--register", "--vision-qc", "off"], {
    HEITUZ_TEST_PLATFORM: "win32", LOCALAPPDATA: localAppData, APPDATA: appData,
    TEMP: path.join(temp, "declared-windows-temp"), TMP: path.join(temp, "declared-windows-temp"),
  });
  const windowsLauncher = path.join(localAppData, "ImgGen2", "bin", "imggen.cmd");
  const windowsPowerShellLauncher = path.join(localAppData, "ImgGen2", "bin", "imggen.ps1");
  assert.equal(fs.existsSync(windowsLauncher), true);
  assert.equal(fs.existsSync(windowsPowerShellLauncher), true);
  assert.match(fs.readFileSync(windowsLauncher, "utf8"), /%APPDATA%\\ImgGen2\\imggen\.mjs/);
  assert.match(fs.readFileSync(windowsPowerShellLauncher, "utf8"), /\$env:APPDATA\\ImgGen2\\imggen\.mjs/);
  assert.equal(fs.existsSync(path.join(windowsBin, "imggen")), false);
  assert.equal(fs.existsSync(path.join(windowsBin, "imggen.mjs")), false);
  assert.equal(fs.existsSync(gitBashLauncher), true);
  const gitBashContent = fs.readFileSync(gitBashLauncher, "utf8");
  assert.match(gitBashContent, /\$appdata\/ImgGen2\/imggen\.mjs/u);
  assert.equal(gitBashContent.includes("_npx"), false);
  const degraded = spawnSync(process.execPath, [path.join(appData, "ImgGen2", "imggen.mjs"), "status"], {
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
  assert.equal(degradedStatus.manifest_path, path.join(appData, "ImgGen2", "installation.json"));
  assert.equal(degradedStatus.manifest_version, 2);
  assert.equal(degradedStatus.selected_launcher_path, windowsLauncher);
  assert.equal(degradedStatus.target_status.length, 1);
  assert.equal(degradedStatus.target_status[0].imggen2_exists, true);
  assert.equal(degradedStatus.target_status[0].mpw_exists, false);
  assert.equal(typeof degradedStatus.target_status[0].imggen2_version, "string");
  assert.equal(degradedStatus.target_status[0].mpw_version, null);
  assert.equal(degradedStatus.active_hermes.registered, false);
  assert.match(degradedStatus.repair_recommendation, /^npx --yes /u);
  assert.equal(degradedStatus.launcher_surfaces.cmd, windowsLauncher);
  assert.equal(degradedStatus.launcher_surfaces.powershell, windowsPowerShellLauncher);
  assert.equal(degradedStatus.launcher_surfaces.git_bash, gitBashLauncher);

  const migrationHome = path.join(temp, "migration-home");
  const migrationImggen = path.join(migrationHome, ".hermes", "skills", "ImgGen2");
  const migrationMpw = path.join(migrationHome, ".hermes", "skills", "prompt-writing", "MPW");
  const migrationConfig = path.join(migrationHome, "config", "imggen");
  fs.mkdirSync(path.join(migrationImggen, "scripts"), { recursive: true });
  fs.mkdirSync(migrationMpw, { recursive: true });
  fs.mkdirSync(migrationConfig, { recursive: true });
  fs.writeFileSync(path.join(migrationImggen, "scripts", "imggen.mjs"), "");
  fs.writeFileSync(path.join(migrationImggen, "SKILL.md"), "");
  fs.writeFileSync(path.join(migrationImggen, "package.json"), JSON.stringify({ version: "1.9.1" }));
  fs.writeFileSync(path.join(migrationMpw, "package.json"), JSON.stringify({ version: "1.2.3" }));
  const migrationManifest = path.join(migrationConfig, "installation.json");
  fs.writeFileSync(migrationManifest, JSON.stringify({ version: 1, imggen2_target: migrationImggen, mpw_target: migrationMpw }));
  const migration = spawnSync(process.execPath, ["scripts/imggen.mjs", "status"], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, HOME: migrationHome, USERPROFILE: migrationHome, XDG_CONFIG_HOME: path.join(migrationHome, "config"), HEITUZ_TEST_PLATFORM: "linux" },
  });
  assert.notEqual(migration.status, 0, "migration status remains degraded until launchers exist");
  assert.equal(JSON.parse(fs.readFileSync(migrationManifest, "utf8")).version, 1, "status must not rewrite the manifest");
  assert.deepEqual(fs.readdirSync(migrationConfig).filter((name) => name.includes(".tmp-")), []);
  assert.equal(fs.existsSync(path.join(appData, "ImgGen2", "installation.json")), true);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(windowsTarget, "vision-qc.json"), "utf8")), { version: 2, requested_mode: "off", qc_mode: "off", reviewer: "host-default-vision" });
  const savedQc = path.join(windowsTarget, "vision-qc.json");
  const preserved = JSON.parse(invoke(["scripts/install.mjs", "--agent", "hermes", "--target", windowsTarget, "--offline", "--force", "--no-register", "--dry-run"]));
  assert.equal(preserved.vision_qc.mode, "off");
  assert.equal(preserved.installs[0].vision_qc.mode, "off");
  invoke(["scripts/install.mjs", "--agent", "hermes", "--target", windowsTarget, "--offline", "--force", "--no-register"]);
  assert.equal(JSON.parse(fs.readFileSync(savedQc, "utf8")).qc_mode, "off");
  invoke(["scripts/install.mjs", "--agent", "hermes", "--target", windowsTarget, "--offline", "--force", "--no-register", "--vision-qc", "auto"]);
  assert.equal(JSON.parse(fs.readFileSync(savedQc, "utf8")).qc_mode, "auto");
  console.log("unified install/update dry-run: OK");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
