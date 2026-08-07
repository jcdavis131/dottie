import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dottie — the always-on AGI factory you can watch train · arxiviq.com",
  description: "Solo personal project: a small always-on factory that builds data, cleans it, learns, and serves chat. Free-tier only, no connection to employer. arxiviq.com is the live control plane.",
  metadataBase: new URL("https://arxiviq.com"),
  openGraph: {
    title: "Dottie — the always-on AGI factory you can watch train",
    description: "Solo, free-tier only. Watch a small factory get a little better every day.",
    url: "https://arxiviq.com",
    siteName: "arxiviq.com",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{margin:0, background:"#fcfcf8"}}>{children}</body>
    </html>
  );
}
