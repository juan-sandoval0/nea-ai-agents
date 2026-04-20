"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  {
    href: "/briefing",
    label: "Meeting Briefing",
    icon: (
      <svg className="w-[14px] h-[14px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0121 9.414V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    href: "/digest",
    label: "News Digest",
    icon: (
      <svg className="w-[14px] h-[14px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
      </svg>
    ),
  },
  {
    href: "/outreach",
    label: "Outreach",
    icon: (
      <svg className="w-[14px] h-[14px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-52 shrink-0 h-screen flex flex-col bg-white border-r border-nea-border">
      <Link
        href="/"
        className="h-12 px-4 border-b border-nea-border flex items-center gap-2.5 hover:bg-nea-surface transition-colors shrink-0"
      >
        <Image
          src="/nea-logo.png"
          alt="NEA"
          width={40}
          height={16}
          className="select-none"
          style={{ filter: "brightness(0) saturate(100%) invert(25%) sepia(60%) saturate(700%) hue-rotate(180deg) brightness(80%)" }}
        />
        <div className="w-px h-4 bg-nea-border" />
        <span className="font-ui text-[11px] font-semibold text-nea-blue tracking-wide uppercase">AI Platform</span>
      </Link>

      <nav className="flex-1 px-2 py-3 overflow-y-auto">
        <p className="font-ui text-[10px] font-semibold text-nea-muted uppercase tracking-widest px-3 mb-1.5">
          Workflows
        </p>
        <div className="space-y-0.5">
          {navItems.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 px-3 py-2 rounded-md text-[13px] font-medium transition-all duration-100 font-ui ${
                  active
                    ? "bg-nea-blue text-white"
                    : "text-nea-mid hover:bg-nea-surface hover:text-nea-dark"
                }`}
              >
                {item.icon}
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>

      <div className="px-4 py-3 border-t border-nea-border shrink-0">
        <p className="font-ui text-[10px] text-nea-muted">New Enterprise Associates</p>
      </div>
    </aside>
  );
}
