from fixtures.png_fixture import png_bytes
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPTS = Path(__file__).parent

def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

fullset = load("apparel_three_fullset")
helper = load("folder_batch_prepare")

class FolderBatchPrepareTests(unittest.TestCase):
    def image(self, root, name, data=None):
        path = root / name; path.write_bytes(data if data is not None else (png_bytes(seed=sum(name.encode())) if path.suffix == ".png" else name.encode())); return path
    def invoke(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out): code = helper.main(list(args))
        return code, json.loads(out.getvalue())
    def prepare(self, source, work, ts="20260715_123456", dry=False, extra=()):
        return self.invoke("--input-dir", str(source), "--work-root", str(work), "--timestamp", ts, *( ["--dry-run"] if dry else []), *extra)
    def test_01_happy_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); src=root/"product"; src.mkdir(); work=root/"work"
            for n in ("f1.jpg","b1.jpg","d1_원단.jpg","Thumbs.db",".DS_Store","notes.txt"): self.image(src,n)
            (src/"AI_RESULT_20260101_000000").mkdir()
            code, result=self.prepare(src,work); self.assertEqual(code,0)
            contract=fullset.read_json(work/"folder-contract.json"); fullset.validate_folder_contract(contract)
            self.assertEqual({x["file"]:x["role"] for x in contract["vision_role_map"]},{"b1.jpg":"main_back","d1_원단.jpg":"fabric_detail","f1.jpg":"color_front"})
            self.assertEqual([x["filename"] for x in contract["outputs"]],["b1.png","d1_원단.png","f1.png"])
            self.assertEqual(result["counts"],{"sources":3,"outputs":3,"skipped":3,"existing_result_folders":1})
            self.assertEqual(result["result_subfolder"],"AI_RESULT_20260715_123456")
            self.assertEqual(result["contract_sha256"],fullset.sha256_file(work/"folder-contract.json"))
            self.assertEqual(len(result["runner"]["task_specs"]),3)
            self.assertEqual(next(x for x in contract["vision_role_map"] if x["file"]=="f1.jpg")["color_identity"],"default")
            self.assertEqual(next(x for x in contract["vision_role_map"] if x["file"]=="d1_원단.jpg")["descriptor"],"원단")
    def test_02_variants(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp); s=r/"p";s.mkdir();w=r/"w"
            for n in ("f1.jpg","f2.jpg","b1.jpg","b2.jpg","c0.jpg","d0.jpg","s0.jpg"):self.image(s,n)
            self.assertEqual(self.prepare(s,w)[0],0); c=fullset.read_json(w/"folder-contract.json")
            self.assertEqual([x["color_identity"] for x in c["vision_role_map"] if x["role"]=="color_front"],["c0","default"])
            self.assertEqual({x["role"] for x in c["vision_role_map"]},{"color_front","front_variant","main_back","back_variant","fabric_detail","composite_source"})
            self.assertEqual(next(x for x in c["vision_role_map"] if x["file"]=="d0.jpg")["role"],"fabric_detail")
    def test_03_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"x1.jpg"); code,result=self.prepare(s,r/"w")
            self.assertEqual(code,2);self.assertIn("x1.jpg",result["error"])
            self.image(s,"f0.jpg"); code,result=self.prepare(s,r/"w");self.assertEqual(code,2);self.assertIn("f0.jpg",result["error"])
    def test_04_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"f1.jpg");self.image(s,"f1_alt.jpg")
            with self.assertRaises(fullset.ContractError):helper.prepare(helper.parser().parse_args(["--input-dir",str(s),"--work-root",str(r/"w")]))
    def test_05_no_front(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"b1.jpg");code,x=self.prepare(s,r/"w");self.assertEqual(code,2);self.assertIn("front cut",x["error"])
    def test_06_unicode_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"상품 코드 2026SS";s.mkdir();self.image(s,"f1.jpg");self.assertEqual(self.prepare(s,r/"w")[0],0)
    def test_07_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"f1.jpg")
            try: os.symlink(s/"f1.jpg",s/"b1.jpg")
            except OSError: self.skipTest("symlinks unavailable")
            code,x=self.prepare(s,r/"w");self.assertEqual(code,2);self.assertIn("symlink",x["error"])
    def test_08_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"f1.jpg")
            for w in (s/"work",r):
                code,x=self.prepare(s,w);self.assertEqual(code,2);self.assertIn("overlaps",x["error"])
    def test_09_existing_result(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"f1.jpg");(s/"AI_RESULT_20260715_123456").mkdir();code,x=self.prepare(s,r/"w");self.assertEqual(code,2);self.assertIn("planned result",x["error"])
    def test_10_dry_run(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"f1.jpg",b"original"); before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in s.iterdir()}
            code,x=self.prepare(s,r/"w",dry=True);self.assertEqual(code,0);self.assertIsNone(x["runner"]);self.assertFalse((r/"w"/"runs").exists());self.assertTrue((r/"w"/"vision-handoff.json").is_file());self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in s.iterdir()})
    def test_11_determinism(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();self.image(s,"f1.jpg");w=r/"w";a=self.prepare(s,w);b=self.prepare(s,w);self.assertEqual(a[0],b[0]);self.assertEqual(a[1]["result_subfolder"],b[1]["result_subfolder"]);code,x=self.prepare(s,w,extra=("--candidate-attempts","4"));self.assertEqual(code,2);self.assertIn("different folder contract",x["error"])
    def selected(self, root, folder_id, names=("f1.png","b1.png","d1.png")):
        source = root.parent / folder_id
        if source.is_dir():
            for name in names:
                source_file = source / (Path(name).stem + ".jpg")
                if not source_file.exists(): source_file.write_bytes(name.encode())
        root.mkdir(); rows=[]
        for n in names:
            p=self.image(root,n); rows.append({"filename":n,"selected_sha256":fullset.sha256_file(p),"output_id":p.stem,"source_candidate_set":"candidate-set-1"})
        fullset.atomic_json(root/"provenance.json",{"schema_version":1,"folder_id":folder_id,"files":rows,"selection_mode":"mixed","min_family_similarity_gate":.8,"score":{"fidelity_sum":.95*len(names),"min_similarity":.93,"average_similarity":.96}});return rows
    def test_publish_blocks_missing_cut_and_nonfinite_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp); source=r/"product"; source.mkdir(); selected=r/"selected"
            self.selected(selected, source.name)
            original=fullset.read_json(selected/"provenance.json")
            for mutation in ("missing", "nan", "weak_gate"):
                data=json.loads(json.dumps(original))
                if mutation == "missing": data["files"].pop()
                elif mutation == "nan": data["score"]["min_similarity"]=float("nan")
                else: data["min_family_similarity_gate"]=0.1
                fullset.atomic_json(selected/"provenance.json", data)
                code, result=self.invoke("--input-dir",str(source),"--publish-from",str(selected),"--timestamp","20260715_123456")
                self.assertEqual(code,2, result)
                self.assertFalse((source/"AI_RESULT_20260715_123456").exists())

    def test_12_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();selected=r/"selected";self.selected(selected,s.name);code,x=self.invoke("--input-dir",str(s),"--publish-from",str(selected),"--timestamp","20260715_123456");self.assertEqual(code,0);self.assertTrue(x["published"]);self.assertEqual(x["counts"]["published"],3);self.assertTrue((s/"AI_RESULT_20260715_123456"/"batch-summary.json").is_file())
    def test_13_publish_nonoverwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();q=r/"q";self.selected(q,s.name);args=("--input-dir",str(s),"--publish-from",str(q),"--timestamp","20260715_123456");self.assertEqual(self.invoke(*args)[0],0);self.assertEqual(self.invoke(*args)[0],2)
    def test_14_publish_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();q=r/"q";self.selected(q,s.name);self.image(q,"f1.png",b"tampered");code,x=self.invoke("--input-dir",str(s),"--publish-from",str(q),"--timestamp","20260715_123456");self.assertEqual(code,2);self.assertFalse((s/"AI_RESULT_20260715_123456").exists());self.assertFalse(any(p.name.startswith(".ai-result-stage-") for p in s.iterdir()))
    def test_15_publish_retry_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();q=r/"q";rows=self.selected(q,s.name);(q/"d1.png").unlink();args=("--input-dir",str(s),"--publish-from",str(q),"--timestamp","20260715_123456");self.assertEqual(self.invoke(*args)[0],2);self.assertFalse((s/"AI_RESULT_20260715_123456").exists());self.assertFalse(any(p.name.startswith(".ai-result-stage-") for p in s.iterdir()));self.image(q,"d1.png");rows[2]["selected_sha256"]=fullset.sha256_file(q/"d1.png");fullset.atomic_json(q/"provenance.json",{"schema_version":1,"folder_id":s.name,"files":rows,"selection_mode":"mixed","min_family_similarity_gate":.8,"score":{"fidelity_sum":2.85,"min_similarity":.93,"average_similarity":.96}});self.assertEqual(self.invoke(*args)[0],0)
    def test_17_publish_provenance_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();q=r/"q";self.selected(q,s.name)
            valid=fullset.read_json(q/"provenance.json")
            for field,value,expected in (("folder_id","other","folder_id"),("files",[],"non-empty"),("score",.9,"score must be an object")):
                provenance=json.loads(json.dumps(valid));provenance[field]=value;fullset.atomic_json(q/"provenance.json",provenance)
                code,x=self.invoke("--input-dir",str(s),"--publish-from",str(q),"--timestamp","20260715_123456");self.assertEqual(code,2);self.assertIn(expected,x["error"])

    def test_18_publish_empty_destination_and_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);s=r/"p";s.mkdir();q=r/"q";self.selected(q,s.name);destination=s/"AI_RESULT_20260715_123456";destination.mkdir()
            args=("--input-dir",str(s),"--publish-from",str(q),"--timestamp","20260715_123456");code,x=self.invoke(*args);self.assertEqual(code,2);self.assertIn("refusing to overwrite",x["error"])
            destination.rmdir();code,x=self.invoke(*args);self.assertEqual(code,0)
            if os.name != "nt":self.assertEqual((destination.stat().st_mode & 0o755),0o755)

    def test_19_publish_provenance_snapshot_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp)
            s = r / "p"
            s.mkdir()
            q = r / "q"
            self.selected(q, s.name)
            real = q / "provenance-real.json"
            (q / "provenance.json").rename(real)
            try:
                os.symlink(real, q / "provenance.json")
            except OSError:
                self.skipTest("symlinks unavailable")
            code, x = self.invoke("--input-dir", str(s), "--publish-from", str(q), "--timestamp", "20260715_123456")
            self.assertEqual(code, 2)
            self.assertIn("provenance.json", x["error"])
            os.unlink(q / "provenance.json")
            real.rename(q / "provenance.json")
            code, x = self.invoke("--input-dir", str(s), "--publish-from", str(q), "--timestamp", "20260715_123456")
            self.assertEqual(code, 0)
            summary = fullset.read_json(s / "AI_RESULT_20260715_123456" / "batch-summary.json")
            self.assertEqual(summary["provenance_sha256"], fullset.sha256_file(q / "provenance.json"))

    def test_20_prepare_rejects_symlinked_run_root(self):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp)
            s = r / "p"
            s.mkdir()
            self.image(s, "f1.jpg")
            w = r / "w"
            (w / "runs").mkdir(parents=True)
            try:
                os.symlink(s, w / "runs" / s.name)
            except OSError:
                self.skipTest("symlinks unavailable")
            before = {p.name: fullset.sha256_file(p) for p in s.iterdir() if p.is_file()}
            code, x = self.invoke("--input-dir", str(s), "--work-root", str(w), "--timestamp", "20260715_123456")
            self.assertEqual(code, 2)
            self.assertIn("symlink", x["error"])
            self.assertEqual(before, {p.name: fullset.sha256_file(p) for p in s.iterdir() if p.is_file()})

    def test_21_publish_cleanup_fault_injection(self):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp)
            s = r / "p"
            s.mkdir()
            q = r / "q"
            self.selected(q, s.name)
            destination = s / "AI_RESULT_20260715_123456"
            args = ("--input-dir", str(s), "--publish-from", str(q), "--timestamp", "20260715_123456")
            with mock.patch.object(helper.os, "chmod", side_effect=OSError("chmod denied")):
                code, x = self.invoke(*args)
            self.assertEqual(code, 2)
            self.assertIn("retry is safe", x["error"])
            self.assertFalse(destination.exists())
            self.assertFalse(any(p.name.startswith(".ai-result-stage-") for p in s.iterdir()))
            with mock.patch.object(helper.os, "rename", side_effect=OSError("smb sharing violation")), \
                    mock.patch.object(helper, "_cleanup_stage", return_value=False):
                code, x = self.invoke(*args)
            self.assertEqual(code, 2)
            self.assertIn("residue remains", x["error"])
            self.assertIn(".ai-result-stage-", x["error"])
            for p in list(s.iterdir()):
                if p.name.startswith(".ai-result-stage-"):
                    shutil.rmtree(p)
            code, x = self.invoke(*args)
            self.assertEqual(code, 0)

    def test_22_publish_hashes_the_parsed_provenance_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp)
            s = r / "p"
            s.mkdir()
            q = r / "q"
            self.selected(q, s.name)
            snapshot = (q / "provenance.json").read_bytes()
            original = helper._validate_provenance

            def swap_after_snapshot(provenance, source, selected_root):
                (q / "provenance.json").write_text("{}", encoding="utf-8")
                return original(provenance, source, selected_root)

            with mock.patch.object(helper, "_validate_provenance", side_effect=swap_after_snapshot):
                code, x = self.invoke("--input-dir", str(s), "--publish-from", str(q), "--timestamp", "20260715_123456")
            self.assertEqual(code, 0)
            summary = fullset.read_json(s / "AI_RESULT_20260715_123456" / "batch-summary.json")
            self.assertEqual(summary["provenance_sha256"], hashlib.sha256(snapshot).hexdigest())
            self.assertNotEqual(summary["provenance_sha256"], fullset.sha256_file(q / "provenance.json"))

    def test_23_prepare_rejects_symlinked_work_root(self):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp)
            s = r / "p"
            s.mkdir()
            self.image(s, "f1.jpg")
            real = r / "real-work"
            real.mkdir()
            try:
                os.symlink(real, r / "w")
            except OSError:
                self.skipTest("symlinks unavailable")
            code, x = self.prepare(s, r / "w")
            self.assertEqual(code, 2)
            self.assertIn("symlink", x["error"])

    def test_24_unc_input_is_canonicalized_once_and_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "상품 공유 폴더"
            source.mkdir()
            self.image(source, "f1_앞면.jpg")
            work = root / "work"
            unc = r"\\server\share\상품 공유 폴더"
            with mock.patch.object(helper, "normalize_local_path", return_value=str(source)) as normalize:
                code, result = self.prepare(unc, work, dry=True)
            self.assertEqual(code, 0)
            normalize.assert_called_once_with(unc, field="--input-dir")
            plan = fullset.read_json(Path(result["output_plan_path"]))
            self.assertEqual(plan["source_folder"], str(source.resolve()))
            self.assertEqual(plan["result_path"], str(source.resolve() / result["result_subfolder"]))

    def test_25_publish_refuses_injected_collision_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "긴 경로" / ("가" * 40) / ("나" * 40)
            source.mkdir(parents=True)
            original = self.image(source, "f1.jpg", b"original-source")
            selected = root / "selected outputs"
            self.selected(selected, source.name, names=("f1.png",))
            destination = source / "AI_RESULT_20260715_123456"
            args = ("--input-dir", str(source), "--publish-from", str(selected), "--timestamp", "20260715_123456")
            source_sha = fullset.sha256_file(original)

            def collide(_stage, _mode):
                destination.mkdir()

            with mock.patch.object(helper.os, "chmod", side_effect=collide):
                code, result = self.invoke(*args)
            self.assertEqual(code, 2)
            self.assertIn("refusing to overwrite", result["error"])
            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual(fullset.sha256_file(original), source_sha)
            self.assertFalse(any(path.name.startswith(".ai-result-stage-") for path in source.iterdir()))

    def test_26_copy_failure_cleans_stage_and_preserves_source_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            original = self.image(source, "f1.jpg", b"read-only-original")
            selected = root / "selected"
            self.selected(selected, source.name, names=("f1.png",))
            args = ("--input-dir", str(source), "--publish-from", str(selected), "--timestamp", "20260715_123456")
            source_sha = fullset.sha256_file(original)
            with mock.patch.object(helper.shutil, "copyfileobj", side_effect=OSError("injected copy failure")):
                code, result = self.invoke(*args)
            self.assertEqual(code, 2)
            self.assertIn("filesystem operation failed", result["error"])
            self.assertEqual(fullset.sha256_file(original), source_sha)
            self.assertFalse(any(path.name.startswith(".ai-result-stage-") for path in source.iterdir()))
            self.assertFalse((source / "AI_RESULT_20260715_123456").exists())
    def test_16_help(self):
        run=subprocess.run([sys.executable,str(SCRIPTS/"folder_batch_prepare.py"),"--help"],capture_output=True,text=True,encoding="utf-8");self.assertEqual(run.returncode,0);self.assertIn("--input-dir",run.stdout);self.assertIn("--publish-from",run.stdout)

if __name__ == "__main__": unittest.main()
