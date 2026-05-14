# Phase 8 Test and Debug Runbook

T1:
```bash
python scripts/seo_control_self_test.py --check-files
```

T2:
```bash
python scripts/seo_command_parser.py /start-seo-review
```

T3:
```bash
python scripts/seo_patch_plan_validator.py
```
This should fail safely unless `approved_patches/approved_patch_plan.json` exists.

T4 GitHub:
```text
command: /start-seo-review
ai_provider: none
approval_token: blank
```

Expected: artifacts and dashboard only. No PR. No deployment.
