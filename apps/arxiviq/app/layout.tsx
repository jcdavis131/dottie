import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dottie — small factory that learns out loud · arxiviq.com",
  description: "Solo personal project: a small always-on factory that builds data, cleans it, learns, and serves chat. Free-tier only, MIT, no employer. The live control plane at arxiviq.com.",
  metadataBase: new URL("https://arxiviq.com"),
  openGraph: {
    title: "Dottie — small factory that learns out loud",
    description: "Solo, MIT, free-tier only. Watch a small factory get a little better each day at arxiviq.com",
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
