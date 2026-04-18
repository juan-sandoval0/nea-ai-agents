"use client";

import { useState, useCallback, useEffect } from "react";
import { getWeeklyDigest, refreshNews, getNewsJobStatus, type WeeklyDigestResponse, type DigestArticle, type JobRunResponse } from "@/lib/api";

const SIG_LABEL: Record<string, string> = { funding:"Funding", FUNDING:"Funding", acquisition:"M&A", M_A:"M&A", product_launch:"Product", PRODUCT:"Product", executive_change:"Exec Change", hiring_expansion:"Hiring", partnership:"Partnership", PARTNERSHIP:"Partnership", EARNINGS:"Earnings", news_coverage:"News" };
const SIG_COLOR: Record<string, string> = { funding:"bg-green-50 text-green-700 border-green-200", FUNDING:"bg-green-50 text-green-700 border-green-200", acquisition:"bg-pink-50 text-pink-700 border-pink-200", M_A:"bg-pink-50 text-pink-700 border-pink-200", product_launch:"bg-blue-50 text-blue-700 border-blue-200", PRODUCT:"bg-blue-50 text-blue-700 border-blue-200", executive_change:"bg-indigo-50 text-indigo-700 border-indigo-200", hiring_expansion:"bg-teal-50 text-teal-700 border-teal-200", partnership:"bg-yellow-50 text-yellow-700 border-yellow-200", PARTNERSHIP:"bg-yellow-50 text-yellow-700 border-yellow-200", EARNINGS:"bg-orange-50 text-orange-700 border-orange-200" };
const sentimentColor = (s?: string | null) => s === "positive" ? "text-green-600" : s === "negative" ? "text-red-500" : "text-nea-muted";
const sentimentIcon  = (s?: string | null) => s === "positive" ? "↑" : s === "negative" ? "↓" : "–";
function sigBadge(type: string) { return (SIG_COLOR[type] ?? "bg-gray-100 text-gray-600 border-gray-200") + " border"; }

function FeaturedCard({ a }: { a: DigestArticle }) {
  return (
    <div className="bg-white rounded-xl border border-nea-border p-5 hover:border-nea-blue transition-colors">
      <div className="flex items-center gap-2 mb-2.5">
        <span className={"font-ui text-xs font-semibold px-2 py-0.5 rounded-full " + (a.category === "portfolio" ? "bg-nea-blue text-white" : "border border-nea-border text-nea-mid")}>
          {a.company}
        </span>
        <span className={"font-ui text-[10px] font-semibold px-2 py-0.5 rounded-full " + sigBadge(a.signal_type)}>
          {SIG_LABEL[a.signal_type] ?? a.signal_type}
        </span>
        <span className={"font-ui text-xs ml-auto " + sentimentColor(a.sentiment)}>{sentimentIcon(a.sentiment)}</span>
      </div>
      {a.url
        ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="font-ui text-sm font-semibold text-nea-dark hover:text-nea-blue hover:underline leading-snug block mb-2">{a.headline}</a>
        : <p className="font-ui text-sm font-semibold text-nea-dark leading-snug mb-2">{a.headline}</p>}
      {a.synopsis && <p className="font-ui text-xs text-nea-mid leading-relaxed">{a.synopsis}</p>}
      <p className="font-ui text-[10px] text-nea-muted mt-2.5">{[a.source, a.published_date].filter(Boolean).join(" · ")}</p>
    </div>
  );
}

function SummaryCard({ a }: { a: DigestArticle }) {
  return (
    <div className="bg-white rounded-lg border border-nea-border p-3.5 hover:border-nea-blue transition-colors">
      <div className="flex items-center gap-1.5 mb-2">
        <span className={"font-ui text-[10px] font-semibold px-1.5 py-0.5 rounded-full " + (a.category === "portfolio" ? "bg-nea-blue-light text-nea-blue" : "border border-nea-border text-nea-muted")}>
          {a.company}
        </span>
        <span className={"font-ui text-[10px] font-semibold px-1.5 py-0.5 rounded-full " + sigBadge(a.signal_type)}>
          {SIG_LABEL[a.signal_type] ?? a.signal_type}
        </span>
      </div>
      {a.url
        ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="font-ui text-sm font-medium text-nea-dark hover:text-nea-blue hover:underline leading-snug line-clamp-2 block">{a.headline}</a>
        : <p className="font-ui text-sm font-medium text-nea-dark leading-snug line-clamp-2">{a.headline}</p>}
      {a.synopsis && <p className="font-ui text-[11px] text-nea-muted mt-1 leading-relaxed line-clamp-2">{a.synopsis}</p>}
      <p className="font-ui text-[10px] text-nea-muted mt-2">{a.published_date ?? ""}</p>
    </div>
  );
}

export default function DigestPage() {
  const [days, setDays] = useState<7 | 14 | 30>(7);
  const [digest, setDigest] = useState<WeeklyDigestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadDigest = useCallback(async (d: number) => {
    setLoading(true); setError(null);
    try { setDigest(await getWeeklyDigest(d, 3, 12)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadDigest(days); }, [days, loadDigest]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true); setJobStatus("Starting…");
    try {
      const job = await refreshNews(days);
      let cur: JobRunResponse = job;
      setJobStatus("Fetching signals…");
      while (cur.status === "pending" || cur.status === "running") {
        await new Promise(r => setTimeout(r, 3000));
        cur = await getNewsJobStatus(cur.id);
        if (cur.status === "running") setJobStatus("Generating digest…");
      }
      if (cur.status === "completed") { setJobStatus(null); await loadDigest(days); }
      else setJobStatus("Failed: " + (cur.error ?? "unknown"));
    } catch (e) { setJobStatus("Error: " + (e instanceof Error ? e.message : "unknown")); }
    finally { setRefreshing(false); }
  }, [days, loadDigest]);

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-nea-border px-6 py-4 flex items-center gap-3 bg-white shrink-0 flex-wrap">
        <div>
          <h1 className="font-display text-xl font-semibold text-nea-blue leading-tight">News Digest</h1>
          <p className="font-ui text-xs text-nea-muted mt-0.5">Portfolio and competitor signals, ranked by relevance</p>
        </div>
        <div className="ml-auto flex items-center gap-2 flex-wrap">
          <div className="flex rounded-lg border border-nea-border overflow-hidden">
            {([7, 14, 30] as const).map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={"font-ui px-3 py-1.5 text-sm font-medium transition-colors " + (days === d ? "bg-nea-blue text-white" : "text-nea-mid hover:bg-nea-blue-light")}>
                {d}d
              </button>
            ))}
          </div>
          <button onClick={handleRefresh} disabled={refreshing || loading}
            className="font-ui flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-nea-border text-sm text-nea-mid hover:bg-nea-blue-light hover:border-nea-blue disabled:opacity-40 transition-colors">
            <svg className={"w-3.5 h-3.5 " + (refreshing ? "animate-spin" : "")} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </button>
          {jobStatus && <span className="font-ui text-xs text-nea-blue bg-nea-blue-light px-3 py-1.5 rounded-lg">{jobStatus}</span>}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {error && <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4 font-ui">{error}</div>}
        {loading && !digest && (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <div className="w-7 h-7 border-2 border-nea-blue-light border-t-nea-blue rounded-full animate-spin" />
            <p className="font-ui text-sm text-nea-muted">Loading digest…</p>
          </div>
        )}

        {digest && (
          <div className="space-y-6 max-w-4xl">
            {/* Stats */}
            <div className="flex flex-wrap gap-2">
              {[
                { label: "Signals", value: digest.stats.total_signals },
                { label: "Companies", value: digest.stats.companies_covered },
                { label: "Portfolio", value: digest.stats.portfolio_signals, blue: true },
                { label: "Competitors", value: digest.stats.competitor_signals },
                { label: "↑ Positive", value: digest.sentiment_rollup.positive, green: true },
                { label: "↓ Negative", value: digest.sentiment_rollup.negative, red: true },
              ].map(({ label, value, blue, green, red }) => (
                <div key={label} className={"flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-ui " + (blue ? "bg-nea-blue-light border-nea-blue/20 text-nea-blue" : green ? "bg-green-50 border-green-200 text-green-700" : red ? "bg-red-50 border-red-200 text-red-700" : "bg-nea-surface border-nea-border text-nea-mid")}>
                  <span className="font-semibold">{value}</span><span>{label}</span>
                </div>
              ))}
            </div>

            {/* Industry tags */}
            {digest.industry_highlights.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {digest.industry_highlights.map(h => (
                  <span key={h.industry} className="font-ui text-xs px-2.5 py-1 rounded-full border border-nea-border bg-white text-nea-mid">
                    {h.industry}: {h.total_signals}
                  </span>
                ))}
              </div>
            )}

            {/* Featured */}
            {digest.featured_articles.length > 0 && (
              <div>
                <p className="font-ui text-[10px] font-semibold text-nea-muted uppercase tracking-widest mb-3">Featured</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {digest.featured_articles.map((a, i) => <FeaturedCard key={i} a={a} />)}
                </div>
              </div>
            )}

            {/* More */}
            {digest.summary_articles.length > 0 && (
              <div>
                <p className="font-ui text-[10px] font-semibold text-nea-muted uppercase tracking-widest mb-3">More Stories</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {digest.summary_articles.map((a, i) => <SummaryCard key={i} a={a} />)}
                </div>
              </div>
            )}

            {!digest.featured_articles.length && !digest.summary_articles.length && (
              <p className="font-ui text-sm text-nea-muted text-center py-16">No stories for the last {days} days. Try refreshing signals.</p>
            )}

            <p className="font-ui text-[10px] text-nea-muted pb-6">
              Generated {new Date(digest.generated_at).toLocaleString()} · {digest.start_date} → {digest.end_date}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
