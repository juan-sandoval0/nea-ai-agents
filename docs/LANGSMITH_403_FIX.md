# Fix LangSmith 403 Errors

## Problem
LangSmith 403 errors appearing in production logs, indicating an expired or invalid API key.

## Solution
Disable LangSmith tracing (recommended) or rotate the API key.

---

## Option 1: Disable Tracing (Recommended)

LangSmith tracing is optional and only needed for debugging/observability. The code gracefully handles missing keys.

### Steps:

1. **Go to Vercel Dashboard**
   - Navigate to your project: https://vercel.com/dashboard
   - Select the `nea-ai-agents` project

2. **Open Environment Variables**
   - Click **Settings** → **Environment Variables**

3. **Remove or comment out the following variables:**
   - `LANGSMITH_API_KEY`
   - `LANGSMITH_TRACING`
   - `LANGSMITH_PROJECT`
   - `LANGCHAIN_API_KEY` (legacy)
   - `LANGCHAIN_TRACING_V2` (legacy)
   - `LANGCHAIN_PROJECT` (legacy)

4. **Redeploy**
   - Go to **Deployments** tab
   - Click **⋮** on the latest deployment → **Redeploy**
   - Or push a new commit to trigger deployment

5. **Verify**
   - Check logs after redeploy - 403 errors should be gone
   - Application functionality is unaffected (tracing is optional)

---

## Option 2: Rotate the API Key

If you want to keep LangSmith tracing enabled:

### Steps:

1. **Generate a new API key**
   - Go to https://smith.langchain.com/settings
   - Click **Create API Key**
   - Copy the new key

2. **Update Vercel environment variables**
   - Go to Vercel → Settings → Environment Variables
   - Update `LANGSMITH_API_KEY` with the new key
   - Update `LANGCHAIN_API_KEY` with the same new key (legacy)

3. **Revoke the old key**
   - Back in LangSmith settings
   - Find the old key and click **Revoke**

4. **Redeploy**
   - Trigger a new deployment to pick up the new key

---

## Verification

After applying the fix, check logs:

```bash
# View recent logs in Vercel Dashboard
# Or use Vercel CLI:
vercel logs --follow
```

Look for:
- ✅ No more 403 errors from LangSmith
- ✅ Briefing and outreach generation still working
- ✅ If tracing enabled: "LangSmith tracing enabled" log message

---

## Notes

- **Code is safe**: `services/logging_setup.py:122-124` gracefully handles missing keys
- **No functionality loss**: Tracing is only for debugging, not required for production
- **Recommended state**: Disabled unless actively debugging
