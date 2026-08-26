import AgentConductorPanel from "../components/AgentConductorPanel";

export const metadata = {
  title: "arxiviq.com — Dottie Conductor",
  description: "Manage sessions across machines — warm sessions, one-touch security, shared notes and tasks. Tandem Local Dottie + Cloud Scout + Paired. The only thing on arxiviq.com.",
};

export default function Home({ searchParams }: { searchParams?: { tandem?: string; pair?: string } }) {
  const tandem = searchParams?.tandem === "1" || searchParams?.tandem === "true";
  const pairCode = searchParams?.pair;
  // support both /conductor?tandem=1 and /?tandem=1 — page.tsx is root conductor
  return <AgentConductorPanel tandem={tandem} pairCode={pairCode} />;
}
