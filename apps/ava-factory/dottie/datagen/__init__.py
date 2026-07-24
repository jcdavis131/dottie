"""Synthetic data generators for the Ava nano training curriculum.

Every generator in this package is a fully offline, deterministic producer of
phase-tagged JSONL training text: zero network access, private seeded RNG
only, every numeric/factual answer computed by Python (never templated as
literal text). See specs/02_data_generation.md for the detailed contract.

Reconciled 2026-07-19 from the three fork tines: the monorepo (compression,
quality taxonomy), the workspace checkout (codeact + ET-CoT trace family),
and the retired live checkout (tool curriculum, synpro, think-in-code, wiki,
trajectory adapters). GENERATORS is the union — configs/sources.yaml refers
to generators by these keys and the collector resolves them here.
"""

from dottie.datagen.base import Generator, write_shards, run_cli, validate_doc
from dottie.datagen.chat_safety import ChatSafetyGenerator
from dottie.datagen.code_gen import CodeGenGenerator
from dottie.datagen.compress_trace import CompressTraceGenerator
from dottie.datagen.compression import CompressionGenerator
from dottie.datagen.db_trace import DBTraceGenerator
from dottie.datagen.encyclopedia import EncyclopediaGenerator
from dottie.datagen.logic import LogicGenerator
from dottie.datagen.math_gen import MathGenerator
from dottie.datagen.react_tools import ReactToolsGenerator
from dottie.datagen.scout_cli import ScoutCliGenerator
from dottie.datagen.synpro_gen import SynProLiteGenerator
from dottie.datagen.think_in_code import ThinkInCodeGenerator, ThinkToolsGenerator
from dottie.datagen.tool_curriculum import ToolUseGenerator
from dottie.datagen.wiki_gen import WikiGenerator
from dottie.datagen.workflow_gaia2 import WorkflowGaia2Generator
from dottie.datagen.workflow_jobbench import WorkflowJobBenchGenerator
from dottie.datagen.zk_math import ZkMathGenerator

#: The single source of truth for synthetic sources. `configs/sources.yaml`
#: refers to generators by these keys; dottie/pipeline/collector.py resolves
#: them here rather than carrying its own copies.
GENERATORS: dict[str, type[Generator]] = {
    ChatSafetyGenerator.name: ChatSafetyGenerator,
    CodeGenGenerator.name: CodeGenGenerator,
    CompressTraceGenerator.name: CompressTraceGenerator,
    CompressionGenerator.name: CompressionGenerator,
    DBTraceGenerator.name: DBTraceGenerator,
    EncyclopediaGenerator.name: EncyclopediaGenerator,
    LogicGenerator.name: LogicGenerator,
    MathGenerator.name: MathGenerator,
    ReactToolsGenerator.name: ReactToolsGenerator,
    ScoutCliGenerator.name: ScoutCliGenerator,
    SynProLiteGenerator.name: SynProLiteGenerator,
    ThinkInCodeGenerator.name: ThinkInCodeGenerator,
    ThinkToolsGenerator.name: ThinkToolsGenerator,
    ToolUseGenerator.name: ToolUseGenerator,
    WikiGenerator.name: WikiGenerator,
    WorkflowGaia2Generator.name: WorkflowGaia2Generator,
    WorkflowJobBenchGenerator.name: WorkflowJobBenchGenerator,
    ZkMathGenerator.name: ZkMathGenerator,
}

__all__ = [
    "Generator", "write_shards", "run_cli", "validate_doc", "GENERATORS",
    "ChatSafetyGenerator", "CodeGenGenerator", "CompressTraceGenerator",
    "CompressionGenerator", "DBTraceGenerator", "EncyclopediaGenerator",
    "LogicGenerator", "MathGenerator", "ReactToolsGenerator",
    "ScoutCliGenerator",
    "SynProLiteGenerator", "ThinkInCodeGenerator", "ThinkToolsGenerator",
    "ToolUseGenerator", "WikiGenerator", "WorkflowGaia2Generator",
    "WorkflowJobBenchGenerator", "ZkMathGenerator",
]
