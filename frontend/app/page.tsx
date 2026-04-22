import Image from "next/image";
import Link from "next/link";

const workflows = [
  {
    href: "/briefing",
    label: "Meeting Briefing",
    description: "Company intelligence for investor meetings.",
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
    description: "Ranked signals across portfolio and competitors.",
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
    description: "Personalized cold outreach in each investor's voice.",
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
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-12">
        <div className="animate-logo-in">
          <Image
            src="/nea-logo.png"
            alt="NEA"
            width={220}
            height={88}
            priority
            className="select-none animate-logo-float"
            style={{ filter: "brightness(0) saturate(100%) invert(25%) sepia(60%) saturate(700%) hue-rotate(180deg) brightness(80%)" }}
          />
        </div>
        <h1
          className="font-ui text-xl font-medium text-nea-dark mt-8 animate-fade-up"
          style={{ animationDelay: "300ms" }}
        >
          How can I help?
        </h1>
      </main>

      <div
        className="px-6 pb-10 animate-fade-up"
        style={{ animationDelay: "550ms" }}
      >
        <div className="max-w-4xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-3">
          {workflows.map((w) => (
            <Link
              key={w.href}
              href={w.href}
              className="bg-white rounded-lg border border-nea-border p-4 hover:border-nea-blue/40 hover:shadow-sm transition-all group flex flex-col gap-2"
            >
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded bg-nea-blue-light text-nea-blue flex items-center justify-center shrink-0 group-hover:bg-nea-blue group-hover:text-white transition-colors">
                  {w.icon}
                </div>
                <span className="font-ui text-sm font-semibold text-nea-dark">{w.label}</span>
              </div>
              <p className="font-ui text-xs text-nea-muted leading-relaxed">{w.description}</p>
            </Link>
          ))}
        </div>
      </div>

      <footer className="shrink-0 px-6 py-4 border-t border-nea-border bg-white">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <span className="font-ui text-xs text-nea-muted">New Enterprise Associates</span>
          <span className="font-ui text-xs text-nea-muted">Internal use only</span>
        </div>
      </footer>
    </div>
  );
}
