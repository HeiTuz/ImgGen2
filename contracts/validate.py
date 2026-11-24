#!/usr/bin/env python3
"""Portable, dependency-free validator for the shared prompt contracts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

CONTRACT_ROOT = Path(__file__).resolve().parent
SCHEMA_FILES = {
    "garden-recipe/v1": CONTRACT_ROOT / "v1" / "garden-recipe.schema.json",
    "prompt-bundle/v1": CONTRACT_ROOT / "v1" / "prompt-bundle.schema.json",
    "source-evidence-index/v1": CONTRACT_ROOT / "v1" / "source-evidence-index.schema.json",
    "production-adapter-options/v1": CONTRACT_ROOT / "v1" / "production-adapter-options.schema.json",
    "imggen2-production-record/v1": CONTRACT_ROOT / "v1" / "imggen2-production-record.schema.json",
    "mpw-recompile-request/v1": CONTRACT_ROOT / "v1" / "mpw-recompile-request.schema.json",
    "apparel-handoff/v1": CONTRACT_ROOT / "v1" / "apparel-handoff.schema.json",
    "image-production-handoff/v2": CONTRACT_ROOT / "v1" / "image-production-handoff.schema.json",
}
# Legacy contracts whose wire discriminator is an integer instead of a contract key.
# An integer is not a globally unique discriminator, so --schema stays the canonical path.
WIRE_SCHEMA_ALIASES = {1: "apparel-handoff/v1"}
_NO_RECIPE = object()
# apparel-handoff and image-production-handoff carry filenames and relative paths by
# design, so _privacy_errors is deliberately not attached to them: PATH_VALUE_RE would
# reject conforming documents. Schema validation is the whole contract for those two.
FORBIDDEN_KEYS = {
    "api_key",
    "authorization",
    "chat_id",
    "file_path",
    "image_path",
    "original",
    "original_path",
    "password",
    "raw_caption",
    "raw_source",
    "secret",
    "source_path",
    "user_id",
}
PATH_VALUE_RE = re.compile(
    r"(?<![\w/])(?:~/(?:[^\s]+)|/+(?:Users|home|tmp|var|private|Volumes)/[^\s]+|[A-Za-z]:\\[^\s]+|file://[^\s]+|data:image/[^\s]+)",
    re.IGNORECASE,
)
FILE_DEPENDENCY_RE = re.compile(
    r"\b(?:read|load|open|see|consult)\s+(?:the\s+)?(?:file|path)\b|(?:파일|경로)(?:을|를|에서|의)?\s*(?:읽|열|참조)",
    re.IGNORECASE,
)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"external_ref_not_supported:{ref}")
    node: Any = root_schema
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(node, dict):
        raise ValueError(f"invalid_ref_target:{ref}")
    return node


def _schema_errors(value: Any, schema: dict[str, Any], root_schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:
        errors.extend(_schema_errors(value, _resolve_ref(root_schema, schema["$ref"]), root_schema, path))

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected_const:{schema['const']!r}")
        return errors
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected_one_of:{schema['enum']!r}")
        return errors

    expected = schema.get("type")
    if expected is not None:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, choice) for choice in choices):
            errors.append(f"{path}: expected_type:{'|'.join(choices)}")
            return errors
    if "oneOf" in schema:
        matches = sum(
            not _schema_errors(value, branch, root_schema, path)
            for branch in schema["oneOf"]
        )
        if matches != 1:
            errors.append(f"{path}: one_of_match_count:{matches}")
    if "allOf" in schema:
        for branch in schema["allOf"]:
            errors.extend(_schema_errors(value, branch, root_schema, path))
    if "if" in schema:
        # Errors raised by the condition itself are discarded; only the taken branch reports.
        taken = "then" if not _schema_errors(value, schema["if"], root_schema, path) else "else"
        if taken in schema:
            errors.extend(_schema_errors(value, schema[taken], root_schema, path))

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: required")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties")
        if additional is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: additional_property")
        elif isinstance(additional, dict):
            for key, child in value.items():
                if key not in properties:
                    errors.extend(_schema_errors(child, additional, root_schema, f"{path}.{key}"))
        for key, child in properties.items():
            if key in value:
                errors.extend(_schema_errors(value[key], child, root_schema, f"{path}.{key}"))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: min_items:{schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: max_items:{schema['maxItems']}")
        if schema.get("uniqueItems") is True:
            seen: set[str] = set()
            for item in value:
                encoded = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if encoded in seen:
                    errors.append(f"{path}: unique_items")
                    break
                seen.add(encoded)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, root_schema, f"{path}[{index}]"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: min_length:{schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: max_length:{schema['maxLength']}")
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, value):
            errors.append(f"{path}: pattern_mismatch:{pattern}")

    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non_finite_number")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: minimum:{schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: maximum:{schema['maximum']}")

    return errors


SUPPORTED_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "$comment",
    "title",
    "description",
    "const",
    "enum",
    "type",
    "oneOf",
    "allOf",
    "if",
    "then",
    "else",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
}


def unsupported_keywords(schema: Any, path: str = "#") -> list[str]:
    """Report schema keywords this validator would silently ignore."""
    if not isinstance(schema, dict):
        return []
    errors: list[str] = []
    if isinstance(schema.get("items"), list):
        errors.append(f"{path}/items: items_array_form_unsupported")
    for keyword, child in schema.items():
        if keyword not in SUPPORTED_KEYWORDS:
            errors.append(f"{path}: unsupported_schema_keyword:{keyword}")
            continue
        if keyword in {"properties", "$defs"} and isinstance(child, dict):
            for name, subschema in child.items():
                errors.extend(unsupported_keywords(subschema, f"{path}/{keyword}/{name}"))
        elif keyword in {"items", "if", "then", "else"}:
            errors.extend(unsupported_keywords(child, f"{path}/{keyword}"))
        elif keyword == "additionalProperties" and isinstance(child, dict):
            errors.extend(unsupported_keywords(child, f"{path}/{keyword}"))
        elif keyword in {"oneOf", "allOf"} and isinstance(child, list):
            for index, branch in enumerate(child):
                errors.extend(unsupported_keywords(branch, f"{path}/{keyword}/{index}"))
    return errors


def _privacy_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.casefold().replace("-", "_")
            if normalized in FORBIDDEN_KEYS:
                errors.append(f"{path}.{key}: forbidden_private_key")
            errors.extend(_privacy_errors(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_privacy_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str) and PATH_VALUE_RE.search(value):
        errors.append(f"{path}: forbidden_path_or_embedded_original")
    return errors


def _garden_semantic_errors(value: dict[str, Any]) -> list[str]:
    errors = _privacy_errors(value)
    intended_use = value.get("intended_use", {})
    if isinstance(intended_use, dict):
        mode = intended_use.get("mode")
        engine = intended_use.get("engine")
        if engine == "frontend-agent" and mode != "DESIGN":
            errors.append("$.intended_use: incompatible_mode_engine")
        elif engine in {"gpt-image-2", "higgsfield", "generic-image"} and mode not in {"IMAGE", "IMAGE_COMPOSITE"}:
            errors.append("$.intended_use: incompatible_mode_engine")
    observations = value.get("observations", {})
    observed_ids: set[str] = set()
    if isinstance(observations, dict):
        for axis, evidence in observations.items():
            if not isinstance(evidence, dict):
                continue
            status = evidence.get("status")
            items = evidence.get("items")
            if status == "observed" and isinstance(items, list) and not items:
                errors.append(f"$.observations.{axis}.items: observed_requires_item")
            if status in {"not_observable", "not_applicable"} and items:
                errors.append(f"$.observations.{axis}.items: unavailable_axis_must_be_empty")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    observation_id = item.get("observation_id")
                    if isinstance(observation_id, str):
                        if observation_id in observed_ids:
                            errors.append(f"$.observations.{axis}: duplicate_observation_id:{observation_id}")
                        observed_ids.add(observation_id)
    inference_ids: set[str] = set()
    for index, inference in enumerate(value.get("inferences", [])):
        if not isinstance(inference, dict):
            continue
        inference_id = inference.get("inference_id")
        if isinstance(inference_id, str):
            if inference_id in inference_ids:
                errors.append(f"$.inferences[{index}].inference_id: duplicate")
            inference_ids.add(inference_id)
        for observation_id in inference.get("based_on", []):
            if observation_id not in observed_ids:
                errors.append(f"$.inferences[{index}].based_on: unknown_observation_id:{observation_id}")
    errors.extend(_token_provenance_errors(value, observed_ids))
    return errors


# Each origin admits exactly the statuses that can honestly describe it, and
# only the two evidence-backed origins may cite an observation.
ORIGIN_STATUS_BINDING = {
    "user": {"explicit"},
    "surface": {"explicit"},
    "evidence": {"explicit", "derived"},
    "derived": {"derived"},
    "default": {"assumed"},
}
ORIGIN_REQUIRES_SOURCE = {"evidence", "derived"}


def _token_provenance_errors(value: dict[str, Any], observed_ids: set[str]) -> list[str]:
    """Node-level provenance on the recipe tokens a prompt is compiled from.

    The fields are optional so existing v1 records stay valid, but a token that
    declares provenance must declare all of it: a half-filled token is worse
    than none because it reads as evidence-backed while citing nothing.

    Provenance is audited here, at the recipe. It is deliberately not carried
    into PromptBundle — that payload is what an engine executes, and the
    compiler renders only the token text into it.
    """
    errors: list[str] = []
    for field in ("qualified_tokens", "layout_tokens"):
        tokens = value.get(field)
        if not isinstance(tokens, list):
            continue
        for index, token in enumerate(tokens):
            if not isinstance(token, dict):
                continue
            path = f"$.{field}[{index}]"
            origin = token.get("origin")
            status = token.get("status")
            source_ref = token.get("source_ref")
            if (origin is None) != (status is None):
                errors.append(f"{path}: incomplete_token_provenance")
            if source_ref is not None and status is None:
                errors.append(f"{path}: incomplete_token_provenance")
            if isinstance(source_ref, list):
                for observation_id in source_ref:
                    if observation_id not in observed_ids:
                        errors.append(f"{path}.source_ref: unknown_observation_id:{observation_id}")
            # Every origin is bound, not just the obvious two. A token whose
            # value came from the user or the surface must not cite an
            # observation as its source: the citation would read as
            # evidence-backed in an audit when nothing was observed.
            allowed_statuses = ORIGIN_STATUS_BINDING.get(origin)
            if allowed_statuses is not None and status not in allowed_statuses:
                errors.append(f"{path}: origin_status_conflict")
            if origin is not None and origin in ORIGIN_REQUIRES_SOURCE and not source_ref:
                errors.append(f"{path}: provenance_requires_source_ref")
            if origin is not None and origin not in ORIGIN_REQUIRES_SOURCE and source_ref:
                errors.append(f"{path}: origin_must_not_cite_observation")
            if status == "assumed" and source_ref:
                errors.append(f"{path}: assumed_token_must_not_cite_source")
    return errors


def recipe_readiness_errors(recipe: dict[str, Any], path: str = "$") -> list[str]:
    """A stored recipe may be incomplete; an executable handoff may not be."""
    unresolved = recipe.get("unresolved_inputs", [])
    if not isinstance(unresolved, list):
        return []  # Structural validation reports a malformed field separately.
    errors: list[str] = []
    for index, item in enumerate(unresolved):
        if not isinstance(item, dict):
            continue
        # GardenRecipe v1 only admits required:true unresolved entries.
        details = json.dumps(
            {key: item.get(key) for key in ("code", "slot", "source_reference_id")},
            ensure_ascii=False,
            sort_keys=True,
        )
        errors.append(f"{path}.unresolved_inputs[{index}]: required_input_unresolved:{details}")
    return errors


def _bundle_semantic_errors(value: dict[str, Any], recipe: Any) -> list[str]:
    errors = _privacy_errors(value)
    if recipe is not _NO_RECIPE:
        source_schema = load_schema("garden-recipe/v1")
        source_errors = _schema_errors(recipe, source_schema, source_schema, "$.source_recipe")
        if source_errors:
            return errors + source_errors
        source_errors = _garden_semantic_errors(recipe)
        if source_errors:
            return errors + [error.replace("$", "$.source_recipe", 1) for error in source_errors]
    handoff = value.get("handoff", {})
    if isinstance(handoff, dict):
        block_ids: set[str] = set()
        for index, block in enumerate(handoff.get("prompt_blocks", [])):
            if not isinstance(block, dict):
                continue
            block_id = block.get("block_id")
            if isinstance(block_id, str):
                if block_id in block_ids:
                    errors.append(f"$.handoff.prompt_blocks[{index}].block_id: duplicate")
                block_ids.add(block_id)
            text = block.get("text")
            count = block.get("unicode_char_count")
            if isinstance(text, str):
                actual = len(text)
                if count != actual:
                    errors.append(f"$.handoff.prompt_blocks[{index}].unicode_char_count: expected:{actual}")
                if actual > 2000:
                    errors.append(f"$.handoff.prompt_blocks[{index}].text: unicode_limit:2000")
                if FILE_DEPENDENCY_RE.search(text):
                    errors.append(f"$.handoff.prompt_blocks[{index}].text: external_file_dependency")

    if recipe is not _NO_RECIPE:
        errors.extend(recipe_readiness_errors(recipe, "$.source_recipe"))
        if value.get("source_recipe", {}).get("recipe_id") != recipe.get("recipe_id"):
            errors.append("$.source_recipe.recipe_id: recipe_id_mismatch")
        expected_hash = canonical_hash(recipe)
        if value.get("source_recipe", {}).get("recipe_hash") != expected_hash:
            errors.append(f"$.source_recipe.recipe_hash: expected:{expected_hash}")
        if handoff.get("immutable_locks") != recipe.get("locks"):
            errors.append("$.handoff.immutable_locks: recipe_lock_drift")
        intended_use = recipe.get("intended_use", {})
        if handoff.get("mode") != intended_use.get("mode"):
            errors.append("$.handoff.mode: recipe_mode_drift")
        if handoff.get("engine") != intended_use.get("engine"):
            errors.append("$.handoff.engine: recipe_engine_drift")
    return errors


AXIS_DELTA = {
    "goal_fit": "clarify_goal_fit",
    "text_accuracy": "resolve_text_from_source",
    "material_realism": "clarify_material_realism",
    "layout": "clarify_layout",
}
PROMO_CHECKS = [
    "physical_type_subject_interaction",
    "generic_card_regression",
    "printed_meta_ui_not_literal",
    "color_lock_2_to_3",
    "finishing_devices_1_to_3",
    "korean_glyph_mask_safety",
]
GEOMETRY = {
    "1:1": "1024x1024",
    "3:4": "1024x1536",
    "4:3": "1536x1024",
    "9:16": "1024x1536",
    "16:9": "1536x1024",
}


def _unique_sorted_strings(values: Any, path: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        return []
    errors: list[str] = []
    if len(values) != len(set(values)):
        errors.append(f"{path}: duplicate")
    if values != sorted(values):
        errors.append(f"{path}: not_sorted")
    return errors


def _source_index_semantic_errors(value: dict[str, Any]) -> list[str]:
    references = value.get("references", [])
    errors = _unique_sorted_strings(
        [item.get("reference_id") for item in references if isinstance(item, dict)],
        "$.references.reference_id",
    )
    return errors + _privacy_errors(value)


def _options_semantic_errors(value: dict[str, Any]) -> list[str]:
    errors = _privacy_errors(value)
    output_path = value.get("output_path")
    if isinstance(output_path, str):
        parts = output_path.replace("\\", "/").split("/")
        if output_path.startswith(("/", "~")) or ".." in parts or "." in parts or "\\" in output_path:
            errors.append("$.output_path: unsafe_relative_path")
    expected_size = GEOMETRY.get(value.get("ar"))
    if expected_size is not None and value.get("size") != expected_size:
        errors.append("$.size: production_geometry_mismatch")
    applicability = value.get("qc_applicability", {})
    evidence_ids = applicability.get("evidence_reference_ids", []) if isinstance(applicability, dict) else []
    errors.extend(_unique_sorted_strings(evidence_ids, "$.qc_applicability.evidence_reference_ids"))
    if isinstance(applicability, dict) and (
        applicability.get("promotional") or applicability.get("rendered_text_expected")
    ) and not evidence_ids:
        errors.append("$.qc_applicability.evidence_reference_ids: required_when_applicable")
    return errors


def _production_semantic_errors(value: dict[str, Any]) -> list[str]:
    errors = _privacy_errors(value)
    errors.extend(_unique_sorted_strings(value.get("reference_ids", []), "$.reference_ids"))
    expected_size = GEOMETRY.get(value.get("ar"))
    if expected_size is not None and value.get("size") != expected_size:
        errors.append("$.size: production_geometry_mismatch")
    return errors


def _image_handoff_semantic_errors(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen_paths: set[str] = set()
    for index, image in enumerate(value.get("input_images", [])):
        if not isinstance(image, dict):
            continue
        path = image.get("path")
        if not isinstance(path, str):
            continue
        if path in seen_paths:
            errors.append(f"$.input_images[{index}].path: duplicate_input_path")
        seen_paths.add(path)
    ratio, size = value.get("aspect_ratio"), value.get("image_size")
    if isinstance(ratio, str) and isinstance(size, str) and re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", ratio) and re.fullmatch(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}", size):
        try:
            a, b = map(int, ratio.split(":"))
            width, height = map(int, size.split("x"))
        except ValueError:
            errors.append("$.aspect_ratio: geometry_numeric_capacity_exceeded")
        else:
            if a * height != b * width:
                errors.append("$.image_size: image_handoff_geometry_mismatch")
    return errors


def _recompile_semantic_errors(value: dict[str, Any]) -> list[str]:
    errors = _privacy_errors(value)
    axes = value.get("failed_axes", [])
    checks = value.get("failed_promo_checks", [])
    if isinstance(axes, list) and isinstance(checks, list) and not axes and not checks:
        errors.append("$: recompile_failure_fact_required")
    for path, items in (("$.failed_axes", axes), ("$.failed_promo_checks", checks)):
        if isinstance(items, list) and len(items) != len(set(item for item in items if isinstance(item, str))):
            errors.append(f"{path}: duplicate")
    expected_reasons = [
        *(f"qc_axis:{axis}" for axis in axes if axis in AXIS_DELTA),
        *(f"promo_check:{check}" for check in checks if check in PROMO_CHECKS),
    ]
    expected_deltas = [
        *(AXIS_DELTA[axis] for axis in axes if axis in AXIS_DELTA),
        *(f"resolve_promo_{check}" for check in checks if check in PROMO_CHECKS),
    ]
    if value.get("reason_codes") != expected_reasons:
        errors.append("$.reason_codes: recompile_reason_mapping_mismatch")
    if value.get("requested_delta_codes") != expected_deltas:
        errors.append("$.requested_delta_codes: recompile_delta_mapping_mismatch")
    return errors
def load_schema(schema_version: str) -> dict[str, Any]:
    path = SCHEMA_FILES.get(schema_version)
    if path is None:
        raise ValueError(f"unsupported_schema_version:{schema_version}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_schema_key(value: dict[str, Any], schema_version: str | None = None) -> tuple[str | None, str | None]:
    """Return (contract key, error) for a document, honouring an explicit override."""
    if isinstance(schema_version, str):
        return schema_version, None
    declared = value.get("schema_version")
    if isinstance(declared, str):
        return declared, None
    if isinstance(declared, int) and not isinstance(declared, bool):
        alias = WIRE_SCHEMA_ALIASES.get(declared)
        if alias is None:
            return None, f"$.schema_version: unsupported_schema_version:{declared!r}"
        return alias, None
    return None, "$.schema_version: required"


def validate_document(
    value: Any,
    recipe: Any = _NO_RECIPE,
    schema_version: str | None = None,
) -> list[str]:
    if not isinstance(value, dict):
        return ["$: expected_type:object"]
    key, key_error = resolve_schema_key(value, schema_version)
    if key is None:
        return [key_error]
    try:
        schema = load_schema(key)
    except ValueError as exc:
        return [f"$.schema_version: {exc}"]
    errors = _schema_errors(value, schema, schema, "$")
    if key == "garden-recipe/v1":
        errors.extend(_garden_semantic_errors(value))
    elif key == "prompt-bundle/v1":
        errors.extend(_bundle_semantic_errors(value, recipe))
    elif key == "source-evidence-index/v1":
        errors.extend(_source_index_semantic_errors(value))
    elif key == "production-adapter-options/v1":
        errors.extend(_options_semantic_errors(value))
    elif key == "imggen2-production-record/v1":
        errors.extend(_production_semantic_errors(value))
    elif key == "mpw-recompile-request/v1":
        errors.extend(_recompile_semantic_errors(value))
    elif key == "image-production-handoff/v2":
        errors.extend(_image_handoff_semantic_errors(value))
    return sorted(set(errors))


def load_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    def reject_constant(value: str) -> Any:
        raise json.JSONDecodeError(f"non_finite_number:{value}", text, 0)
    return json.loads(text, parse_constant=reject_constant)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate GardenRecipe and PromptBundle JSON")
    parser.add_argument("document", type=Path)
    parser.add_argument("--recipe", type=Path, help="GardenRecipe used to prove PromptBundle provenance and lock preservation")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable validation result")
    parser.add_argument(
        "--schema",
        dest="schema_version",
        help="Validate against an explicit contract key when the document carries no string discriminator",
    )
    args = parser.parse_args(argv)

    try:
        value = load_json(args.document)
        recipe = load_json(args.recipe) if args.recipe else _NO_RECIPE
    except (OSError, json.JSONDecodeError) as exc:
        result = {"ok": False, "errors": [f"input_error:{exc}"]}
    else:
        errors = validate_document(value, recipe, schema_version=args.schema_version)
        result = {"ok": not errors, "schema_version": value.get("schema_version") if isinstance(value, dict) else None, "errors": errors}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["ok"]:
        print(f"OK {result['schema_version']} {args.document}")
    else:
        for error in result["errors"]:
            print(f"FAIL {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
