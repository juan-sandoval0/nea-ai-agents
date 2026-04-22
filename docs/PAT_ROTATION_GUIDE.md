# Personal Access Token (PAT) Rotation Guide

**Phase 3 Security Requirement**: Rotate GitHub and Databricks PATs for security hardening.

---

## Executive Summary

**Priority Assessment**:
- **GitHub PAT**: ⚠️ **LOW PRIORITY** - GitHub Actions uses auto-rotated `GITHUB_TOKEN`, not a custom PAT
- **Databricks PAT**: ⚠️ **VERY LOW PRIORITY** - Databricks is documentation-only, not deployed

**Recommendation**: Only rotate if you've manually added custom PATs to GitHub Actions secrets or plan to activate Databricks deployment.

---

## Task #9: GitHub PAT Rotation

### Current State

**GitHub Actions workflows** (`.github/workflows/news_refresh.yml`, `investor_digest.yml`) use these secrets:
- `ANTHROPIC_API_KEY`
- `HARMONIC_API_KEY`
- `OPENAI_API_KEY`
- `PARALLEL_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

**No custom GitHub PAT is currently configured.** The workflows use the default `GITHUB_TOKEN` which is:
- Automatically provided by GitHub Actions
- Scoped to the repository
- Automatically rotated by GitHub
- Sufficient for checking out code

### When to Rotate a GitHub PAT

You **only need a custom GitHub PAT** if:
1. Workflows need to access **other private repositories**
2. Workflows need to create pull requests or push commits (default token has limited permissions)
3. Workflows need to trigger other workflows
4. You're using the `gh` CLI with elevated permissions

**Currently**: ✅ None of these apply. No custom PAT needed.

### How to Add/Rotate a GitHub PAT (If Needed)

#### Step 1: Generate New PAT

1. Go to GitHub: https://github.com/settings/tokens
2. Click **Generate new token** → **Generate new token (classic)**
3. Set expiration: **90 days** (or custom)
4. Select scopes (minimum required):
   - ✅ `repo` (if accessing private repos)
   - ✅ `workflow` (if triggering workflows)
   - ✅ `read:org` (if reading org data)
5. Click **Generate token**
6. **Copy the token immediately** (you can't see it again)

#### Step 2: Add to GitHub Actions Secrets

1. Go to repo: https://github.com/juan-sandoval0/nea-ai-agents/settings/secrets/actions
2. Click **New repository secret**
3. Name: `GH_PAT` (or `GITHUB_PAT`)
4. Value: Paste the token from Step 1
5. Click **Add secret**

#### Step 3: Update Workflows (If Needed)

If workflows need the custom PAT, update `.github/workflows/*.yml`:

```yaml
steps:
  - name: Checkout repository
    uses: actions/checkout@v4
    with:
      token: ${{ secrets.GH_PAT }}  # Use custom PAT instead of default GITHUB_TOKEN
```

#### Step 4: Revoke Old PAT

1. Go back to https://github.com/settings/tokens
2. Find the old token
3. Click **Delete**
4. Confirm deletion

#### Step 5: Test

1. Trigger a workflow manually: **Actions** → **News Refresh** → **Run workflow**
2. Verify it completes successfully
3. Check logs for authentication errors

---

## Task #10: Databricks PAT Rotation

### Current State

**Databricks deployment is DOCUMENTATION ONLY** (see `databricks.yml` header):
- Not currently deployed
- GitHub Actions used instead for batch jobs
- Would only be used on a paid Databricks tier (Free Edition has DNS restrictions)

**No Databricks PAT is currently in use.**

### When to Rotate a Databricks PAT

You **only need a Databricks PAT** if:
1. You deploy to Databricks using `databricks bundle deploy`
2. You run jobs on Databricks clusters
3. You access Databricks APIs programmatically

**Currently**: ❌ None of these apply. Databricks is inactive.

### How to Add/Rotate a Databricks PAT (If Needed)

#### Step 1: Generate New PAT in Databricks

1. Log into Databricks workspace
2. Click your user icon → **Settings**
3. Click **Developer** → **Access tokens**
4. Click **Generate new token**
5. Set description: `NEA AI Platform - Batch Jobs`
6. Set lifetime: **90 days** (or custom)
7. Click **Generate**
8. **Copy the token immediately** (you can't see it again)

#### Step 2: Update Local `.databrickscfg` (For CLI Deployment)

If deploying from your local machine:

```bash
# Edit ~/.databrickscfg
[DEFAULT]
host = https://your-workspace.cloud.databricks.com
token = dapi1234567890abcdef...  # New token
```

Or set environment variables:

```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=dapi1234567890abcdef...
```

#### Step 3: Update GitHub Actions Secrets (If Using CI/CD)

If deploying from GitHub Actions:

1. Go to https://github.com/juan-sandoval0/nea-ai-agents/settings/secrets/actions
2. Add or update:
   - **DATABRICKS_HOST**: `https://your-workspace.cloud.databricks.com`
   - **DATABRICKS_TOKEN**: Paste new token
3. Update workflow to use these secrets:

```yaml
- name: Deploy to Databricks
  env:
    DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
    DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
  run: databricks bundle deploy --target prod
```

#### Step 4: Revoke Old PAT

1. Back in Databricks → Settings → Developer → Access tokens
2. Find the old token
3. Click **Revoke**
4. Confirm revocation

#### Step 5: Test

```bash
# Validate bundle
databricks bundle validate --target prod

# Test deploy (dry run)
databricks bundle deploy --target dev

# Full deployment
databricks bundle deploy --target prod
```

---

## Security Best Practices

### Token Expiration
- **Short-lived tokens**: Set 90-day expiration
- **Calendar reminders**: Add reminder 2 weeks before expiration
- **Rotation schedule**: Rotate every 90 days or on team member departure

### Token Storage
- ✅ **DO**: Store in GitHub Actions secrets (encrypted)
- ✅ **DO**: Store in password manager for local dev
- ❌ **DON'T**: Commit tokens to git (even in `.env` files)
- ❌ **DON'T**: Share tokens via Slack/email

### Token Scopes
- **Principle of least privilege**: Grant minimum required scopes
- **GitHub PAT**: Only `repo` if just accessing private code, add `workflow` only if triggering workflows
- **Databricks PAT**: Workspace-scoped by default (can't access other workspaces)

### Token Auditing
- **GitHub**: Review token activity at https://github.com/settings/tokens → click token → see "Last used"
- **Databricks**: Check access logs in Admin Console → Audit logs
- **Quarterly review**: Revoke unused tokens

---

## Verification Checklist

### After GitHub PAT Rotation
- [ ] Workflows trigger successfully
- [ ] Code checkout works (no 401/403 errors)
- [ ] Old PAT revoked
- [ ] Calendar reminder set for next rotation (90 days)

### After Databricks PAT Rotation
- [ ] `databricks bundle validate` passes
- [ ] Bundle deployment succeeds
- [ ] Jobs can run on clusters
- [ ] Old PAT revoked
- [ ] Calendar reminder set for next rotation (90 days)

---

## Current Status

| Token Type | Currently Used? | Priority | Action Required |
|------------|-----------------|----------|-----------------|
| GitHub PAT | ❌ No (using auto-rotated `GITHUB_TOKEN`) | Low | None unless custom PAT added |
| Databricks PAT | ❌ No (Databricks not deployed) | Very Low | None unless Databricks activated |

**Recommendation**: Mark Tasks #9 and #10 as **low priority** / **on hold** until custom PATs are actually needed.

---

## Future Considerations

### When to Use Custom PATs

**GitHub PAT** - Use if you need to:
- Create automated PRs from workflows
- Access multiple repositories in a workflow
- Trigger workflows from other workflows
- Use `gh` CLI with elevated permissions

**Databricks PAT** - Use if you:
- Upgrade to a paid Databricks tier (to bypass Free Edition DNS restrictions)
- Deploy batch jobs to Databricks clusters
- Want to centralize job orchestration in Databricks instead of GitHub Actions

### Alternatives to PATs

- **GitHub Apps**: More secure than PATs for automation (fine-grained permissions, auditable)
- **OIDC tokens**: For cloud provider authentication (AWS, Azure, GCP)
- **Service principals**: For Databricks (more granular than PATs)

---

## Related Documentation

- **Phase 4 Cleanup Checklist**: `docs/PHASE4_CLEANUP_CHECKLIST.md`
- **RLS Audit**: `docs/SUPABASE_RLS_AUDIT.md`
- **GitHub Actions Workflows**: `.github/workflows/`
- **Databricks Bundle**: `databricks.yml`
