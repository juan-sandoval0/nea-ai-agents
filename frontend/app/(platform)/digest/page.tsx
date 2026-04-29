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
  news_coverage: "bg-zinc-100 text-zinc-600 border-zinc-200",
};

function sigBadge(type: string) {
  return (SIG_COLOR[type] ?? "bg-zinc-100 text-zinc-600 border-zinc-200") + " border";
}

const sentimentColor = (s?: string | null) =>
  s === "positive" ? "text-green-600" : s === "negative" ? "text-red-500" : "text-zinc-400";
const sentimentIcon = (s?: string | null) =>
  s === "positive" ? "↑" : s === "negative" ? "↓" : "–";

function FeaturedCard({ a }: { a: DigestArticle }) {
  return (
    <div className="bg-white rounded-xl border border-zinc-200 p-4 hover:shadow-md transition-all h-full flex flex-col">
      <div className="flex items-center gap-1.5 mb-3 min-w-0">
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full truncate max-w-[50%] ${
          a.category === "portfolio" ? "bg-nea-blue text-white" : "border border-zinc-200 text-zinc-500"
        }`}>
          {a.company}
        </span>
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0 ${sigBadge(a.signal_type)}`}>
          {SIG_LABEL[a.signal_type] ?? a.signal_type}
        </span>
        <span className={`text-xs ml-auto shrink-0 font-medium ${sentimentColor(a.sentiment)}`}>
          {sentimentIcon(a.sentiment)}
        </span>
      </div>
      {a.url
        ? <a href={a.url} target="_blank" rel="noopener noreferrer"
            className="text-sm font-semibold text-zinc-900 hover:text-nea-blue transition-colors leading-snug block mb-2 line-clamp-3">
            {a.headline}
          </a>
        : <p className="text-sm font-semibold text-zinc-900 leading-snug mb-2 line-clamp-3">{a.headline}</p>
      }
      {a.synopsis && <p className="text-xs text-zinc-500 leading-relaxed line-clamp-2 flex-1">{a.synopsis}</p>}
      <p className="text-[10px] text-zinc-400 mt-auto pt-2">{[a.source, a.published_date].filter(Boolean).join(" · ")}</p>
    </div>
  );
}

function ArticleRow({ a }: { a: DigestArticle }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-zinc-100 last:border-0">
      <div className="w-28 shrink-0 pt-0.5 min-w-0">
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full block truncate max-w-full ${
          a.category === "portfolio" ? "bg-nea-blue-light text-nea-blue" : "text-zinc-400"
        }`}>
          {a.company}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        {a.url
          ? <a href={a.url} target="_blank" rel="noopener noreferrer"
              className="text-sm text-zinc-800 hover:text-nea-blue transition-colors line-clamp-1 block leading-snug">
              {a.headline}
            </a>
          : <p className="text-sm text-zinc-800 line-clamp-1 leading-snug">{a.headline}</p>
        }
        {a.synopsis && <p className="text-[11px] text-zinc-400 mt-0.5 line-clamp-1">{a.synopsis}</p>}
      </div>
      <div className="flex items-center gap-2 shrink-0 pt-0.5">
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${sigBadge(a.signal_type)}`}>
          {SIG_LABEL[a.signal_type] ?? a.signal_type}
        </span>
        <span className="text-[10px] text-zinc-400 w-16 text-right tabular-nums">{a.published_date ?? ""}</span>
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
      <div className="h-14 border-b border-zinc-200 px-6 flex items-center gap-3 bg-white shrink-0">
        <h1 className="text-sm font-semibold text-zinc-900 flex-1">News Digest</h1>
        <div className="flex rounded-lg border border-zinc-200 overflow-hidden">
          {([7, 14, 30] as const).map(d => (
            <button key={d} onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                days === d ? "bg-nea-blue text-white" : "text-zinc-500 hover:bg-zinc-50 bg-white"
              }`}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">

        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-5">{error}</div>
        )}

        {loading && !digest && (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <div className="w-5 h-5 border-2 border-zinc-200 border-t-nea-blue rounded-full animate-spin" />
            <p className="text-sm text-zinc-400">Loading digest…</p>
          </div>
        )}

        {digest && (
          <div className="space-y-7 max-w-4xl">

            {/* Stats row */}
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 pb-5 border-b border-zinc-200">
              <div>
                <span className="text-2xl font-semibold text-zinc-900 tabular-nums">{digest.stats.total_signals}</span>
                <span className="text-xs text-zinc-400 ml-1.5">signals</span>
              </div>
              <div className="w-px h-5 bg-zinc-200 hidden sm:block" />
              <div>
                <span className="text-2xl font-semibold text-zinc-900 tabular-nums">{digest.stats.companies_covered}</span>
                <span className="text-xs text-zinc-400 ml-1.5">companies</span>
              </div>
              <div className="w-px h-5 bg-zinc-200 hidden sm:block" />
              <div>
                <span className="text-sm font-semibold text-nea-blue tabular-nums">{digest.stats.portfolio_signals}</span>
                <span className="text-xs text-zinc-400 ml-1.5">portfolio</span>
              </div>
              <div>
                <span className="text-sm font-semibold text-zinc-500 tabular-nums">{digest.stats.competitor_signals}</span>
                <span className="text-xs text-zinc-400 ml-1.5">competitor</span>
              </div>
              <div className="w-px h-5 bg-zinc-200 hidden sm:block" />
              <div>
                <span className="text-sm font-semibold text-green-600 tabular-nums">↑{digest.sentiment_rollup.positive}</span>
                <span className="text-xs text-zinc-400 ml-1">positive</span>
              </div>
              <div>
                <span className="text-sm font-semibold text-red-500 tabular-nums">↓{digest.sentiment_rollup.negative}</span>
                <span className="text-xs text-zinc-400 ml-1">negative</span>
              </div>
            </div>

            {/* Industry tags */}
            {digest.industry_highlights.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {digest.industry_highlights.map(h => (
                  <span key={h.industry}
                    className="text-[11px] font-medium px-2.5 py-1 rounded-full border border-zinc-200 bg-white text-zinc-500">
                    {h.industry} · {h.total_signals}
                  </span>
                ))}
              </div>
            )}

            {/* Featured articles */}
            {digest.featured_articles.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">Top Stories</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {digest.featured_articles.map((a, i) => <FeaturedCard key={i} a={a} />)}
                </div>
              </div>
            )}

            {/* All stories */}
            {digest.summary_articles.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">All Stories</p>
                <div className="border border-zinc-200 rounded-xl bg-white px-4">
                  {digest.summary_articles.map((a, i) => <ArticleRow key={i} a={a} />)}
                </div>
              </div>
            )}

            {!digest.featured_articles.length && !digest.summary_articles.length && (
              <p className="text-sm text-zinc-400 text-center py-16">
                No stories for the last {days} days.
              </p>
            )}

            <p className="text-[11px] text-zinc-400 pb-6">
              Generated {new Date(digest.generated_at).toLocaleString()} · {digest.start_date} – {digest.end_date}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
