import AgentConductorPanel from '../components/AgentConductorPanel';

export const metadata = {
  title: 'Dottie • Conductor',
  description: 'Manage sessions across machines — warm sessions, one-touch security, shared notes and tasks.',
};

export default function ConductorPage({ searchParams }: { searchParams?: { tandem?: string; pair?: string } }) {
  const tandem = searchParams?.tandem === '1' || searchParams?.tandem === 'true';
  const pairCode = searchParams?.pair;
  return <AgentConductorPanel tandem={tandem} pairCode={pairCode} />;
}
