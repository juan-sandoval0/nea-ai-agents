import Image from "next/image";
import Link from "next/link";

const agents = [
  {
    href: "/briefing",
    label: "Meeting Briefing",
    delay: "animate-card-1",
    description: "Company intelligence generated in seconds — founders, signals, news, and competitive landscape for any meeting.",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0121 9.414V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    href: "/digest",
    label: "News Digest",
    delay: "animate-card-2",
    description: "Ranked weekly signals across your portfolio and competitors — funding, hires, launches, and M&A, filtered for what matters.",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
          d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
      </svg>
    ),
  },
  {
    href: "/outreach",
    label: "Outreach",
    delay: "animate-card-3",
    description: "Personalized cold outreach in each investor's voice — thesis-driven, grounded in real company data, ready to send.",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
          d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
  },
];

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-white flex flex-col">
      {/* ── Hero ── */}
      <section className="relative flex flex-col items-center justify-center pt-20 pb-16 px-6 overflow-hidden">
        {/* Background blue gradient blob */}
        <div
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(ellipse 80% 55% at 50% 0%, #1B527618 0%, transparent 70%)",
          }}
        />

        {/* NEA Logo */}
        <div className="animate-logo-reveal mb-8">
          <Image
            src="/nea-logo.png"
            alt="NEA"
            width={220}
            height={90}
            priority
            className="select-none"
            style={{ filter: "brightness(0) saturate(100%) invert(25%) sepia(60%) saturate(700%) hue-rotate(180deg) brightness(80%)" }}
          />
        </div>

        {/* Animated divider line */}
        <div
          className="animate-line h-px bg-nea-blue mb-8 block"
          style={{ width: 0 }}
        />

        {/* Headline */}
        <div
          className="animate-fade-up text-center"
          style={{ animationDelay: "0.45s", opacity: 0 }}
        >
          <h1 className="font-display text-5xl md:text-6xl font-700 text-nea-blue leading-tight tracking-tight mb-4">
            AI Platform
          </h1>
          <p className="font-ui text-base text-nea-mid max-w-md mx-auto leading-relaxed">
            Intelligent agents for venture capital workflows — briefings, signals, and outreach at the speed of thought.
          </p>
        </div>
      </section>

      {/* ── Agent cards ── */}
      <section className="flex-1 px-6 pb-16 max-w-4xl mx-auto w-full">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {agents.map((agent) => (
            <Link
              key={agent.href}
              href={agent.href}
              className={`group ${agent.delay} block rounded-2xl border border-nea-border bg-white p-6 hover:border-nea-blue hover:shadow-lg hover:shadow-nea-blue/8 transition-all duration-200`}
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="w-9 h-9 rounded-xl bg-nea-blue-light text-nea-blue flex items-center justify-center group-hover:bg-nea-blue group-hover:text-white transition-colors duration-200">
                  {agent.icon}
                </div>
                <span className="font-ui font-semibold text-sm text-nea-dark">{agent.label}</span>
              </div>
              <p className="font-ui text-sm text-nea-mid leading-relaxed">{agent.description}</p>
              <div className="mt-4 flex items-center gap-1 text-xs font-medium text-nea-blue opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                Open
                <svg className="w-3.5 h-3.5 translate-x-0 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </Link>
          ))}
        </div>

        {/* CTA */}
        <div
          className="animate-fade-up mt-10 flex justify-center"
          style={{ animationDelay: "1.4s", opacity: 0 }}
        >
          <Link
            href="/briefing"
            className="font-ui inline-flex items-center gap-2 px-7 py-3 rounded-full bg-nea-blue text-white text-sm font-semibold hover:bg-nea-blue-dark transition-colors duration-200 shadow-md shadow-nea-blue/20"
          >
            Enter Platform
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-nea-border px-6 py-5 flex items-center justify-between max-w-4xl mx-auto w-full">
        <span className="font-ui text-xs text-nea-muted">New Enterprise Associates</span>
        <span className="font-ui text-xs text-nea-muted">Internal AI Platform</span>
      </footer>
    </main>
  );
}
