# Rendered Crawler Upgrade Pack

This pack upgrades the SEO automation from a raw starter audit to a Playwright-rendered audit.

## Replace this file

```text
scripts/run_daily_pipeline.py
```

## Add this file

```text
seo-control/source-map.example.json
```

## What changes

The new audit creates:

```text
reports/rendered_crawl.csv
reports/raw_vs_rendered.csv
reports/title_meta_h1_audit.csv
reports/internal_links_audit.csv
reports/bad_terms_scan.csv
reports/seo_findings.json
reports/rendered_pipeline_summary.json
proposals/rendered_seo_notes.md
seo-control/rendered-pipeline-summary.json
```

## Why this matters

The previous starter audit read raw HTML only. Your React site returns weak raw HTML, so it showed:

```text
title = Academic Teacher
meta_description_length = 0
h1_count = 0
```

The rendered crawler uses Playwright so it can see the real page after JavaScript loads.

## Install

1. Replace:

```text
scripts/run_daily_pipeline.py
```

2. Add:

```text
seo-control/source-map.example.json
```

3. Commit:

```text
Upgrade SEO audit to rendered crawler
```

4. Push.

5. Run workflow:

```text
command: /start-seo-review
ai_provider: none
approval_token: blank
```

6. Check artifact for:

```text
reports/rendered_crawl.csv
reports/raw_vs_rendered.csv
reports/seo_findings.json
proposals/rendered_seo_notes.md
```

## Safety

This crawler still does not edit, PR or deploy anything.

Do not run `/start-approved-implementation` until source mapping is verified and a real `approved_patches/approved_patch_plan.json` is manually created.
