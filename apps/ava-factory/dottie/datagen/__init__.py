"""Synthetic data generators for the Dottie nano training curriculum.

Every generator in this package is a fully offline, deterministic producer of
phase-tagged JSONL training text: zero network access, private seeded RNG
only, every numeric/factual answer computed by Python (never templated as
literal text). See specs/02_data_generation.md for the detailed contract.
"""

from dottie.datagen.base import Generator, write_shards, run_cli, validate_doc
from dottie.datagen.chat_safety import ChatSafetyGenerator
from dottie.datagen.code_gen import CodeGenGenerator
from dottie.datagen.compression import CompressionGenerator
from dottie.datagen.encyclopedia import EncyclopediaGenerator
from dottie.datagen.logic import LogicGenerator
from dottie.datagen.math_gen import MathGenerator
from dottie.datagen.react_tools import ReactToolsGenerator
from dottie.datagen.workflow_gaia2 import WorkflowGaia2Generator
from dottie.datagen.workflow_jobbench import WorkflowJobBenchGenerator

#: The single source of truth for synthetic sources. `configs/sources.yaml`
#: refers to generators by these keys; dottie/pipeline/collector.py resolves them
#: here rather than carrying its own copies.
GENERATORS: dict[str, type[Generator]] = {
    ChatSafetyGenerator.name: ChatSafetyGenerator,
    CodeGenGenerator.name: CodeGenGenerator,
    CompressionGenerator.name: CompressionGenerator,
    EncyclopediaGenerator.name: EncyclopediaGenerator,
    LogicGenerator.name: LogicGenerator,
    MathGenerator.name: MathGenerator,
    ReactToolsGenerator.name: ReactToolsGenerator,
    WorkflowGaia2Generator.name: WorkflowGaia2Generator,
    WorkflowJobBenchGenerator.name: WorkflowJobBenchGenerator,
}

__all__ = [
    "Generator", "write_shards", "run_cli", "validate_doc", "GENERATORS",
    "ChatSafetyGenerator", "CodeGenGenerator", "CompressionGenerator", "EncyclopediaGenerator",
    "LogicGenerator", "MathGenerator", "ReactToolsGenerator",
    "WorkflowGaia2Generator", "WorkflowJobBenchGenerator",
]
