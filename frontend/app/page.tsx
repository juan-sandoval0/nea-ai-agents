import Image from "next/image";
import Link from "next/link";

const workflows = [
  {
    href: "/briefing",
    label: "Meeting Briefing",
    description: "Company intelligence for investor meetings — founders, signals, news, and competitive landscape.",
    timing: "~30 sec per company",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0121 9.414V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    href: "/digest",
    label: "News Digest",
    description: "Ranked signals across portfolio and competitors — funding, hires, launches, and M&A.",
    timing: "Last 7, 14, or 30 days",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
      </svg>
    ),
  },
  {
    href: "/outreach",
    label: "Outreach",
    description: "Personalized cold outreach in each investor's voice, grounded in real company data.",
    timing: "~20 sec per message",
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
  },
];

export default function HomePage() {
  return (
    <div className="min-h-screen bg-nea-shell flex flex-col">
      <header className="h-12 bg-white border-b border-nea-border px-6 flex items-center gap-3 shrink-0">
        <Image
          src="/nea-logo.png"
          alt="NEA"
          width={40}
          height={16}
          priority
          className="select-none"
          style={{ filter: "brightness(0) saturate(100%) invert(25%) sepia(60%) saturate(700%) hue-rotate(180deg) brightness(80%)" }}
        />
        <div className="w-px h-4 bg-nea-border" />
        <span className="font-ui text-xs font-medium text-nea-muted">AI Platform</span>
      </header>

      <main className="flex-1 flex items-start justify-center px-6 pt-16 pb-10">
        <div className="w-full max-w-xl">
          <div className="mb-7">
            <h1 className="font-ui text-lg font-semibold text-nea-dark mb-1">Venture Intelligence</h1>
            <p className="font-ui text-sm text-nea-muted">Three workflows for deal-flow and portfolio operations.</p>
          </div>

          <div className="bg-white rounded-lg border border-nea-border overflow-hidden">
            {workflows.map((w, i) => (
              <Link
                key={w.href}
                href={w.href}
                className={`flex items-center gap-4 px-5 py-4 hover:bg-nea-surface transition-colors group ${
                  i < workflows.length - 1 ? "border-b border-nea-border" : ""
                }`}
              >
                <div className="w-8 h-8 rounded bg-nea-blue-light text-nea-blue flex items-center justify-center shrink-0 group-hover:bg-nea-blue group-hover:text-white transition-colors">
                  {w.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-ui text-sm font-semibold text-nea-dark">{w.label}</div>
                  <div className="font-ui text-xs text-nea-muted mt-0.5">{w.description}</div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="font-ui text-[11px] text-nea-muted hidden sm:block">{w.timing}</span>
                  <svg className="w-4 h-4 text-nea-muted group-hover:text-nea-blue transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </main>

      <footer className="shrink-0 px-6 py-4 border-t border-nea-border bg-white">
        <div className="max-w-xl mx-auto flex items-center justify-between">
          <span className="font-ui text-xs text-nea-muted">New Enterprise Associates</span>
          <span className="font-ui text-xs text-nea-muted">Internal use only</span>
        </div>
      </footer>
    </div>
  );
}
