#!/usr/bin/env python3
"""
Academic Teacher SEO Control - safe starter audit pipeline.

This file exists so the GitHub workflow has a real core audit step.

It is intentionally conservative:
- uses only Python standard library
- does not edit source files
- does not deploy
- writes reports/proposals only
- returns 0 so scheduled reporting can continue even if a page/network check fails

Later, you can replace or extend this file with the fuller SEO audit scripts:
01_rendered_crawl.py, 02_raw_vs_rendered.py, 03_sitemap_audit.py, etc.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Optional


SITE_URL = os.getenv("SITE_URL", "https://academicteacher.co.uk").rstrip("/")

PRIORITY_PATHS = [
    "/",
    "/services/",
    "/guides/",
    "/subjects/",
    "/subjects/project-management/",
    "/subjects/business-management/",
    "/subjects/nursing/",
    "/subjects/health-social-care/",
    "/subjects/computer-science/",
    "/subjects/artificial-intelligence/",
    "/subjects/mba/",
]

BANNED_TERMS = [
    "guaranteed grade",
    "guaranteed grades",
    "take my exam",
    "do my quiz",
    "pay someone to do my assignment",
    "write my assignment for me",
    "cheap essay writing service",
]

REPORTS = Path("reports")
PROPOSALS = Path("proposals")
LOGS = Path("logs")
SEO_CONTROL = Path("seo-control")

for directory in [REPORTS, PROPOSALS, LOGS, SEO_CONTROL]:
    directory.mkdir(parents=True, exist_ok=True)


@dataclass
class PageAudit:
    url: str
    ok: bool
    status: Optional[int]
    content_type: str
    final_url: str
    title: str
    meta_description: str
    h1_count: int
    banned_terms: list[str]
    error: str


@dataclass
class PipelineSummary:
    generated_at_utc: str
    site_url: str
    pages_checked: int
    pages_ok: int
    pages_with_errors: int
    banned_term_hits: int
    status: str
    reports: list[str]
    proposals: list[str]
    message: str


def fetch_url(url: str, timeout: int = 25) -> tuple[Optional[int], str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AcademicTeacherSEOControl/1.0 (+https://academicteacher.co.uk)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        return response.status, content_type, response.geturl(), text


def first_match(pattern: str, text: str, flags: int = re.I | re.S) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        return ""
    return unescape(re.sub(r"\s+", " ", match.group(1)).strip())


def audit_page(url: str) -> PageAudit:
    try:
        status, content_type, final_url, html = fetch_url(url)
        title = first_match(r"<title[^>]*>(.*?)</title>", html)
        description = first_match(
            r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"'][^>]*>",
            html,
        )
        if not description:
            description = first_match(
                r"<meta[^>]+content=[\"'](.*?)[\"'][^>]+name=[\"']description[\"'][^>]*>",
                html,
            )

        h1_count = len(re.findall(r"<h1\b", html, flags=re.I))
        lower_html = html.lower()
        found_terms = [term for term in BANNED_TERMS if term in lower_html]

        return PageAudit(
            url=url,
            ok=bool(status and 200 <= status < 400),
            status=status,
            content_type=content_type,
            final_url=final_url,
            title=title,
            meta_description=description,
            h1_count=h1_count,
            banned_terms=found_terms,
            error="",
        )

    except urllib.error.HTTPError as exc:
        return PageAudit(
            url=url,
            ok=False,
            status=exc.code,
            content_type=exc.headers.get("Content-Type", "") if exc.headers else "",
            final_url=url,
            title="",
            meta_description="",
            h1_count=0,
            banned_terms=[],
            error=f"HTTPError: {exc}",
        )
    except Exception as exc:
        return PageAudit(
            url=url,
            ok=False,
            status=None,
            content_type="",
            final_url=url,
            title="",
            meta_description="",
            h1_count=0,
            banned_terms=[],
            error=f"{type(exc).__name__}: {exc}",
        )


def write_page_report(results: list[PageAudit]) -> str:
    path = REPORTS / "basic_url_status.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "url",
                "ok",
                "status",
                "content_type",
                "final_url",
                "title",
                "meta_description_length",
                "h1_count",
                "banned_terms",
                "error",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "url": result.url,
                    "ok": result.ok,
                    "status": result.status,
                    "content_type": result.content_type,
                    "final_url": result.final_url,
                    "title": result.title,
                    "meta_description_length": len(result.meta_description),
                    "h1_count": result.h1_count,
                    "banned_terms": "; ".join(result.banned_terms),
                    "error": result.error,
                }
            )
    return str(path)


def write_bad_terms_report(results: list[PageAudit]) -> str:
    path = REPORTS / "bad_terms_scan.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["url", "term"])
        writer.writeheader()
        for result in results:
            for term in result.banned_terms:
                writer.writerow({"url": result.url, "term": term})
    return str(path)


def write_proposal(results: list[PageAudit]) -> str:
    path = PROPOSALS / "starter_audit_notes.md"
    lines = [
        "# Starter SEO Audit Notes",
        "",
        "This is a safe starter audit generated by `scripts/run_daily_pipeline.py`.",
        "It does not edit the website.",
        "",
        "## Findings",
        "",
    ]

    for result in results:
        issues = []
        if not result.ok:
            issues.append(f"status/error issue: {result.status or result.error}")
        if not result.title:
            issues.append("missing raw HTML title")
        if not result.meta_description:
            issues.append("missing raw HTML meta description")
        if result.h1_count == 0:
            issues.append("missing raw HTML H1")
        if result.banned_terms:
            issues.append("banned/risky terms: " + ", ".join(result.banned_terms))

        if issues:
            lines.append(f"### {result.url}")
            for issue in issues:
                lines.append(f"- {issue}")
            lines.append("")

    if len(lines) <= 8:
        lines.append("- No starter-audit issues found in the checked priority URLs.")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def main() -> int:
    started = time.time()
    urls = [SITE_URL + path for path in PRIORITY_PATHS]
    results = [audit_page(url) for url in urls]

    page_report = write_page_report(results)
    bad_terms_report = write_bad_terms_report(results)
    proposal = write_proposal(results)

    pages_ok = sum(1 for result in results if result.ok)
    pages_with_errors = len(results) - pages_ok
    banned_term_hits = sum(len(result.banned_terms) for result in results)

    if pages_with_errors or banned_term_hits:
        status = "AUDIT_COMPLETE_WITH_WARNINGS"
    else:
        status = "AUDIT_COMPLETE_CLEAR"

    summary = PipelineSummary(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        site_url=SITE_URL,
        pages_checked=len(results),
        pages_ok=pages_ok,
        pages_with_errors=pages_with_errors,
        banned_term_hits=banned_term_hits,
        status=status,
        reports=[page_report, bad_terms_report],
        proposals=[proposal],
        message=(
            "Starter SEO audit complete. Replace or extend this script with the fuller "
            "rendered crawl / sitemap / title-meta pipeline when ready."
        ),
    )

    summary_path = REPORTS / "starter_pipeline_summary.json"
    summary_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")

    control_path = SEO_CONTROL / "starter-pipeline-summary.json"
    control_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")

    print(json.dumps(asdict(summary), indent=2))
    print(f"Elapsed seconds: {time.time() - started:.2f}")

    # Return 0 deliberately. The dashboard will report warnings/blockers.
    # This prevents scheduled reporting from dying before artifacts are uploaded.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
