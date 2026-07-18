"""Synthetic data generators for the Ava nano training curriculum.

Every generator in this package is a fully offline, deterministic producer of
phase-tagged JSONL training text: zero network access, private seeded RNG
only, every numeric/factual answer computed by Python (never templated as
literal text). See specs/02_data_generation.md for the detailed contract.
"""

from ava.datagen.base import Generator, write_shards, run_cli, validate_doc
from ava.datagen.chat_safety import ChatSafetyGenerator
from ava.datagen.code_gen import CodeGenGenerator
from ava.datagen.compress_trace import CompressTraceGenerator
from ava.datagen.db_trace import DBTraceGenerator
from ava.datagen.encyclopedia import EncyclopediaGenerator
from ava.datagen.logic import LogicGenerator
from ava.datagen.math_gen import MathGenerator
from ava.datagen.react_tools import ReactToolsGenerator
from ava.datagen.workflow_gaia2 import WorkflowGaia2Generator
from ava.datagen.workflow_jobbench import WorkflowJobBenchGenerator

#: The single source of truth for synthetic sources. `configs/sources.yaml`
#: refers to generators by these keys; ava/pipeline/collector.py resolves them
#: here rather than carrying its own copies.
GENERATORS: dict[str, type[Generator]] = {
    ChatSafetyGenerator.name: ChatSafetyGenerator,
    CodeGenGenerator.name: CodeGenGenerator,
    CompressTraceGenerator.name: CompressTraceGenerator,
    DBTraceGenerator.name: DBTraceGenerator,
    EncyclopediaGenerator.name: EncyclopediaGenerator,
    LogicGenerator.name: LogicGenerator,
    MathGenerator.name: MathGenerator,
    ReactToolsGenerator.name: ReactToolsGenerator,
    WorkflowGaia2Generator.name: WorkflowGaia2Generator,
    WorkflowJobBenchGenerator.name: WorkflowJobBenchGenerator,
}

__all__ = [
    "Generator", "write_shards", "run_cli", "validate_doc", "GENERATORS",
    "ChatSafetyGenerator", "CodeGenGenerator", "CompressTraceGenerator",
    "DBTraceGenerator", "EncyclopediaGenerator",
    "LogicGenerator", "MathGenerator", "ReactToolsGenerator",
    "WorkflowGaia2Generator", "WorkflowJobBenchGenerator",
]
