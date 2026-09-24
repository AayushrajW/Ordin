import type { Metadata } from "next";
import "./globals.css";

/**
 * No `next/font/google`. That helper fetches from Google's CDN at build time and
 * would break the air-gapped demo path (security invariant 11). A system font
 * stack costs nothing and ships with the machine.
 */
export const metadata: Metadata = {
  title: "Ordin · Evidence registry",
  description: "Case-centric evidence intelligence for Indian legal and investigation agencies",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-paper font-sans text-ink-900 antialiased">
        {children}
      </body>
    </html>
  );
}
