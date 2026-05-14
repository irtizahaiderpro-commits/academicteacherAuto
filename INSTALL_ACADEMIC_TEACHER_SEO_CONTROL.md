# Academic Teacher SEO Control - Install Pack

Copy this folder into your Academic Teacher GitHub repo.

## First local test

```bash
python scripts/seo_control_self_test.py --check-files
```

## First GitHub safe test

GitHub Actions → Academic Teacher SEO Control → Run workflow:

```text
command: /start-seo-review
ai_provider: none
approval_token: blank
```

Expected: audit runs, artifacts upload, dashboard snapshot generated, no PR, no deployment.

## AI test

Add `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` as a GitHub Secret, then run:

```text
command: /start-seo-review
ai_provider: anthropic or openai
approval_token: blank
```

Expected: AI review artifacts, no PR, no deployment.

## Approved implementation test

Create `approved_patches/approved_patch_plan.json`, then run:

```text
command: /start-approved-implementation
approval_token: APPROVE_METADATA_ONLY
```

Expected: PR created only if patch plan validates. No deployment.

## Never commit

`.env`, `.private/*`, real API keys, Hostinger mail config.
