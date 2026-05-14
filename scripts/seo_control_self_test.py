#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, subprocess, sys
from dataclasses import asdict, dataclass
from pathlib import Path

REQUIRED_FILES = [
    ".github/workflows/academic-teacher-seo-control.yml",
    "scripts/seo_command_parser.py",
    "scripts/seo_ai_review_runner.py",
    "scripts/seo_patch_plan_validator.py",
    "scripts/seo_deploy_readiness.py",
    "scripts/seo_dashboard_reporter.py",
    "scripts/seo_control_self_test.py",
    "scripts/run_daily_pipeline.py",
    "approved_patches/approved_patch_plan.example.json",
    "INSTALL_ACADEMIC_TEACHER_SEO_CONTROL.md",
]
SECRET_PATTERNS = [r"sk-[A-Za-z0-9_-]{20,}", r"ANTHROPIC_API_KEY\s*=\s*['\"][^'\"]+['\"]", r"OPENAI_API_KEY\s*=\s*['\"][^'\"]+['\"]", r"BEGIN PRIVATE KEY"]

@dataclass
class SelfTestResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    required_files_checked: list[str]
    message: str

def read_text(path: Path) -> str:
    try: return path.read_text(encoding="utf-8", errors="ignore")
    except Exception: return ""

def check_files() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for file in REQUIRED_FILES:
        if not Path(file).exists(): errors.append(f"Missing required file: {file}")
    for file in REQUIRED_FILES:
        path = Path(file)
        if not path.exists() or path.is_dir():
            continue
        # Do not flag the self-test script for containing the secret-detection patterns themselves.
        if file == "scripts/seo_control_self_test.py":
            continue
        text = read_text(path)
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, text, re.I):
                errors.append(f"Possible secret found in {file}: pattern {pattern}")
    workflow = Path(".github/workflows/academic-teacher-seo-control.yml")
    if workflow.exists():
        text = read_text(workflow)
        if "create-pull-request" not in text: warnings.append("Workflow does not appear to include PR creation action.")
        if "schedule:" not in text: warnings.append("Workflow does not include scheduled reporting.")
        if "No deployment was performed" not in text and "auto_deploy_enabled" not in text: errors.append("Workflow does not clearly state auto deployment is disabled.")
    return errors, warnings

def run_command_parser() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    parser = Path("scripts/seo_command_parser.py")
    if not parser.exists(): return ["Cannot test command parser because scripts/seo_command_parser.py is missing"], warnings
    try:
        output = subprocess.check_output([sys.executable, str(parser), "/start-seo-review"], text=True)
        data = json.loads(output)
        if data.get("valid") is not True: errors.append("Command parser did not mark /start-seo-review valid")
        if data.get("can_edit") is not False: errors.append("/start-seo-review must not allow edits")
        if data.get("can_deploy") is not False: errors.append("/start-seo-review must not allow deployment")
    except Exception as exc:
        errors.append(f"Command parser test failed: {exc}")
    return errors, warnings

def check_patch_example() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    sample = Path("approved_patches/approved_patch_plan.example.json")
    if not sample.exists(): return ["Example patch plan missing"], warnings
    try:
        data = json.loads(sample.read_text(encoding="utf-8"))
        if data.get("approved_by_human") is not False: errors.append("Example patch plan must have approved_by_human=false")
        if data.get("approval_required") is not True: errors.append("Example patch plan must have approval_required=true")
    except Exception as exc:
        errors.append(f"Example patch plan is invalid JSON: {exc}")
    return errors, warnings

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-files", action="store_true")
    parser.parse_known_args()
    errors, warnings = [], []
    for check in [check_files, run_command_parser, check_patch_example]:
        e, w = check()
        errors.extend(e); warnings.extend(w)
    result = SelfTestResult(not errors, errors, warnings, REQUIRED_FILES, "Self-test passed" if not errors else "Self-test failed. Fix errors before running GitHub automation.")
    Path("seo-control").mkdir(exist_ok=True)
    Path("seo-control/self-test-result.json").write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
