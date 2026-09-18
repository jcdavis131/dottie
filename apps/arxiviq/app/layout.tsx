import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "arxiviq.com — Dottie Factory + Conductor",
  description: "Dottie pairing and conductor status with explicit service provenance.",
  metadataBase: new URL("https://arxiviq.com"),
  openGraph: {
    title: "arxiviq.com — Dottie Factory",
    description: "Dottie pairing and conductor status with explicit service provenance.",
    url: "https://arxiviq.com",
    siteName: "arxiviq.com",
    type: "website",
  },
  manifest: "/manifest.json",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta name="theme-color" content="#080A0F" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </head>
      <body style={{ margin: 0, background: "#080A0F" }}>
        <nav
          aria-label="Site"
          style={{
            alignItems: "center",
            background: "rgba(8,10,15,.92)",
            backdropFilter: "blur(12px)",
            borderBottom: "1px solid #1E3328",
            display: "flex",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: 13,
            gap: 20,
            height: 40,
            padding: "0 20px",
            position: "sticky",
            top: 0,
            zIndex: 40,
          }}
        >
          <a href="/" style={{ color: "#EDEAE2", textDecoration: "none", fontWeight: 700 }}>
            arxiviq
          </a>
          <a href="/" style={{ color: "#8A9A8B", textDecoration: "none" }}>
            Conductor
          </a>
          <a href="/hive" style={{ color: "#8A9A8B", textDecoration: "none" }}>
            The hive
          </a>
          <a href="/dottie" style={{ color: "#8A9A8B", textDecoration: "none" }}>
            Pair
          </a>
        </nav>
        {children}
      </body>
    </html>
  );
}
