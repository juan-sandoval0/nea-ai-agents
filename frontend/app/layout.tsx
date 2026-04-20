import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "NEA AI Platform",
  description: "New Enterprise Associates",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable + " h-full"}>
      <body className="h-full antialiased text-nea-dark">
        {children}
      </body>
    </html>
  );
}
