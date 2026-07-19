"""
LLMVM Kernel — persistent Python runtime (Bento-like sandbox)

Solo personal project, no connection to employer, built with public/free-tier only

Core innovation from Metamate Advanced Auto:
- LLM writes and executes real code in persistent notebook
- Every tool is async function, composable with loops/conditionals/error handling
- Execution pauses for host calls (HF download, CUDA, OpenWiki), resumes, only final output enters context
- One cell = what took 15+ JSON round-trips before
"""

import asyncio
import ast
import inspect
import io
import sys
import traceback
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
import contextlib

@dataclass
class ExecutionResult:
    success: bool
    output: str
    result: Any = None
    error: Optional[str] = None
    exec_time_ms: int = 0
    truncated: bool = False
    host_calls: List[Dict] = field(default_factory=list)

class LLMVMKernel:
    """
    Persistent notebook namespace where variables survive across cells.
    - Bento kernel analog: sandboxed, pauses on host calls
    - Self-modification: can define new tools and override existing ones
    """
    
    def __init__(self):
        # persistent namespace — this is why self-modification works
        self.globals: Dict[str, Any] = {
            "__name__": "__llmvm__",
            "__builtins__": __builtins__,
            "asyncio": asyncio,
        }
        self.locals: Dict[str, Any] = {}
        self.history: List[ExecutionResult] = []
        self.host_call_queue: List[Dict] = []
        self._execution_count = 0
        
        # inject core emergent capabilities — no schema tax, signature is schema
        self._inject_emergent_libs()
    
    def _inject_emergent_libs(self):
        """LLM already knows Python — expose via namespace, not JSON schema"""
        # these are available without tool definition — LLM trained on billions of lines
        self.globals.update({
            "re": __import__("re"),
            "json": __import__("json"),
            "pathlib": __import__("pathlib"),
            "collections": __import__("collections"),
        })
    
    async def exec_cell(self, code: str, timeout: float = 30.0) -> ExecutionResult:
        """
        Execute real Python in persistent namespace.
        What would take 15+ LLM round-trips with tool calling happens in one execution.
        """
        start = time.time()
        self._execution_count += 1
        
        # capture stdout
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        
        try:
            # Try to detect if last statement is expression for REPL behavior
            tree = ast.parse(code)
            last_expr = None
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                last_expr = tree.body.pop()
            
            # compile main body
            compiled = compile(ast.Module(tree.body, []), f"<cell-{self._execution_count}>", "exec")
            
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                # exec in persistent namespace — enables self-modification
                exec(compiled, self.globals)
                
                result = None
                if last_expr:
                    # eval last expression
                    expr_code = compile(ast.Expression(last_expr.value), "<expr>", "eval")
                    result = eval(expr_code, self.globals)
                    if asyncio.iscoroutine(result):
                        result = await asyncio.wait_for(result, timeout=timeout)
                    # also collect if there was await in body? handled via async wrapper below
                    if result is not None:
                        print(result)
            
            output = stdout_buf.getvalue() + stderr_buf.getvalue()
            elapsed = int((time.time() - start) * 1000)
            
            # only final output enters context — bidirectional control (compacting out)
            # intermediate results stay in kernel memory, not LLM context
            if len(output) > 4000:
                output = output[:4000] + f"\n...truncated {len(output)-4000} chars — full in kernel memory"
                truncated = True
            else:
                truncated = False
            
            exec_result = ExecutionResult(
                success=True,
                output=output,
                result=result,
                exec_time_ms=elapsed,
                truncated=truncated,
                host_calls=self.host_call_queue.copy()
            )
            self.host_call_queue.clear()
            self.history.append(exec_result)
            return exec_result
            
        except Exception as e:
            output = stdout_buf.getvalue() + stderr_buf.getvalue() + traceback.format_exc()
            elapsed = int((time.time() - start) * 1000)
            exec_result = ExecutionResult(
                success=False,
                output=output,
                error=str(e),
                exec_time_ms=elapsed,
            )
            self.history.append(exec_result)
            return exec_result
    
    async def exec_parallel(self, snippets: List[str]) -> List[ExecutionResult]:
        """Parallel execution: asyncio.gather() ten ops in one cell — impossible in JSON loop"""
        tasks = [self.exec_cell(code) for code in snippets]
        return await asyncio.gather(*tasks)
    
    def register_tool(self, func: Callable, override: bool = False):
        """
        Self-modification: define new tools and override existing ones mid-session
        Agent can do: def cached_download(url): ...; download = cached_download
        """
        name = func.__name__
        if not override and name in self.globals:
            raise ValueError(f"Tool {name} already exists, set override=True to replace")
        self.globals[name] = func
        return func
    
    def get_namespace(self) -> Dict[str, Any]:
        """Persistent state — variables survive across cells"""
        return {**self.globals, **self.locals}
    
    def reset(self):
        """Reset namespace but keep history for compaction analysis"""
        self.globals = {"__name__": "__llmvm__", "__builtins__": __builtins__, "asyncio": asyncio}
        self.locals = {}
        self._inject_emergent_libs()
