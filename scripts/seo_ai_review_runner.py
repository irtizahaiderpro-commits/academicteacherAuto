#!/usr/bin/env python3
from __future__ import annotations
import glob, json, os, re, urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
SEO_CONTROL = ROOT / "seo-control"
PROPOSALS = ROOT / "proposals"
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
for d in [SEO_CONTROL, PROPOSALS, REPORTS, LOGS]: d.mkdir(parents=True, exist_ok=True)
BLOCKED_FILES = [".htaccess", "robots.txt", "sitemap.xml", ".env", ".private/*"]
DECISIONS = {"APPROVED", "APPROVED_WITH_CHANGES", "REJECTED", "NEEDS_EVIDENCE", "NEEDS_HUMAN_DECISION"}
SPECIALIST_PROMPT = """You are the Academic Teacher SEO/AEO Specialist Agent.
Return evidence-based SEO proposals only. Never invent reviews, ratings, writers, addresses, guarantees, or credentials.
Never suggest cheating-style or essay-mill language.
Every website change must have evidence, affected_url, affected_file, exact recommendation, risk, rollback_note, and approval_required=true.
Return valid JSON only.
"""
DIRECTOR_PROMPT = """You are the Academic Teacher SEO/AEO Director Agent.
Reject vague, risky, unsupported or spammy SEO work.
Reject fake claims, keyword stuffing, unsupported schema, risky academic wording, and technical file changes without hard evidence.
Return valid JSON only with decision: APPROVED, APPROVED_WITH_CHANGES, REJECTED, NEEDS_EVIDENCE, or NEEDS_HUMAN_DECISION.
implementation_allowed_now must be false.
"""
@dataclass
class Result:
    ok: bool
    provider: str
    specialist_status: str
    director_decision: str
    implementation_allowed_now: bool
    approval_required: bool
    message: str

def read_tail(path: str, limit: int = 10000) -> str:
    try: return Path(path).read_text(encoding="utf-8", errors="replace")[-limit:]
    except Exception as exc: return f"[read failed: {path}: {exc}]"

def latest(pattern: str, n: int) -> list[str]:
    return sorted(glob.glob(pattern), key=os.path.getmtime)[-n:]

def build_evidence() -> dict[str, Any]:
    data = {"site": os.getenv("SITE_URL", "https://academicteacher.co.uk"), "command": os.getenv("COMMAND", ""), "blocked_files": BLOCKED_FILES, "reports": [], "proposals": []}
    for file in latest("reports/*", 20): data["reports"].append({"path": file, "tail": read_tail(file)})
    for file in latest("proposals/*", 10): data["proposals"].append({"path": file, "tail": read_tail(file)})
    for name in ["latest-run-summary.json", "command-result.json"]:
        path = SEO_CONTROL / name
        if path.exists():
            key = name.replace("-", "_").replace(".json", "")
            try: data[key] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc: data[key] = {"error": str(exc)}
    (SEO_CONTROL / "ai-input-package.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data

def extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?", "", text.strip()).strip()
    text = re.sub(r"```$", "", text).strip()
    try: return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match: raise ValueError("No JSON object in AI output")
        return json.loads(match.group(0))

def call_openai(prompt: str, payload: dict[str, Any]) -> str:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key: raise RuntimeError("OPENAI_API_KEY missing")
    body = json.dumps({"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(payload)[:120000]}], "temperature": 0.1, "response_format": {"type": "json_object"}}).encode("utf-8")
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as response: return json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"]

def call_anthropic(prompt: str, payload: dict[str, Any]) -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key: raise RuntimeError("ANTHROPIC_API_KEY missing")
    body = json.dumps({"model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"), "max_tokens": 4000, "temperature": 0.1, "system": prompt, "messages": [{"role": "user", "content": json.dumps(payload)[:120000]}]}).encode("utf-8")
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as response: data = json.loads(response.read().decode("utf-8"))
    return "\n".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")

def call_ai(prompt: str, payload: dict[str, Any]) -> tuple[str, str]:
    provider = os.getenv("AI_PROVIDER", "").lower().strip()
    if provider == "openai": return "openai", call_openai(prompt, payload)
    if provider == "anthropic": return "anthropic", call_anthropic(prompt, payload)
    if os.getenv("ANTHROPIC_API_KEY"): return "anthropic", call_anthropic(prompt, payload)
    if os.getenv("OPENAI_API_KEY"): return "openai", call_openai(prompt, payload)
    raise RuntimeError("No AI API key found")

def validate_specialist(data: dict[str, Any]) -> list[str]:
    errors = []
    for index, finding in enumerate(data.get("findings", [])):
        if not finding.get("evidence"): errors.append(f"finding {index} missing evidence")
        if finding.get("approval_required") is not True: errors.append(f"finding {index} must require approval")
        affected_file = str(finding.get("affected_file", ""))
        if affected_file in BLOCKED_FILES or affected_file.startswith(".private"): errors.append(f"finding {index} touches blocked file {affected_file}")
    return errors

def validate_director(data: dict[str, Any]) -> list[str]:
    errors = []
    if data.get("decision") not in DECISIONS: errors.append("invalid director decision")
    if data.get("approval_required") is not True: errors.append("director must require approval")
    if data.get("implementation_allowed_now") is not False: errors.append("implementation_allowed_now must be false")
    return errors

def write_markdown(path: Path, title: str, data: dict[str, Any]) -> None:
    path.write_text("# " + title + "\n\n```json\n" + json.dumps(data, indent=2) + "\n```\n", encoding="utf-8")

def main() -> int:
    provider = "none"
    try:
        evidence = build_evidence()
        provider, specialist_text = call_ai(SPECIALIST_PROMPT, evidence)
        specialist = extract_json(specialist_text)
        errors = validate_specialist(specialist)
        if errors: raise ValueError("Specialist validation failed: " + "; ".join(errors))
        (SEO_CONTROL / "specialist-output.json").write_text(json.dumps(specialist, indent=2), encoding="utf-8")
        write_markdown(PROPOSALS / "ai-specialist-proposal.md", "AI Specialist Proposal", specialist)
        provider, director_text = call_ai(DIRECTOR_PROMPT, {"evidence": evidence, "specialist_output": specialist})
        director = extract_json(director_text)
        errors = validate_director(director)
        if errors: raise ValueError("Director validation failed: " + "; ".join(errors))
        (SEO_CONTROL / "director-review.json").write_text(json.dumps(director, indent=2), encoding="utf-8")
        write_markdown(PROPOSALS / "director-review.md", "AI Director Review", director)
        result = Result(True, provider, str(specialist.get("status", "UNKNOWN")), str(director.get("decision", "UNKNOWN")), False, True, "AI review completed. Implementation remains locked.")
    except Exception as exc:
        result = Result(False, provider, "FAILED", "NEEDS_EVIDENCE", False, True, f"AI review failed safely: {exc}")
        (LOGS / "ai-review-error.log").write_text(str(exc), encoding="utf-8")
    (SEO_CONTROL / "ai-run-result.json").write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    print(json.dumps(asdict(result), indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
