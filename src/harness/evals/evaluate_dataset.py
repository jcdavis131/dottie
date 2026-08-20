"""evaluate_dataset helper like harness-evals."""
import asyncio
from .core.golden import EvalCase, Golden
from .core.metric import evaluate_cases

async def evaluate_dataset(goldens, agent_fn, metrics, simulator_llm=None, sinks=None):
    cases=[]
    for g in goldens:
        if isinstance(g, Golden):
            ec = await agent_fn(g) if asyncio.iscoroutinefunction(agent_fn) else agent_fn(g)
            if isinstance(ec, EvalCase): cases.append(ec)
            else: cases.append(EvalCase(input=g.input, output=str(ec), expected=g.expected))
        else:
            # ConversationGolden path — simplified
            cases.append(EvalCase(input=getattr(g,'scenario','conv'), output="stub", expected=getattr(g,'expected_outcome','')))
    return evaluate_cases(cases, metrics, sinks=sinks)
