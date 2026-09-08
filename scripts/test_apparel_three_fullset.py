from fixtures.png_fixture import png_bytes
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

try:
    from mpw_root import no_installation_message, resolve_mpw_root
except ModuleNotFoundError:
    from scripts.mpw_root import no_installation_message, resolve_mpw_root


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
MPW_ROOT = resolve_mpw_root()

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fullset = load("apparel_three_fullset_test", SCRIPT_DIR / "apparel_three_fullset.py")
mpw_compiler = load("mpw_apparel_handoff_test", MPW_ROOT / "scripts" / "compile_apparel_handoff.py") if MPW_ROOT else None


class ApparelDynamicFullSetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ("front-a.png", "back-a.png", "detail-a.png", "front-b.png", "front-c.png", "front-d.png"):
            (self.source / name).write_bytes(name.encode())
        self.outputs = [
            {"id": "front-a", "filename": "front-a.png", "prompt": "IMAGE. front A"},
            {"id": "front-b", "filename": "front-b.png", "prompt": "IMAGE. front B"},
            {"id": "main-back", "filename": "main-back.png", "prompt": "IMAGE. main back"},
        ]
        self.run_root = self.root / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def contract(self, colors=("navy", "ivory", "red", "black"), selection_mode=None):
        role_map = [
            {"file": "front-a.png", "role": "color_front", "color_identity": colors[0]},
            {"file": "back-a.png", "role": "main_back", "color_identity": colors[0]},
            {"file": "detail-a.png", "role": "fabric_detail", "color_identity": colors[0]},
        ]
        for index, color in enumerate(colors[1:], start=1):
            role_map.append({"file": f"front-{chr(ord('a') + index)}.png", "role": "color_front", "color_identity": color})
        return {
            "schema_version": 1,
            "folder_id": "sku-001",
            "source_folder": str(self.source),
            "sources": [path.name for path in sorted(self.source.iterdir())],
            "vision_role_map": role_map,
            "normalized_color_identity": list(colors),
            "unique_color_count": len(colors),
            "mpw_folder_master": "same immutable folder master",
            "qc_contract": "source fidelity, support removal, pure white, no invention, family similarity",
            "outputs": self.outputs,
            **({"selection_mode": selection_mode} if selection_mode is not None else {}),
        }

    def prepare(self, colors=("navy", "ivory", "red", "black"), selection_mode=None, folder_id=None):
        contract = self.contract(colors, selection_mode=selection_mode)
        contract["folder_id"] = folder_id or f"sku-{len(colors)}"
        contract_path = self.root / f"contract-{contract['folder_id']}.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return fullset.prepare_folder(contract_path, self.run_root)

    def populate_candidates(self, coordinator, missing=None):
        folder_root = Path(coordinator["folder_root"])
        shared = fullset.read_json(folder_root / "shared-folder-contract.json")
        missing = missing or set()
        for task_number, set_name in enumerate(coordinator["candidate_sets"], start=1):
            rows = {}
            for output in self.outputs:
                path = folder_root / set_name / output["filename"]
                if (set_name, output["id"]) in missing:
                    continue
                path.write_bytes(png_bytes(seed=sum(f"{set_name}:{output['id']}".encode())))
                rows[output["id"]] = {
                    "state": "completed",
                    "filename": output["filename"],
                    "sha256": fullset.sha256_file(path),
                    "size": path.stat().st_size,
                }
            ledger = {
                "schema_version": 1,
                "task_id": f"task-{task_number}",
                "candidate_set": set_name,
                "shared_contract_sha256": coordinator["shared_contract_sha256"],
                "outputs": rows,
                "state": "complete" if len(rows) == len(self.outputs) else "partial",
                "identical_output_inventory": [output["filename"] for output in self.outputs],
            }
            (folder_root / set_name / "task-ledger.json").write_text(json.dumps(ledger), encoding="utf-8")

    def report(self, coordinator, preferred=None, similarity=0.90, omit_assessments=None,
               pair_overrides=None, omit_pairs=None, selection_mode=None):
        preferred = preferred or {}
        omit_assessments = omit_assessments or set()
        pair_overrides = pair_overrides or {}
        omit_pairs = omit_pairs or set()
        sets = coordinator["candidate_sets"]
        report = {"shared_contract_sha256": coordinator["shared_contract_sha256"], "outputs": {}, "similarities": []}
        if selection_mode is not None:
            report["selection_mode"] = selection_mode
        for output in self.outputs:
            candidates = {}
            for set_name in sets:
                if (set_name, output["id"]) not in omit_assessments:
                    candidates[set_name] = {
                        "source_fidelity": 0.99 if preferred.get(output["id"]) == set_name else 0.80,
                        "support_removal": True,
                        "pure_white_no_shadow": True,
                        "no_invented_detail": True,
                        "vision_verdict": f"accept {set_name} {output['id']}",
                    }
            report["outputs"][output["id"]] = {"candidates": candidates}
        for i, first in enumerate(self.outputs):
            for second in self.outputs[i + 1:]:
                for first_set in sets:
                    for second_set in sets:
                        key = (first["id"], first_set, second["id"], second_set)
                        if key in omit_pairs:
                            continue
                        report["similarities"].append({
                            "a_output": first["id"], "a_set": first_set,
                            "b_output": second["id"], "b_set": second_set,
                            "score": pair_overrides.get(key, similarity),
                        })
        path = Path(coordinator["folder_root"]) / "vision-selector-report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_resume_rejects_changed_report_and_incomplete_provenance(self):
        coordinator = self.prepare(("navy",))
        self.populate_candidates(coordinator)
        report = self.report(coordinator)
        coordinator_path = Path(coordinator["folder_root"]) / "coordinator.json"
        fullset.select_candidates(coordinator_path, report)
        original = report.read_bytes()
        report.write_bytes(original + b" ")
        with self.assertRaisesRegex(fullset.ContractError, "identity mismatch"):
            fullset.select_candidates(coordinator_path, report)
        report.write_bytes(original)
        provenance_path = Path(coordinator["selected_root"]) / "provenance.json"
        provenance = fullset.read_json(provenance_path)
        provenance["files"].pop()
        provenance_path.write_text(json.dumps(provenance))
        with self.assertRaisesRegex(fullset.ContractError, "inventory mismatch"):
            fullset.select_candidates(coordinator_path, report)

    def test_string_false_is_not_a_passing_vision_gate(self):
        with self.assertRaisesRegex(fullset.ContractError, "booleans"):
            fullset._candidate_quality({"source_fidelity": .9, "support_removal": "false",
                "pure_white_no_shadow": True, "no_invented_detail": True})

    def test_reversed_duplicate_similarity_is_rejected(self):
        row = {"a_output":"a", "a_set":"1", "b_output":"b", "b_set":"2", "score":.9}
        reverse = {"a_output":"b", "a_set":"2", "b_output":"a", "b_set":"1", "score":.95}
        with self.assertRaisesRegex(fullset.ContractError, "duplicate"):
            fullset._similarity_map({"similarities": [row, reverse]})

    def test_zero_one_and_four_color_task_count(self):
        zero = self.contract(("navy",))
        zero["vision_role_map"] = [{"file": "front-a.png", "role": "detail", "color_identity": "navy"}]
        zero["normalized_color_identity"] = []
        zero["unique_color_count"] = 0
        with self.assertRaisesRegex(fullset.ContractError, "blocked"):
            fullset.validate_folder_contract(zero)
        one = self.prepare(("navy",))
        four = self.prepare(("navy", "ivory", "red", "black"))
        self.assertEqual((one["task_count"], one["candidate_sets"]), (3, [f"candidate-set-{n}" for n in range(1, 4)]))
        self.assertEqual((four["task_count"], four["candidate_sets"]), (3, [f"candidate-set-{n}" for n in range(1, 4)]))
        self.assertEqual(one["candidate_attempt_count"], 3)
        self.assertEqual(four["color_identities"], ["navy", "ivory", "red", "black"])

    def test_plain_product_folder_auto_maps_roles_and_defaults_to_three_attempts(self):
        plain = self.contract(("navy",))
        for old, new in (("front-a.png", "f1.jpg"), ("back-a.png", "b1.jpg"), ("detail-a.png", "d1.jpg")):
            (self.source / old).rename(self.source / new)
        plain["sources"] = [path.name for path in sorted(self.source.iterdir())]
        plain["vision_role_map"] = []
        plain.pop("normalized_color_identity", None)
        plain.pop("unique_color_count", None)
        normalized = fullset.validate_folder_contract(plain)
        self.assertEqual(normalized["candidate_attempt_count"], 3)
        self.assertEqual(normalized["task_count"], 3)
        self.assertEqual(normalized["color_identities"], ["default"])
        self.assertEqual({row["file"] for row in normalized["vision_role_map"]}, {"f1.jpg", "b1.jpg", "d1.jpg"})

    def test_duplicate_colors_and_filename_do_not_change_count(self):
        contract = self.contract(("navy", "ivory"))
        contract["vision_role_map"].extend([
            {"file": "back-a.png", "role": "color_front", "color_identity": "ＮＡＶＹ\u00a0 BLUE"},
            {"file": "detail-a.png", "role": "fabric_detail", "color_identity": "red"},
        ])
        contract["vision_role_map"][0]["color_identity"] = "navy blue"
        contract["normalized_color_identity"] = ["navy blue", "ivory"]
        contract["unique_color_count"] = 2
        normalized = fullset.validate_folder_contract(contract)
        self.assertEqual(normalized["color_identities"], ["navy blue", "ivory"])
        no_identity = copy.deepcopy(contract)
        del no_identity["vision_role_map"][0]["color_identity"]
        with self.assertRaisesRegex(fullset.ContractError, "cannot be inferred from filenames|requires"):
            fullset.validate_folder_contract(no_identity)

    def test_dynamic_tasks_share_complete_inventory_and_disjoint_paths(self):
        coordinator = self.prepare()
        specs = [fullset.read_json(Path(path)) for path in coordinator["task_specs"]]
        self.assertEqual(len(specs), 3)
        self.assertEqual([spec["task_id"] for spec in specs], [f"task-{n}" for n in range(1, 4)])
        self.assertEqual(len({spec["candidate_root"] for spec in specs}), 3)
        self.assertTrue(all(spec["color_identities"] == ["navy", "ivory", "red", "black"] for spec in specs))
        dry_runs = [fullset.inspect_candidate_task(Path(path)) for path in coordinator["task_specs"]]
        inventories = [[row["filename"] for row in result["complete_output_inventory"]] for result in dry_runs]
        self.assertTrue(all(inventory == inventories[0] for inventory in inventories))
        self.assertEqual(inventories[0], [output["filename"] for output in self.outputs])
        self.assertTrue(all(result["source_count"] == len(self.contract()["sources"]) for result in dry_runs))
        self.assertTrue(all(result["invariants"]["complete_source_inventory"] for result in dry_runs))

    def test_runtime_20_packs_five_four_task_folders_and_blocks_oversize(self):
        base = self.prepare()
        coords = []
        for index in range(6):
            clone = dict(base)
            clone["folder_id"] = f"sku-{index}"
            clone["folder_root"] = f"/tmp/sku-{index}"
            clone["task_specs"] = [f"/tmp/sku-{index}-task-{task}.json" for task in range(1, 4)]
            coords.append(clone)
        waves = fullset.build_schedule(coords, 20)
        self.assertEqual([wave["active_count"] for wave in waves], [18, 6])
        oversize = dict(base)
        oversize["task_count"] = 21
        oversize["candidate_sets"] = [f"candidate-set-{n}" for n in range(1, 22)]
        oversize["task_specs"] = [f"/tmp/task-{n}.json" for n in range(1, 22)]
        with self.assertRaisesRegex(fullset.ContractError, "blocked"):
            fullset.build_schedule([oversize], 20)

    def test_default_mixed_selection_picks_best_cut_per_output_across_sets(self):
        coordinator = self.prepare()
        self.populate_candidates(coordinator)
        preferred = {"front-a": "candidate-set-1", "front-b": "candidate-set-2", "main-back": "candidate-set-3"}
        report = self.report(coordinator, preferred=preferred)
        coordinator_path = Path(coordinator["folder_root"]) / "coordinator.json"
        result = fullset.select_candidates(coordinator_path, report)
        selected = {row["output_id"]: row["source_candidate_set"] for row in result["files"]}
        self.assertEqual(selected, preferred)
        self.assertEqual(result["selection"], "mixed")
        self.assertEqual(result["selection_mode"], "mixed")
        self.assertGreaterEqual(result["score"]["min_similarity"], 0.80)
        for row in result["files"]:
            self.assertEqual(len(row["rejected_alternatives"]), 2)
            self.assertIn("source_task", row)
            self.assertIn("source_path", row)
            self.assertIn("source_sha256", row)
            self.assertEqual(row["source_fidelity"], 0.99)
            for alternative in row["rejected_alternatives"]:
                self.assertIn("source_fidelity", alternative)
        for set_name in coordinator["candidate_sets"]:
            self.assertFalse((Path(coordinator["folder_root"]) / set_name).exists())
        resumed = fullset.select_candidates(coordinator_path, report)
        self.assertTrue(resumed["resume_verified"])
        with self.assertRaisesRegex(fullset.ContractError, "refusing overwrite"):
            fullset.select_candidates(coordinator_path, report, selection_mode="whole-set")
        target = Path(coordinator["selected_root"]) / "front-a.png"
        target.write_bytes(b"tampered")
        with self.assertRaisesRegex(fullset.ContractError, "resume verification"):
            fullset.select_candidates(coordinator_path, report)

    def test_explicit_whole_set_mode_keeps_one_coherent_set(self):
        preferred = {"front-a": "candidate-set-1", "front-b": "candidate-set-2", "main-back": "candidate-set-3"}
        for label, kwargs in (
            ("contract", {"prepare": {"selection_mode": "whole-set"}}),
            ("cli", {"select": {"selection_mode": "whole-set"}}),
            ("report", {"report": {"selection_mode": "whole-set"}}),
        ):
            coordinator = self.prepare(folder_id=f"sku-whole-{label}", **kwargs.get("prepare", {}))
            self.populate_candidates(coordinator)
            report = self.report(coordinator, preferred=preferred, **kwargs.get("report", {}))
            result = fullset.select_candidates(
                Path(coordinator["folder_root"]) / "coordinator.json", report, **kwargs.get("select", {})
            )
            selected = {row["output_id"]: row["source_candidate_set"] for row in result["files"]}
            self.assertEqual(set(selected.values()), {"candidate-set-1"}, label)
            self.assertEqual(result["selection"], "whole-set", label)
            self.assertEqual(result["selection_mode"], "whole-set", label)

    def test_mixed_family_fails_closed_when_any_selected_pair_is_below_threshold(self):
        coordinator = self.prepare()
        self.populate_candidates(coordinator)
        preferred = {"front-a": "candidate-set-1", "front-b": "candidate-set-2", "main-back": "candidate-set-3"}
        bad_pair = {("front-a", "candidate-set-1", "front-b", "candidate-set-2"): 0.79}
        report = self.report(coordinator, preferred=preferred, pair_overrides=bad_pair)
        with self.assertRaisesRegex(fullset.ContractError, "80%"):
            fullset.select_candidates(Path(coordinator["folder_root"]) / "coordinator.json", report)
        self.assertFalse(Path(coordinator["selected_root"]).exists())
        # The same report still passes for an explicit whole-set request because
        # intra-set pairs stay above the gate.
        whole = fullset.select_candidates(
            Path(coordinator["folder_root"]) / "coordinator.json", report, selection_mode="whole-set"
        )
        self.assertEqual(whole["selection"], "whole-set")

    def test_mixed_family_fails_closed_when_a_selected_pair_is_unscored(self):
        coordinator = self.prepare()
        self.populate_candidates(coordinator)
        preferred = {"front-a": "candidate-set-1", "front-b": "candidate-set-2", "main-back": "candidate-set-3"}
        missing = {
            ("front-a", "candidate-set-1", "front-b", "candidate-set-2"),
            ("front-b", "candidate-set-2", "front-a", "candidate-set-1"),
        }
        report = self.report(coordinator, preferred=preferred, omit_pairs=missing)
        with self.assertRaisesRegex(fullset.ContractError, "missing family similarity"):
            fullset.select_candidates(Path(coordinator["folder_root"]) / "coordinator.json", report)
        self.assertFalse(Path(coordinator["selected_root"]).exists())

    def test_mixed_fidelity_ties_resolve_deterministically_to_lowest_attempt(self):
        selections = []
        for run in ("first", "second"):
            coordinator = self.prepare(folder_id=f"sku-tie-{run}")
            self.populate_candidates(coordinator)
            report = self.report(coordinator)  # every candidate has identical fidelity
            result = fullset.select_candidates(Path(coordinator["folder_root"]) / "coordinator.json", report)
            selections.append({row["output_id"]: row["source_candidate_set"] for row in result["files"]})
        self.assertEqual(selections[0], selections[1])
        self.assertEqual(set(selections[0].values()), {"candidate-set-1"})

    def test_unknown_or_conflicting_selection_modes_fail_closed(self):
        with self.assertRaisesRegex(fullset.ContractError, "unknown selection_mode"):
            fullset.validate_folder_contract(self.contract(selection_mode="best-of"))
        coordinator = self.prepare()
        self.populate_candidates(coordinator)
        coordinator_path = Path(coordinator["folder_root"]) / "coordinator.json"
        report = self.report(coordinator)
        with self.assertRaisesRegex(fullset.ContractError, "unknown --selection-mode"):
            fullset.select_candidates(coordinator_path, report, selection_mode="banana")
        bad_report = self.report(coordinator, selection_mode="per-cut")
        with self.assertRaisesRegex(fullset.ContractError, "unknown report selection_mode"):
            fullset.select_candidates(coordinator_path, bad_report)
        conflicted = self.report(coordinator, selection_mode="whole-set")
        with self.assertRaisesRegex(fullset.ContractError, "different selection modes"):
            fullset.select_candidates(coordinator_path, conflicted, selection_mode="mixed")
        self.assertFalse(Path(coordinator["selected_root"]).exists())

    def test_80_percent_gate_and_unowned_selected_directory_fail_closed(self):
        coordinator = self.prepare()
        self.populate_candidates(coordinator)
        path = self.report(coordinator, similarity=0.79)
        with self.assertRaisesRegex(fullset.ContractError, "80%"):
            fullset.select_candidates(Path(coordinator["folder_root"]) / "coordinator.json", path)
        self.assertFalse(Path(coordinator["selected_root"]).exists())
        selected = Path(coordinator["selected_root"])
        selected.mkdir()
        with self.assertRaisesRegex(fullset.ContractError, "without provenance"):
            fullset.select_candidates(Path(coordinator["folder_root"]) / "coordinator.json", path)

    def test_complete_inventory_immutable_sources_and_bound_candidate_roots(self):
        missing = self.contract(("navy",))
        missing["sources"].remove("detail-a.png")
        with self.assertRaisesRegex(fullset.ContractError, "complete source image inventory"):
            fullset.validate_folder_contract(missing)
        unknown_role_source = self.contract(("navy",))
        unknown_role_source["vision_role_map"].append({"file": "not-in-inventory.png", "role": "detail"})
        with self.assertRaisesRegex(fullset.ContractError, "not in complete source inventory"):
            fullset.validate_folder_contract(unknown_role_source)

        coordinator = self.prepare(("navy",))
        spec_path = Path(coordinator["task_specs"][0])
        (self.source / "front-a.png").write_bytes(b"changed after prepare")
        with self.assertRaisesRegex(fullset.ContractError, "immutable source inventory changed"):
            fullset.inspect_candidate_task(spec_path)

        fresh_contract = self.contract(("ivory",))
        fresh_contract["folder_id"] = "sku-fresh"
        fresh_contract_path = self.root / "fresh-contract.json"
        fresh_contract_path.write_text(json.dumps(fresh_contract), encoding="utf-8")
        fresh = fullset.prepare_folder(fresh_contract_path, self.run_root)
        fresh_spec_path = Path(fresh["task_specs"][0])
        spec = fullset.read_json(fresh_spec_path)
        spec["candidate_root"] = str(self.root / "outside" / spec["candidate_set"])
        external_spec_path = self.root / "external-task.json"
        external_spec_path.write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaisesRegex(fullset.ContractError, "disjoint attempt ownership"):
            fullset.inspect_candidate_task(external_spec_path)

    def test_source_overlap_and_candidate_ledger_provenance_fail_closed(self):
        overlap = self.contract(("navy",))
        overlap["folder_id"] = self.source.name
        overlap_path = self.root / "overlap-contract.json"
        overlap_path.write_text(json.dumps(overlap), encoding="utf-8")
        with self.assertRaisesRegex(fullset.ContractError, "overlaps read-only source"):
            fullset.prepare_folder(overlap_path, self.root)

        no_ledger = self.prepare(("navy", "ivory"))
        self.populate_candidates(no_ledger)
        no_ledger_report = self.report(no_ledger)
        (Path(no_ledger["folder_root"]) / "candidate-set-1" / "task-ledger.json").unlink()
        with self.assertRaisesRegex(fullset.ContractError, "ledger missing"):
            fullset.select_candidates(Path(no_ledger["folder_root"]) / "coordinator.json", no_ledger_report)

        tampered = self.prepare(("navy", "ivory", "red"))
        self.populate_candidates(tampered)
        tampered_report = self.report(tampered)
        (Path(tampered["folder_root"]) / "candidate-set-1" / "front-a.png").write_bytes(b"forged")
        with self.assertRaisesRegex(fullset.ContractError, "not ledger-verified"):
            fullset.select_candidates(Path(tampered["folder_root"]) / "coordinator.json", tampered_report)

        incomplete = self.prepare(("navy", "ivory", "red", "black"))
        self.populate_candidates(incomplete, missing={("candidate-set-1", "front-a")})
        incomplete_report = self.report(incomplete)
        with self.assertRaisesRegex(fullset.ContractError, "ledger identity|ledger inventory"):
            fullset.select_candidates(Path(incomplete["folder_root"]) / "coordinator.json", incomplete_report)

    def test_portable_producer_to_consumer_handoff_is_network_free(self):
        if MPW_ROOT is None or mpw_compiler is None:
            self.skipTest(no_installation_message())
        self.assertEqual(
            (SKILL_ROOT / "references" / "apparel-handoff.schema.json").read_bytes(),
            (MPW_ROOT / "contracts" / "v1" / "apparel-handoff.schema.json").read_bytes(),
        )
        self.assertEqual(
            (SKILL_ROOT / "references" / "fixtures" / "apparel-handoff.valid.json").read_bytes(),
            (MPW_ROOT / "contracts" / "v1" / "fixtures" / "apparel-handoff.valid.json").read_bytes(),
        )
        request = {
            "schema_version": "apparel-compile-request/v1",
            "folder_id": "handoff-sku",
            "source_folder": str(self.source),
            "sources": [path.name for path in sorted(self.source.iterdir())],
            "vision_role_map": [
                {"file": "front-a.png", "role": "color_front", "color_identity": " NAVY "},
                {"file": "front-b.png", "role": "color_front", "color_identity": "ivory"},
                {"file": "back-a.png", "role": "main_back", "color_identity": "navy"},
            ],
            "requested_outputs": [
                {"id": "navy", "filename": "navy.png", "view": "front", "color_identity": "navy", "product_description": "knit top", "cut_type": "ghost_cut", "visible_details": []},
                {"id": "ivory", "filename": "ivory.png", "view": "front", "color_identity": "ivory", "product_description": "knit top", "cut_type": "ghost_cut", "visible_details": []},
            ],
        }
        handoff = mpw_compiler.compile_request(request)
        path = self.root / "handoff.json"
        path.write_text(json.dumps(handoff), encoding="utf-8")
        coordinator = fullset.prepare_folder(path, self.run_root)
        self.assertEqual(coordinator["task_count"], 3)
        self.assertEqual(coordinator["candidate_sets"], ["candidate-set-1", "candidate-set-2", "candidate-set-3"])
        self.assertEqual(coordinator["output_inventory"], ["navy.png", "ivory.png"])


if __name__ == "__main__":
    unittest.main()
