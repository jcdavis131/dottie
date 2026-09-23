import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import "./globals.css";
import {
  META_DESCRIPTION,
  META_TITLE,
  OG_DESCRIPTION,
  OG_TITLE,
} from "../lib/system-one-copy";

export const metadata: Metadata = {
  title: META_TITLE,
  description: META_DESCRIPTION,
  metadataBase: new URL("https://arxiviq.com"),
  openGraph: {
    title: OG_TITLE,
    description: OG_DESCRIPTION,
    url: "https://arxiviq.com",
    siteName: "arxiviq.com",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: OG_TITLE,
    description: OG_DESCRIPTION,
  },
  manifest: "/manifest.json",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta name="theme-color" content="#f1e7e0" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </head>
      <body style={{ margin: 0, background: "#f1e7e0" }}>
        <nav
          aria-label="Site"
          style={{
            alignItems: "center",
            background: "rgba(251,246,239,.92)",
            backdropFilter: "blur(12px)",
            borderBottom: "1px solid #d9cabe",
            display: "flex",
            fontFamily: "IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: 13,
            gap: 20,
            height: 40,
            padding: "0 20px",
            position: "sticky",
            top: 0,
            zIndex: 40,
          }}
        >
          <Link href="/" style={{ color: "#201a13", textDecoration: "none", fontWeight: 700 }}>
            dottie-os
          </Link>
          <Link href="/conductor" style={{ color: "#6f655a", textDecoration: "none" }}>
            Conductor
          </Link>
          <Link href="/hive" style={{ color: "#6f655a", textDecoration: "none" }}>
            The hive
          </Link>
          <Link href="/dottie" style={{ color: "#6f655a", textDecoration: "none" }}>
            Pair
          </Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
