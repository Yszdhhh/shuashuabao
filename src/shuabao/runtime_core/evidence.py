"""Evidence identity and causal boundary checks; no LIVE inference from mocks."""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import hashlib
import inspect
import json
from pathlib import Path
import re
from typing import Any, Mapping

SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class RunIdentity:
    candidate_sha: str
    production_sha: str
    harness_sha: str
    effective_config_hash: str
    rules_hash: str
    assets_hash: str
    bindings_hash: str

    def __post_init__(self) -> None:
        for field in ("candidate_sha", "production_sha", "harness_sha"):
            if not SHA1.fullmatch(getattr(self, field)):
                raise ValueError(f"invalid {field}")
        for field in ("effective_config_hash", "rules_hash", "assets_hash", "bindings_hash"):
            if not SHA256.fullmatch(getattr(self, field)):
                raise ValueError(f"invalid {field}")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def runtime_bindings(instance: Any, methods: tuple[str, ...], root: Path) -> dict:
    """Record actual resolved bound methods, including inherited/modified ones.

    Compare against an independently approved expected identity. This is not a
    signature or protection against a malicious process lying about its state.
    """
    root = root.resolve()
    result = {}
    for name in methods:
        bound = getattr(instance, name)
        func = getattr(bound, "__func__", bound)
        source = inspect.getsourcefile(func)
        if source is None:
            raise ValueError(f"uninspectable runtime binding: {name}")
        path = Path(source).resolve()
        relative = path.relative_to(root)
        result[name] = {
            "module": func.__module__, "qualname": func.__qualname__,
            "file": relative.as_posix(), "file_sha256": file_hash(path),
            "source_sha256": hashlib.sha256(inspect.getsource(func).encode("utf-8")).hexdigest(),
        }
    return result


def validate_live_record(record: Mapping[str, Any], expected: RunIdentity) -> tuple[str, ...]:
    """Validate admissibility for LIVE review, never automatically certify gameplay."""
    errors: list[str] = []
    for key, value in expected.to_dict().items():
        if record.get(key) != value:
            errors.append(f"identity_mismatch:{key}")
    if record.get("evidence_kind") != "LIVE":
        errors.append("not_live_evidence")
    if record.get("manual_intervention") is not False:
        errors.append("manual_intervention_or_unknown")
    if record.get("worktree_clean_start") is not True or record.get("worktree_clean_end") is not True:
        errors.append("runtime_inputs_dirty_or_unknown")
    for key in ("manifest", "run_log", "before_frame", "after_frame", "action_id", "postcondition_id"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            errors.append(f"missing:{key}")
    before, after = record.get("before_generation"), record.get("after_generation")
    if type(before) is not int or type(after) is not int or before < 0 or after <= before:
        errors.append("postcondition_not_from_new_frame")
    if record.get("postcondition_confirmed") is not True:
        errors.append("business_postcondition_unconfirmed")
    if record.get("status") != "PASS":
        errors.append("scenario_not_passed")
    return tuple(errors)


def verify_bundle_files(record: Mapping[str, Any], root: Path,
                        expected_hashes: Mapping[str, str]) -> tuple[str, ...]:
    """Check local evidence bytes, reject missing hashes and paths outside bundle."""
    root = root.resolve()
    errors: list[str] = []
    for key in ("manifest", "run_log", "before_frame", "after_frame"):
        relative = record.get(key)
        if not isinstance(relative, str) or not relative:
            errors.append(f"missing:{key}")
            continue
        try:
            candidate = (root / relative).resolve()
            candidate.relative_to(root)
            expected = expected_hashes.get(relative, "")
            if not SHA256.fullmatch(expected) or file_hash(candidate) != expected:
                errors.append(f"artifact_hash_mismatch:{key}")
        except (OSError, ValueError):
            errors.append(f"artifact_unavailable_or_outside_bundle:{key}")
    return tuple(errors)


def method_rebindings(source: str, class_name: str = "RuntimeMediator") -> tuple[str, ...]:
    """Find direct class method replacement in the legacy capture factory."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
        )
        for target in targets:
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == class_name):
                found.append(f"{class_name}.{target.attr}:{node.lineno}")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "setattr" and node.args
                and isinstance(node.args[0], ast.Name) and node.args[0].id == class_name):
            found.append(f"setattr:{class_name}:{node.lineno}")
    return tuple(sorted(found))
