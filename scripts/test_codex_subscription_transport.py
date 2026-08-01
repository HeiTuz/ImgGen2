import importlib.util
import sys
from types import SimpleNamespace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import codex_cli_resolver as resolver

MODULE_PATH = SCRIPTS / "codex_subscription_transport.py"
SPEC = importlib.util.spec_from_file_location("codex_subscription_transport", MODULE_PATH)
transport = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(transport)


class CodexSubscriptionTransportTests(unittest.TestCase):
    CURRENT_SESSION = "-".join(("019f5670", "ef96", "7530", "8c39", "962ed2b739a1"))
    PRIOR_SESSION = "-".join(("119f5670", "ef96", "7530", "8c39", "962ed2b739a1"))
    OTHER_SESSION = "-".join(("219f5670", "ef96", "7530", "8c39", "962ed2b739a1"))
    @staticmethod
    def _resolved(command="/bin/codex"):
        return SimpleNamespace(
            command=command,
            source="explicit",
            version=(0, 144, 3),
            provenance={"path": command, "source": "explicit", "version": [0, 144, 3]},
        )

    @staticmethod
    def _version_runner(version="0.144.3"):
        return lambda *_args, **_kwargs: resolver.subprocess.CompletedProcess(
            [], 0, stdout=f"codex-cli {version}", stderr=""
        )

    @staticmethod
    def _executable(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nprintf 'codex-cli 0.144.3\\n'\n", encoding="utf-8")
        path.chmod(0o755)
        return path
    def test_resolver_prefers_canonical_on_macos_and_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alternate = self._executable(root / "alternate" / "codex")
            for platform in ("darwin", "linux"):
                canonical = self._executable(root / platform / ".local" / "bin" / "codex")
                resolved = resolver.resolve_codex_command(
                    platform=platform,
                    home=root / platform,
                    which=lambda _name: str(alternate),
                    runner=self._version_runner(),
                )
                self.assertEqual(resolved.command, str(canonical.resolve()))
                self.assertEqual(resolved.source, "official")

    def test_resolver_uses_windows_path_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self._executable(Path(tmp) / "tools" / "codex.exe")
            resolved = resolver.resolve_codex_command(
                platform="win32",
                environ={},
                which=lambda name: str(candidate) if name == "codex.exe" else None,
                runner=self._version_runner(),
            )
        self.assertEqual(resolved.command, str(candidate.resolve()))
        self.assertEqual(resolved.source, "path")
    def test_resolver_accepts_windows_cmd_from_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self._executable(Path(tmp) / "tools" / "codex.cmd")
            resolved = resolver.resolve_codex_command(
                platform="win32",
                environ={},
                which=lambda name: str(candidate) if name == "codex.cmd" else None,
                runner=self._version_runner(),
            )
        self.assertEqual(resolved.command, str(candidate.resolve()))
        self.assertEqual(resolved.source, "path")

    def test_resolver_honors_explicit_and_environment_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = self._executable(root / "explicit" / "codex")
            environment = self._executable(root / "environment" / "codex")
            explicit_resolved = resolver.resolve_codex_command(
                explicit,
                platform="linux",
                environ={resolver.CODEX_OVERRIDE_ENV: str(environment)},
                runner=self._version_runner(),
            )
            environment_resolved = resolver.resolve_codex_command(
                platform="linux",
                environ={resolver.CODEX_OVERRIDE_ENV: str(environment)},
                runner=self._version_runner(),
            )
        self.assertEqual(explicit_resolved.command, str(explicit.resolve()))
        self.assertEqual(explicit_resolved.source, "explicit")
        self.assertEqual(environment_resolved.command, str(environment.resolve()))
        self.assertEqual(environment_resolved.source, "environment")
    def test_resolver_prefers_install_dir_before_standard_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = self._executable(root / "install" / "codex")
            self._executable(root / "home" / ".local" / "bin" / "codex")
            path = self._executable(root / "path" / "codex")
            resolved = resolver.resolve_codex_command(
                platform="linux",
                home=root / "home",
                environ={resolver.CODEX_INSTALL_DIR_ENV: str(install.parent)},
                which=lambda _name: str(path),
                runner=self._version_runner(),
            )
        self.assertEqual(resolved.command, str(install.resolve()))
        self.assertEqual(resolved.source, "install_dir")

    def test_resolver_rejects_versions_below_an_explicit_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self._executable(Path(tmp) / "codex")
            with self.assertRaisesRegex(resolver.CodexResolutionError, "compatibility floor"):
                resolver.resolve_codex_command(
                    candidate,
                    platform="linux",
                    minimum_version=(0, 145, 0),
                    runner=self._version_runner("0.144.3"),
                )

    def test_explicit_command_propagates_to_transport(self):
        explicit = Path("/opt/official/codex")
        with patch.object(
            transport,
            "resolve_codex_command",
            return_value=self._resolved(str(explicit)),
        ) as resolve:
            command = transport.build_command("draw", Path("/tmp/out.png"), [], explicit)
        resolve.assert_called_once_with(explicit)
        self.assertEqual(command[0], str(explicit))

    def _run_live_with_artifacts(self, tmp, cli_output, create_artifacts, returncode=0):
        generated_root = Path(tmp) / "generated"
        completed = transport.subprocess.CompletedProcess(
            [], returncode, stdout=cli_output, stderr=""
        )

        def fake_run(*_args, **_kwargs):
            create_artifacts(generated_root)
            return completed

        with (
            patch.object(transport, "resolve_codex_command", return_value=self._resolved()),
            patch.object(transport.subprocess, "run", side_effect=fake_run),
            patch.object(transport, "GENERATED_IMAGES_DIR", generated_root),
            patch.dict(os.environ, {}, clear=True),
        ):
            return transport.run("draw", Path(tmp) / "out.png", [], execute=True)

    def test_dry_run_uses_supported_cli_and_honest_model_label(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            transport, "resolve_codex_command", return_value=self._resolved()
        ):
            result = transport.run("draw a blue square", Path(tmp) / "image.png", [])
        self.assertEqual(result["transport"], "official-codex-cli-subscription")
        self.assertEqual(result["transport_state"], "dry_run")
        self.assertEqual(
            result["codex_provenance"],
            {"path": "/bin/codex", "source": "explicit", "version": [0, 144, 3]},
        )
        self.assertEqual(result["qc_status"], "not_evaluated")
        self.assertIsNone(result["requested_model"])
        self.assertIsNone(result["observed_model"])
        self.assertFalse(result["model_identity_attested"])
        self.assertIn("--skip-git-repo-check", result["command"])
        self.assertIn('model_reasoning_effort="medium"', result["command"])
        self.assertNotIn("--model", result["command"])
        self.assertNotIn("--enable", result["command"])
        self.assertNotIn("draw a blue square", " ".join(result["command"]))

    def test_variadic_image_arguments_are_terminated_before_prompt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            transport, "resolve_codex_command", return_value=self._resolved()
        ):
            root = Path(tmp)
            refs = [root / "front.jpg", root / "detail.jpg"]
            command = transport.build_command("preserve the garment", root / "out.png", refs)
        self.assertEqual(command[-2], "--")
        self.assertIn("preserve the garment", command[-1])
        self.assertEqual(command.count("--image"), 2)
        self.assertLess(
            max(i for i, value in enumerate(command) if value == "--image"),
            command.index("--"),
        )

    def test_live_call_needs_no_redundant_approval_marker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            transport, "resolve_codex_command", return_value=self._resolved()
        ), patch.dict(os.environ, {}, clear=True), patch.object(
            transport.subprocess, "run", side_effect=RuntimeError("transport reached")
        ):
            with self.assertRaisesRegex(RuntimeError, "transport reached"):
                transport.run("draw", Path(tmp) / "image.png", [], execute=True)

    def test_references_are_bounded_and_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            refs = []
            for index in range(5):
                ref = root / f"ref-{index}.png"
                ref.write_bytes(b"x")
                refs.append(ref)
            with self.assertRaisesRegex(transport.TransportError, "At most four"):
                transport.validate_request("draw", root / "out.png", refs)

    def test_existing_output_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.png"
            output.write_bytes(b"existing")
            with self.assertRaisesRegex(transport.TransportError, "Refusing to overwrite"):
                transport.validate_request("draw", output, [])

    def test_cli_failure_classifies_without_echoing_subprocess_output(self):
        completed = transport.subprocess.CompletedProcess(
            [],
            7,
            stdout="request token=secret",
            stderr="The model gpt-5.6-sol is unsupported; cookie=secret",
        )
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            transport, "resolve_codex_command", return_value=self._resolved()
        ), patch.object(
            transport.subprocess, "run", return_value=completed
        ), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                transport.TransportError, "category=model_unavailable"
            ) as caught:
                transport.run("draw", Path(tmp) / "out.png", [], execute=True)
        self.assertNotIn("token=secret", str(caught.exception))
        self.assertNotIn("cookie=secret", str(caught.exception))
        self.assertNotIn("unsupported", str(caught.exception))

    def test_cli_failure_categories_are_secret_free(self):
        cases = {
            "cli_argument_error": ("", "No prompt provided via stdin."),
            "authentication_required": ("", "Login required: bearer abc"),
            "entitlement_denied": ("", "Account does not have access; session=abc"),
            "rate_limited": ("", "Too many requests; token=abc"),
            "image_tool_unavailable": ("", "image_generation is disabled; cookie=abc"),
            "moderation_rejected": (
                "I'm unable to generate this image due to content policy restrictions.",
                "",
            ),
            "unknown_cli_failure": ("opaque secret payload", ""),
        }
        for expected, streams in cases.items():
            self.assertEqual(transport.classify_cli_failure(*streams), expected)

    def test_session_pngs_are_scoped_to_session_ids_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mine = root / self.CURRENT_SESSION
            other = root / self.OTHER_SESSION
            mine.mkdir()
            other.mkdir()
            (mine / "img.png").write_bytes(b"mine")
            (other / "img.png").write_bytes(b"other")
            found = transport.session_pngs(
                f'{{"thread_id":"{self.CURRENT_SESSION}"}}', root
            )
            self.assertEqual(found, {(mine / "img.png").resolve()})
    def test_unkeyed_uuid_in_cli_output_is_not_session_provenance(self):
        output = f'{{"message":"artifact for {self.CURRENT_SESSION}"}}'
        self.assertEqual(transport.session_ids_in_cli(output), set())

    def test_live_rejects_png_outside_reported_session(self):
        def create_artifacts(root):
            outside = root / "unscoped"
            outside.mkdir(parents=True)
            (outside / "fresh.png").write_bytes(b"outside")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                transport.TransportError, "fresh session-scoped PNG"
            ):
                self._run_live_with_artifacts(
                    tmp,
                    f'{{"thread_id":"{self.CURRENT_SESSION}"}}',
                    create_artifacts,
                )
    def test_live_rejects_missing_session_id(self):
        def create_artifacts(root):
            current = root / self.CURRENT_SESSION
            current.mkdir(parents=True)
            (current / "fresh.png").write_bytes(b"unattributed")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                transport.TransportError, "no session/thread ID was reported"
            ):
                self._run_live_with_artifacts(
                    tmp,
                    "completed without a session identifier",
                    create_artifacts,
                )

    def test_live_moderation_refusal_is_classified_without_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                transport.TransportError, "category=moderation_rejected"
            ) as caught:
                self._run_live_with_artifacts(
                    tmp,
                    f'{{"thread_id":"{self.CURRENT_SESSION}"}}\n'
                    "I'm unable to generate this image due to content policy restrictions.",
                    lambda _root: None,
                )
        self.assertNotIn("content policy restrictions", str(caught.exception))

    def test_live_rejects_preexisting_png_in_current_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_root = Path(tmp) / "generated"
            current = generated_root / self.CURRENT_SESSION
            current.mkdir(parents=True)
            (current / "stale.png").write_bytes(b"stale")

            with self.assertRaisesRegex(
                transport.TransportError, "fresh session-scoped PNG"
            ):
                self._run_live_with_artifacts(
                    tmp,
                    f'{{"thread_id":"{self.CURRENT_SESSION}"}}',
                    lambda _root: None,
                )

    def test_live_rejects_late_artifact_from_prior_session(self):
        def create_artifacts(root):
            prior = root / self.PRIOR_SESSION
            prior.mkdir(parents=True)
            (prior / "late.png").write_bytes(b"prior retry")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                transport.TransportError, "fresh session-scoped PNG"
            ):
                self._run_live_with_artifacts(
                    tmp,
                    f'{{"thread_id":"{self.CURRENT_SESSION}"}}',
                    create_artifacts,
                )

    def test_live_rejects_parallel_other_session_artifact(self):
        def create_artifacts(root):
            other = root / self.OTHER_SESSION
            other.mkdir(parents=True)
            (other / "parallel.png").write_bytes(b"parallel")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                transport.TransportError, "fresh session-scoped PNG"
            ):
                self._run_live_with_artifacts(
                    tmp,
                    f'{{"thread_id":"{self.CURRENT_SESSION}"}}',
                    create_artifacts,
                )

    def test_live_copies_current_session_artifact_with_provenance(self):
        def create_artifacts(root):
            current = root / self.CURRENT_SESSION
            current.mkdir(parents=True)
            (current / "current.png").write_bytes(b"current session")

        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_live_with_artifacts(
                tmp,
                f'{{"thread_id":"{self.CURRENT_SESSION}"}}',
                create_artifacts,
            )
            source = (
                Path(tmp) / "generated" / self.CURRENT_SESSION / "current.png"
            ).resolve()
            self.assertEqual(result["transport_state"], "succeeded")
            self.assertEqual(result["qc_status"], "not_evaluated")
            self.assertEqual(result["source_artifact"], str(source))
            self.assertEqual((Path(tmp) / "out.png").read_bytes(), b"current session")

    def test_live_rejects_artifact_when_cli_exit_is_nonzero(self):
        def create_artifacts(root):
            current = root / self.CURRENT_SESSION
            current.mkdir(parents=True)
            (current / "failed.png").write_bytes(b"must not escape")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                transport.TransportError, "artifact from the failed invocation was rejected"
            ):
                self._run_live_with_artifacts(
                    tmp,
                    f'{{"thread_id":"{self.CURRENT_SESSION}"}}',
                    create_artifacts,
                    returncode=1,
                )
            self.assertFalse((Path(tmp) / "out.png").exists())

    def test_copy_png_exclusive_refuses_destination_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "output.png"
            source.write_bytes(b"verified")
            output.write_bytes(b"racer")
            with self.assertRaisesRegex(transport.TransportError, "Refusing to overwrite"):
                transport.copy_png_exclusive(source, output)
            self.assertEqual(output.read_bytes(), b"racer")

    def test_copy_png_exclusive_rejects_symlink_source(self):
        if not hasattr(transport.os, "O_NOFOLLOW"):
            self.skipTest("O_NOFOLLOW is unavailable on this platform")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.png"
            source = root / "source.png"
            output = root / "output.png"
            real.write_bytes(b"outside")
            source.symlink_to(real)
            with self.assertRaisesRegex(transport.TransportError, "Could not copy"):
                transport.copy_png_exclusive(source, output)
            self.assertFalse(output.exists())

    def test_timeout_is_converted_to_transport_error(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(transport, "resolve_codex_command", return_value=self._resolved()), \
                patch.object(
                    transport.subprocess,
                    "run",
                    side_effect=transport.subprocess.TimeoutExpired(cmd="codex", timeout=1),
                ), \
                patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(transport.TransportError, "timed out"):
                transport.run("draw", Path(tmp) / "out.png", [], execute=True)

    def test_empty_artifacts_are_ignored(self):
        def create_artifacts(root):
            current = root / self.CURRENT_SESSION
            current.mkdir(parents=True)
            (current / "empty.png").write_bytes(b"")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                transport.TransportError, "fresh session-scoped PNG"
            ):
                self._run_live_with_artifacts(
                    tmp,
                    f'{{"thread_id":"{self.CURRENT_SESSION}"}}',
                    create_artifacts,
                )

    def test_qc_requires_average_floor(self):
        report = transport.evaluate_qc(
            {
                "goal_fit": 3,
                "text_accuracy": 4,
                "material_realism": 4,
                "layout": 4,
            },
            rendered_text_exists=False,
        )
        self.assertEqual(report["qc_status"], "failed")
        self.assertEqual(report["average"], 3.75)
        self.assertEqual(report["failed_axes"], ["goal_fit"])
        self.assertEqual(set(report["deltas"]), {"goal_fit"})

    def test_qc_requires_text_floor_when_text_is_rendered(self):
        scores = {
            "goal_fit": 5,
            "text_accuracy": 3,
            "material_realism": 5,
            "layout": 5,
        }
        with_text = transport.evaluate_qc(scores, rendered_text_exists=True)
        without_text = transport.evaluate_qc(scores, rendered_text_exists=False)
        self.assertEqual(with_text["qc_status"], "failed")
        self.assertEqual(with_text["failed_axes"], ["text_accuracy"])
        self.assertEqual(without_text["qc_status"], "passed")
        self.assertEqual(without_text["failed_axes"], [])
    def test_qc_optional_identity_axis_passes_without_changing_canonical_average(self):
        scores = {
            "goal_fit": 4,
            "text_accuracy": 4,
            "material_realism": 4,
            "layout": 4,
            "identity_consistency": 5,
        }
        report = transport.evaluate_qc(scores, rendered_text_exists=True)
        self.assertEqual(report["qc_status"], "passed")
        self.assertEqual(report["average"], 4.0)
        self.assertEqual(report["axis_scores"], {axis: float(score) for axis, score in scores.items()})

    def test_qc_optional_identity_axis_floor_failure_has_delta(self):
        report = transport.evaluate_qc(
            {
                "goal_fit": 5,
                "text_accuracy": 5,
                "material_realism": 5,
                "layout": 5,
                "identity_consistency": 3,
            },
            rendered_text_exists=False,
        )
        self.assertEqual(report["qc_status"], "failed")
        self.assertEqual(report["failed_axes"], ["identity_consistency"])
        self.assertEqual(
            report["deltas"]["identity_consistency"],
            "re-lock the identity anchors — face geometry, hairline/part, distinctive "
            "marks — against the reference and regenerate only drifted panels.",
        )
        self.assertEqual(
            transport.plan_qc_regeneration(Path("/tmp/identity.png"), report)["failed_axes"],
            ["identity_consistency"],
        )

    def test_qc_rejects_unknown_optional_axis(self):
        with self.assertRaisesRegex(ValueError, "unexpected=.*composition"):
            transport.evaluate_qc(
                {
                    "goal_fit": 5,
                    "text_accuracy": 5,
                    "material_realism": 5,
                    "layout": 5,
                    "composition": 5,
                },
                rendered_text_exists=False,
            )

    def test_qc_four_axis_report_remains_unchanged(self):
        report = transport.evaluate_qc(
            {
                "goal_fit": 5,
                "text_accuracy": 5,
                "material_realism": 5,
                "layout": 5,
            },
            rendered_text_exists=True,
        )
        self.assertEqual(
            report,
            {
                "qc_status": "passed",
                "average": 5.0,
                "axis_scores": {
                    "goal_fit": 5.0,
                    "text_accuracy": 5.0,
                    "material_realism": 5.0,
                    "layout": 5.0,
                },
                "rendered_text_exists": True,
                "failed_axes": [],
                "deltas": {},
            },
        )

    def test_qc_plan_returns_failed_axis_deltas_and_one_output_only(self):
        report = transport.evaluate_qc(
            {
                "goal_fit": 2,
                "text_accuracy": 5,
                "material_realism": 3,
                "layout": 5,
            },
            rendered_text_exists=True,
        )
        output = Path("/tmp/affected.png")
        plan = transport.plan_qc_regeneration(output, report)
        self.assertEqual(plan["failed_axes"], ["goal_fit", "material_realism"])
        self.assertEqual(set(plan["deltas"]), {"goal_fit", "material_realism"})
        self.assertEqual(plan["regenerate_outputs"], [str(output)])

    def test_promo_qc_covers_layout_and_safety_checks(self):
        passing = transport.evaluate_promo_qc(
            physical_type_subject_interaction=True,
            generic_card_regression=False,
            printed_meta_ui_not_literal=True,
            color_count=3,
            finishing_device_count=2,
            korean_glyph_mask_safe=True,
        )
        self.assertEqual(passing["promo_status"], "passed")
        self.assertEqual(passing["failed_promo_checks"], [])

        failing = transport.evaluate_promo_qc(
            physical_type_subject_interaction=False,
            generic_card_regression=True,
            printed_meta_ui_not_literal=False,
            color_count=4,
            finishing_device_count=0,
            korean_glyph_mask_safe=False,
        )
        self.assertEqual(failing["promo_status"], "failed")
        self.assertEqual(
            failing["failed_promo_checks"],
            [
                "physical_type_subject_interaction",
                "generic_card_regression",
                "printed_meta_ui_not_literal",
                "color_lock_2_to_3",
                "finishing_devices_1_to_3",
                "korean_glyph_mask_safety",
            ],
        )

        passed_axes = transport.evaluate_qc(
            {
                "goal_fit": 5,
                "text_accuracy": 5,
                "material_realism": 5,
                "layout": 5,
            },
            rendered_text_exists=True,
        )
        output = Path(tempfile.gettempdir()) / "promo.png"
        plan = transport.plan_qc_regeneration(
            output, passed_axes, failing, promotional=True
        )
        self.assertEqual(plan["deltas"], {})
        self.assertEqual(plan["regenerate_outputs"], [str(output)])

    def test_promotional_regeneration_requires_promo_qc(self):
        output = Path(tempfile.gettempdir()) / "promo.png"
        passed_axes = transport.evaluate_qc(
            {
                "goal_fit": 5,
                "text_accuracy": 5,
                "material_realism": 5,
                "layout": 5,
            },
            rendered_text_exists=True,
        )
        with self.assertRaisesRegex(ValueError, "require a promo QC report"):
            transport.plan_qc_regeneration(
                output, passed_axes, promotional=True
            )


if __name__ == "__main__":
    unittest.main()
