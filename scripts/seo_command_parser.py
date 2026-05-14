#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from dataclasses import asdict, dataclass
from pathlib import Path

ALLOWED_COMMANDS = {
    "/start-seo-review": {"mode": "audit_only", "can_edit": False, "can_deploy": False},
    "/start-phase-0-cleanup": {"mode": "proposal_only_until_approval", "can_edit": False, "can_deploy": False},
    "/start-approved-implementation": {"mode": "approved_patch_pr_only", "can_edit": True, "can_deploy": False},
    "/prepare-deploy-pack": {"mode": "deploy_readiness_only", "can_edit": False, "can_deploy": False},
    "/refresh-dashboard": {"mode": "dashboard_reporting_only", "can_edit": False, "can_deploy": False},
    "/install-seo-control": {"mode": "install_guidance_only", "can_edit": False, "can_deploy": False},
}
VALID_APPROVAL_TOKENS = {"APPROVE_SEO_PHASE_0", "APPROVE_METADATA_ONLY", "APPROVE_INTERNAL_LINKS_ONLY"}
BLOCKED_FILES = [".htaccess", "robots.txt", "sitemap.xml", ".env", ".private/*"]

@dataclass
class CommandResult:
    command: str
    valid: bool
    mode: str
    can_edit: bool
    can_deploy: bool
    approval_required: bool
    approval_granted: bool
    blocked_files: list[str]
    message: str

def parse_command(raw: str, token: str = "") -> CommandResult:
    found = next((cmd for cmd in ALLOWED_COMMANDS if cmd in raw), "")
    if not found:
        return CommandResult(raw, False, "none", False, False, True, False, BLOCKED_FILES, "No allowed SEO command found. Exiting safely.")
    spec = ALLOWED_COMMANDS[found]
    approval_granted = token in VALID_APPROVAL_TOKENS
    can_edit = bool(spec["can_edit"] and approval_granted)
    return CommandResult(found, True, str(spec["mode"]), can_edit, False, True, approval_granted, BLOCKED_FILES, "Command parsed safely. Live deployment remains disabled.")

def main() -> int:
    raw = " ".join(sys.argv[1:]) or os.getenv("COMMAND", "")
    token = os.getenv("APPROVAL_TOKEN", "")
    result = parse_command(raw, token)
    Path("seo-control").mkdir(exist_ok=True)
    Path("seo-control/command-result.json").write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    print(json.dumps(asdict(result), indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
