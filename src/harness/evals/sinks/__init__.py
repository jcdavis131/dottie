"""Sinks — Stdout, Json, stub Langfuse/Otlp like harness-evals."""
import json, pathlib, sys
class BaseSink:
    def write(self, scores, eval_case): pass

class StdoutSink(BaseSink):
    def write(self, scores, ec):
        for s in scores:
            print(f"{'PASS' if s.passed else 'FAIL'} {s.name}({s.dimension}):{s.value:.2f} {s.reason}", file=sys.stdout)

class JsonSink(BaseSink):
    def __init__(self, path="results/scores.jsonl"):
        self.path=pathlib.Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
    def write(self, scores, ec):
        with self.path.open("a") as f:
            for s in scores:
                f.write(json.dumps({"case_id":ec.id,"input":ec.input[:200],"metric":s.name,"value":s.value,"passed":s.passed,"dim":s.dimension,"reason":s.reason})+"\n")
