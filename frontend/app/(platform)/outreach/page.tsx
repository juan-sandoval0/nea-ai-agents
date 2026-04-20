"use client";

import { useState, useCallback, useId } from "react";
import { generateOutreach, submitOutreachFeedback, type OutreachResponse } from "@/lib/api";

const INVESTORS = [
  { key: "ashley",   name: "Ashley Jepson",  role: "Investor — Data/AI Infra" },
  { key: "tiffany",  name: "Tiffany",         role: "Investor — B2B SaaS & AI" },
  { key: "danielle", name: "Danielle",        role: "Partner — Consumer" },
  { key: "madison",  name: "Madison",         role: "Partner — Former Meta AI Researcher" },
  { key: "alexa",    name: "Alexa Grabelle",  role: "Associate — Technology" },
  { key: "andrew",   name: "Andrew Schoen",   role: "Partner — AI/Security/Deep Tech" },
  { key: "maanasi",  name: "Maanasi",         role: "Associate — AI Infrastructure" },
];

const CTX_TYPES = [
  { value: "",                              label: "Auto-detect" },
  { value: "thesis_driven_deep_dive",       label: "Thesis-driven deep dive" },
  { value: "problem_solving_discussion",    label: "Problem-solving discussion" },
  { value: "founder_background_connection", label: "Founder background connection" },
  { value: "stealth_founder_outreach",      label: "Stealth founder outreach" },
];

export default function OutreachPage() {
  const fid = useId();
  const [company, setCompany]       = useState("");
  const [investor, setInvestor]     = useState("ashley");
  const [format, setFormat]         = useState<"email" | "linkedin">("email");
  const [contact, setContact]       = useState("");
  const [ctx, setCtx]               = useState("");
  const [advanced, setAdvanced]     = useState(false);
  const [skipIngest, setSkipIngest] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const [result, setResult]         = useState<OutreachResponse | null>(null);
  const [fbMode, setFbMode]         = useState<"idle" | "editing" | "done">("idle");
  const [edited, setEdited]         = useState("");
  const [fbBusy, setFbBusy]         = useState(false);
  const [copied, setCopied]         = useState(false);

  const handleGenerate = useCallback(async () => {
    const t = company.trim(); if (!t) return;
    setLoading(true); setError(null); setResult(null); setFbMode("idle");
    try {
      const r = await generateOutreach({
        company_id: t,
        investor_key: investor,
        output_format: format,
        contact_name: contact.trim() || undefined,
        context_type_override: ctx || undefined,
        skip_ingest: skipIngest,
      });
      setResult(r); setEdited(r.message ?? "");
    } catch (e) { setError(e instanceof Error ? e.message : "Generation failed"); }
    finally { setLoading(false); }
  }, [company, investor, format, contact, ctx, skipIngest]);

  const handleFeedback = useCallback(async (status: "approved" | "edited" | "rejected") => {
    if (!result) return;
    setFbBusy(true);
    try {
      await submitOutreachFeedback({
        outreach_id: result.company_id + "_" + result.investor_key + "_" + Date.now(),
        investor_key: result.investor_key,
        company_id: result.company_id,
        context_type: result.context_type ?? undefined,
        original_message: result.message ?? "",
        edited_message: status === "edited" ? edited : undefined,
        approval_status: status,
      });
      setFbMode("done");
    } catch (e) { setError(e instanceof Error ? e.message : "Feedback failed"); }
    finally { setFbBusy(false); }
  }, [result, edited]);

  const copyEmail = useCallback(() => {
    const txt = result?.subject ? "Subject: " + result.subject + "\n\n" + result.message : result?.message ?? "";
    navigator.clipboard.writeText(txt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [result]);

  const selInv = INVESTORS.find(i => i.key === investor);

  return (
    <div className="flex h-full">
      {/* Config panel */}
      <div className="w-68 shrink-0 border-r border-nea-border bg-nea-surface overflow-y-auto flex flex-col" style={{ width: "17rem" }}>
        <div className="h-12 px-5 border-b border-nea-border bg-white flex items-center shrink-0">
          <h1 className="font-ui text-sm font-semibold text-nea-dark">Outreach</h1>
        </div>

        <div className="flex-1 px-4 py-4 space-y-4">
          <div>
            <label htmlFor={fid + "-co"} className="font-ui block text-xs font-semibold text-nea-dark mb-1.5">
              Company Domain
            </label>
            <input
              id={fid + "-co"}
              type="text"
              placeholder="distyl.ai"
              value={company}
              onChange={e => setCompany(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleGenerate()}
              className="font-ui w-full px-3 py-2 rounded-md border border-nea-border text-sm text-nea-dark placeholder:text-nea-muted focus:outline-none focus:ring-2 focus:ring-nea-blue/20 focus:border-nea-blue bg-white"
            />
          </div>

          <div>
            <label htmlFor={fid + "-inv"} className="font-ui block text-xs font-semibold text-nea-dark mb-1.5">
              Investor Voice
            </label>
            <select
              id={fid + "-inv"}
              value={investor}
              onChange={e => setInvestor(e.target.value)}
              className="font-ui w-full px-3 py-2 rounded-md border border-nea-border text-sm text-nea-dark bg-white focus:outline-none focus:ring-2 focus:ring-nea-blue/20 focus:border-nea-blue"
            >
              {INVESTORS.map(inv => <option key={inv.key} value={inv.key}>{inv.name}</option>)}
            </select>
            {selInv && <p className="font-ui text-[11px] text-nea-muted mt-1">{selInv.role}</p>}
          </div>

          <div>
            <label className="font-ui block text-xs font-semibold text-nea-dark mb-1.5">Format</label>
            <div className="flex rounded-md border border-nea-border overflow-hidden">
              {(["email", "linkedin"] as const).map(f => (
                <button key={f} onClick={() => setFormat(f)}
                  className={"flex-1 py-1.5 font-ui text-sm font-medium transition-colors " + (format === f ? "bg-nea-blue text-white" : "text-nea-mid hover:bg-nea-surface bg-white")}>
                  {f === "email" ? "Email" : "LinkedIn"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <button
              onClick={() => setAdvanced(v => !v)}
              className="font-ui flex items-center gap-1 text-xs text-nea-mid hover:text-nea-blue transition-colors"
            >
              <svg className={"w-3 h-3 transition-transform " + (advanced ? "rotate-90" : "")} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              Advanced options
            </button>
            {advanced && (
              <div className="mt-3 space-y-3 pl-3 border-l-2 border-nea-border">
                <div>
                  <label className="font-ui block text-xs font-medium text-nea-mid mb-1">Contact Name</label>
                  <input
                    type="text"
                    placeholder="Patrick Collison"
                    value={contact}
                    onChange={e => setContact(e.target.value)}
                    className="font-ui w-full px-3 py-1.5 rounded-md border border-nea-border text-sm text-nea-dark placeholder:text-nea-muted focus:outline-none focus:ring-2 focus:ring-nea-blue/20 bg-white"
                  />
                </div>
                <div>
                  <label className="font-ui block text-xs font-medium text-nea-mid mb-1">Context Type</label>
                  <select
                    value={ctx}
                    onChange={e => setCtx(e.target.value)}
                    className="font-ui w-full px-3 py-1.5 rounded-md border border-nea-border text-sm text-nea-dark bg-white focus:outline-none focus:ring-2 focus:ring-nea-blue/20"
                  >
                    {CTX_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                </div>
                <label className="font-ui flex items-center gap-2 cursor-pointer text-xs text-nea-mid">
                  <input type="checkbox" checked={skipIngest} onChange={e => setSkipIngest(e.target.checked)} className="rounded border-nea-border" />
                  Use cached company data
                </label>
              </div>
            )}
          </div>

          <button
            onClick={handleGenerate}
            disabled={loading || !company.trim()}
            className="font-ui w-full py-2 rounded-md bg-nea-blue text-white text-sm font-semibold hover:bg-nea-blue-dark disabled:opacity-40 transition-colors"
          >
            {loading ? "Generating…" : "Run Outreach"}
          </button>
        </div>
      </div>

      {/* Result panel */}
      <div className="flex-1 overflow-y-auto px-7 py-6">
        {!result && !loading && !error && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-center">
            <div className="w-8 h-8 rounded-lg bg-nea-surface border border-nea-border flex items-center justify-center mb-1">
              <svg className="w-4 h-4 text-nea-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <p className="font-ui text-sm text-nea-muted">Enter a company domain and click Run Outreach</p>
          </div>
        )}

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-5 font-ui">{error}</div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <div className="w-6 h-6 border-2 border-nea-blue-light border-t-nea-blue rounded-full animate-spin" />
            <p className="font-ui text-sm text-nea-muted">Generating outreach — about 20 seconds</p>
          </div>
        )}

        {result && !loading && (
          <div className="max-w-2xl">
            {/* Result meta */}
            <div className="flex items-center gap-2 mb-4 flex-wrap">
              <span className="font-ui text-lg font-semibold text-nea-dark">{result.company_name}</span>
              <span className="font-ui text-xs px-2 py-0.5 rounded bg-nea-blue text-white">{selInv?.name ?? result.investor_key}</span>
              {result.context_type && (
                <span className="font-ui text-xs px-2 py-0.5 rounded border border-nea-border text-nea-muted">
                  {result.context_type.replace(/_/g, " ")}
                </span>
              )}
              {result.contact_name && (
                <div className="ml-auto flex items-center gap-1.5 font-ui text-xs text-nea-muted">
                  To: {result.contact_name}{result.contact_title ? ` (${result.contact_title})` : ""}
                  {result.contact_linkedin && (
                    <a href={result.contact_linkedin} target="_blank" rel="noopener noreferrer" className="text-nea-muted hover:text-nea-blue">
                      <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
                      </svg>
                    </a>
                  )}
                </div>
              )}
            </div>

            {/* Message card */}
            <div className="bg-white rounded-lg border border-nea-border overflow-hidden mb-4">
              {result.subject && (
                <div className="px-5 py-2.5 border-b border-nea-border bg-nea-surface flex items-baseline gap-2">
                  <span className="font-ui text-[11px] font-semibold text-nea-muted uppercase tracking-wide shrink-0">Subject</span>
                  <span className="font-ui text-sm font-semibold text-nea-dark">{result.subject}</span>
                </div>
              )}
              {fbMode === "editing"
                ? <textarea
                    value={edited}
                    onChange={e => setEdited(e.target.value)}
                    className="font-ui w-full px-5 py-4 text-sm text-nea-dark leading-relaxed focus:outline-none resize-none"
                    rows={18}
                  />
                : <div className="font-ui px-5 py-4 text-sm text-nea-dark leading-relaxed whitespace-pre-wrap">{result.message}</div>
              }
            </div>

            {/* Actions */}
            {fbMode === "done" ? (
              <div className="flex items-center gap-2 font-ui text-sm text-green-700">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Feedback saved
              </div>
            ) : (
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={copyEmail}
                  className="font-ui flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-nea-border text-xs text-nea-mid hover:border-nea-blue hover:text-nea-blue transition-colors"
                >
                  {copied ? "✓ Copied" : "Copy"}
                </button>
                <div className="flex items-center gap-1.5 ml-auto">
                  {fbMode === "editing" ? (
                    <>
                      <button onClick={() => setFbMode("idle")} className="font-ui px-3 py-1.5 rounded-md border border-nea-border text-xs text-nea-mid hover:bg-nea-surface transition-colors">
                        Cancel
                      </button>
                      <button onClick={() => handleFeedback("edited")} disabled={fbBusy} className="font-ui px-4 py-1.5 rounded-md bg-nea-blue text-white text-xs font-semibold hover:bg-nea-blue-dark disabled:opacity-40 transition-colors">
                        {fbBusy ? "Saving…" : "Save Edit"}
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => setFbMode("editing")} className="font-ui px-3 py-1.5 rounded-md border border-nea-border text-xs text-nea-mid hover:bg-nea-surface transition-colors">
                        Edit
                      </button>
                      <button onClick={() => handleFeedback("approved")} disabled={fbBusy} className="font-ui px-3 py-1.5 rounded-md bg-green-50 text-green-700 border border-green-200 text-xs font-semibold hover:bg-green-100 disabled:opacity-40 transition-colors">
                        Approve
                      </button>
                      <button onClick={() => handleFeedback("rejected")} disabled={fbBusy} className="font-ui px-3 py-1.5 rounded-md bg-red-50 text-red-700 border border-red-200 text-xs font-semibold hover:bg-red-100 disabled:opacity-40 transition-colors">
                        Reject
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
