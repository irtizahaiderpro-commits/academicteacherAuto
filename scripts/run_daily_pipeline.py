#!/usr/bin/env python3
"""
Academic Teacher SEO Control - rendered crawler upgrade.

This replaces the safe starter raw-HTML audit with a real rendered crawler.

What it does:
- Uses Playwright Chromium when available.
- Falls back to raw urllib if Playwright is unavailable.
- Checks raw HTML and rendered HTML separately.
- Extracts title, meta description, H1s, canonical, word count and internal links.
- Scans risky/banned phrases.
- Writes machine-readable reports for AI review.
- Does not edit source files.
- Does not create PRs.
- Does not deploy.

Expected outputs:
- reports/rendered_crawl.csv
- reports/raw_vs_rendered.csv
- reports/title_meta_h1_audit.csv
- reports/internal_links_audit.csv
- reports/bad_terms_scan.csv
- reports/seo_findings.json
- reports/rendered_pipeline_summary.json
- proposals/rendered_seo_notes.md
- seo-control/rendered-pipeline-summary.json
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional


SITE_URL = os.getenv("SITE_URL", "https://academicteacher.co.uk").rstrip("/")
MAX_PAGES = int(os.getenv("SEO_CRAWL_MAX_PAGES", "80"))
CRAWL_TIMEOUT_MS = int(os.getenv("SEO_CRAWL_TIMEOUT_MS", "35000"))

SEED_PATHS = [
    "/",
    "/services/",
    "/guides/",
    "/subjects/",
    "/samples/",
    "/contact/",
    "/subjects/project-management/",
    "/subjects/business-management/",
    "/subjects/nursing/",
    "/subjects/health-social-care/",
    "/subjects/computer-science/",
    "/subjects/artificial-intelligence/",
    "/subjects/mba/",
    "/services/assignment-writing/",
    "/services/dissertation-help/",
    "/services/proofreading-editing/",
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

# GitHub-hosted Linux runners can sometimes hit IPv6 "network unreachable"
# while the domain still has a valid IPv4 route. Force Python urllib to use IPv4.
_ORIGINAL_GETADDRINFO = socket.getaddrinfo

def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _ORIGINAL_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = _ipv4_getaddrinfo



@dataclass
class PageAudit:
    url: str
    ok: bool
    status: Optional[int]
    content_type: str
    final_url: str
    raw_title: str
    rendered_title: str
    raw_meta_description: str
    rendered_meta_description: str
    raw_h1_count: int
    rendered_h1_count: int
    rendered_h1_text: str
    canonical: str
    word_count: int
    internal_link_count: int
    internal_links: list[str] = field(default_factory=list)
    banned_terms: list[str] = field(default_factory=list)
    js_render_gap: bool = False
    error: str = ""


@dataclass
class Finding:
    id: str
    severity: str
    issue_type: str
    url: str
    evidence: str
    recommendation: str
    affected_file: str = "unknown"
    approval_required: bool = True


@dataclass
class PipelineSummary:
    generated_at_utc: str
    site_url: str
    mode: str
    pages_checked: int
    pages_ok: int
    pages_with_errors: int
    findings_count: int
    banned_term_hits: int
    js_render_gap_pages: int
    status: str
    reports: list[str]
    proposals: list[str]
    message: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.canonicals: list[str] = []
        self.h1_texts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "a" and attrs_dict.get("href"):
            self.links.append(attrs_dict["href"])
        if tag.lower() == "link" and attrs_dict.get("rel", "").lower() == "canonical":
            if attrs_dict.get("href"):
                self.canonicals.append(attrs_dict["href"])
        if tag.lower() == "h1":
            self._in_h1 = True
            self._h1_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "h1" and self._in_h1:
            text = re.sub(r"\s+", " ", " ".join(self._h1_parts)).strip()
            if text:
                self.h1_texts.append(unescape(text))
            self._in_h1 = False
            self._h1_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self._h1_parts.append(data)


def abs_url(path_or_url: str) -> str:
    return urllib.parse.urljoin(SITE_URL + "/", path_or_url)


def is_internal_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    site = urllib.parse.urlparse(SITE_URL)
    return parsed.netloc in {"", site.netloc} and parsed.scheme in {"", "http", "https"}


def clean_url(url: str) -> str:
    parsed = urllib.parse.urlparse(abs_url(url))
    clean = parsed._replace(fragment="", query="")
    return urllib.parse.urlunparse(clean)


def first_match(pattern: str, text: str, flags: int = re.I | re.S) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        return ""
    return unescape(re.sub(r"\s+", " ", match.group(1)).strip())


def meta_description(html: str) -> str:
    desc = first_match(
        r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"'][^>]*>",
        html,
    )
    if not desc:
        desc = first_match(
            r"<meta[^>]+content=[\"'](.*?)[\"'][^>]+name=[\"']description[\"'][^>]*>",
            html,
        )
    return desc


def title(html: str) -> str:
    return first_match(r"<title[^>]*>(.*?)</title>", html)


def strip_tags(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(re.sub(r"\s+", " ", text))
    return text.strip()


def word_count(html: str) -> int:
    text = strip_tags(html)
    return len(re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}\b", text))


def fetch_raw(url: str, timeout: int = 25) -> tuple[Optional[int], str, str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AcademicTeacherSEOControl/RenderedCrawler/1.0 (+https://academicteacher.co.uk)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        return response.status, content_type, response.geturl(), text, ""


def safe_fetch_raw(url: str) -> tuple[Optional[int], str, str, str, str]:
    try:
        return fetch_raw(url)
    except urllib.error.HTTPError as exc:
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        try:
            html = exc.read().decode("utf-8", errors="replace")
        except Exception:
            html = ""
        return exc.code, content_type, url, html, f"HTTPError: {exc}"
    except Exception as exc:
        return None, "", url, "", f"{type(exc).__name__}: {exc}"


async def render_with_playwright(urls: list[str]) -> dict[str, dict[str, str]]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        (LOGS / "playwright-unavailable.log").write_text(str(exc), encoding="utf-8")
        return {}

    rendered: dict[str, dict[str, str]] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="AcademicTeacherSEOControl/RenderedCrawler/1.0 (+https://academicteacher.co.uk)"
        )

        for url in urls:
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=CRAWL_TIMEOUT_MS)
                await page.wait_for_timeout(1200)
                html = await page.content()
                final_url = page.url
                status = response.status if response else None
                rendered[url] = {
                    "html": html,
                    "final_url": final_url,
                    "status": str(status or ""),
                    "error": "",
                }
            except Exception as exc:
                rendered[url] = {
                    "html": "",
                    "final_url": url,
                    "status": "",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        await browser.close()

    return rendered


def parse_page(url: str, raw_status: Optional[int], content_type: str, raw_final_url: str, raw_html: str, raw_error: str, rendered_data: dict[str, str]) -> PageAudit:
    rendered_html = rendered_data.get("html") or raw_html
    final_url = rendered_data.get("final_url") or raw_final_url or url
    status = raw_status
    if rendered_data.get("status"):
        try:
            status = int(rendered_data["status"])
        except Exception:
            pass

    parser = LinkParser()
    try:
        parser.feed(rendered_html)
    except Exception:
        pass

    internal_links = sorted(
        {
            clean_url(link)
            for link in parser.links
            if link
            and is_internal_url(link)
            and not link.startswith(("mailto:", "tel:", "javascript:"))
        }
    )

    rendered_text = strip_tags(rendered_html).lower()
    found_terms = [term for term in BANNED_TERMS if term in rendered_text]

    raw_h1_count = len(re.findall(r"<h1\b", raw_html, flags=re.I))
    rendered_h1_count = len(parser.h1_texts)

    raw_title = title(raw_html)
    rendered_title = title(rendered_html)
    raw_desc = meta_description(raw_html)
    rendered_desc = meta_description(rendered_html)

    js_render_gap = (
        (not raw_desc and bool(rendered_desc))
        or (raw_h1_count == 0 and rendered_h1_count > 0)
        or abs(word_count(rendered_html) - word_count(raw_html)) > 80
    )

    return PageAudit(
        url=url,
        ok=bool(status and 200 <= status < 400),
        status=status,
        content_type=content_type,
        final_url=final_url,
        raw_title=raw_title,
        rendered_title=rendered_title,
        raw_meta_description=raw_desc,
        rendered_meta_description=rendered_desc,
        raw_h1_count=raw_h1_count,
        rendered_h1_count=rendered_h1_count,
        rendered_h1_text=" | ".join(parser.h1_texts[:4]),
        canonical=parser.canonicals[0] if parser.canonicals else "",
        word_count=word_count(rendered_html),
        internal_link_count=len(internal_links),
        internal_links=internal_links,
        banned_terms=found_terms,
        js_render_gap=js_render_gap,
        error=raw_error or rendered_data.get("error", ""),
    )


def crawl_urls() -> list[str]:
    urls = []
    for path in SEED_PATHS:
        url = clean_url(path)
        if url not in urls:
            urls.append(url)
    return urls[:MAX_PAGES]


def build_findings(pages: list[PageAudit]) -> list[Finding]:
    findings: list[Finding] = []
    counter = 1

    def add(severity: str, issue_type: str, page: PageAudit, evidence: str, recommendation: str) -> None:
        nonlocal counter
        findings.append(
            Finding(
                id=f"finding-{counter:03d}",
                severity=severity,
                issue_type=issue_type,
                url=page.url,
                evidence=evidence,
                recommendation=recommendation,
            )
        )
        counter += 1

    for page in pages:
        if not page.ok:
            add(
                "high",
                "url_status",
                page,
                f"URL returned status/error: {page.status or page.error}",
                "Investigate route, redirect, server response or crawl access.",
            )
            # Do not create false title/meta/H1/thin-content findings when the page was not fetched.
            # If network access fails, only report the network/status issue for that URL.
            continue

        if not page.rendered_title:
            add(
                "high",
                "missing_title",
                page,
                "Rendered page has no title tag.",
                "Add a unique title tag for this URL.",
            )
        elif len(page.rendered_title) > 65:
            add(
                "medium",
                "long_title",
                page,
                f"Rendered title length is {len(page.rendered_title)}.",
                "Shorten the title to a more focused search result title.",
            )

        if not page.rendered_meta_description:
            add(
                "medium",
                "missing_meta_description",
                page,
                "Rendered page has no meta description.",
                "Add a concise human-written meta description.",
            )
        elif len(page.rendered_meta_description) > 160:
            add(
                "low",
                "long_meta_description",
                page,
                f"Rendered meta description length is {len(page.rendered_meta_description)}.",
                "Shorten the meta description to roughly 140-160 characters.",
            )

        if page.rendered_h1_count == 0:
            add(
                "medium",
                "missing_h1",
                page,
                "Rendered page has no H1.",
                "Add one clear H1 aligned with the page search intent.",
            )
        elif page.rendered_h1_count > 1:
            add(
                "low",
                "multiple_h1",
                page,
                f"Rendered page has {page.rendered_h1_count} H1 tags.",
                "Consider using one primary H1 and H2/H3 for subheadings.",
            )

        if page.word_count < 250:
            add(
                "low",
                "thin_rendered_content",
                page,
                f"Rendered word count is {page.word_count}.",
                "Review whether this page has enough useful page-specific content.",
            )

        if page.banned_terms:
            add(
                "high",
                "risky_academic_wording",
                page,
                "Risky terms found: " + ", ".join(page.banned_terms),
                "Replace with policy-safe academic support wording.",
            )

        if page.js_render_gap:
            add(
                "medium",
                "raw_vs_rendered_gap",
                page,
                "Raw HTML and rendered HTML differ significantly for SEO elements/content.",
                "Consider prerendering/SSG for priority money pages.",
            )

    return findings


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> str:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def write_reports(pages: list[PageAudit], findings: list[Finding]) -> list[str]:
    reports: list[str] = []

    reports.append(
        write_csv(
            REPORTS / "rendered_crawl.csv",
            [
                {
                    "url": p.url,
                    "ok": p.ok,
                    "status": p.status,
                    "final_url": p.final_url,
                    "rendered_title": p.rendered_title,
                    "rendered_meta_description_length": len(p.rendered_meta_description),
                    "rendered_h1_count": p.rendered_h1_count,
                    "rendered_h1_text": p.rendered_h1_text,
                    "canonical": p.canonical,
                    "word_count": p.word_count,
                    "internal_link_count": p.internal_link_count,
                    "banned_terms": "; ".join(p.banned_terms),
                    "error": p.error,
                }
                for p in pages
            ],
            [
                "url",
                "ok",
                "status",
                "final_url",
                "rendered_title",
                "rendered_meta_description_length",
                "rendered_h1_count",
                "rendered_h1_text",
                "canonical",
                "word_count",
                "internal_link_count",
                "banned_terms",
                "error",
            ],
        )
    )

    reports.append(
        write_csv(
            REPORTS / "raw_vs_rendered.csv",
            [
                {
                    "url": p.url,
                    "raw_title": p.raw_title,
                    "rendered_title": p.rendered_title,
                    "raw_meta_description_length": len(p.raw_meta_description),
                    "rendered_meta_description_length": len(p.rendered_meta_description),
                    "raw_h1_count": p.raw_h1_count,
                    "rendered_h1_count": p.rendered_h1_count,
                    "js_render_gap": p.js_render_gap,
                }
                for p in pages
            ],
            [
                "url",
                "raw_title",
                "rendered_title",
                "raw_meta_description_length",
                "rendered_meta_description_length",
                "raw_h1_count",
                "rendered_h1_count",
                "js_render_gap",
            ],
        )
    )

    reports.append(
        write_csv(
            REPORTS / "title_meta_h1_audit.csv",
            [
                {
                    "url": p.url,
                    "title": p.rendered_title,
                    "title_length": len(p.rendered_title),
                    "meta_description_length": len(p.rendered_meta_description),
                    "h1_count": p.rendered_h1_count,
                    "h1_text": p.rendered_h1_text,
                    "canonical": p.canonical,
                }
                for p in pages
            ],
            [
                "url",
                "title",
                "title_length",
                "meta_description_length",
                "h1_count",
                "h1_text",
                "canonical",
            ],
        )
    )

    link_rows = []
    for p in pages:
        for link in p.internal_links:
            link_rows.append({"source_url": p.url, "target_url": link})
    reports.append(write_csv(REPORTS / "internal_links_audit.csv", link_rows, ["source_url", "target_url"]))

    bad_term_rows = []
    for p in pages:
        for term in p.banned_terms:
            bad_term_rows.append({"url": p.url, "term": term})
    reports.append(write_csv(REPORTS / "bad_terms_scan.csv", bad_term_rows, ["url", "term"]))

    findings_path = REPORTS / "seo_findings.json"
    findings_path.write_text(
        json.dumps([asdict(f) for f in findings], indent=2),
        encoding="utf-8",
    )
    reports.append(str(findings_path))

    return reports


def write_proposal(findings: list[Finding], mode: str) -> list[str]:
    path = PROPOSALS / "rendered_seo_notes.md"
    lines = [
        "# Rendered SEO Audit Notes",
        "",
        f"Mode: `{mode}`",
        "",
        "This report is generated from rendered page content where Playwright is available.",
        "It does not edit the website.",
        "",
        "## Findings",
        "",
    ]

    if not findings:
        lines.append("- No rendered-audit issues found in the checked priority URLs.")
    else:
        for finding in findings:
            lines.append(f"### {finding.id} — {finding.issue_type} — {finding.severity}")
            lines.append(f"- URL: {finding.url}")
            lines.append(f"- Evidence: {finding.evidence}")
            lines.append(f"- Recommendation: {finding.recommendation}")
            lines.append(f"- Affected file: {finding.affected_file}")
            lines.append(f"- Approval required: {finding.approval_required}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return [str(path)]


async def run() -> int:
    started = time.time()
    urls = crawl_urls()

    raw_data = {url: safe_fetch_raw(url) for url in urls}
    rendered_data = await render_with_playwright(urls)
    mode = "playwright_rendered" if rendered_data else "raw_fallback_no_playwright"

    pages = [
        parse_page(
            url=url,
            raw_status=raw_data[url][0],
            content_type=raw_data[url][1],
            raw_final_url=raw_data[url][2],
            raw_html=raw_data[url][3],
            raw_error=raw_data[url][4],
            rendered_data=rendered_data.get(url, {}),
        )
        for url in urls
    ]

    findings = build_findings(pages)
    reports = write_reports(pages, findings)
    proposals = write_proposal(findings, mode)

    pages_ok = sum(1 for p in pages if p.ok)
    pages_with_errors = len(pages) - pages_ok
    banned_hits = sum(len(p.banned_terms) for p in pages)
    js_gap_pages = sum(1 for p in pages if p.js_render_gap)

    status = "AUDIT_COMPLETE_CLEAR"
    if findings:
        status = "AUDIT_COMPLETE_WITH_FINDINGS"
    if pages_with_errors:
        status = "AUDIT_COMPLETE_WITH_ERRORS"

    summary = PipelineSummary(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        site_url=SITE_URL,
        mode=mode,
        pages_checked=len(pages),
        pages_ok=pages_ok,
        pages_with_errors=pages_with_errors,
        findings_count=len(findings),
        banned_term_hits=banned_hits,
        js_render_gap_pages=js_gap_pages,
        status=status,
        reports=reports,
        proposals=proposals,
        message="Rendered SEO audit complete. If mode is not playwright_rendered, fix Playwright/network before trusting SEO findings. Source-file mapping is still required before approved implementation.",
    )

    summary_json = json.dumps(asdict(summary), indent=2)
    (REPORTS / "rendered_pipeline_summary.json").write_text(summary_json, encoding="utf-8")
    (SEO_CONTROL / "rendered-pipeline-summary.json").write_text(summary_json, encoding="utf-8")

    # Backward-compatible files expected by older dashboard logic
    (REPORTS / "starter_pipeline_summary.json").write_text(summary_json, encoding="utf-8")
    (SEO_CONTROL / "starter-pipeline-summary.json").write_text(summary_json, encoding="utf-8")

    print(summary_json)
    print(f"Elapsed seconds: {time.time() - started:.2f}")

    # Deliberately return 0 so reports/artifacts still upload.
    # Problems are reported as findings, not as workflow crashes.
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
