import type { Metadata } from "next";

import { NavBar, SiteFooter } from "@/components/nav";
import { I18nProvider } from "@/lib/i18n";
import "./globals.css";

export const metadata: Metadata = {
  title: "US Stock Watcher — U.S. Equity Market Intelligence",
  description: "AI-driven U.S. stock market analysis, news, and investment research.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen">
        <I18nProvider>
          <NavBar />
          <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
          <SiteFooter />
        </I18nProvider>
      </body>
    </html>
  );
}
