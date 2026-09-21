import AgentConductorPanel from "../components/AgentConductorPanel";

export const metadata = {
  title: "Conductor — dottie-os · arxiviq.com",
  description: "Manage daemon-reported sessions, shared notes, and tasks next to the System One sidecar. Tandem status and pairing are shown only when confirmed.",
};

export default async function Home({ searchParams }: { searchParams?: Promise<{ tandem?: string }> }) {
  const params = await searchParams;
  const tandem = params?.tandem === "1" || params?.tandem === "true";
  return <AgentConductorPanel tandem={tandem} />;
}
