import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "arxiviq — ACNE × Graphify for ML architecture intelligence",
  description:
    "World models • JEPA • ImageBind • Hamiltonian nets • training dynamics — local-first, no vectors. ACNE extracts, Graphify compresses, you explore.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
