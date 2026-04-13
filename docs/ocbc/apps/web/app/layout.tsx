import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { AppNavLink } from "@/components/app-nav-link";

import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Tax Build",
  description: "Singapore corporate tax filing engine"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.className} min-h-screen bg-muted/30`}>
        <div className="min-h-screen">
          <header className="border-b bg-background/95 print:hidden">
            <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">Tax Build</p>
                <h1 className="text-xl font-semibold text-foreground">Singapore corporate tax workspace</h1>
              </div>
              <nav className="flex flex-wrap gap-2">
                <AppNavLink href="/" label="Dashboard" />
                <AppNavLink href="/company" label="Company Setup" />
                <AppNavLink href="/statements" label="Statements" />
                <AppNavLink href="/transactions" label="Transactions" />
                <AppNavLink href="/tax" label="Tax Computation" />
                <AppNavLink href="/filing" label="Filing" />
              </nav>
            </div>
          </header>
          <main className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
