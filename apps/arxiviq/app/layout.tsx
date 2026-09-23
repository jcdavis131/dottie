import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import SiteFooter from "./components/SiteFooter";
import SiteNav from "./components/SiteNav";
import {
  META_DESCRIPTION,
  META_TITLE,
  OG_DESCRIPTION,
  OG_TITLE,
} from "../lib/system-one-copy";

export const metadata: Metadata = {
  title: {
    default: META_TITLE,
    template: "%s · dottie-os · arxiviq.com",
  },
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
    card: "summary_large_image",
    title: OG_TITLE,
    description: OG_DESCRIPTION,
  },
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafaf8" },
    { media: "(prefers-color-scheme: dark)", color: "#060607" },
  ],
};

const FONTS =
  "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Jost:wght@300;400;500&display=swap";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={FONTS} />
      </head>
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <SiteNav />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
