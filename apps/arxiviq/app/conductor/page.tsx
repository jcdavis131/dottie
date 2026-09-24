import AgentConductorPanel from "../components/AgentConductorPanel";

export const metadata = {
  title: { absolute: "Conductor — dottie-os" },
  description: "Manage daemon-reported sessions, shared notes, and tasks next to the System One sidecar. Tandem status and pairing are shown only when confirmed.",
};

export default async function Home({ searchParams }: { searchParams?: Promise<{ tandem?: string }> }) {
  const params = await searchParams;
  const tandem = params?.tandem === "1" || params?.tandem === "true";
  return (
    <main className="main room" id="main" tabIndex={-1}>
      <div className="container">
        <header className="room__head">
          <p className="label seq">Daemon-reported · authenticated</p>
          <h1 className="display room__title seq" style={{ "--i": 1 } as React.CSSProperties}>
            Conductor
          </h1>
          <p className="lede seq" style={{ "--i": 2 } as React.CSSProperties}>
            Sessions, shared notes, and tasks next to the System One sidecar. Tandem
            status and pairing are shown only when confirmed.
          </p>
        </header>
        <AgentConductorPanel tandem={tandem} />
      </div>
    </main>
  );
}
