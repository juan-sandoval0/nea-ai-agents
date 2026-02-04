# Lovable Prompt for Meeting Briefing App

Copy this prompt into Lovable to generate the frontend.

---

## Prompt

Build a meeting briefing app for venture capital investors. The app generates company research briefings from a URL.

### Main Page - Briefing Generator

**Header:**
- Title: "Meeting Briefing"
- Subtitle: "Company intelligence for your next meeting"

**Input Section:**
- Large text input field with placeholder "Enter company URL (e.g., stripe.com)"
- "Generate Briefing" button (primary, prominent)
- Loading state: Show spinner with "Generating briefing..." text (takes 30-60 seconds)

**Results Section** (appears after generation):
Collapsible accordion sections:

1. **TL;DR** - 2-3 sentence summary (always expanded by default)

2. **Why This Meeting Matters** - Bullet list of key points

3. **Company Snapshot** - Table/card with:
   - Company Name
   - Founded
   - HQ Location
   - Employees
   - Products
   - Customers
   - Total Funding
   - Last Round

4. **Founders** - Cards for each founder:
   - Name and role
   - LinkedIn link (icon)
   - Background summary

5. **Key Signals** - List with signal type badges:
   - hiring, funding, traffic, website_update, etc.
   - Description text

6. **Recent News** - List of articles:
   - Headline (linked to URL)
   - Outlet and date
   - Takeaway summary

7. **For This Meeting** - Meeting prep suggestions

**Actions:**
- "Copy to Clipboard" button - copies full markdown
- "View History" link - navigates to history page

**Error States:**
- Invalid URL: "Please enter a valid company URL"
- Company not found: "Could not find company information for [URL]"
- Server error: "Something went wrong. Please try again."

### History Page

**Header:**
- Title: "Briefing History"
- Search bar: Filter by company name or URL
- Back link to main page

**List View:**
- Cards showing:
  - Company name
  - Company URL
  - Generated date/time
  - Click to view full briefing
- Delete button (with confirmation)
- Pagination or infinite scroll

### Design Requirements

- Clean, professional look (think Notion or Linear)
- Light mode only (for now)
- Mobile responsive
- Use shadcn/ui components
- Colors: Use a professional blue/gray palette

### API Integration

Backend URL: `http://localhost:8000` (will be configured for production)

**Endpoints:**

```
POST /api/briefing
Body: { "url": "stripe.com" }
Response: BriefingResponse (see below)

GET /api/briefings?search=stripe&limit=50&offset=0
Response: { briefings: [...], total: number }

GET /api/briefings/{id}
Response: BriefingResponse

DELETE /api/briefings/{id}
Response: { status: "deleted", id: "..." }
```

**BriefingResponse Schema:**
```typescript
interface BriefingResponse {
  id: string;
  company_id: string;
  company_name: string;
  created_at: string; // ISO datetime

  // Structured sections
  tldr: string | null;
  why_it_matters: string[] | null;
  company_snapshot: {
    company_name: string;
    founded: string | null;
    hq: string | null;
    employees: number | null;
    products: string | null;
    customers: string | null;
    total_funding: number | null;
    last_round: string | null;
  } | null;
  founders: Array<{
    name: string;
    role: string | null;
    linkedin_url: string | null;
    background: string | null;
  }>;
  signals: Array<{
    signal_type: string;
    description: string;
    source: string;
  }>;
  news: Array<{
    headline: string;
    outlet: string | null;
    url: string | null;
    published_date: string | null;
    takeaway: string | null;
  }>;
  meeting_prep: string | null;

  // Full markdown for copy/export
  markdown: string;

  // Metadata
  success: boolean;
  error: string | null;
  data_sources: Record<string, any>;
}
```

### Environment Variable

Add configuration for API URL:
```
VITE_API_URL=http://localhost:8000
```

---

## Notes for Lovable

- The briefing generation takes 30-60 seconds, so the loading state needs to handle long waits
- The markdown field contains the full briefing - use this for the "Copy to Clipboard" feature
- Signal types should have colored badges (funding=green, hiring=blue, traffic=purple, etc.)
- Founders may not have LinkedIn URLs - handle gracefully
- Some sections may be null if data is unavailable - don't show empty sections
