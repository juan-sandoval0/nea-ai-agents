"use client";

import { useState, useCallback, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { getWeeklyDigest, type WeeklyDigestResponse, type DigestArticle } from "@/lib/api";

const SIG_LABEL: Record<string, string> = {
  funding: "Funding", FUNDING: "Funding",
  acquisition: "M&A", M_A: "M&A",
  product_launch: "Product", PRODUCT: "Product",
  executive_change: "Leadership",
  hiring_expansion: "Hiring",
  partnership: "Partnership", PARTNERSHIP: "Partnership",
  EARNINGS: "Earnings",
  news_coverage: "Coverage",
};

// 4 semantic colors: green=financial, amber=material change, blue=growth, slate=noise
const SIG_COLOR: Record<string, string> = {
  funding: "bg-green-50 text-green-700 border-green-200",
  FUNDING: "bg-green-50 text-green-700 border-green-200",
  EARNINGS: "bg-green-50 text-green-700 border-green-200",
  acquisition: "bg-amber-50 text-amber-700 border-amber-200",
  M_A: "bg-amber-50 text-amber-700 border-amber-200",
  executive_change: "bg-amber-50 text-amber-700 border-amber-200",
  partnership: "bg-amber-50 text-amber-700 border-amber-200",
  PARTNERSHIP: "bg-amber-50 text-amber-700 border-amber-200",
  product_launch: "bg-blue-50 text-blue-700 border-blue-200",
  PRODUCT: "bg-blue-50 text-blue-700 border-blue-200",
  hiring_expansion: "bg-blue-50 text-blue-700 border-blue-200",
  news_coverage: "bg-slate-50 text-slate-600 border-slate-200",
};

function sigBadge(type: string) {
  return (SIG_COLOR[type] ?? "bg-slate-50 text-slate-600 border-slate-200") + " border";
}

const sentimentColor = (s?: string | null) =>
  s === "positive" ? "text-green-600" : s === "negative" ? "text-red-500" : "text-nea-muted";
const sentimentIcon = (s?: string | null) =>
  s === "positive" ? "↑" : s === "negative" ? "↓" : "–";

function FeaturedCard({ a }: { a: DigestArticle }) {
  return (
    <div className="bg-white rounded-lg border border-nea-border p-4 hover:border-nea-blue/40 transition-colors">
      <div className="flex items-center gap-1.5 mb-2.5">
        <span className={"font-ui text-[10px] font-semibold px-1.5 py-0.5 rounded " + (a.category === "portfolio" ? "bg-nea-blue text-white" : "border border-nea-border text-nea-mid")}>
          {a.company}
        </span>
        <span className={"font-ui text-[10px] font-semibold px-1.5 py-0.5 rounded " + sigBadge(a.signal_type)}>
          {SIG_LABEL[a.signal_type] ?? a.signal_type}
        </span>
        <span className={"font-ui text-xs ml-auto " + sentimentColor(a.sentiment)}>{sentimentIcon(a.sentiment)}</span>
      </div>
      {a.url
        ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="font-ui text-sm font-semibold text-nea-dark hover:text-nea-blue hover:underline leading-snug block mb-1.5">{a.headline}</a>
        : <p className="font-ui text-sm font-semibold text-nea-dark leading-snug mb-1.5">{a.headline}</p>
      }
      {a.synopsis && <p className="font-ui text-xs text-nea-mid leading-relaxed">{a.synopsis}</p>}
      <p className="font-ui text-[10px] text-nea-muted mt-2">{[a.source, a.published_date].filter(Boolean).join(" · ")}</p>
    </div>
  );
}

function ArticleRow({ a }: { a: DigestArticle }) {
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-nea-border last:border-0">
      <div className="w-28 shrink-0 pt-0.5">
        <span className={`font-ui text-[10px] font-semibold px-1.5 py-0.5 rounded ${
          a.category === "portfolio" ? "bg-nea-blue-light text-nea-blue" : "text-nea-muted"
        }`}>
          {a.company}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        {a.url
          ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="font-ui text-sm text-nea-dark hover:text-nea-blue hover:underline line-clamp-1 block leading-snug">{a.headline}</a>
          : <p className="font-ui text-sm text-nea-dark line-clamp-1 leading-snug">{a.headline}</p>
        }
        {a.synopsis && <p className="font-ui text-[11px] text-nea-muted mt-0.5 line-clamp-1">{a.synopsis}</p>}
      </div>
      <div className="flex items-center gap-2 shrink-0 pt-0.5">
        <span className={"font-ui text-[10px] font-semibold px-1.5 py-0.5 rounded " + sigBadge(a.signal_type)}>
          {SIG_LABEL[a.signal_type] ?? a.signal_type}
        </span>
        <span className="font-ui text-[10px] text-nea-muted w-14 text-right tabular-nums">{a.published_date ?? ""}</span>
      </div>
    </div>
  );
}

export default function DigestPage() {
  const { getToken } = useAuth();
  const [days, setDays] = useState<7 | 14 | 30>(7);
  const [digest, setDigest] = useState<WeeklyDigestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDigest = useCallback(async (d: number) => {
    setLoading(true); setError(null);
    try { setDigest(await getWeeklyDigest(d, 3, 12, getToken)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
    finally { setLoading(false); }
  }, [getToken]);

  useEffect(() => { loadDigest(days); }, [days, loadDigest]);

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="h-12 border-b border-nea-border px-5 flex items-center gap-3 bg-white shrink-0">
        <h1 className="font-ui text-sm font-semibold text-nea-dark">News Digest</h1>
        <div className="ml-auto flex items-center gap-2">
          {/* Day range toggle */}
          <div className="flex rounded-md border border-nea-border overflow-hidden">
            {([7, 14, 30] as const).map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={"font-ui px-2.5 py-1 text-xs font-medium transition-colors " + (days === d ? "bg-nea-blue text-white" : "text-nea-mid hover:bg-nea-surface bg-white")}>
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4 font-ui">{error}</div>
        )}

        {loading && !digest && (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <div className="w-6 h-6 border-2 border-nea-blue-light border-t-nea-blue rounded-full animate-spin" />
            <p className="font-ui text-sm text-nea-muted">Loading digest…</p>
          </div>
        )}

        {digest && (
          <div className="space-y-6 max-w-4xl">
            {/* Stats row */}
            <div className="flex items-center gap-5 pb-4 border-b border-nea-border">
              <div>
                <span className="font-ui text-xl font-semibold text-nea-dark tabular-nums">{digest.stats.total_signals}</span>
                <span className="font-ui text-xs text-nea-muted ml-1.5">signals</span>
              </div>
              <div className="w-px h-5 bg-nea-border" />
              <div>
                <span className="font-ui text-xl font-semibold text-nea-dark tabular-nums">{digest.stats.companies_covered}</span>
                <span className="font-ui text-xs text-nea-muted ml-1.5">companies</span>
              </div>
              <div className="w-px h-5 bg-nea-border" />
              <div>
                <span className="font-ui text-sm font-semibold text-nea-blue tabular-nums">{digest.stats.portfolio_signals}</span>
                <span className="font-ui text-xs text-nea-muted ml-1.5">portfolio</span>
              </div>
              <div>
                <span className="font-ui text-sm font-semibold text-nea-mid tabular-nums">{digest.stats.competitor_signals}</span>
                <span className="font-ui text-xs text-nea-muted ml-1.5">competitor</span>
              </div>
              <div className="w-px h-5 bg-nea-border" />
              <div>
                <span className="font-ui text-sm font-semibold text-green-600 tabular-nums">↑{digest.sentiment_rollup.positive}</span>
                <span className="font-ui text-xs text-nea-muted ml-1">positive</span>
              </div>
              <div>
                <span className="font-ui text-sm font-semibold text-red-500 tabular-nums">↓{digest.sentiment_rollup.negative}</span>
                <span className="font-ui text-xs text-nea-muted ml-1">negative</span>
              </div>
            </div>

            {/* Industry tags */}
            {digest.industry_highlights.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {digest.industry_highlights.map(h => (
                  <span key={h.industry} className="font-ui text-[11px] px-2 py-0.5 rounded border border-nea-border bg-white text-nea-mid">
                    {h.industry} · {h.total_signals}
                  </span>
                ))}
              </div>
            )}

            {/* Featured articles */}
            {digest.featured_articles.length > 0 && (
              <div>
                <p className="font-ui text-[10px] font-semibold text-nea-muted uppercase tracking-widest mb-3">Top Stories</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {digest.featured_articles.map((a, i) => <FeaturedCard key={i} a={a} />)}
                </div>
              </div>
            )}

            {/* All other stories as compact list */}
            {digest.summary_articles.length > 0 && (
              <div>
                <p className="font-ui text-[10px] font-semibold text-nea-muted uppercase tracking-widest mb-2">All Stories</p>
                <div className="border border-nea-border rounded-lg overflow-hidden bg-white px-4">
                  {digest.summary_articles.map((a, i) => <ArticleRow key={i} a={a} />)}
                </div>
              </div>
            )}

            {!digest.featured_articles.length && !digest.summary_articles.length && (
              <p className="font-ui text-sm text-nea-muted text-center py-16">
                No stories for the last {days} days. Try refreshing signals.
              </p>
            )}

            <p className="font-ui text-[10px] text-nea-muted pb-6">
              Generated {new Date(digest.generated_at).toLocaleString()} · {digest.start_date} – {digest.end_date}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
