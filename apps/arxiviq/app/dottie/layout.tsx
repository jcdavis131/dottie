import type { ReactNode } from "react";

export const metadata = {
  title: { absolute: "Pair — dottie-os · arxiviq.com" },
  description:
    "Server-confirmed pairing with jarvisd. There is no local, in-memory, or accept-any fallback.",
};

export default function PairLayout({ children }: { children: ReactNode }) {
  return children;
}
