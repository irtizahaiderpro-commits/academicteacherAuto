#!/usr/bin/env python3
from __future__ import annotations
import glob, json, subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

OUT_JSON = Path("seo-control/deploy-readiness.json")
OUT_MD = Path("seo-control/deploy-readiness.md")
BLOCKED_FILES = [".htaccess", "robots.txt", "sitemap.xml", ".env", ".private/*"]
REQUIRED_LIVE_CHECKS = [
    "curl -I https://academicteacher.co.uk/",
    "curl -I https://academicteacher.co.uk/services/",
    "curl -I https://academicteacher.co.uk/subjects/project-management/",
    "curl -I https://academicteacher.co.uk/wp-content/plugins/essential-addons-for-elementor-lite/assets/front-end/img/image-masking/svg-shapes/",
]
@dataclass
class DeployReadiness:
    ready_for_manual_deploy: bool
    auto_deploy_enabled: bool
    deployment_mode: str
    changed_files: list[str]
    reports: list[str]
    proposals: list[str]
    required_pre_deploy_checks: list[str]
    required_post_deploy_checks: list[str]
    rollback_plan: list[str]
    blocked_files: list[str]
    message: str

def git_changed_files() -> list[str]:
    try:
        output = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], text=True).strip()
        return [line for line in output.splitlines() if line.strip()]
    except Exception:
        return []

def main() -> int:
    Path("seo-control").mkdir(exist_ok=True)
    changed = git_changed_files()
    blocked_touched = [f for f in changed if f in {".htaccess", "robots.txt", "sitemap.xml", ".env"} or f.startswith(".private/")]
    result = DeployReadiness(
        ready_for_manual_deploy=not blocked_touched,
        auto_deploy_enabled=False,
        deployment_mode="manual_only",
        changed_files=changed,
        reports=sorted(glob.glob("reports/*"))[-25:],
        proposals=sorted(glob.glob("proposals/*"))[-10:],
        required_pre_deploy_checks=[
            "Review and merge PR manually",
            "Confirm build passed",
            "Confirm SEO audit passed after patch",
            "Backup current Hostinger/public_html before upload",
            "Do not overwrite .private or live mail config",
            "Keep rollback copy of previous build",
        ],
        required_post_deploy_checks=REQUIRED_LIVE_CHECKS + [
            "Check Search Console after 48-72 hours, not every few minutes",
            "Request indexing only for priority changed URLs",
        ],
        rollback_plan=[
            "Restore previous public_html backup",
            "Re-upload previous dist/build folder",
            "Re-test homepage and priority routes with curl",
            "Re-run SEO audit pipeline",
        ],
        blocked_files=BLOCKED_FILES,
        message="Deploy pack created. Auto deployment is disabled. Human must deploy manually after PR review.",
    )
    OUT_JSON.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    OUT_MD.write_text("# Deploy Readiness Pack\n\n```json\n" + json.dumps(asdict(result), indent=2) + "\n```\n", encoding="utf-8")
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.ready_for_manual_deploy else 1
if __name__ == "__main__":
    raise SystemExit(main())
