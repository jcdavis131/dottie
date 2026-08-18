import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "arxiviq.com — Conductor",
  description: "Manage sessions across machines — warm sessions, one-touch security, shared notes and tasks. The only thing on arxiviq.com.",
  metadataBase: new URL("https://arxiviq.com"),
  openGraph: {
    title: "arxiviq.com — Conductor",
    description: "Single daemon, warm sessions, one-touch security, shared scratchpad & todos. The factory control plane.",
    url: "https://arxiviq.com",
    siteName: "arxiviq.com",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{margin:0, background:"#080A0F"}}>{children}</body>
    </html>
  );
}
