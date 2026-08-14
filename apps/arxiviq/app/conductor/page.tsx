// Thin UI route /conductor — one place to herd agents
import AgentConductorPanel from '../components/AgentConductorPanel';

export const metadata = {
  title: 'Dottie • Conductor',
  description: 'Manage sessions across machines — warm sessions, one-touch security, shared notes and tasks.',
};

export default function ConductorPage() {
  return <AgentConductorPanel />;
}
