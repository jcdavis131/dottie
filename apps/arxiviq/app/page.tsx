import AgentConductorPanel from "./components/AgentConductorPanel";

export const metadata = {
  title: "arxiviq.com — Dottie Conductor",
  description: "Manage daemon-reported sessions, shared notes, and tasks. Tandem status and pairing are shown only when confirmed.",
};

export default async function Home({ searchParams }: { searchParams?: Promise<{ tandem?: string }> }) {
  const params = await searchParams;
  const tandem = params?.tandem === "1" || params?.tandem === "true";
  // support both /conductor?tandem=1 and /?tandem=1 — page.tsx is root conductor
  return <AgentConductorPanel tandem={tandem} />;
}
