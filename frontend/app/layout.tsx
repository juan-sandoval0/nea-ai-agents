import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "NEA AI Platform",
  description: "New Enterprise Associates",
};

/**
 * Root Layout with Clerk Authentication (Phase 3.1)
 *
 * Wraps the entire app with ClerkProvider for authentication.
 * Requires NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY env var to be set.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en" className={inter.variable + " h-full"}>
        <body className="h-full antialiased text-nea-dark">
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
