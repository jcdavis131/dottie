"""
TMUX Extension — real interactive terminal for agent

Solo personal project, no connection to employer, built with public/free-tier only

Most frameworks: one-shot command execution — run command, get stdout, done.
Real engineering: interactive. Run command, see partial output, decide next, maybe Ctrl+C.

With TMUX extension, agent can:
- Create/manage persistent tmux sessions
- Send keystrokes including Ctrl sequences
- Capture pane output and react to it
- Run truly interactive workflows (debugging, REPLs, watching logs)

Combined with Python runtime, agent writes debugging strategy as code and executes across panes.
"""

import subprocess
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

@dataclass
class TmuxPane:
    session: str
    pane_id: str
    buffer: str = ""
    last_capture: float = 0.0

class TmuxManager:
    """
    Gives agent real interactive command-line experience.
    Uses tmux if available, falls back to subprocess for Hatch VM.
    """
    
    def __init__(self):
        self.sessions: Dict[str, List[TmuxPane]] = {}
        self._use_tmux = self._check_tmux()
    
    def _check_tmux(self) -> bool:
        try:
            subprocess.run(["tmux", "-V"], capture_output=True, check=True)
            return True
        except:
            return False
    
    def create_session(self, name: str) -> TmuxPane:
        """Create persistent tmux session"""
        if name in self.sessions:
            return self.sessions[name][0]
        
        pane = TmuxPane(session=name, pane_id=f"{name}:0.0")
        self.sessions[name] = [pane]
        
        if self._use_tmux:
            try:
                subprocess.run(["tmux", "new-session", "-d", "-s", name], check=False, capture_output=True)
            except:
                pass
        
        return pane
    
    def send_keys(self, session: str, keys: str, literal: bool = False):
        """
        Send keystrokes including Ctrl sequences
        e.g., send_keys("train", "C-c") for Ctrl+C, or send_keys("train", "python train.py\n")
        """
        pane = self.sessions.get(session, [None])[0]
        if pane is None:
            pane = self.create_session(session)
        
        if self._use_tmux:
            try:
                if keys == "C-c":
                    subprocess.run(["tmux", "send-keys", "-t", session, "C-c"], capture_output=True)
                elif keys == "C-d":
                    subprocess.run(["tmux", "send-keys", "-t", session, "C-d"], capture_output=True)
                else:
                    subprocess.run(["tmux", "send-keys", "-t", session, keys], capture_output=True)
            except:
                pass
        
        # also log for fallback
        pane.buffer += f"\n[send_keys:{keys}]\n"
        return pane
    
    def capture_pane(self, session: str, lines: int = 100) -> str:
        """Capture pane output and react to it"""
        pane = self.sessions.get(session, [None])[0]
        if pane is None:
            return ""
        
        if self._use_tmux:
            try:
                result = subprocess.run(
                    ["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"],
                    capture_output=True, text=True
                )
                pane.buffer = result.stdout
                pane.last_capture = time.time()
                return result.stdout
            except:
                pass
        
        return pane.buffer
    
    def run_interactive_workflow(self, session: str, strategy_code: str) -> str:
        """
        Combined with Python runtime, agent writes debugging strategy as code:
        "run this test, if it fails check log for X, if X appears try Y"
        """
        # This is pseudocode execution plan — real version execs python that drives tmux
        steps = []
        steps.append(f"# Strategy: {strategy_code}")
        steps.append(f"session={session}")
        steps.append("# 1. Run command, capture partial output")
        steps.append("# 2. Decide next, maybe Ctrl+C and try something else")
        steps.append("# 3. Agent has conversation with terminal, not one-shot")
        return "\n".join(steps)
    
    def debug_training_flow(self) -> str:
        """Pre-canned debug flow for Dottie training stalls"""
        return """
# Dottie Training Debug Flow (TMUX extension)
# Session: train

pane = tmux.create_session("train")
tmux.send_keys("train", "tail -f logs/builder.log\n")
output = tmux.capture_pane("train", lines=50)

if "Backpressure" in output and "27 shards pending" in output:
    # From builder.log 2026-07-09 — classic JSON loop bottleneck
    tmux.send_keys("train", "C-c")
    tmux.send_keys("train", "python scripts/dataset_expansion_fast.py --quick --dedup md5\n")
elif "loss spike > 3x median" in output or "NaN" in output:
    tmux.send_keys("train", "C-c")
    tmux.send_keys("train", "python eval_branch_harness.py --branch all --mode mock | tail -n 30\n")
    tmux.send_keys("train", "cat checkpoints/builder_state.json | jq .current_phase\n")
else:
    tmux.send_keys("train", "nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv\n")

# Watch second pane for eval
tmux.create_session("eval")
tmux.send_keys("eval", "watch -n 5 'cat evals/run_harness.py output'\n")
"""

AvaTmux = TmuxManager
