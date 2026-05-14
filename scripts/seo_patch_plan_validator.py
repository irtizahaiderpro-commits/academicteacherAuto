#!/usr/bin/env python3
from __future__ import annotations
import json, os
from dataclasses import asdict, dataclass
from pathlib import Path

PLAN_PATH = Path("approved_patches/approved_patch_plan.json")
RESULT_PATH = Path("seo-control/patch-validation-result.json")
BLOCKED_EXACT = {".htaccess", "robots.txt", "sitemap.xml", ".env"}
BLOCKED_PREFIX = (".private/",)
VALID_TOKENS = {"APPROVE_SEO_PHASE_0", "APPROVE_METADATA_ONLY", "APPROVE_INTERNAL_LINKS_ONLY"}
BANNED_TEXT = ["guaranteed grade", "guaranteed grades", "take my exam", "do my quiz", "pay someone to do my assignment", "write my assignment for me"]
ALLOWED_OPS = {"replace_text"}

@dataclass
class ValidationResult:
    ok: bool
    can_create_pr: bool
    approval_granted: bool
    errors: list[str]
    changed_files: list[str]
    message: str

def is_blocked(path: str) -> bool:
    clean = path.replace("\\", "/").strip()
    return clean in BLOCKED_EXACT or clean.startswith(BLOCKED_PREFIX) or clean.startswith("/") or ".." in clean.split("/")

def validate(plan: dict, token: str) -> ValidationResult:
    errors, files = [], []
    if token not in VALID_TOKENS: errors.append("Valid approval token missing")
    if plan.get("approval_required") is not True: errors.append("Plan must set approval_required=true")
    if plan.get("approved_by_human") is not True: errors.append("Plan must set approved_by_human=true")
    changes = plan.get("changes", [])
    if not isinstance(changes, list) or not changes: errors.append("Plan changes must be a non-empty list")
    for index, change in enumerate(changes):
        path = str(change.get("file", ""))
        if change.get("operation") not in ALLOWED_OPS: errors.append(f"Change {index}: only replace_text is allowed")
        if not path or is_blocked(path): errors.append(f"Change {index}: blocked or unsafe file path: {path}")
        if path and path not in files: files.append(path)
        for key in ["current_text", "replacement_text", "evidence", "rollback_note"]:
            if not change.get(key): errors.append(f"Change {index}: {key} missing")
        proposed = str(change.get("replacement_text", "")).lower()
        for banned in BANNED_TEXT:
            if banned in proposed: errors.append(f"Change {index}: banned wording found: {banned}")
    return ValidationResult(not errors, not errors, token in VALID_TOKENS, errors, files, "Patch plan valid" if not errors else "Patch plan blocked")

def apply_plan(plan: dict) -> None:
    for index, change in enumerate(plan.get("changes", [])):
        path = Path(str(change["file"]))
        current = str(change["current_text"])
        replacement = str(change["replacement_text"])
        text = path.read_text(encoding="utf-8")
        count = text.count(current)
        if count != 1:
            raise RuntimeError(f"Change {index}: current_text must match exactly once in {path}, got {count}")
        path.write_text(text.replace(current, replacement, 1), encoding="utf-8")

def main() -> int:
    Path("seo-control").mkdir(exist_ok=True)
    try:
        if not PLAN_PATH.exists():
            raise FileNotFoundError("approved_patches/approved_patch_plan.json missing")
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        result = validate(plan, os.getenv("APPROVAL_TOKEN", ""))
        RESULT_PATH.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        print(json.dumps(asdict(result), indent=2))
        if not result.ok: return 1
        if os.getenv("APPLY_APPROVED_PATCH", "false").lower() == "true": apply_plan(plan)
        return 0
    except Exception as exc:
        result = ValidationResult(False, False, False, [str(exc)], [], "Patch plan failed safely")
        RESULT_PATH.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        print(json.dumps(asdict(result), indent=2))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
