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
      <body style={{ margin: 0, background: "#080A0F" }}>{children}</body>
    </html>
  );
}
