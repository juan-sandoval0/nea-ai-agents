// Empty string = relative URLs → Next.js proxy route (production via Databricks)
// Set NEXT_PUBLIC_API_URL to override (e.g. http://localhost:8000 for local backend dev)
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// Provided by Clerk's `useAuth().getToken`. Optional so the helpers work
// both when Clerk is active and during the USE_CLERK_AUTH=false rollback path.
export type GetToken = () => Promise<string | null>;

// ── Types ──────────────────────────────────────────────────────────────────

export interface CompanySnapshot {
  company_name: string;
  founded?: string | null;
  hq?: string | null;
  employees?: number | null;
  products?: string | null;
  customers?: string | null;
  total_funding?: number | null;
  last_round?: string | null;
}

export interface FounderInfo {
  name: string;
  role?: string | null;
  linkedin_url?: string | null;
  background?: string | null;
}

export interface Signal {
  signal_type: string;
  description: string;
  source: string;
}

export interface NewsItem {
  headline: string;
  outlet?: string | null;
  url?: string | null;
  published_date?: string | null;
  takeaway?: string | null;
  synopsis?: string | null;
  sentiment?: string | null;
  news_type?: string | null;
}

export interface CompetitorInfo {
  name: string;
  domain?: string | null;
  competitor_type?: string | null;
  description?: string | null;
  funding_total?: number | null;
  funding_stage?: string | null;
  funding_last_amount?: number | null;
  funding_last_date?: string | null;
  headcount?: number | null;
  tags?: string | null;
}

export interface BriefingResponse {
  id: string;
  company_id: string;
  company_name: string;
  created_at: string;
  tldr?: string | null;
  why_it_matters?: string[] | null;
  company_snapshot?: CompanySnapshot | null;
  founders: FounderInfo[];
  signals: Signal[];
  news: NewsItem[];
  competitors: CompetitorInfo[];
  meeting_prep?: string | null;
  markdown: string;
  success: boolean;
  error?: string | null;
  data_sources: Record<string, unknown>;
}

export interface BriefingListItem {
  id: string;
  company_id: string;
  company_name: string;
  created_at: string;
  success: boolean;
}

export interface DigestArticle {
  headline: string;
  company: string;
  category: string;
  signal_type: string;
  source?: string | null;
  url?: string | null;
  published_date?: string | null;
  relevance_score: number;
  rank_score: number;
  sentiment?: string | null;
  synopsis?: string | null;
}

export interface SentimentRollup {
  positive: number;
  negative: number;
  neutral: number;
  total: number;
}

export interface IndustryHighlight {
  industry: string;
  total_signals: number;
  company_count: number;
  top_types: Record<string, number>;
}

export interface DigestStats {
  total_signals: number;
  companies_covered: number;
  portfolio_signals: number;
  competitor_signals: number;
  featured_count: number;
  summary_count: number;
}

export interface WeeklyDigestResponse {
  start_date: string;
  end_date: string;
  generated_at: string;
  featured_articles: DigestArticle[];
  summary_articles: DigestArticle[];
  sentiment_rollup: SentimentRollup;
  industry_highlights: IndustryHighlight[];
  stats: DigestStats;
  markdown?: string | null;
}

export interface JobRunResponse {
  id: string;
  agent_type: string;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  result_summary: Record<string, unknown>;
}

export interface OutreachResponse {
  company_id: string;
  company_name?: string | null;
  contact_name?: string | null;
  contact_title?: string | null;
  contact_linkedin?: string | null;
  investor_key: string;
  output_format: string;
  context_type?: string | null;
  subject?: string | null;
  message?: string | null;
  generated_at: string;
  data_sources: Record<string, unknown>;
  success: boolean;
  error?: string | null;
  stealth_mode: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

type ApiInit = RequestInit & { getToken?: GetToken };

async function apiFetch<T>(path: string, init?: ApiInit): Promise<T> {
  const { getToken, headers, ...rest } = init ?? {};
  const token = getToken ? await getToken() : null;
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers as Record<string, string> | undefined),
    },
    ...rest,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── Briefing ───────────────────────────────────────────────────────────────

export function generateBriefing(
  url: string,
  getToken?: GetToken
): Promise<BriefingResponse> {
  return apiFetch<BriefingResponse>("/api/briefing", {
    method: "POST",
    body: JSON.stringify({ url }),
    getToken,
  });
}

export function listBriefings(
  search?: string,
  limit = 10,
  getToken?: GetToken
): Promise<{ briefings: BriefingListItem[]; total: number }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (search) params.set("search", search);
  return apiFetch(`/api/briefings?${params}`, { getToken });
}

export function getBriefing(
  id: string,
  getToken?: GetToken
): Promise<BriefingResponse> {
  return apiFetch<BriefingResponse>(`/api/briefings/${id}`, { getToken });
}

// ── Digest ─────────────────────────────────────────────────────────────────

export function getWeeklyDigest(
  days = 7,
  featuredCount = 3,
  summaryCount = 10,
  getToken?: GetToken
): Promise<WeeklyDigestResponse> {
  const params = new URLSearchParams({
    days: String(days),
    featured_count: String(featuredCount),
    summary_count: String(summaryCount),
    include_markdown: "false",
  });
  return apiFetch<WeeklyDigestResponse>(`/api/digest/weekly?${params}`, { getToken });
}

export function getNewsJobStatus(
  jobId: string,
  getToken?: GetToken
): Promise<JobRunResponse> {
  return apiFetch<JobRunResponse>(`/api/news/status/${jobId}`, { getToken });
}

export function getLatestNewsStatus(
  getToken?: GetToken
): Promise<JobRunResponse> {
  return apiFetch<JobRunResponse>("/api/news/status", { getToken });
}

// ── Outreach ───────────────────────────────────────────────────────────────

export interface OutreachParams {
  company_id: string;
  investor_key: string;
  output_format?: "email" | "linkedin";
  contact_name?: string;
  context_type_override?: string;
  skip_ingest?: boolean;
}

export function generateOutreach(
  params: OutreachParams,
  getToken?: GetToken
): Promise<OutreachResponse> {
  return apiFetch<OutreachResponse>("/api/outreach", {
    method: "POST",
    body: JSON.stringify({
      output_format: "email",
      skip_ingest: false,
      ...params,
    }),
    getToken,
  });
}

export function submitOutreachFeedback(
  params: {
    outreach_id: string;
    investor_key: string;
    company_id: string;
    context_type?: string;
    original_message: string;
    edited_message?: string;
    approval_status: "approved" | "edited" | "rejected";
    investor_notes?: string;
  },
  getToken?: GetToken
): Promise<{ id: string; approval_status: string; promoted: boolean }> {
  return apiFetch("/api/outreach/feedback", {
    method: "POST",
    body: JSON.stringify(params),
    getToken,
  });
}
