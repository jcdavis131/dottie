import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "arxiviq.com — Dottie Factory + Conductor — human-first v5",
  description: "Dottie factory — human-first v5: what needs attention, and what can I confidently do next? Current objective, one next action, evidence, active work, honest blockers. Ingest→serve MTNN v9.2 20719×128-d, LCG 20260813 chain same-link-same-stars, tandem Local Dottie + Cloud Scout + Paired, PWA v67 offline13k CORE20 verifier≥8.",
  metadataBase: new URL("https://arxiviq.com"),
  openGraph: {
    title: "arxiviq.com — Dottie Factory — human-first v5",
    description: "Factory control plane — paper #F9F6F0 ink #2A2A2A terracotta #C17C60 44px mono nav 40px sticky z40 PWA v67 offline13k CORE20 verifier≥8 Launched 99.9→100% free — what needs attention, next safe action in 15s.",
    url: "https://arxiviq.com/dottie",
    siteName: "arxiviq.com",
    type: "website",
  },
  manifest: "/manifest.json",
  icons: { icon: "/icon-192.png", apple: "/icon-192.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta name="theme-color" content="#F9F6F0" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <link rel="stylesheet" href="/assets/human-v5/tokens.css" />
      </head>
      <body style={{ margin: 0, background: "#F9F6F0", color: "#2A2A2A" }}>{children}</body>
    </html>
  );
}
