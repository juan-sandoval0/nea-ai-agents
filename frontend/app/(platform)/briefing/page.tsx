"use client";

import { useState, useCallback } from "react";
import {
  generateBriefing, listBriefings, getBriefing,
  type BriefingResponse, type BriefingListItem,
} from "@/lib/api";

// 4 semantic signal colors: green=financial, amber=material change, blue=growth, slate=noise
const SIGNAL_CONFIG: Record<string, { label: string; cls: string }> = {
  funding:          { label: "Funding",   cls: "bg-green-50 text-green-700 border-green-200" },
  acquisition:      { label: "M&A",       cls: "bg-amber-50 text-amber-700 border-amber-200" },
  team_change:      { label: "Team",      cls: "bg-amber-50 text-amber-700 border-amber-200" },
  product_launch:   { label: "Product",   cls: "bg-blue-50 text-blue-700 border-blue-200" },
  hiring_expansion: { label: "Hiring",    cls: "bg-blue-50 text-blue-700 border-blue-200" },
  web_traffic:      { label: "Traffic",   cls: "bg-slate-50 text-slate-600 border-slate-200" },
  website_update:   { label: "Website",   cls: "bg-slate-50 text-slate-600 border-slate-200" },
  website_product:  { label: "Product",   cls: "bg-blue-50 text-blue-700 border-blue-200" },
  website_pricing:  { label: "Pricing",   cls: "bg-amber-50 text-amber-700 border-amber-200" },
  website_team:     { label: "Team",      cls: "bg-amber-50 text-amber-700 border-amber-200" },
  website_news:     { label: "Coverage",  cls: "bg-slate-50 text-slate-600 border-slate-200" },
};

function signalCls(t: string) {
  return (SIGNAL_CONFIG[t]?.cls ?? "bg-slate-50 text-slate-600 border-slate-200") + " border";
}
function signalLabel(t: string) {
  return SIGNAL_CONFIG[t]?.label ?? t.replace(/_/g, " ");
}

function Section({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-nea-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-nea-surface hover:bg-nea-blue-light transition-colors text-left"
      >
        <span className="font-ui font-semibold text-[11px] text-nea-dark uppercase tracking-wider">{title}</span>
        <svg
          className={"w-3 h-3 text-nea-muted transition-transform " + (open ? "rotate-180" : "")}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && <div className="px-4 py-3.5 bg-white border-t border-nea-border">{children}</div>}
    </div>
  );
}

export default function BriefingPage() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BriefingResponse | null>(null);
  const [history, setHistory] = useState<BriefingListItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleGenerate = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    setLoading(true); setError(null); setResult(null);
    try { setResult(await generateBriefing(trimmed)); }
    catch (e) { setError(e instanceof Error ? e.message : "Generation failed"); }
    finally { setLoading(false); }
  }, [url]);

  const openHistory = useCallback(async () => {
    setHistoryOpen(v => !v);
    if (!historyOpen) {
      try { const { briefings } = await listBriefings(undefined, 10); setHistory(briefings); }
      catch { /* silent */ }
    }
  }, [historyOpen]);

  const loadHistoryItem = useCallback(async (id: string) => {
    setLoading(true); setHistoryOpen(false);
    try { setResult(await getBriefing(id)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
    finally { setLoading(false); }
  }, []);

  const copyMarkdown = useCallback(() => {
    if (result?.markdown) {
      navigator.clipboard.writeText(result.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [result]);

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Page header */}
        <div className="h-12 border-b border-nea-border px-5 flex items-center gap-3 bg-white shrink-0">
          <div className="flex-1 min-w-0">
            <h1 className="font-ui text-sm font-semibold text-nea-dark leading-none">Meeting Briefing</h1>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="stripe.com"
              value={url}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleGenerate()}
              className="font-ui w-48 px-3 py-1.5 rounded-md border border-nea-border text-sm text-nea-dark placeholder:text-nea-muted focus:outline-none focus:ring-2 focus:ring-nea-blue/20 focus:border-nea-blue bg-white"
            />
            <button
              onClick={handleGenerate}
              disabled={loading || !url.trim()}
              className="font-ui px-3.5 py-1.5 rounded-md bg-nea-blue text-white text-sm font-medium hover:bg-nea-blue-dark disabled:opacity-40 transition-colors"
            >
              {loading ? "Running…" : "Run Briefing"}
            </button>
            <button
              onClick={openHistory}
              title="Recent briefings"
              className={"p-1.5 rounded-md border transition-colors " + (historyOpen ? "border-nea-blue bg-nea-blue-light text-nea-blue" : "border-nea-border hover:bg-nea-surface text-nea-muted")}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4 font-ui">{error}</div>
          )}

          {loading && (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <div className="w-6 h-6 border-2 border-nea-blue-light border-t-nea-blue rounded-full animate-spin" />
              <p className="font-ui text-sm text-nea-muted">Generating briefing — about 30 seconds</p>
            </div>
          )}

          {!result && !loading && !error && (
            <div className="flex flex-col items-center justify-center py-20 gap-2 text-center">
              <div className="w-8 h-8 rounded-lg bg-nea-surface border border-nea-border flex items-center justify-center mb-1">
                <svg className="w-4 h-4 text-nea-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0121 9.414V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <p className="font-ui text-sm text-nea-muted">Enter a company domain above to generate a briefing</p>
              <p className="font-ui text-xs text-nea-muted opacity-70">e.g. stripe.com, notion.so, distyl.ai</p>
            </div>
          )}

          {result && !loading && (
            <div className="space-y-3 max-w-3xl">
              {/* Result header */}
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h2 className="font-ui text-xl font-semibold text-nea-dark leading-tight">{result.company_name}</h2>
                  {result.company_snapshot?.hq && (
                    <p className="font-ui text-xs text-nea-muted mt-0.5">{result.company_snapshot.hq}</p>
                  )}
                </div>
                <button
                  onClick={copyMarkdown}
                  className="font-ui flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-nea-border text-xs text-nea-mid hover:border-nea-blue hover:text-nea-blue transition-colors"
                >
                  {copied ? "✓ Copied" : "Copy Markdown"}
                </button>
              </div>

              {result.tldr && (
                <Section title="TL;DR">
                  <p className="font-ui text-sm text-nea-dark leading-relaxed">{result.tldr}</p>
                </Section>
              )}

              {result.why_it_matters && result.why_it_matters.length > 0 && (
                <Section title="Why This Meeting Matters">
                  <ul className="space-y-1.5">
                    {result.why_it_matters.map((p, i) => (
                      <li key={i} className="flex gap-2 text-sm font-ui text-nea-dark">
                        <span className="text-nea-blue shrink-0 mt-0.5">·</span>
                        <span className="leading-relaxed">{p}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              <div className="grid grid-cols-2 gap-3">
                {result.company_snapshot && (
                  <div className="border border-nea-border rounded-lg overflow-hidden">
                    <div className="px-4 py-2 bg-nea-surface border-b border-nea-border">
                      <span className="font-ui font-semibold text-[11px] text-nea-dark uppercase tracking-wider">Company Snapshot</span>
                    </div>
                    <table className="w-full text-sm bg-white">
                      <tbody className="divide-y divide-nea-border">
                        {([
                          ["Founded", result.company_snapshot.founded],
                          ["HQ", result.company_snapshot.hq],
                          ["Employees", result.company_snapshot.employees?.toLocaleString()],
                          ["Products", result.company_snapshot.products],
                          ["Customers", result.company_snapshot.customers],
                          ["Total Raised", result.company_snapshot.total_funding ? "$" + (result.company_snapshot.total_funding / 1_000_000).toFixed(1) + "M" : null],
                          ["Last Round", result.company_snapshot.last_round],
                        ] as [string, string | null | undefined][]).filter(([, v]) => v).map(([label, value]) => (
                          <tr key={label}>
                            <td className="py-2 px-4 text-nea-muted font-ui font-medium w-28 text-xs">{label}</td>
                            <td className="py-2 px-4 text-nea-dark font-ui text-xs">{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {result.founders.length > 0 && (
                  <div className="border border-nea-border rounded-lg overflow-hidden">
                    <div className="px-4 py-2 bg-nea-surface border-b border-nea-border">
                      <span className="font-ui font-semibold text-[11px] text-nea-dark uppercase tracking-wider">Founders</span>
                    </div>
                    <div className="p-4 space-y-3 bg-white">
                      {result.founders.map((f, i) => (
                        <div key={i} className="flex gap-2.5">
                          <div className="w-6 h-6 rounded bg-nea-blue-light text-nea-blue flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">
                            {f.name[0]}
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="font-ui text-xs font-semibold text-nea-dark">{f.name}</span>
                              {f.role && <span className="font-ui text-[11px] text-nea-muted">{f.role}</span>}
                              {f.linkedin_url && (
                                <a href={f.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-nea-muted hover:text-nea-blue transition-colors">
                                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                                    <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
                                  </svg>
                                </a>
                              )}
                            </div>
                            {f.background && (
                              <p className="font-ui text-[11px] text-nea-muted mt-0.5 leading-relaxed line-clamp-2">{f.background}</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {result.signals.length > 0 && (
                <Section title="Key Signals">
                  <div className="space-y-2">
                    {result.signals.map((s, i) => (
                      <div key={i} className="flex gap-2.5 items-start">
                        <span className={"inline-flex shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold font-ui mt-0.5 " + signalCls(s.signal_type)}>
                          {signalLabel(s.signal_type)}
                        </span>
                        <span className="font-ui text-xs text-nea-dark leading-relaxed">{s.description}</span>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {result.news.length > 0 && (
                <Section title="In the News">
                  <div className="space-y-0 divide-y divide-nea-border">
                    {result.news.map((n, i) => (
                      <div key={i} className="py-2.5 first:pt-0 last:pb-0">
                        {n.url
                          ? <a href={n.url} target="_blank" rel="noopener noreferrer" className="font-ui text-sm font-medium text-nea-dark hover:text-nea-blue hover:underline leading-snug block">{n.headline}</a>
                          : <span className="font-ui text-sm font-medium text-nea-dark leading-snug block">{n.headline}</span>
                        }
                        <p className="font-ui text-[11px] text-nea-muted mt-0.5">{[n.outlet, n.published_date].filter(Boolean).join(" · ")}</p>
                        {(n.takeaway || n.synopsis) && (
                          <p className="font-ui text-xs text-nea-mid mt-1 leading-relaxed">{n.takeaway || n.synopsis}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {result.competitors.length > 0 && (
                <Section title="Competitive Landscape" defaultOpen={false}>
                  {(["startup", "incumbent"] as const).map(type => {
                    const group = result.competitors.filter(c => c.competitor_type === type);
                    if (!group.length) return null;
                    return (
                      <div key={type} className="mb-3 last:mb-0">
                        <p className="font-ui text-[10px] font-semibold text-nea-muted uppercase tracking-wide mb-2">
                          {type === "startup" ? "Startups" : "Incumbents"}
                        </p>
                        <div className="space-y-1.5">
                          {group.map((c, i) => (
                            <div key={i} className="flex gap-2 items-center">
                              <span className="font-ui text-sm font-medium text-nea-dark">{c.name}</span>
                              {c.funding_stage && (
                                <span className="font-ui text-[10px] text-nea-muted border border-nea-border rounded px-1.5 py-0.5">{c.funding_stage}</span>
                              )}
                              {c.funding_total && (
                                <span className="font-ui text-[11px] text-nea-muted">${(c.funding_total / 1_000_000).toFixed(0)}M raised</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </Section>
              )}

              {result.meeting_prep && (
                <Section title="For This Meeting" defaultOpen={false}>
                  <div className="font-ui text-sm text-nea-dark leading-relaxed whitespace-pre-wrap">{result.meeting_prep}</div>
                </Section>
              )}
            </div>
          )}
        </div>
      </div>

      {/* History panel */}
      {historyOpen && (
        <div className="w-56 shrink-0 border-l border-nea-border bg-nea-surface overflow-y-auto flex flex-col">
          <div className="px-4 py-2.5 border-b border-nea-border bg-white shrink-0">
            <h3 className="font-ui text-[11px] font-semibold text-nea-dark uppercase tracking-wider">Recent Briefings</h3>
          </div>
          <div className="p-1.5 flex-1">
            {history.length === 0
              ? <p className="font-ui text-xs text-nea-muted px-3 py-2">No briefings yet.</p>
              : history.map(b => (
                <button key={b.id} onClick={() => loadHistoryItem(b.id)}
                  className="w-full text-left px-3 py-2 rounded-md hover:bg-nea-blue-light transition-colors"
                >
                  <p className="font-ui text-sm font-medium text-nea-dark truncate">{b.company_name}</p>
                  <p className="font-ui text-[11px] text-nea-muted mt-0.5">{new Date(b.created_at).toLocaleDateString()}</p>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
