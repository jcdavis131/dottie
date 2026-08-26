import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "arxiviq.com — Dottie Factory + Conductor",
  description: "Dottie factory — ingest→serve MTNN v9.2 20719×128-d, LCG 20260813 chain same-link-same-stars, tandem Local Dottie + Cloud Scout + Paired, PWA v67 offline13k CORE20 verifier≥8.",
  metadataBase: new URL("https://arxiviq.com"),
  openGraph: {
    title: "arxiviq.com — Dottie Factory",
    description: "Factory control plane — paper #FAFAF8 void #080A0F 40px sticky z40 PWA v67 offline13k verifier≥8 Launched 99.9→100% free.",
    url: "https://arxiviq.com",
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
        <meta name="theme-color" content="#080A0F" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </head>
      <body style={{ margin: 0, background: "#080A0F" }}>{children}</body>
    </html>
  );
}
