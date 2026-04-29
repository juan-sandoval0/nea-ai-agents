import Image from "next/image";
import Link from "next/link";

const NEA_FILTER = "brightness(0) saturate(100%) invert(25%) sepia(60%) saturate(700%) hue-rotate(180deg) brightness(80%)";

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
    <div className="min-h-screen bg-zinc-50 flex flex-col">
      <main className="flex-1 flex flex-col items-center justify-center px-6">
        <div className="w-full max-w-sm">

          {/* Logo */}
          <div className="flex justify-center mb-8 animate-logo-in">
            <Image
              src="/nea-logo.png"
              alt="NEA"
              width={160}
              height={64}
              priority
              className="select-none"
              style={{ filter: NEA_FILTER }}
            />
          </div>

          {/* Workflow list */}
          <div className="flex flex-col gap-2 animate-fade-up" style={{ animationDelay: "150ms" }}>
            {workflows.map((w) => (
              <Link
                key={w.href}
                href={w.href}
                className="group flex items-center gap-3.5 px-4 py-3.5 bg-white border border-zinc-200 rounded-xl hover:border-nea-blue/40 hover:shadow-sm transition-all"
              >
                <div className="w-8 h-8 rounded-lg bg-nea-blue-light text-nea-blue flex items-center justify-center shrink-0 group-hover:bg-nea-blue group-hover:text-white transition-colors">
                  {w.icon}
                </div>
                <p className="flex-1 text-sm font-medium text-zinc-900">{w.label}</p>
                <svg
                  className="w-4 h-4 text-zinc-300 group-hover:text-zinc-500 group-hover:translate-x-0.5 transition-all shrink-0"
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 18l6-6-6-6" />
                </svg>
              </Link>
            ))}
          </div>

        </div>
      </main>

      <footer className="border-t border-zinc-200 px-6 py-4">
        <p className="text-center text-xs text-zinc-400">
          New Enterprise Associates · Internal use only
        </p>
      </footer>
    </div>
  );
}
