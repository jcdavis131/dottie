"""Synthesizer + InputGenerator + PromptOptimizer like harness-evals."""
from ..core.golden import Golden
import random

class Synthesizer:
    def __init__(self, llm=None): self.llm=llm
    async def generate(self, documents, n=20, difficulty="mixed"):
        # zero-deps stub: synthesize from doc sentences
        golds=[]
        for doc in documents:
            sents=doc.split(". ")[:n]
            for sent in sents[:n]:
                golds.append(Golden(input=sent.strip()+"?", expected=sent.strip()))
                if len(golds)>=n: break
        return golds[:n]

class InputGenerator:
    def rephrase(self, golden: Golden, n=3):
        return [Golden(input=f"{golden.input} (rephrase {i})", expected=golden.expected) for i in range(n)]

class PromptOptimizer:
    def __init__(self, model, judge, metrics, target_score=0.85, max_iterations=10):
        self.model=model; self.judge=judge; self.metrics=metrics; self.target_score=target_score; self.max_iterations=max_iterations
    async def optimize(self, prompt_template, goldens):
        # stub — returns placeholder result
        class R: initial_score=0.6; best_score=0.72; iterations=3; best_prompt=prompt_template
        def save(self,path): open(path,'w').write(str(prompt_template))
        R.save=R.save
        return R()
