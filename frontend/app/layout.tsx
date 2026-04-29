import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "NEA AI Platform",
  description: "New Enterprise Associates",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en" className={inter.variable + " h-full"}>
        <body className="h-full antialiased text-zinc-900">
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
