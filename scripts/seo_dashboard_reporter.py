#!/usr/bin/env python3
from __future__ import annotations
import glob, json, os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

OUT_JSON = Path("seo-control/dashboard-snapshot.json")
OUT_MD = Path("seo-control/dashboard-summary.md")
HISTORY = Path("seo-control/dashboard-history.jsonl")

@dataclass
class DashboardSnapshot:
    generated_at_utc: str
    site: str
    command: str
    overall_status: str
    audit_status: str
    ai_status: str
    director_decision: str
    patch_status: str
    deploy_status: str
    auto_deploy_enabled: bool
    open_blockers: list[str]
    latest_reports: list[str]
    latest_proposals: list[str]
    next_actions: list[str]

def read_json(path: str) -> dict:
    target = Path(path)
    if not target.exists(): return {}
    try: return json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc: return {"error": str(exc)}

def latest(pattern: str, n: int) -> list[str]:
    return sorted(glob.glob(pattern), key=os.path.getmtime)[-n:]

def count_bad_terms() -> int:
    total = 0
    for file in glob.glob("reports/*bad*terms*.csv") + glob.glob("reports/*bad_terms*.csv"):
        try:
            lines = [line for line in Path(file).read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
            total += max(0, len(lines) - 1)
        except Exception:
            pass
    return total

def main() -> int:
    Path("seo-control").mkdir(exist_ok=True)
    run = read_json("seo-control/latest-run-summary.json")
    ai = read_json("seo-control/ai-run-result.json")
    director = read_json("seo-control/director-review.json")
    patch = read_json("seo-control/patch-validation-result.json")
    deploy = read_json("seo-control/deploy-readiness.json")
    blockers = []
    bad_terms = count_bad_terms()
    if bad_terms > 0: blockers.append(f"Bad/risky term hits detected: {bad_terms}")
    if ai and not ai.get("ok", False): blockers.append("AI review failed or needs evidence")
    if director.get("decision") in {"REJECTED", "NEEDS_EVIDENCE", "NEEDS_HUMAN_DECISION"}: blockers.append(f"Director decision: {director.get('decision')}")
    if patch and not patch.get("ok", False): blockers.append("Patch plan blocked or invalid")
    if deploy and not deploy.get("ready_for_manual_deploy", True): blockers.append("Deploy readiness blocked")
    next_actions = []
    if bad_terms > 0: next_actions.append("Review risky wording report and prepare approved Phase 0 patch plan")
    if director.get("decision") in {"NEEDS_EVIDENCE", "NEEDS_HUMAN_DECISION"}: next_actions.append("Gather missing evidence before allowing implementation")
    if not next_actions: next_actions.append("Monitor Search Console and run next scheduled review")
    snapshot = DashboardSnapshot(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        site=os.getenv("SITE_URL", "https://academicteacher.co.uk"),
        command=os.getenv("COMMAND", run.get("command", "")),
        overall_status="ATTENTION_REQUIRED" if blockers else "CLEAR_MONITORING",
        audit_status=run.get("status", "UNKNOWN"),
        ai_status=ai.get("message", "AI review not run"),
        director_decision=director.get("decision", "NO_DECISION"),
        patch_status=patch.get("message", "No patch validation run"),
        deploy_status=deploy.get("message", "No deploy pack yet"),
        auto_deploy_enabled=False,
        open_blockers=blockers,
        latest_reports=latest("reports/*", 12),
        latest_proposals=latest("proposals/*", 8),
        next_actions=next_actions,
    )
    data = asdict(snapshot)
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    HISTORY.open("a", encoding="utf-8").write(json.dumps(data) + "\n")
    md = [
        "# Academic Teacher SEO Dashboard Snapshot", "",
        f"**Status:** {snapshot.overall_status}",
        f"**Generated:** {snapshot.generated_at_utc}",
        f"**Director decision:** {snapshot.director_decision}",
        f"**Auto deploy:** {snapshot.auto_deploy_enabled}", "",
        "## Open blockers",
    ]
    md += [f"- {b}" for b in blockers] or ["- None"]
    md += ["", "## Next actions"]
    md += [f"- {a}" for a in next_actions]
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
