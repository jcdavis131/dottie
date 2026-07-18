# Awesome Open Source AI - Structured Summary

Source: https://github.com/alvinreal/awesome-opensource-ai

Total lines in README: 1370

## Overview of 14 Categories

- **1. Core Frameworks & Libraries**: 14 subcategories
- **2. Model Codebases & Model Families**: 3 subcategories
- **3. Inference Engines & Serving**: 5 subcategories
- **4. Agentic AI & Multi-Agent Systems**: 8 subcategories
- **5. Retrieval-Augmented Generation (RAG) & Knowledge**: 8 subcategories
- **6. Generative Media Tools**: 6 subcategories
- **7. Training & Fine-tuning Ecosystem**: 5 subcategories
- **8. MLOps / LLMOps & Production**: 7 subcategories
- **9. Evaluation, Benchmarks & Datasets**: 3 subcategories
- **10. AI Safety, Alignment & Interpretability**: 7 subcategories
- **11. Specialized Domains**: 14 subcategories
- **12. User Interfaces & Self-hosted Platforms**: 4 subcategories
- **13. Developer Tools & Integrations**: 9 subcategories
- **14. Resources & Learning**: 6 subcategories

---

## PRIORITY FOCUS - Detailed Extract

### Data Processing  (Data Processing & Manipulation)  — under 1. Core Frameworks & Libraries

- **Pandas** (https://github.com/pandas-dev/pandas) - The gold standard for data analysis and manipulation in Python.
- **Polars** (https://github.com/pola-rs/polars) - Blazing-fast DataFrame library (Rust backend) - modern alternative to Pandas for large-scale workloads.
- **cuDF** (https://github.com/rapidsai/cudf) - GPU DataFrame library from RAPIDS. Accelerates Pandas workflows on NVIDIA GPUs with zero code changes using cuDF.pandas accelerator mode.
- **Modin** (https://github.com/modin-project/modin) - Parallel Pandas DataFrames. Scale Pandas workflows by changing a single line of code - distributes data and computation automatically.
- **Dask** (https://github.com/dask/dask) - Parallel computing for big data - scales Pandas/NumPy/scikit-learn to clusters.
- **NumPy** (https://github.com/numpy/numpy) - Fundamental array computing library that powers almost every AI stack.
- **SciPy** (https://github.com/scipy/scipy) - Scientific computing algorithms (optimization, linear algebra, statistics, signal processing).
- **CuPy** (https://github.com/cupy/cupy) - NumPy and SciPy-compatible array library for GPU-accelerated computing in Python.
- **NetworkX** (https://github.com/networkx/networkx) - Creation, manipulation, and study of complex networks. The foundational graph analysis library for Python data science.
- **cuGraph** (https://github.com/rapidsai/cugraph) - GPU graph analytics library with NetworkX-compatible API. 10-100x faster than CPU for large-scale graph algorithms. Apache 2.0 licensed.
- **Vaex** (https://github.com/vaexio/vaex) - Out-of-Core hybrid Apache Arrow/NumPy DataFrame for Python. Visualize and explore billion-row datasets at millions of rows per second. MIT licensed.
- **Datashader** (https://github.com/holoviz/datashader) - High-performance large data visualization. Renders billions of points interactively without aggregation artifacts. BSD-3-Clause licensed.
- **Zarr** (https://github.com/zarr-developers/zarr-python) - Chunked, compressed, N-dimensional array storage. Scalable tensor data format optimized for cloud and parallel computing. MIT licensed.
- **NVIDIA DALI** (https://github.com/NVIDIA/DALI) - GPU-accelerated data loading and augmentation library with highly optimized building blocks for deep learning applications. Apache 2.0 licensed.
- **Narwhals** (https://github.com/narwhals-dev/narwhals) - Lightweight compatibility layer between DataFrame libraries. Write Polars-like code that works seamlessly across Pandas, Polars, cuDF, Modin, and more. MIT licensed.
- **Ibis** (https://github.com/ibis-project/ibis) - Portable Python dataframe library with 20+ backends. Write Pandas-like code that runs locally with DuckDB or scales to production databases (BigQuery, Snowflake, PostgreSQL) by changing one line. Apache 2.0 licensed.
- **skrub** (https://github.com/skrub-data/skrub) - Machine learning with dataframes for dirty categorical data. Preprocessing and feature engineering for heterogeneous data with seamless Pandas/Polars integration. BSD-3-Clause licensed.
- **Oxen** (https://github.com/Oxen-AI/Oxen) - Lightning fast data version control for machine learning. Optimized for large datasets with efficient diffing, branching, and collaboration. Apache 2.0 licensed.
- **Pandera** (https://github.com/unionai-oss/pandera) - Statistical data testing and validation for dataframes. Pydantic-like API for Pandas, Polars, and other dataframe libraries with type hints and lazy validation. MIT licensed.
- **Snorkel** (https://github.com/snorkel-team/snorkel) - System for quickly generating training data with weak supervision. Programmatically label, build, and manage training data using labeling functions and probabilistic consensus models. Powers Snorkel Flow and used by Google, Apple, and Intel. Apache 2.0 licensed.
- **DuckDB** (https://github.com/duckdb/duckdb) - High-performance analytical in-process SQL database system. Fast, reliable, portable, and easy to use with rich SQL dialect support. Perfect for data processing and analytics workloads. MIT licensed.
- **FiftyOne** (https://github.com/voxel51/fiftyone) - Visual AI development toolkit for visualizing, labeling, and evaluating visual datasets and models. Supercharges computer vision workflows with dataset exploration and model analysis. Apache 2.0 licensed.
- **Label Studio** (https://github.com/HumanSignal/label-studio) - Multi-type data labeling and annotation tool with standardized output format. Configurable interface for images, text, audio, video, and time series with ML-assisted labeling. Apache 2.0 licensed.
- **Delta Lake** (https://github.com/delta-io/delta) - Open-source storage framework enabling Lakehouse architecture with ACID transactions, scalable metadata handling, and unified batch/streaming processing. Apache 2.0 licensed.
- **Apache Iceberg** (https://github.com/apache/iceberg) - High-performance open table format for huge analytic tables. Brings SQL table reliability to big data with time travel, hidden partitioning, and schema evolution. Works with Spark, Trino, Flink, Presto, Hive and Impala. Apache 2.0 licensed.
- **Apache Hudi** (https://github.com/apache/hudi) - Open data lakehouse platform for ingesting, indexing, storing, serving, transforming and managing data across cloud environments. Supports upserts, deletes and incremental processing on big data with built-in ingestion tools for Spark and Flink. Apache 2.0 licensed.
- **lakeFS** (https://github.com/treeverse/lakeFS) - Data version control for your data lake that transforms object storage into Git-like repositories. Enables atomic, versioned data lake operations with branching, committing, and merging for data pipelines. Apache 2.0 licensed.
- **Apache Airflow** (https://github.com/apache/airflow) - Platform to programmatically author, schedule, and monitor workflows. Industry-standard orchestration for data pipelines and ML workflows with 500+ integrations. Apache 2.0 licensed.
- **Apache Spark** (https://github.com/apache/spark) - Unified analytics engine for large-scale data processing. In-memory cluster computing with high-level APIs in Python, Scala, Java, and R. Powers MLlib for distributed machine learning and Structured Streaming for real-time data. Apache 2.0 licensed.
- **Apache Flink** (https://github.com/apache/flink) - Stream processing framework with powerful batch and streaming capabilities. High-throughput, low-latency runtime with exactly-once processing guarantees. Ideal for real-time AI inference pipelines and event-driven ML applications. Apache 2.0 licensed.
- **Apache Beam** (https://github.com/apache/beam) - Unified programming model for batch and streaming data processing. Write pipelines once, run anywhere on Flink, Spark, or Google Cloud Dataflow. Portable, extensible, and enterprise-ready for AI data pipelines. Apache 2.0 licensed.
- **Scrapy** (https://github.com/scrapy/scrapy) - Fast, high-level web crawling and scraping framework for Python. Extract structured data from websites at scale with built-in support for handling common challenges like pagination, cookies, and concurrent requests. BSD-3-Clause licensed.
- **Temporal** (https://github.com/temporalio/temporal) - Durable execution platform for reliable workflow orchestration. Build resilient data pipelines and ML workflows that survive failures and continue execution exactly where they left off. MIT licensed.
- **Luigi** (https://github.com/spotify/luigi) - Python module for building complex pipelines of batch jobs. Handles dependency resolution, workflow management, visualization, and Hadoop integration. Built at Spotify and battle-tested in production. Apache 2.0 licensed.
- **Mage.ai** (https://github.com/mage-ai/mage-ai) - Modern open-source data pipeline tool for integrating and transforming data. AI-native ETL/ELT platform with 100+ integrations, real-time monitoring, and collaborative features. Apache 2.0 licensed.
- **Hamilton** (https://github.com/apache/hamilton) - Declarative dataflow framework for building testable, modular, self-documenting data pipelines. Encode lineage and metadata directly in Python functions. Originally from Stitch Fix, now Apache incubating. Apache 2.0 licensed.
- **D-Tale** (https://github.com/man-group/dtale) - Visualizer for Pandas data structures with a Flask back-end and React front-end. Interactive data exploration with charting, filtering, and code export. LGPL-2.1 licensed.
- **Sweetviz** (https://github.com/fbdesignpro/sweetviz) - Beautiful, high-density visualizations for exploratory data analysis in two lines of code. Self-contained HTML reports for dataset comparison and target analysis. MIT licensed.
- **TextAttack** (https://github.com/QData/TextAttack) - Python framework for adversarial attacks, data augmentation, and model training in NLP. Augment datasets to increase model robustness and generate adversarial examples. MIT licensed.
- **uv** (https://github.com/astral-sh/uv) - An extremely fast Python package and project manager, written in Rust. 10-100x faster than pip with built-in virtual environment management, dependency resolution, and lockfiles. Essential for modern AI/ML development workflows. Apache 2.0 and MIT dual-licensed.
- **Vector** (https://github.com/vectordotdev/vector) - A high-performance observability data pipeline for collecting, transforming, and routing logs and metrics. Real-time data processing with 50+ sources and sinks including Kafka, S3, and Elasticsearch. Ideal for AI/ML log processing and data ingestion. MPL 2.0 licensed.

### Data Engineering  (Data Engineering & Feature Stores)  — under 1. Core Frameworks & Libraries

- **DataHub** (https://github.com/datahub-project/datahub) - The #1 open-source metadata platform for data and AI. Data discovery, governance, and observability with 80+ connectors, column-level lineage, and AI assistant integration. Originally built at LinkedIn. Apache 2.0 licensed.
- **OpenMetadata** (https://github.com/open-metadata/OpenMetadata) - Unified metadata platform for data discovery, observability, and governance. Column-level lineage, semantic search, and team collaboration with 70+ data service connectors. Apache 2.0 licensed.
- **Amundsen** (https://github.com/amundsen-io/amundsen) - Data discovery and metadata engine from Lyft. PageRank-style search for data resources with usage-based ranking. LF AI & Data Foundation project. Apache 2.0 licensed.

### Data Transformation  (Data Transformation & Analytics Engineering)  — under 1. Core Frameworks & Libraries

- **dbt-core** (https://github.com/dbt-labs/dbt-core) - Transform data using software engineering best practices. The industry-standard framework for analytics engineering with 15M+ monthly downloads. Enables version control, testing, and documentation for SQL transformations. Apache 2.0 licensed.
- **SQLMesh** (https://github.com/TobikoData/sqlmesh) - Scalable and efficient data transformation framework with dbt compatibility. Features automatic data lineage, time travel, and virtual data environments for testing. Optimized for large-scale data warehouses. Apache 2.0 licensed.
- **SLayer** (https://github.com/MotleyAI/slayer) - Semantic layer for AI-powered data analytics. Allows AI agents to describe data models and query the data using an expressive format with measures, dimensions, and filters, without writing raw SQL. MCP, CLI, API, and Python clients. Embeddable as a Python library. MIT licensed.

### Data Quality  (Data Quality & Validation)  — under 1. Core Frameworks & Libraries

- **Deequ** (https://github.com/awslabs/deequ) - Library built on top of Apache Spark for defining "unit tests for data". Measures data quality in large datasets with constraint verification, anomaly detection, and incremental validation. Used at Amazon for production data quality. Apache 2.0 licensed.
- **Great Expectations** (https://github.com/great-expectations/great_expectations) - Always know what to expect from your data. Data validation, profiling, and documentation for data pipelines. Apache 2.0 licensed.
- **ydata-profiling** (https://github.com/ydataai/ydata-profiling) - One line of code for comprehensive data quality profiling and exploratory data analysis. Generates detailed reports for Pandas and Spark DataFrames including statistics, correlations, missing values, and data quality alerts. MIT licensed.
- **Soda Core** (https://github.com/sodadata/soda-core) - Data contracts engine for the modern data stack. Define data quality checks in YAML and automatically validate schema and data across your pipelines. Supports 20+ data sources including Snowflake, BigQuery, and PostgreSQL. Apache 2.0 licensed.
- **TFX (TensorFlow Extended)** (https://github.com/tensorflow/tfx) - End-to-end platform for deploying production ML pipelines. Data validation, transformation, model training, and serving with TensorFlow. Powers Google's production ML infrastructure. Apache 2.0 licensed.

### Data Labeling  (Data Labeling & Annotation)  — under 1. Core Frameworks & Libraries

- **Doccano** (https://github.com/doccano/doccano) - Open-source text annotation tool for machine learning practitioners. Features text classification, sequence labeling, and sequence-to-sequence tasks for sentiment analysis, NER, and summarization. MIT licensed.
- **OpenRefine** (https://github.com/OpenRefine/OpenRefine) - Free, open-source power tool for working with messy data. Clean, transform, and extend data with web services. Formerly Google Refine. BSD-3-Clause licensed.

### Orchestration - Multi-Agent  (Multi-Agent Orchestration)  — under 4. Agentic AI & Multi-Agent Systems

- **MetaGPT** (https://github.com/FoundationAgents/MetaGPT) - The Multi-Agent Framework: First AI Software Company. Assigns different roles to GPTs to form a collaborative software entity. Takes one-line requirements and outputs comprehensive software development artifacts including user stories, competitive analysis, requirements, data structures, APIs, and documents. ICLR 2024 oral presentation (top 1.2%). MIT licensed.
- **ChatDev** (https://github.com/OpenBMB/ChatDev) - Multi-agent software development framework where AI agents collaborate as programmers, designers, and testers to build software. Apache 2.0 licensed.
- **CAMEL** (https://github.com/camel-ai/camel) - First and best multi-agent framework for building scalable agent systems. Apache 2.0 licensed with extensive tooling for agent communication and task automation.
- **DeepAgents** (https://github.com/langchain-ai/deepagents) - Batteries-included LangChain agent harness for building and running structured multi-agent workflows with reusable runtime patterns.
- **Swarms** (https://github.com/kyegomez/swarms) - Bleeding-edge enterprise multi-agent orchestration.
- **Mastra** (https://github.com/mastra-ai/mastra) - TypeScript-first agent framework with built-in RAG, workflows, tool integrations, observability and observational memory.
- **Deer-Flow (ByteDance)** (https://github.com/bytedance/deer-flow) - Open-source long-horizon SuperAgent harness that researches, codes, and creates. Handles tasks from minutes to hours with sandboxes, memories, tools, skills, subagents, and message gateway.
- **OpenAI Agents SDK** (https://github.com/openai/openai-agents-python) - Production-ready lightweight framework for multi-agent workflows. The evolution of Swarm with enhanced orchestration capabilities and enterprise-grade features.
- **Symphony** (https://github.com/openai/symphony) - Turns project work into isolated, autonomous implementation runs. Monitors work boards, spawns agents to handle tasks, and provides proof of work including CI status, PR reviews, and walkthrough videos. Engineering preview for managing work instead of supervising coding agents. Apache 2.0 licensed.
- **Paperclip** (https://github.com/paperclipai/paperclip) - AI agent company and orchestration framework with 55K+ stars. MIT licensed.
- **AgentScope** (https://github.com/agentscope-ai/agentscope) - Alibaba's production-ready multi-agent framework with 23K+ stars. Features built-in MCP and A2A support, message hub for flexible orchestration, and AgentScope Runtime for production deployment.
- **mcp-agent** (https://github.com/lastmile-ai/mcp-agent) - Build effective agents using Model Context Protocol and simple workflow patterns. Handles connection mechanics, LLM integration, and persistent state for production MCP-based agents. MIT licensed.
- **Microsoft Agent Framework** (https://github.com/microsoft/agent-framework) - Microsoft's official framework combining AutoGen's agent abstractions with Semantic Kernel's enterprise features. Supports Python and .NET with graph-based workflows.
- **Agency Swarm** (https://github.com/VRSEN/agency-swarm) - Reliable multi-agent orchestration framework built on top of the OpenAI Assistants API with organizational structure modeling.
- **elizaOS** (https://github.com/elizaOS/eliza) - Autonomous multi-agent framework for building and deploying AI-powered applications. Features Discord/Telegram/Farcaster connectors, RAG support, and a modern web dashboard.
- **OpenManus** (https://github.com/FoundationAgents/OpenManus) - Open-source framework for building general AI agents. Modular agent architecture with planning, tool use, and autonomous task execution. 56k+ stars. MIT licensed.
- **OpenAgents** (https://github.com/openagents-org/openagents) - AI Agent Networks for Open Collaboration. Platform for building collaborative multi-agent systems with shared knowledge and distributed task execution. Apache 2.0 licensed.
- **Hive (Aden)** (https://github.com/aden-hive/hive) - Production-grade multi-agent orchestration framework with 10K+ stars. Apache 2.0 licensed.
- **Agent Squad (AWS Labs)** (https://github.com/awslabs/agent-squad) - Flexible multi-agent orchestration framework with intelligent intent classification and context management. Supports Python and TypeScript with pre-built agents for Bedrock, Lex, and custom integrations. Apache 2.0 licensed.
- **DeepResearchAgent** (https://github.com/SkyworkAI/DeepResearchAgent) - Hierarchical multi-agent system for deep research tasks with automated task decomposition and execution across complex domains.
- **Composio Agent Orchestrator** (https://github.com/ComposioHQ/agent-orchestrator) - Agentic orchestrator for parallel coding agents. Plans tasks, spawns agents, and autonomously handles CI fixes, merge conflicts, and code reviews. MIT licensed.
- **Open Multi-Agent** (https://github.com/JackChen-me/open-multi-agent) - TypeScript-native multi-agent orchestration with multi-model teams and parallel execution. Automatically converts goals to task DAGs. MIT licensed.
- **BeeAI Framework (IBM)** (https://github.com/i-am-bee/beeai-framework) - Production-ready multi-agent framework in Python and TypeScript. Features workflow orchestration, ACP/MCP protocol support, and deep watsonx integration. Part of Linux Foundation AI & Data program.
- **AI Town** (https://github.com/a16z-infra/ai-town) - Deployable starter kit for building virtual towns where AI characters live, chat and socialize. Inspired by Stanford's Generative Agents research with persistent agent memory and social interactions. MIT licensed.
- **Conductor OSS** (https://github.com/conductor-oss/conductor) - Event-driven agentic orchestration platform providing durable and resilient execution engine for applications and AI agents. Battle-tested at Netflix, Tesla, LinkedIn, and J.P. Morgan with 30K+ stars. Apache 2.0 licensed.
- **A2A Protocol** (https://github.com/a2aproject/A2A) - Agent2Agent (A2A) open protocol enabling communication and interoperability between opaque agentic applications. Donated to Linux Foundation by Google with 50+ technology partners. Apache 2.0 licensed.
- **777genius/agent-teams-ai** (https://github.com/777genius/agent-teams-ai) - Multi-agent orchestration runtime with Kanban-style team management, message review loops, and provider integrations for reusable agentic teams.
- **Panniantong/Agent-Reach** (https://github.com/Panniantong/Agent-Reach) - Reusable search and web-ingestion layer for AI agents spanning Reddit, X/Twitter, YouTube, GitHub, Bilibili and more through one CLI.
- **xerrors/Yuxi** (https://github.com/xerrors/Yuxi) - Self-hosted multi-tenant agent harness combining retrieval, knowledge graph grounding, and workflow orchestration for production teams.
- **Sim Studio** (https://github.com/simstudioai/sim) - Open-source AI workspace for building, deploying, and orchestrating AI agents. Visual canvas with 1000+ integrations, multi-framework support (Agno, OpenAI, LangChain, Google ADK), and self-hosted or cloud deployment. Apache 2.0 licensed.
- **2FastLabs Agent Squad** (https://github.com/2FastLabs/agent-squad) - Flexible, lightweight open-source framework for orchestrating multiple AI agents to handle complex conversations with parallel execution capabilities. Apache 2.0 licensed.
- **SIA** (https://github.com/hexo-ai/sia) - Self-improving framework that orchestrates meta, target, and feedback agents to autonomously optimize the performance of AI models and agents on benchmark tasks. MIT licensed.
- **Council of High Intelligence** (https://github.com/0xNyk/council-of-high-intelligence) - Multi-agent deliberation framework that routes specialized personas across different LLM providers to debate topics and reach consensus.
- **Gas Town** (https://github.com/gastownhall/gastown) - Multi-agent workspace manager and orchestration system for Claude Code and other coding agents with persistent work tracking, mailboxes, and automated merge queues. MIT licensed.

### Vector DBs  (Vector Databases & Search Engines)  — under 5. Retrieval-Augmented Generation (RAG) & Knowledge

- **Chroma** (https://github.com/chroma-core/chroma) - Most popular open-source embedding database.
- **Qdrant** (https://github.com/qdrant/qdrant) - High-performance vector search engine in Rust.
- **Weaviate** (https://github.com/weaviate/weaviate) - GraphQL-native vector search engine.
- **Milvus** (https://github.com/milvus-io/milvus) - Scalable cloud-native vector database.
- **NornicDB** (https://github.com/orneryd/NornicDB) - Low-latency graph and vector hybrid retrieval database in Go with Neo4j and Qdrant-compatible drivers.
- **Faiss** (https://github.com/facebookresearch/faiss) - Similarity search and clustering library for dense vectors with CPU and GPU implementations.
- **LanceDB** (https://github.com/lancedb/lancedb) - Serverless vector DB optimized for multimodal data.
- **Vespa** (https://github.com/vespa-engine/vespa) - AI + Data platform with hybrid search (vector + keyword) and real-time indexing at scale. Battle-tested serving billions of queries daily.
- **pgvector** (https://github.com/pgvector/pgvector) - PostgreSQL extension for vector similarity search.
- **pgvectorscale** (https://github.com/timescale/pgvectorscale) - PostgreSQL extension for scalable vector search with DiskANN algorithm. Complements pgvector with significantly faster search and higher recall at large scale. PostgreSQL licensed.
- **VectorChord** (https://github.com/tensorchord/VectorChord) - Scalable, fast, and disk-friendly vector search in Postgres. Successor to pgvecto.rs with production-grade performance and efficient storage. AGPL-3.0 licensed.
- **Quickwit** (https://github.com/quickwit-oss/quickwit) - Cloud-native search engine for observability. Open-source alternative to Datadog, Elasticsearch, Loki, and Tempo with native vector search support.
- **Tantivy** (https://github.com/quickwit-oss/tantivy) - Full-text search engine library inspired by Apache Lucene and written in Rust. Powers Quickwit and other production search systems.
- **Manticore Search** (https://github.com/manticoresoftware/manticoresearch) - Easy to use open source fast database for search. Good alternative to Elasticsearch with SQL-like interface and vector search capabilities.
- **OpenSearch** (https://github.com/opensearch-project/OpenSearch) - Open-source distributed and RESTful search and analytics suite with native vector search. Enterprise-grade fork of Elasticsearch with k-NN plugin for semantic search at scale.
- **Marqo** (https://github.com/marqo-ai/marqo) - Multimodal vector search for text, image, and structured data. End-to-end indexing and search with built-in embedding models. Apache 2.0 licensed.
- **Vald** (https://github.com/vdaas/vald) - Highly scalable distributed vector search engine. Cloud-native architecture with automatic indexing, horizontal scaling, and multiple ANN algorithm support. Apache 2.0 licensed.
- **hnswlib** (https://github.com/nmslib/hnswlib) - Header-only C++ library for fast approximate nearest neighbors with Python bindings. Supports CRUD operations and concurrent read/write - unique among ANN libraries. Powers many production vector databases. Apache 2.0 licensed.
- **turbovec** (https://github.com/RyanCodrai/turbovec) - Rust-native high-performance vector index with Python bindings optimized for fast ANN search and SIMD acceleration on modern CPUs. MIT licensed.
- **sqlite-vec** (https://github.com/asg017/sqlite-vec) - A vector search SQLite extension that runs anywhere. Extremely small, "fast enough" vector search written in pure C with no dependencies. Perfect for embedded and edge deployments. MIT/Apache-2.0 dual licensed.
- **zvec** (https://github.com/alibaba/zvec) - Lightweight, lightning-fast, in-process vector database from Alibaba. Built on Proxima (Alibaba's battle-tested vector search engine) for production-grade, low-latency similarity search. Apache 2.0 licensed.
- **Meilisearch** (https://github.com/meilisearch/meilisearch) - Lightning-fast search engine API with AI-powered hybrid search. Features typo-tolerant full-text search combined with HNSW-based vector search for semantic retrieval. MIT licensed.
- **Typesense** (https://github.com/typesense/typesense) - Open source alternative to Algolia + Pinecone. Fast, typo-tolerant, in-memory fuzzy search engine with native vector search capabilities. GPL-3.0 licensed.
- **Elasticsearch** (https://github.com/elastic/elasticsearch) - Distributed search and analytics engine with native k-NN vector search, hybrid search, and dense vector indexing. Industry-standard for full-text search now with powerful semantic search capabilities. AGPL-3.0/Elastic-2.0 dual licensed.
- **Apache Solr** (https://github.com/apache/solr) - Mature Lucene-based search platform with dense vector search, filtering, faceting, and hybrid retrieval patterns for production search-heavy RAG systems.
- **RediSearch** (https://github.com/RediSearch/RediSearch) - Full-text, secondary indexing, and vector similarity search for Redis deployments. Useful when retrieval needs low-latency Redis-native search.
- **ParadeDB** (https://github.com/paradedb/paradedb) - Postgres-native search and analytics engine for full-text, faceted, and hybrid retrieval without moving data out of PostgreSQL.
- **Orama** (https://github.com/oramasearch/orama) - Lightweight search engine with full-text, vector, and hybrid search for browser, server, and edge applications.
- **HelixDB** (https://github.com/HelixDB/helix-db) - Graph-vector database for retrieval systems that need relationship traversal alongside semantic search.
- **USearch** (https://github.com/unum-cloud/usearch) - Fast single-file similarity search & clustering engine for vectors. Smaller and faster than FAISS with 20+ language bindings (C++, Python, JavaScript, Rust, Java, Go, etc.) and support for custom metrics. Apache 2.0 licensed.
- **Voyager (Spotify)** (https://github.com/spotify/voyager) - Spotify's next-gen approximate nearest-neighbor search library for Python and Java. Up to 10x faster than Annoy with 4x less memory, designed for production use at billion-vector scale. Apache 2.0 licensed.
- **Deep Lake** (https://github.com/activeloopai/deeplake) - AI Data Runtime for Agents with serverless PostgreSQL and multimodal datalake. Store and search vectors, images, text, videos, and more with LangChain/LlamaIndex integrations. Used by Intel, Bayer, Yale, and Oxford. Apache 2.0 licensed.
- **DiskANN (Microsoft)** (https://github.com/microsoft/DiskANN) - Graph-structured indices for scalable, fast, fresh and filtered approximate nearest neighbor search. Handles billion-vector datasets on a single node with SSD-based indexing. MIT licensed.
- **SPTAG (Microsoft)** (https://github.com/microsoft/SPTAG) - Distributed approximate nearest neighbor search library with high-quality vector index build and online serving toolkits. Powers Bing's vector search at trillion-vector scale. MIT licensed.
- **nanoflann** (https://github.com/jlblancoc/nanoflann) - C++11 header-only library for fast nearest neighbor search with KD-trees. Zero dependencies, single-file integration, and 2-3x faster than FLANN with modern C++. BSD licensed.
- **NMSLIB** (https://github.com/nmslib/nmslib) - Non-Metric Space Library for efficient similarity search in generic non-metric spaces. Comprehensive toolkit for evaluating k-NN methods with support for exotic distance functions. Apache 2.0 licensed.
- **Vearch** (https://github.com/vearch/vearch) - Cloud-native distributed vector database for AI-native applications. Efficient similarity search of embedding vectors with horizontal scaling and real-time indexing. Apache 2.0 licensed.
- **JVector (DataStax)** (https://github.com/datastax/jvector) - The most advanced embedded vector search engine for Java. DiskANN-based algorithm for billion-scale vector search with efficient memory mapping. Apache 2.0 licensed.
- **VectorDBBench (Zilliz)** (https://github.com/zilliztech/VectorDBBench) - Industry-standard benchmark suite for vector databases. Test and compare performance of Milvus, Zilliz Cloud, and other vector DBs with your own datasets. MIT licensed.

### Embeddings  (Embedding Models)  — under 5. Retrieval-Augmented Generation (RAG) & Knowledge

- **BGE (FlagEmbedding)** (https://github.com/FlagOpen/FlagEmbedding) - BAAI's best-in-class embedding family.
- **E5 (Microsoft)** (https://github.com/microsoft/unilm) - High-performance text embeddings for retrieval.
- **FastEmbed (Qdrant)** (https://github.com/qdrant/fastembed) - Lightweight, fast Python library for embedding generation with ONNX Runtime. Supports text, sparse (SPLADE), and late-interaction (ColBERT) embeddings without GPU dependencies. Apache 2.0 licensed.
- **EmbedAnything** (https://github.com/StarlightSearch/EmbedAnything) - Minimalist, highly performant multimodal embedding pipeline built in Rust. Memory-safe, modular, and production-ready for text, image, and audio embeddings with seamless vector DB integration. Apache 2.0 licensed.
- **Text Embeddings Inference (Hugging Face)** (https://github.com/huggingface/text-embeddings-inference) - Blazing fast inference solution for text embedding models. High-performance extraction with token-based dynamic batching, Flash Attention, and support for FlagEmbedding, E5, GTE, and more. OpenAI-compatible API with Docker deployment. Apache 2.0 licensed.

### RAG / Retrieval  (RAG Frameworks & Advanced Retrieval Tools)  — under 5. Retrieval-Augmented Generation (RAG) & Knowledge

- **EmbedChain** (https://github.com/embedchain/embedchain) - Universal memory layer for AI agents. Simple API to create RAG applications over any dataset with support for multiple vector stores, embedding models, and LLM providers. Apache 2.0 licensed.
- **LlamaIndex** (https://github.com/run-llama/llama_index) - Full-featured RAG pipeline with advanced indexing.
- **Haystack** (https://github.com/deepset-ai/haystack) - End-to-end NLP and RAG framework.
- **RAGFlow** (https://github.com/infiniflow/ragflow) - Deep-document-understanding RAG engine.
- **GraphRAG (Microsoft)** (https://github.com/microsoft/graphrag) - Knowledge-graph-based RAG.
- **Docling** (https://github.com/docling-project/docling) - Document processing toolkit for turning PDFs and other files into structured data for GenAI workflows.
- **Unstructured** (https://github.com/Unstructured-IO/unstructured) - Best-in-class document preprocessing.
- **MinerU** (https://github.com/opendatalab/MinerU) - High-accuracy document parsing for LLM and RAG workflows. Converts PDFs, Word, PPTs, and images into structured Markdown/JSON with VLM+OCR dual engine.
- **Marker** (https://github.com/datalab-to/marker) - Fast, accurate PDF-to-markdown converter with table extraction, equation handling, and optional LLM enhancement for RAG pipelines.
- **ColPali / ColQwen** (https://github.com/illuin-tech/colpali) - Vision-language models for document retrieval.
- **LightRAG** (https://github.com/HKUDS/LightRAG) - Graph-based RAG with dual-level retrieval system. Simple and fast with comprehensive knowledge discovery (EMNLP 2025).
- **RAG-Anything** (https://github.com/HKUDS/RAG-Anything) - All-in-One Multimodal RAG system for seamless processing of text, images, tables, and equations. Built on LightRAG.
- **RAGLite (Superlinear)** (https://github.com/superlinear-ai/raglite) - Python toolkit for RAG with DuckDB or PostgreSQL. Lightweight, efficient retrieval-augmented generation without heavy dependencies. MPL 2.0 licensed.
- **GPT-RAG (Azure)** (https://github.com/Azure/GPT-RAG) - Enterprise RAG pattern for Azure OpenAI at scale. Secure, production-ready architecture using Azure Cognitive Search and Azure OpenAI LLMs for ChatGPT-style Q&A experiences. MIT licensed.
- **LangChain4j** (https://github.com/langchain4j/langchain4j) - Java library for integrating LLMs into Java applications. Implements RAG, tool calling (including MCP support), and agents with seamless integration into enterprise Java frameworks like Spring Boot. Apache 2.0 licensed.
- **Kernel Memory (Microsoft)** (https://github.com/microsoft/kernel-memory) - Memory solution for users, teams, and applications. RAG pipelines with document ingestion, vector indexing, and natural language querying with citations. Supports multiple LLM providers and vector stores. MIT licensed.
- **txtai** (https://github.com/neuml/txtai) - All-in-one AI framework for semantic search, LLM orchestration and language model workflows. Embeddings database with customizable pipelines.
- **Infinity (Embeddings Server)** (https://github.com/michaelfeil/infinity) - High-throughput, low-latency serving engine for text-embeddings, reranking, CLIP, and ColPali. OpenAI-compatible API.
- **FlashRAG** (https://github.com/RUC-NLPIR/FlashRAG) - Efficient toolkit for RAG research with 40+ retrieval and reranking models, 20+ benchmark datasets, and optimized evaluation pipelines (WWW 2025 Resource). MIT licensed.
- **DocsGPT** (https://github.com/arc53/DocsGPT) - Private AI platform for building intelligent agents and assistants with enterprise search. Features Agent Builder, deep research tools, multi-format document analysis, and multi-model support. MIT licensed.
- **llmware** (https://github.com/llmware-ai/llmware) - Unified framework for building enterprise RAG pipelines with small, specialized models. Optimized for AI PC and local deployment with 300+ models in catalog. Apache 2.0 licensed.
- **AutoFlow** (https://github.com/pingcap/autoflow) - Graph RAG-based conversational knowledge base tool built on TiDB Vector and LlamaIndex. Features Perplexity-style search with built-in website crawler. Apache 2.0 licensed.
- **KAG (OpenSPG)** (https://github.com/OpenSPG/KAG) - Knowledge Augmented Generation framework for logical reasoning and factual Q&A in professional domains. Builds on OpenSPG knowledge graph engine to overcome traditional RAG vector similarity limitations. Supports multi-hop reasoning with schema-constrained knowledge construction. Apache 2.0 licensed.
- **Chonkie** (https://github.com/chonkie-inc/chonkie) - Lightweight document chunking library for fast, efficient RAG pipelines. Memory-safe with multiple chunking strategies (semantic, token, recursive) and direct vector DB integration. MIT licensed.
- **PageIndex (VectifyAI)** (https://github.com/VectifyAI/PageIndex) - Vectorless, reasoning-based RAG framework using document index structure. Achieves high accuracy without vector databases through intelligent context engineering and reasoning-based retrieval. MIT licensed.
- **Kotaemon (Cinnamon)** (https://github.com/Cinnamon/kotaemon) - Open-source RAG-based tool for chatting with your documents. Hybrid RAG pipeline with full-text and vector retriever, re-ranking, and multi-modal capabilities. Clean Gradio-based UI with support for local and API-based LLMs. Apache 2.0 licensed.
- **Reader (Jina AI)** (https://github.com/jina-ai/reader) - Convert any URL to LLM-friendly input with a simple prefix (r.jina.ai). Free service that extracts article content, removes clutter, and returns clean Markdown for RAG and agentic workflows. Apache 2.0 licensed.
- **UltraRAG (OpenBMB)** (https://github.com/OpenBMB/UltraRAG) - First lightweight RAG framework based on Model Context Protocol (MCP) architecture. Low-code RAG pipeline builder with comprehensive evaluation system and DeepResearch capabilities. From Tsinghua THUNLP, NEUIR, OpenBMB, and AI9stars. Apache 2.0 licensed.
- **Semantic Router** (https://github.com/aurelio-labs/semantic-router) - Superfast AI decision-making layer for LLMs and agents. Uses semantic vector space to route requests using semantic meaning rather than waiting for slow LLM generations. Cuts routing time from seconds to milliseconds. MIT licensed.
- **Neurite** (https://github.com/satellitecomponent/Neurite) - Fractal Graph-of-Thought mind-mapping for AI agents, web-links, notes, and code. Rhizomatic workspace blending chaos theory, graph theory, and fractal logic for creative thinking and RAG workflows. MIT licensed.
- **Pathway** (https://github.com/pathwaycom/pathway) - Python ETL framework for stream processing, real-time analytics, LLM pipelines, and RAG. Features 350+ connectors with always-in-sync data from SharePoint, Google Drive, S3, Kafka, PostgreSQL and more. BSL 1.1 license (becomes Apache 2.0 after 4 years).
- **Infinity (AI Database)** (https://github.com/infiniflow/infinity) - AI-native database built for LLM applications with incredibly fast hybrid search of dense vector, sparse vector, tensor (multi-vector), and full-text. Powers RAGFlow's document engine. Apache 2.0 licensed.
- **PrivateGPT** (https://github.com/zylon-ai/private-gpt) - Private document Q&A project for local and offline RAG workflows where data stays inside the user's environment.
- **FastGPT** (https://github.com/labring/FastGPT) - Knowledge-base platform with RAG retrieval, document processing, visual AI workflows, and self-hosted deployment options.
- **MaxKB** (https://github.com/1Panel-dev/MaxKB) - Self-hostable knowledge-base and agent platform for document ingestion, RAG pipelines, and enterprise assistant workflows.
- **DB-GPT** (https://github.com/eosphoros-ai/DB-GPT) - Self-hosted AI data assistant for private knowledge, database-aware conversations, and data-heavy RAG workflows.
- **localGPT** (https://github.com/PromtEngineer/localGPT) - Local document-chat project for private, on-device Q&A over files without sending data to external APIs.
- **SurfSense** (https://github.com/MODSetter/SurfSense) - Privacy-focused NotebookLM-style workspace for teams to search, organize, and query knowledge with self-hosted RAG.
- **Morphik** (https://github.com/morphik-org/morphik-core) - Open-source multimodal RAG framework for building AI apps over private knowledge. Handles text, images, and documents with built-in embedding generation and vector search. MIT licensed.

### Web Ingestion  (Web Data Ingestion)  — under 5. Retrieval-Augmented Generation (RAG) & Knowledge

- **Crawl4AI** (https://github.com/unclecode/crawl4ai) - LLM-friendly web crawler that turns websites into clean Markdown for RAG and agentic workflows.
- **Scrapling** (https://github.com/D4Vinci/Scrapling) - Adaptive web scraping and crawling framework for robust structured extraction from pages to large-scale pipelines.
- **Lightpanda** (https://github.com/lightpanda-io/browser) - Machine-first headless browser in Zig; rendering-free and ultra-lightweight for AI agent browsing.
- **Paperless-AI** (https://github.com/clusterzx/paperless-ai) - Automated document analyzer for Paperless-ngx with RAG-powered semantic search across your document archive.
- **Firecrawl** (https://github.com/firecrawl/firecrawl) - Web Data API for AI - search, scrape, and interact with the web at scale. Clean markdown/JSON output with proxy rotation and JS-blocking handled automatically.
- **invisible-playwright** (https://github.com/feder-cr/invisible_playwright) - Playwright wrapper for a stealth-patched Firefox 150 binary. Drop-in Browser object for AI agents that need to ingest web data from sites with anti-bot guardrails (reCAPTCHA, FingerprintPro, Cloudflare). Spoofing happens in C++ source, not via JS overrides. MIT (wrapper) + MPL-2.0 (patches).

### Chunking / Document Preprocessing  (Document Conversion & Preprocessing)  — under 5. Retrieval-Augmented Generation (RAG) & Knowledge

- **OpenDataLoader PDF** (https://github.com/opendataloader-project/opendataloader-pdf) - Accessibility-aware PDF parser and conversion pipeline for AI-ready markdown and structured data workflows.
- **MarkItDown (Microsoft)** (https://github.com/microsoft/markitdown) - Python tool for converting files and office documents to Markdown. Supports PDF, PowerPoint, Word, Excel, images, audio, HTML, and more with OCR and transcription capabilities. MIT licensed.
- **LiteParse** (https://github.com/run-llama/liteparse) - Lightweight document parsing toolkit for AI and RAG pipelines with PDF/OCR extraction and clean preprocessing defaults.
- **PaddleOCR** (https://github.com/PaddlePaddle/PaddleOCR) - Large-scale OCR suite with detection, recognition, and layout analysis, used widely for document digitization and downstream RAG pipelines.
- **DocETL (UC Berkeley)** (https://github.com/ucbepic/docetl) - Agentic LLM-powered data processing and ETL system for complex document processing. Query rewriting and evaluation for unstructured data analysis with 80% higher accuracy than baselines. MIT licensed.
- **olmOCR (Allen Institute for AI)** (https://github.com/allenai/olmocr) - Toolkit for reconstructing and linearizing PDF documents into clean text optimized for LLM datasets, training, and RAG pipelines. Apache 2.0 licensed.

### Training - Full Frameworks  (Full Training Frameworks)  — under 7. Training & Fine-tuning Ecosystem

- **Oumi** (https://github.com/oumi-ai/oumi) - Fully open-source platform for the complete foundation model lifecycle - from data preparation and training to evaluation and deployment. Supports 100+ models with 200+ recipes for fine-tuning gpt-oss, Qwen3, DeepSeek-R1, and more. Apache 2.0 licensed.
- **Marin** (https://github.com/marin-community/marin) - Open-source framework for foundation-model development with composable data, training, and evaluation pipelines for modern LLM research.
- **LLaMA-Factory** (https://github.com/hiyouga/LLaMA-Factory) - One-stop unified framework for SFT, DPO, ORPO, KTO with web UI.
- **Axolotl** (https://github.com/axolotl-ai-cloud/axolotl) - YAML-driven full pipeline for SFT, DPO, GRPO.
- **ms-swift** (https://github.com/modelscope/ms-swift) - Unified training framework for 600+ LLMs and 300+ MLLMs with CPT/SFT/DPO/GRPO (AAAI 2025).
- **Unsloth** (https://github.com/unslothai/unsloth) - 2× faster, 70% less memory fine-tuning.
- **LitGPT** (https://github.com/Lightning-AI/litgpt) - Clean from-scratch implementations of 20+ LLMs.
- **LLM Foundry** (https://github.com/mosaicml/llm-foundry) - Databricks' training framework for composable LLM training with StreamingDataset and Composer.
- **torchtune** (https://github.com/pytorch/torchtune) - PyTorch-native library for post-training, fine-tuning, and experimentation with LLMs.
- **kohya_ss** (https://github.com/bmaltais/kohya_ss) - Gradio-based GUI and CLI for training Stable Diffusion models (LoRA, Dreambooth, fine-tuning, SDXL). Provides accessible interface to Kohya's powerful training scripts.
- **TRL (Transformers Reinforcement Learning)** (https://github.com/huggingface/trl) - Official library for RLHF, SFT, DPO, ORPO.
- **verl** (https://github.com/volcengine/verl) - Volcano Engine Reinforcement Learning for LLMs with PPO, GRPO, REINFORCE++, DAPO (EuroSys 2025).
- **NeMo-RL** (https://github.com/NVIDIA-NeMo/RL) - Scalable toolkit for efficient model reinforcement with DTensor and Megatron backends.
- **OpenRLHF** (https://github.com/OpenRLHF/OpenRLHF) - Easy-to-use, scalable RLHF framework based on Ray. Supports PPO, GRPO, REINFORCE++, DAPO with vLLM integration and async training. Apache 2.0 licensed.
- **LMFlow** (https://github.com/OptimalScale/LMFlow) - Extensible toolkit for finetuning and inference of large foundation models. Features RAFT alignment algorithm and comprehensive model support. Apache 2.0 licensed.
- **XTuner** (https://github.com/InternLM/xtuner) - A next-generation training engine built for ultra-large MoE models with efficient QLoRA and full-parameter fine-tuning. Apache 2.0 licensed.
- **Ludwig** (https://github.com/ludwig-ai/ludwig) - Low-code framework for building custom LLMs and deep neural networks. Declarative YAML configuration for training state-of-the-art models with PEFT/LoRA, 4-bit quantization, distributed training via Hugging Face Accelerate, and native Kubernetes support. Linux Foundation AI project. Apache 2.0 licensed.
- **TorchTitan (PyTorch)** (https://github.com/pytorch/torchtitan) - PyTorch native platform for training generative AI models at scale. Showcases 4D parallelism (FSDP, tensor, pipeline, context) for LLM pretraining with 65%+ speedups over optimized baselines. BSD-3-Clause licensed.
- **VeOmni (ByteDance)** (https://github.com/ByteDance-Seed/VeOmni) - Versatile framework for both single- and multi-modal pre-training and post-training. Model-centric distributed recipe zoo supporting text, vision, audio, and video models with unified training interface. Apache 2.0 licensed.
- **H2O LLM Studio** (https://github.com/h2oai/h2o-llmstudio) - No-code GUI framework for fine-tuning LLMs. Streamlined interface for SFT, reward modeling, and model deployment. Apache 2.0 licensed.
- **TinyZero** (https://github.com/Jiayi-Pan/TinyZero) - Minimal reproduction of DeepSeek R1-Zero for countdown and multiplication tasks. Clean, accessible implementation for understanding RL-based reasoning training. Apache 2.0 licensed.
- **PRIME-RL** (https://github.com/PrimeIntellect-ai/prime-rl) - Agentic RL Training at Scale from Prime Intellect. Framework for large-scale reinforcement learning capable of scaling to 1000+ GPUs with fully asynchronous RL, FSDP2 training, and vLLM inference. Apache 2.0 licensed.
- **slime** (https://github.com/THUDM/slime) - LLM post-training framework for RL Scaling from THUDM. Supports SFT and RL training with multi-turn compilation feedback, powering projects like TritonForge for automated GPU kernel generation. Apache 2.0 licensed.
- **rLLM** (https://github.com/rllm-org/rllm) - Democratizing Reinforcement Learning for LLMs. Framework for training AI agents with RL featuring near-zero code changes, CLI-first workflow, and 50+ built-in benchmarks. Supports GRPO, REINFORCE, RLOO with verl and tinker backends. Apache 2.0 licensed.
- **EasyR1** (https://github.com/hiyouga/EasyR1) - Efficient, scalable, multi-modality RL training framework based on veRL. Extends veRL to support vision-language models with GRPO algorithm for efficient RL training. Apache 2.0 licensed.
- **LeRobot** (https://github.com/huggingface/lerobot) - Making AI for robotics more accessible with end-to-end learning. State-of-the-art approaches for imitation learning and reinforcement learning with pretrained models, datasets, and simulated environments. Apache 2.0 licensed.
- **AI-Toolkit** (https://github.com/ostris/ai-toolkit) - Ultimate training toolkit for finetuning diffusion models. Easy-to-use all-in-one training suite supporting FLUX.1, FLUX.2, Stable Diffusion, and video models with both GUI and CLI interfaces. Consumer-grade hardware friendly with comprehensive LoRA and full fine-tuning support. MIT licensed.
- **OneTrainer** (https://github.com/Nerogar/OneTrainer) - One-stop solution for all your Diffusion training needs. Supports FLUX, Stable Diffusion 1.5/2.x/3.x/SDXL, Würstchen, PixArt, Hunyuan Video and more. Features full fine-tuning, LoRA, embeddings, masked training, automatic backups, and TensorBoard integration. GPL-3.0 licensed.
- **FluxGym** (https://github.com/cocktailpeanut/fluxgym) - Dead simple FLUX LoRA training UI with LOW VRAM support (12GB/16GB/20GB). WebUI forked from AI-Toolkit with backend powered by Kohya Scripts. Combines simplicity of Gradio interface with flexibility of Kohya's powerful training scripts. GPL-3.0 licensed.
- **MiniMind** (https://github.com/jingyaogong/minimind) - Train a 64M-parameter LLM from scratch in just 2 hours for $3. Complete from-scratch implementation covering MoE, data cleaning, pretraining, SFT, LoRA, RLHF (DPO/PPO/GRPO), tool use, and model distillation. All core algorithms implemented in pure PyTorch without high-level abstractions. Educational framework for understanding LLM internals. Apache 2.0 licensed.
- **FastChat** (https://github.com/lm-sys/FastChat) - Open platform for training, serving, and evaluating large language model chatbots. Powers Chatbot Arena (lmarena.ai) serving 10M+ requests for 70+ LLMs. Includes training code for Vicuna, MT-Bench evaluation, and distributed multi-model serving with OpenAI-compatible APIs. Apache 2.0 licensed.
- **PaddleNLP** (https://github.com/PaddlePaddle/PaddleNLP) - Easy-to-use and powerful LLM library built on Baidu's PaddlePaddle framework. Supports 100+ models with efficient training, compression, and high-performance inference on diverse hardware. Features RsLoRA+ algorithm, DeepSeek V3/R1 support with FP8/INT8 quantization, and unified checkpointing. Apache 2.0 licensed.

### Training - PEFT  (LoRA / PEFT Tools)  — under 7. Training & Fine-tuning Ecosystem

- **PEFT (Parameter-Efficient Fine-Tuning)** (https://github.com/huggingface/peft) - Official library with LoRA, QLoRA, DoRA, etc.
- **Liger Kernel** (https://github.com/linkedin/Liger-Kernel) - Ultra-fast custom kernels for training speedup.
- **MergeKit** (https://github.com/arcee-ai/mergekit) - Advanced model merging tools.

### Training - Synthetic Data  (Synthetic Data Generation)  — under 7. Training & Fine-tuning Ecosystem

- **distilabel** (https://github.com/argilla-io/distilabel) - End-to-end pipeline for synthetic instruction data.
- **Data-Juicer** (https://github.com/alibaba/data-juicer) - High-performance data processing for LLM training.
- **Argilla** (https://github.com/argilla-io/argilla) - Open-source data labeling + synthetic data platform.
- **SDV (Synthetic Data Vault)** (https://github.com/sdv-dev/SDV) - High-fidelity tabular and relational synthetic data.
- **DataTrove (Hugging Face)** (https://github.com/huggingface/datatrove) - Platform-agnostic data processing pipelines for LLM training at scale. Handles filtering, deduplication, and tokenization on local machines or SLURM clusters.
- **Bespoke Curator** (https://github.com/bespokelabsai/curator) - Synthetic data curation for post-training and structured data extraction. Makes it easy to build pipelines around LLMs with batching and progress tracking. Apache 2.0 licensed.
- **SDG (Harbin Institute)** (https://github.com/hitsz-ids/synthetic-data-generator) - Specialized framework for generating high-quality structured tabular synthetic data with CTGAN models supporting billion-level data processing. Apache 2.0 licensed.

### Training - Distributed  (Distributed Training)  — under 7. Training & Fine-tuning Ecosystem

- **DeepSpeed** (https://github.com/deepspeedai/DeepSpeed) - Extreme-scale training optimizations.
- **Colossal-AI** (https://github.com/hpcaitech/ColossalAI) - Unified system for 100B+ models.
- **Megatron-LM** (https://github.com/NVIDIA/Megatron-LM) - Distributed training framework and reference codebase for large transformer models at scale.
- **Ray Train** (https://github.com/ray-project/ray) - Scalable distributed training.
- **Nanotron (Hugging Face)** (https://github.com/huggingface/nanotron) - Minimalistic 3D-parallelism LLM pretraining with tensor, pipeline, and data parallelism. Designed for simplicity and speed.
- **veScale (ByteDance)** (https://github.com/volcengine/veScale) - Hyperscale PyTorch distributed training with flexible FSDP implementation for LLMs and RL training at scale.
- **RLinf** (https://github.com/RLinf/RLinf) - Scalable open-source RL infrastructure for post-training foundation models via reinforcement learning. Features M2Flow paradigm for embodied AI and agentic workflows with real-world robotics integrations. Apache 2.0 licensed.
- **dstack** (https://github.com/dstackai/dstack) - Vendor-agnostic orchestration for training, inference and agentic workloads across NVIDIA, AMD, TPU, and Tenstorrent on clouds, Kubernetes, and bare metal. MPL-2.0 licensed.
- **Streaming (MosaicML)** (https://github.com/mosaicml/streaming) - High-performance data streaming library for efficient neural network training. Streams training data from cloud storage (S3, GCS, Azure) with local caching and deterministic shuffling. Apache 2.0 licensed.

### Training - Quantization  (Model Quantization & Optimization)  — under 7. Training & Fine-tuning Ecosystem

- **LLM Compressor (vLLM)** (https://github.com/vllm-project/llm-compressor) - Transformers-compatible library for applying various compression algorithms to LLMs for optimized deployment with vLLM. Supports GPTQ, AWQ, SmoothQuant, AutoRound, and FP8/INT8 quantization with seamless Hugging Face integration.
- **NVIDIA Model Optimizer** (https://github.com/NVIDIA/Model-Optimizer) - Unified library of SOTA model optimization techniques including quantization, pruning, distillation, and speculative decoding. Compresses deep learning models for deployment with TensorRT-LLM, TensorRT, and vLLM to optimize inference speed across NVIDIA hardware.

### Orchestration - Deployment  (Deployment & Orchestration)  — under 8. MLOps / LLMOps & Production

- **BentoML** (https://github.com/bentoml/BentoML) - Unified framework to build, ship, and scale AI apps.
- **ZenML** (https://github.com/zenml-io/zenml) - Pipeline and orchestration framework for taking ML and LLM systems from development to production.
- **Kubeflow** (https://github.com/kubeflow/kubeflow) - Kubernetes-native ML/LLM platform.
- **KServe** (https://github.com/kserve/kserve) - Kubernetes-based model serving.
- **Seldon Core** (https://github.com/SeldonIO/seldon-core) - MLOps and LLMOps framework for deploying, managing and scaling AI systems in Kubernetes. Standardized deployment across model types with autoscaling, multi-model serving, and A/B experiments.
- **Metaflow** (https://github.com/Netflix/metaflow) - Netflix's ML platform for building and managing real-world AI systems. Powers thousands of projects at Netflix, Amazon, and DoorDash. Apache 2.0 licensed.
- **Flyte** (https://github.com/flyteorg/flyte) - Kubernetes-native workflow orchestration platform for AI/ML pipelines. Dynamic, resilient orchestration with strong type safety and reproducibility. Used by Lyft, Spotify, and Gojek. Apache 2.0 licensed.
- **Prefect** (https://github.com/prefecthq/prefect) - Workflow orchestration framework for building resilient data and ML pipelines. Python-native with modern observability and 200+ integrations. Apache 2.0 licensed.
- **Dagster** (https://github.com/dagster-io/dagster) - Cloud-native orchestration platform for developing and maintaining data assets including ML models. Declarative programming model with integrated lineage and observability. Apache 2.0 licensed.
- **Kubeflow Pipelines** (https://github.com/kubeflow/pipelines) - Machine Learning Pipelines for Kubeflow. Platform for building and deploying portable, scalable ML workflows using Kubernetes and Argo. Apache 2.0 licensed.
- **Argo Workflows** (https://github.com/argoproj/argo-workflows) - CNCF graduated container-native workflow engine for orchestrating parallel jobs on Kubernetes. Powers Kubeflow Pipelines and widely used for ML/data processing at scale. Apache 2.0 licensed.
- **MLRun** (https://github.com/mlrun/mlrun) - Open-source AI orchestration platform for quickly building and managing continuous ML and generative AI applications across their lifecycle. Automates data preparation, model tuning, and deployment. Apache 2.0 licensed.
- **Kestra** (https://github.com/kestra-io/kestra) - Event-driven orchestration and scheduling platform for mission-critical workflows. Infrastructure-as-Code approach with declarative YAML, Git version control integration, and hundreds of plugins for data pipelines and ML workflows. Apache 2.0 licensed.
- **KitOps** (https://github.com/jozu-ai/kitops) - CNCF open source DevOps tool for packaging, versioning, and securely sharing AI/ML models, datasets, code, and configuration. Packages everything into OCI artifacts stored in existing container registries. Apache 2.0 licensed.
- **Polyaxon** (https://github.com/polyaxon/polyaxon) - MLOps Tools For Managing & Orchestrating The Machine Learning LifeCycle. Reproducible and scalable machine learning workflows on Kubernetes with experiment tracking, model management, and pipeline orchestration. Apache 2.0 licensed.
- **Netflix Maestro** (https://github.com/Netflix/maestro) - Netflix's next-generation workflow orchestrator for data and ML pipelines at massive scale. Highly scalable and flexible scheduler designed to handle millions of workflows across thousands of nodes. Apache 2.0 licensed.
- **HAMi** (https://github.com/Project-HAMi/HAMi) - Heterogeneous GPU Sharing on Kubernetes. CNCF sandbox project providing GPU virtualization, slicing, and scheduling for efficient AI workload management across heterogeneous accelerators (GPUs, NPUs, MLUs). Apache 2.0 licensed.
- **NVIDIA KAI Scheduler** (https://github.com/NVIDIA/KAI-Scheduler) - Kubernetes-native GPU scheduler for AI workloads at large scale. Originally developed by Run:ai, now open-sourced by NVIDIA. Optimizes GPU resource allocation with dynamic allocation and efficient queue management. Apache 2.0 licensed.
- **NVIDIA DeepOps** (https://github.com/NVIDIA/deepops) - Infrastructure automation tools for building GPU clusters with Kubernetes and Slurm. Deploys multi-node GPU clusters with monitoring, logging, and storage for AI/HPC workloads. BSD-3-Clause licensed.
- **SkyPilot** (https://github.com/skypilot-org/skypilot) - Run, manage, and scale AI workloads on any AI infrastructure. Unified interface to access and manage compute across Kubernetes, Slurm, and 20+ cloud providers. Used by Shopify and research institutions for training and inference. Apache 2.0 licensed.
- **Volcano** (https://github.com/volcano-sh/volcano) - Cloud-native batch scheduling system for compute-intensive workloads. CNCF incubating project with gang scheduling, job dependency management, and topology-aware scheduling for AI/ML and deep learning. Apache 2.0 licensed.
- **Apache YuniKorn** (https://github.com/apache/yunikorn-core) - Kubernetes resource scheduler for batch, data, and ML workloads. Provides hierarchical resource queues, multi-tenancy fairness, and gang scheduling for big data and machine learning applications. Apache 2.0 licensed.
- **Kueue** (https://github.com/kubernetes-sigs/kueue) - Kubernetes-native job queueing system for batch, HPC, AI/ML, and similar applications. Cloud-native job queueing with resource flavor fungibility, fair sharing, cohorts, and preemption policies. Integrates with Kubeflow, Ray, and JobSet. Apache 2.0 licensed.

### Evaluation - Observability  (Monitoring, Evaluation & Observability)  — under 8. MLOps / LLMOps & Production

- **Langfuse** (https://github.com/langfuse/langfuse) - #1 open-source LLM observability platform.
- **Phoenix (Arize)** (https://github.com/Arize-ai/phoenix) - AI observability & evaluation platform.
- **Evidently** (https://github.com/evidentlyai/evidently) - ML & LLM monitoring framework.
- **Opik (Comet)** (https://github.com/comet-ml/opik) - Production-ready LLM evaluation platform.
- **LiteLLM** (https://github.com/BerriAI/litellm) - AI Gateway to call 100+ LLM APIs in OpenAI format with unified cost tracking, guardrails, load balancing, and logging.
- **OpenLIT** (https://github.com/openlit/openlit) - OpenTelemetry-native LLM observability platform with GPU monitoring, evaluations, prompt management, and guardrails.
- **OpenLLMetry (Traceloop)** (https://github.com/traceloop/openllmetry) - Open-source observability for GenAI/LLM applications based on OpenTelemetry with 25+ integration backends.
- **Agenta** (https://github.com/Agenta-AI/agenta) - Open-source LLMOps platform combining prompt playground, prompt management, LLM evaluation, and observability.
- **Latitude** (https://github.com/latitude-dev/latitude-llm) - Open-source agent engineering platform with prompt management, evaluations, and optimization. Features prompt playground, LLM-as-judge evals, and GEPA prompt optimizer for production LLM features. LGPL-3.0 licensed.
- **Helicone** (https://github.com/helicone/helicone) - Open-source LLM observability with request logging, caching, rate limiting, and cost analytics.
- **Giskard** (https://github.com/Giskard-AI/giskard-oss) - Open-source evaluation and testing library for LLM agents. Red teaming, vulnerability scanning, RAG evaluation, and safety testing with modular architecture. Apache 2.0 licensed.
- **Portkey Gateway** (https://github.com/Portkey-AI/gateway) - Blazing fast AI Gateway to route 200+ LLMs with unified API. Integrated guardrails, load balancing, fallbacks, and cost tracking. MIT licensed.
- **Envoy AI Gateway** (https://github.com/envoyproxy/ai-gateway) - Manages unified access to generative AI services built on Envoy Gateway. Kubernetes-native AI gateway for routing, load balancing, and managing LLM traffic with enterprise-grade reliability. Apache 2.0 licensed.
- **Pezzo** (https://github.com/pezzolabs/pezzo) - Cloud-native LLMOps platform with prompt management, versioning, and observability. Features collaborative prompt editing, A/B testing, and cost analytics. Apache 2.0 licensed.
- **Microsoft PromptFlow** (https://github.com/microsoft/promptflow) - Comprehensive suite for LLM-based AI app development from prototyping to production. Includes prompt engineering, evaluation, and deployment tools with VS Code integration. MIT licensed.
- **ChainForge** (https://github.com/ianarawjo/ChainForge) - Visual programming environment for battle-testing prompts and evaluating LLM outputs. Features node-based prompt chains, multi-model comparison, and hypothesis testing. MIT licensed.
- **Future AGI** (https://github.com/future-agi/future-agi) - Open-source self-hostable end-to-end agent engineering and optimization platform that unifies tracing, evals, simulations, datasets, gateway, and guardrails. Built for shipping self-improving AI agents with one feedback loop from prototype to production. Apache 2.0 licensed.
- **KubeStellar Console** (https://github.com/kubestellar/console) - AI-powered multi-cluster Kubernetes dashboard with GPU workload monitoring, AI pipeline observability, and CNCF ecosystem integrations. Apache 2.0 licensed.

### Evaluation - Benchmarks  (Benchmark Suites)  — under 9. Evaluation, Benchmarks & Datasets

- **LiveBench** (https://github.com/LiveBench/LiveBench) - Contamination-free LLM benchmark with objective ground-truth scoring. ICLR 2025 spotlight paper featuring frequently-updated questions from recent sources. Tests math, coding, reasoning, language, instruction following, and data analysis.
- **lm-evaluation-harness (EleutherAI)** (https://github.com/EleutherAI/lm-evaluation-harness) - De-facto standard for generative model evaluation.
- **HELM (Stanford)** (https://github.com/stanford-crfm/helm) - Holistic Evaluation of Language Models.
- **MMLU-Pro / GPQA** (https://github.com/TIGER-AI-Lab/MMLU-Pro) - More challenging MMLU-style benchmark suite for evaluating advanced language models with expert-level reasoning questions.
- **SWE-bench** (https://github.com/SWE-bench/SWE-bench) - Evaluates LLMs on real-world GitHub issues from 15+ Python repositories.
- **GAIA** (https://huggingface.co/datasets/gaia-benchmark/GAIA) - Real-world multi-step agentic benchmark.
- **OpenCompass** (https://github.com/open-compass/opencompass) - Evaluation platform for benchmarking language and multimodal models across large benchmark suites.
- **MLPerf Inference** (https://github.com/mlcommons/inference) - Industry-standard ML inference benchmarks with reference implementations for AI accelerators.
- **MLPerf Training** (https://github.com/mlcommons/training) - Industry-standard ML training benchmarks from MLCommons. Reference implementations for training AI models at scale across image classification, object detection, NLP, and recommendation tasks. Apache 2.0 licensed.
- **VLMEvalKit** (https://github.com/open-compass/VLMEvalKit) - Open-source evaluation toolkit for large multi-modality models (LMMs). Supports 220+ LMMs and 80+ benchmarks including MMMU, MathVista, and ChartQA. Powers the OpenVLM Leaderboard. Apache 2.0 licensed.
- **Vectara Hallucination Leaderboard** (https://github.com/vectara/hallucination-leaderboard) - Leaderboard comparing LLM performance at producing hallucinations when summarizing short documents. Systematic evaluation of factual consistency across major models. Apache 2.0 licensed.
- **SWE-rebench (Nebius)** (https://huggingface.co/datasets/nebius/SWE-rebench) - Continuously updated benchmark with 21,000+ real-world SWE tasks for evaluating agentic LLMs. Decontaminated, mined from GitHub.
- **AgentBench (THUDM)** (https://github.com/THUDM/AgentBench) - Comprehensive benchmark to evaluate LLMs as agents across 8 diverse environments including household, web shopping, OS interaction, and database tasks. ICLR 2024. Apache 2.0 licensed.
- **MLE-bench (OpenAI)** (https://github.com/openai/mle-bench) - Benchmark for measuring how well AI agents perform at machine learning engineering. Evaluates agents on 75 Kaggle competitions covering diverse ML tasks. MIT licensed.
- **PinchBench** (https://github.com/pinchbench/skill) - Benchmarking system for evaluating LLM models as OpenClaw coding agents. Built with Rust by the kilo.ai team. MIT licensed.

### Evaluation - Frameworks  (Evaluation Frameworks)  — under 9. Evaluation, Benchmarks & Datasets

- **DeepEval** (https://github.com/confident-ai/deepeval) - The "Pytest for LLMs".
- **Inspect AI** (https://github.com/UKGovernmentBEIS/inspect_ai) - Framework for large language model evaluations from the UK AI Security Institute.
- **RAGAs** (https://github.com/explodinggradients/ragas) - End-to-end RAG evaluation framework.
- **Lighteval** (https://github.com/huggingface/lighteval) - Evaluation toolkit for LLMs across multiple backends with reusable tasks, metrics, and result tracking.
- **Hugging Face Evaluate** (https://github.com/huggingface/evaluate) - Standardized evaluation metrics.
- **OpenAI Evals** (https://github.com/openai/evals) - Framework for evaluating LLMs and LLM systems with an open-source registry of 100+ community-contributed benchmarks. MIT licensed.
- **LMMs-Eval** (https://github.com/EvolvingLMMs-Lab/lmms-eval) - Unified multimodal evaluation toolkit for text, image, video, and audio tasks with 100+ supported benchmarks.
- **BrowserGym** (https://github.com/ServiceNow/BrowserGym) - Gym environment for web task automation and agent evaluation. Includes MiniWoB, WebArena, WorkArena, and more. Apache 2.0 licensed.
- **TruLens** (https://github.com/truera/trulens) - Evaluation and tracking for LLM experiments and AI agents. Provides feedback functions for measuring quality, relevance, and groundedness with LangChain and LlamaIndex integrations. MIT licensed.
- **OpenEvals** (https://github.com/langchain-ai/openevals) - Open-source evaluation library for LLM and agent applications. Built by LangChain with pre-built evaluators for common use cases including RAG, agents, and structured output validation. MIT licensed.
- **AutoRAG** (https://github.com/Marker-Inc-Korea/AutoRAG) - RAG AutoML tool for automatically finding optimal RAG pipelines. Evaluates and optimizes retrieval-augmented generation with AutoML-style automation for your own data and use-case. Apache 2.0 licensed.
- **E2B Code Interpreter** (https://github.com/e2b-dev/code-interpreter) - Python & JS/TS SDK for running AI-generated code in secure isolated sandboxes. Essential infrastructure for evaluating code-generating LLMs with safe execution environments. Apache 2.0 licensed.
- **SimpleEvals (OpenAI)** (https://github.com/openai/simple-evals) - Lightweight library for evaluating language models with transparent accuracy numbers. Reference implementations for MMLU, GPQA, MATH, HumanEval, MGSM, DROP, and SimpleQA benchmarks. MIT licensed.
- **EvalScope (ModelScope)** (https://github.com/modelscope/evalscope) - Streamlined and customizable framework for efficient large model (LLM, VLM, AIGC) evaluation and performance benchmarking. One-stop evaluation solution with 80+ benchmarks. Apache 2.0 licensed.
- **Harbor** (https://github.com/harbor-framework/harbor) - Framework for running agent evaluations and creating/using RL environments. Evaluate arbitrary agents like Claude Code, OpenHands, and Codex CLI. Build and share benchmarks and environments. Apache 2.0 licensed.


---

## Full Category Tree with Tools (Condensed)

## 1. Core Frameworks & Libraries

#### Deep Learning Frameworks (16 tools)

- **PyTorch**: Dynamic computation graphs, Pythonic API, dominant in research and production. The current standard for most frontier AI work.
- **TensorFlow**: End-to-end platform with excellent production deployment, TPU support, and large-scale serving tools.
- **JAX**: High-performance numerical computing with composable transformations (JIT, vmap, grad). Rising favorite for research and scientific ML.
- **dm-haiku**: JAX-based neural network library from Google DeepMind. Elegant functional API with state management, widely used in DeepMind's research. Apache 2.0 licensed.
- **Equinox**: Elegant easy-to-use neural networks and scientific computing in JAX. Callable PyTrees with filtered transformations, seamless interoperability with the JAX ecosystem. Apache 2.0 licensed.
- **Diffrax**: Numerical differential equation solvers in JAX. Autodifferentiable and GPU-capable ODE/SDE/CDE solvers for scientific machine learning and neural differential equations. Apache 2.0 licensed.
- **vit-pytorch**: Comprehensive Vision Transformer (ViT) implementations in PyTorch. Reference implementations of all major vision transformer variants including ViT, DeiT, Swin, and more. MIT licensed.
- **NumPyro**: Probabilistic programming with NumPy powered by JAX for autograd and JIT compilation. Bayesian modeling and inference at scale.
- **Keras**: High-level, beginner-friendly API that now runs on multiple backends (TensorFlow, JAX, PyTorch). Perfect for rapid experimentation.
- **tinygrad**: Minimalist deep learning framework with tiny code footprint. The "you like PyTorch? you like micrograd? you love tinygrad!" philosophy - simple yet powerful.
- **PaddlePaddle**: Industrial deep learning platform from Baidu serving 23+ million developers and 760,000+ companies. China's first independent R&D framework with advanced distributed training and deployment capabilities.
- **PyTorch Geometric**: Library for deep learning on irregular input data such as graphs, point clouds, and manifolds. Part of the PyTorch ecosystem.
- **timm (PyTorch Image Models)**: The largest collection of PyTorch image encoders and backbones. 900+ pretrained models including ResNet, EfficientNet, Vision Transformer, ConvNeXt, and more with training and inference scripts. Apache 2.0 licensed.
- **Triton**: Language and compiler for writing highly efficient custom deep-learning primitives. Powers kernel optimizations in PyTorch, JAX, and other frameworks. MIT licensed.
- **GGML**: Tensor library for machine learning. The foundational C/C++ library powering llama.cpp and many on-device inference engines. MIT licensed.
- **MLX**: Array framework for machine learning on Apple silicon. Efficient unified memory design with NumPy-like API, automatic differentiation, and multi-device support. MIT licensed.

#### High-Performance Compute Libraries (3 tools)

- **oneDNN**: oneAPI Deep Neural Network Library. Cross-platform performance library of basic building blocks for deep learning, optimized for Intel CPUs, GPUs, and Arm architectures. Apache 2.0 licensed.
- **ONNX**: Open standard for machine learning interoperability. Open Neural Network Exchange provides an open ecosystem that empowers AI developers to choose the right tools as their project evolves. Apache 2.0 licensed.
- **IREE**: Retargetable MLIR-based machine learning compiler and runtime toolkit. Lowers ML models to unified IR that scales from datacenter to mobile and edge deployments. Apache 2.0 licensed.

#### Rust ML Frameworks (3 tools)

- **Burn**: Next-generation deep learning framework in Rust. Backend-agnostic with CPU, GPU, WebAssembly support.
- **Candle (Hugging Face)**: Minimalist ML framework for Rust. PyTorch-like API with focus on performance and simplicity.
- **linfa**: Comprehensive Rust ML toolkit with classical algorithms. scikit-learn equivalent for Rust with clustering, regression, and preprocessing.

#### Julia ML Frameworks (3 tools)

- **Flux.jl**: 100% pure-Julia ML stack with lightweight abstractions on top of native GPU and AD support. Elegant, hackable, and fully integrated with Julia's scientific computing ecosystem.
- **MLJ.jl**: Comprehensive Julia machine learning framework providing a unified interface to 200+ models with meta-algorithms for selection, tuning, and evaluation. MIT licensed.
- **ModelingToolkit.jl**: High-performance symbolic-numeric modeling framework for scientific machine learning. Automatically generates fast functions for model components like Jacobians and Hessians with automatic sparsification and parallelization. MIT licensed.

#### NLP & Transformers (5 tools)

- **spaCy (Explosion AI)**: Industrial-strength natural language processing with 75+ languages, transformer pipelines, and production-grade NER, parsing, and text classification.
- **Transformers (Hugging Face)**: The de facto standard library for pretrained NLP models. 1M+ models, 250,000+ downloads/day. BERT, GPT, Llama, Qwen, and hundreds more.
- **sentence-transformers**: Classic library for sentence and image embeddings.
- **tokenizers (Hugging Face)**: Fast state-of-the-art tokenizers for training and inference.
- **fairseq2**: FAIR Sequence Modeling Toolkit 2. Complete rewrite of fairseq with modern PyTorch APIs, native support for LLM training (70B+ models), vLLM integration, and first-party recipes for instruction finetuning and preference optimization. MIT licensed.

#### Data Processing & Manipulation (41 tools)

- **Pandas**: The gold standard for data analysis and manipulation in Python.
- **Polars**: Blazing-fast DataFrame library (Rust backend) - modern alternative to Pandas for large-scale workloads.
- **cuDF**: GPU DataFrame library from RAPIDS. Accelerates Pandas workflows on NVIDIA GPUs with zero code changes using cuDF.pandas accelerator mode.
- **Modin**: Parallel Pandas DataFrames. Scale Pandas workflows by changing a single line of code - distributes data and computation automatically.
- **Dask**: Parallel computing for big data - scales Pandas/NumPy/scikit-learn to clusters.
- **NumPy**: Fundamental array computing library that powers almost every AI stack.
- **SciPy**: Scientific computing algorithms (optimization, linear algebra, statistics, signal processing).
- **CuPy**: NumPy and SciPy-compatible array library for GPU-accelerated computing in Python.
- **NetworkX**: Creation, manipulation, and study of complex networks. The foundational graph analysis library for Python data science.
- **cuGraph**: GPU graph analytics library with NetworkX-compatible API. 10-100x faster than CPU for large-scale graph algorithms. Apache 2.0 licensed.
- **Vaex**: Out-of-Core hybrid Apache Arrow/NumPy DataFrame for Python. Visualize and explore billion-row datasets at millions of rows per second. MIT licensed.
- **Datashader**: High-performance large data visualization. Renders billions of points interactively without aggregation artifacts. BSD-3-Clause licensed.
- **Zarr**: Chunked, compressed, N-dimensional array storage. Scalable tensor data format optimized for cloud and parallel computing. MIT licensed.
- **NVIDIA DALI**: GPU-accelerated data loading and augmentation library with highly optimized building blocks for deep learning applications. Apache 2.0 licensed.
- **Narwhals**: Lightweight compatibility layer between DataFrame libraries. Write Polars-like code that works seamlessly across Pandas, Polars, cuDF, Modin, and more. MIT licensed.
- **Ibis**: Portable Python dataframe library with 20+ backends. Write Pandas-like code that runs locally with DuckDB or scales to production databases (BigQuery, Snowflake, PostgreSQL) by changing one line. Apache 2.0 licensed.
- **skrub**: Machine learning with dataframes for dirty categorical data. Preprocessing and feature engineering for heterogeneous data with seamless Pandas/Polars integration. BSD-3-Clause licensed.
- **Oxen**: Lightning fast data version control for machine learning. Optimized for large datasets with efficient diffing, branching, and collaboration. Apache 2.0 licensed.
- **Pandera**: Statistical data testing and validation for dataframes. Pydantic-like API for Pandas, Polars, and other dataframe libraries with type hints and lazy validation. MIT licensed.
- **Snorkel**: System for quickly generating training data with weak supervision. Programmatically label, build, and manage training data using labeling functions and probabilistic consensus models. Powers Snorkel Flow and used by Google, Apple, and Intel. Apache 2
- **DuckDB**: High-performance analytical in-process SQL database system. Fast, reliable, portable, and easy to use with rich SQL dialect support. Perfect for data processing and analytics workloads. MIT licensed.
- **FiftyOne**: Visual AI development toolkit for visualizing, labeling, and evaluating visual datasets and models. Supercharges computer vision workflows with dataset exploration and model analysis. Apache 2.0 licensed.
- **Label Studio**: Multi-type data labeling and annotation tool with standardized output format. Configurable interface for images, text, audio, video, and time series with ML-assisted labeling. Apache 2.0 licensed.
- **Delta Lake**: Open-source storage framework enabling Lakehouse architecture with ACID transactions, scalable metadata handling, and unified batch/streaming processing. Apache 2.0 licensed.
- **Apache Iceberg**: High-performance open table format for huge analytic tables. Brings SQL table reliability to big data with time travel, hidden partitioning, and schema evolution. Works with Spark, Trino, Flink, Presto, Hive and Impala. Apache 2.0 licensed.
- **Apache Hudi**: Open data lakehouse platform for ingesting, indexing, storing, serving, transforming and managing data across cloud environments. Supports upserts, deletes and incremental processing on big data with built-in ingestion tools for Spark and Flink. Apac
- **lakeFS**: Data version control for your data lake that transforms object storage into Git-like repositories. Enables atomic, versioned data lake operations with branching, committing, and merging for data pipelines. Apache 2.0 licensed.
- **Apache Airflow**: Platform to programmatically author, schedule, and monitor workflows. Industry-standard orchestration for data pipelines and ML workflows with 500+ integrations. Apache 2.0 licensed.
- **Apache Spark**: Unified analytics engine for large-scale data processing. In-memory cluster computing with high-level APIs in Python, Scala, Java, and R. Powers MLlib for distributed machine learning and Structured Streaming for real-time data. Apache 2.0 licensed.
- **Apache Flink**: Stream processing framework with powerful batch and streaming capabilities. High-throughput, low-latency runtime with exactly-once processing guarantees. Ideal for real-time AI inference pipelines and event-driven ML applications. Apache 2.0 licensed
- **Apache Beam**: Unified programming model for batch and streaming data processing. Write pipelines once, run anywhere on Flink, Spark, or Google Cloud Dataflow. Portable, extensible, and enterprise-ready for AI data pipelines. Apache 2.0 licensed.
- **Scrapy**: Fast, high-level web crawling and scraping framework for Python. Extract structured data from websites at scale with built-in support for handling common challenges like pagination, cookies, and concurrent requests. BSD-3-Clause licensed.
- **Temporal**: Durable execution platform for reliable workflow orchestration. Build resilient data pipelines and ML workflows that survive failures and continue execution exactly where they left off. MIT licensed.
- **Luigi**: Python module for building complex pipelines of batch jobs. Handles dependency resolution, workflow management, visualization, and Hadoop integration. Built at Spotify and battle-tested in production. Apache 2.0 licensed.
- **Mage.ai**: Modern open-source data pipeline tool for integrating and transforming data. AI-native ETL/ELT platform with 100+ integrations, real-time monitoring, and collaborative features. Apache 2.0 licensed.
- **Hamilton**: Declarative dataflow framework for building testable, modular, self-documenting data pipelines. Encode lineage and metadata directly in Python functions. Originally from Stitch Fix, now Apache incubating. Apache 2.0 licensed.
- **D-Tale**: Visualizer for Pandas data structures with a Flask back-end and React front-end. Interactive data exploration with charting, filtering, and code export. LGPL-2.1 licensed.
- **Sweetviz**: Beautiful, high-density visualizations for exploratory data analysis in two lines of code. Self-contained HTML reports for dataset comparison and target analysis. MIT licensed.
- **TextAttack**: Python framework for adversarial attacks, data augmentation, and model training in NLP. Augment datasets to increase model robustness and generate adversarial examples. MIT licensed.
- **uv**: An extremely fast Python package and project manager, written in Rust. 10-100x faster than pip with built-in virtual environment management, dependency resolution, and lockfiles. Essential for modern AI/ML development workflows. Apache 2.0 and MIT du
- **Vector**: A high-performance observability data pipeline for collecting, transforming, and routing logs and metrics. Real-time data processing with 50+ sources and sinks including Kafka, S3, and Elasticsearch. Ideal for AI/ML log processing and data ingestion.

#### Classical ML & Gradient Boosting (11 tools)

- **scikit-learn**: Industry-standard library for traditional machine learning (classification, regression, clustering, pipelines).
- **XGBoost**: Scalable, high-performance gradient boosting library. Still dominates Kaggle and tabular competitions.
- **LightGBM**: Microsoft's ultra-fast gradient boosting framework, optimized for speed and memory.
- **CatBoost**: Gradient boosting that handles categorical features natively with great out-of-the-box performance.
- **sktime**: Unified framework for machine learning with time series. scikit-learn compatible API for forecasting, classification, clustering, and anomaly detection.
- **StatsForecast**: Lightning-fast statistical forecasting with ARIMA, ETS, CES, and Theta models. Optimized for high-performance time series workloads.
- **MLForecast**: Scalable machine learning for time series forecasting. Train any sklearn-compatible model on millions of time series with efficient feature engineering. Apache 2.0 licensed.
- **cuML**: GPU-accelerated machine learning algorithms with scikit-learn compatible API. 10-50x faster than CPU implementations for large datasets. Apache 2.0 licensed.
- **SynapseML**: Distributed machine learning on Apache Spark. Scalable, composable APIs for text analytics, vision, anomaly detection with seamless Python/Scala/R/.NET integration. MIT licensed.
- **Darts**: User-friendly forecasting and anomaly detection for time series. Unifies classical statistical models (ARIMA, ETS) with modern neural networks (N-BEATS, TFT, DeepAR) in a single scikit-learn compatible API. Apache 2.0 licensed.
- **PyTorch Forecasting**: Time series forecasting with PyTorch. Multiple neural architectures (N-BEATS, TFT, DeepAR) with in-built interpretation capabilities, built on PyTorch Lightning for distributed training. MIT licensed.

#### Data Engineering & Feature Stores (3 tools)

- **DataHub**: The #1 open-source metadata platform for data and AI. Data discovery, governance, and observability with 80+ connectors, column-level lineage, and AI assistant integration. Originally built at LinkedIn. Apache 2.0 licensed.
- **OpenMetadata**: Unified metadata platform for data discovery, observability, and governance. Column-level lineage, semantic search, and team collaboration with 70+ data service connectors. Apache 2.0 licensed.
- **Amundsen**: Data discovery and metadata engine from Lyft. PageRank-style search for data resources with usage-based ranking. LF AI & Data Foundation project. Apache 2.0 licensed.

#### Data Transformation & Analytics Engineering (3 tools)

- **dbt-core**: Transform data using software engineering best practices. The industry-standard framework for analytics engineering with 15M+ monthly downloads. Enables version control, testing, and documentation for SQL transformations. Apache 2.0 licensed.
- **SQLMesh**: Scalable and efficient data transformation framework with dbt compatibility. Features automatic data lineage, time travel, and virtual data environments for testing. Optimized for large-scale data warehouses. Apache 2.0 licensed.
- **SLayer**: Semantic layer for AI-powered data analytics. Allows AI agents to describe data models and query the data using an expressive format with measures, dimensions, and filters, without writing raw SQL. MCP, CLI, API, and Python clients. Embeddable as a P

#### Data Quality & Validation (5 tools)

- **Deequ**: Library built on top of Apache Spark for defining "unit tests for data". Measures data quality in large datasets with constraint verification, anomaly detection, and incremental validation. Used at Amazon for production data quality. Apache 2.0 licen
- **Great Expectations**: Always know what to expect from your data. Data validation, profiling, and documentation for data pipelines. Apache 2.0 licensed.
- **ydata-profiling**: One line of code for comprehensive data quality profiling and exploratory data analysis. Generates detailed reports for Pandas and Spark DataFrames including statistics, correlations, missing values, and data quality alerts. MIT licensed.
- **Soda Core**: Data contracts engine for the modern data stack. Define data quality checks in YAML and automatically validate schema and data across your pipelines. Supports 20+ data sources including Snowflake, BigQuery, and PostgreSQL. Apache 2.0 licensed.
- **TFX (TensorFlow Extended)**: End-to-end platform for deploying production ML pipelines. Data validation, transformation, model training, and serving with TensorFlow. Powers Google's production ML infrastructure. Apache 2.0 licensed.

#### Data Labeling & Annotation (2 tools)

- **Doccano**: Open-source text annotation tool for machine learning practitioners. Features text classification, sequence labeling, and sequence-to-sequence tasks for sentiment analysis, NER, and summarization. MIT licensed.
- **OpenRefine**: Free, open-source power tool for working with messy data. Clean, transform, and extend data with web services. Formerly Google Refine. BSD-3-Clause licensed.

#### AutoML & Hyperparameter Optimization (4 tools)

- **Optuna**: Modern, define-by-run hyperparameter optimization with pruning and visualizations. Extremely popular in 2026.
- **AutoGluon**: AWS AutoML toolkit for tabular, image, text, and multimodal data - state-of-the-art with almost zero code.
- **FLAML**: Microsoft's fast & lightweight AutoML focused on efficiency and low compute.
- **Katib (Kubeflow)**: Kubernetes-native AutoML for hyperparameter tuning, early stopping, and neural architecture search. Framework-agnostic with support for TensorFlow, PyTorch, XGBoost, and custom training operators. Apache 2.0 licensed.

#### Interactive ML Apps & Notebooks (3 tools)

- **Streamlit**: The fastest way to build and share data apps. Transform Python scripts into beautiful web applications with minimal code. Widely used for ML model demos, data visualization, and internal tools.
- **Gradio**: Build and share delightful machine learning apps, all in Python. The de facto standard for creating interactive ML demos with automatic UI generation from function signatures. Powers thousands of Hugging Face Spaces.
- **Marimo**: A reactive notebook for Python — run reproducible experiments, query with SQL, execute as a script, deploy as an app, and version with git. Stored as pure Python. All in a modern, AI-native editor.

#### Model Training & Optimization Utilities (16 tools)

- **Hugging Face Accelerate**: Simple API to make training scripts run on any hardware (multi-GPU, TPU, mixed precision) with minimal code changes.
- **DeepSpeed**: Microsoft's deep learning optimization library for extreme-scale training (ZeRO, offloading, MoE).
- **FlashAttention**: Fast exact attention kernels that reduce memory usage and accelerate transformer training and inference.
- **xFormers**: Optimized transformer building blocks and attention operators for PyTorch.
- **PyTorch Lightning**: High-level wrapper for PyTorch that removes boilerplate and adds best practices.
- **fastai**: Deep learning library providing practitioners with high-level components for state-of-the-art results. Built on PyTorch with a focus on usability and transfer learning. Apache 2.0 licensed.
- **PyTorch Ignite**: High-level library for training and evaluating neural networks in PyTorch with an engine, events & handlers system for maximum flexibility. BSD-3-Clause licensed.
- **ONNX Runtime**: High-performance inference and training for ONNX models across hardware.
- **einops**: Flexible, powerful tensor operations for readable and reliable code. Supports PyTorch, JAX, TensorFlow, NumPy, MLX.
- **safetensors**: Simple, safe way to store and distribute tensors. Fast, secure alternative to pickle for model serialization.
- **torchmetrics**: Machine learning metrics for distributed, scalable PyTorch applications. 80+ metrics with built-in distributed synchronization.
- **torchao**: PyTorch native quantization and sparsity for training and inference. Drop-in optimizations for production deployment.
- **SHAP**: Game theoretic approach to explain the output of any machine learning model. Industry standard for model interpretability.
- **skorch**: scikit-learn compatible neural network library that wraps PyTorch. Seamlessly integrate PyTorch models with scikit-learn pipelines, grid search, and cross-validation.
- **Composer**: Supercharge your model training. MosaicML's PyTorch training library with built-in algorithms for efficient training (FSDP, gradient compression, progressive resizing) and seamless distributed training on large-scale clusters. Apache 2.0 licensed.
- **NVIDIA Apex**: PyTorch extension for mixed precision training and distributed training optimizations. Powers many production deep learning workloads with tools for automatic mixed precision (AMP), distributed data parallel, and fused optimizers. BSD-3-Clause licens

## 2. Model Codebases & Model Families

#### Language Model Families (9 tools)

- **RWKV**: Attention-free language model architecture with linear-time inference, training code, inference examples, and an active open-source ecosystem.
- **Qwen**: Canonical open model family from Alibaba with model cards, inference examples, fine-tuning guidance, and ecosystem links.
- **Qwen3-VL**: Vision-language branch of the Qwen3 model stack with multimodal checkpoints, training recipes, and reference tooling.
- **MiniCPM**: Compact open model family with practical code, deployment notes, and active edge/on-device focus.
- **Llama Models**: Meta's canonical repository for Llama model documentation, examples, safety materials, and integration guidance.
- **GPT-OSS**: OpenAI open-weight model repository with inference examples, recipes, and deployment guidance.
- **Mamba**: State Space Model implementation with pretrained checkpoints, architecture code, and research tooling for efficient long-sequence modeling.
- **GPT-NeoX**: Large-scale language model training codebase from EleutherAI with distributed training support and historical open-model importance.
- **GLM-5**: Open-source mixture-of-experts language model family optimized for long-horizon planning, agentic tasks, and coding. Apache 2.0 licensed.

#### Multimodal & Vision-Language Codebases (9 tools)

- **openai/CLIP**: Canonical OpenAI contrastive vision-language model codebase with pretrained checkpoints and practical reference implementation for image-text retrieval and classification.
- **OpenCLIP**: Open implementation of CLIP with training code, pretrained models, and zero-shot evaluation tooling.
- **OmniParser**: Vision-based GUI parsing model and tooling for computer-use agents.
- **MiniCPM-V**: Compact vision-language model family with edge-focused deployment examples and strong OCR-oriented use cases.
- **Eagle**: NVIDIA multimodal model codebase with open checkpoints and reusable research materials for vision-language and video-language tasks.
- **Moondream**: Small vision-language model with practical inference examples for edge and real-time image understanding.
- **VILA**: NVIDIA vision-language model family with training, evaluation, and deployment materials across edge and datacenter settings.
- **Depth Anything V2**: Monocular depth-estimation foundation model with practical inference code and broad computer-vision reuse.
- **NVIDIA Cosmos**: Open platform of world models, tokenizers, and post-training tools designed for physical AI, robotics, and autonomous systems.

#### Speech & Audio Model Codebases (8 tools)

- **Whisper**: Canonical open speech-to-text model codebase with widespread ecosystem support and many downstream implementations.
- **FunASR**: Speech recognition toolkit with pretrained models, streaming support, diarization, VAD, and production-oriented examples.
- **NVIDIA NeMo**: Scalable framework and model codebase for speech, language, and multimodal AI with recipes and deployment guidance.
- **Sherpa-ONNX**: Complete speech toolkit with ASR, TTS, diarization, source separation, and VAD across embedded and edge environments via ONNX Runtime.
- **MOSS-TTS**: Open speech and sound generation family focused on expressive, long-form text-to-speech with streaming and multi-speaker support.
- **VoxCPM**: Open-sourced tokenizer-free multilingual speech synthesis model with high-quality TTS and style transfer workflows.
- **VibeVoice**: Open Frontier Voice AI toolkit spanning speech understanding, generation, and multilingual TTS workflows, with active research and deployment tooling.
- **SpeechBrain**: PyTorch speech toolkit with recipes for ASR, TTS, speaker recognition, and speech enhancement.

## 3. Inference Engines & Serving

#### Local / On-device Inference (13 tools)

- **llama.cpp**: Pure C/C++ inference engine with GGUF format support. The gold standard for CPU/GPU/Apple Silicon on-device running. Includes llama-server for OpenAI-compatible API. Now at 100K+ stars.
- **Ollama**: Dead-simple local LLM runner with a one-line install, model registry, and OpenAI-compatible API.
- **Foundry Local**: Open-source on-device AI platform covering discovery, model running, sandboxed execution, and evaluation of open models.
- **Potato OS**: Linux distribution for fully local AI inference on Raspberry Pi 5 and 4, optimized for running open models at the edge.
- **MLC-LLM**: Deployment engine that compiles and runs LLMs across browsers, mobile devices, and local hardware.
- **WebLLM**: High-performance in-browser LLM inference engine. Runs models directly in the browser with WebGPU acceleration.
- **llama-cpp-python**: Official Python bindings for llama.cpp.
- **KoboldCpp**: User-friendly llama.cpp fork focused on role-playing and creative writing.
- **RamaLama**: Container-centric tool for simplifying local AI model serving. Automatically detects GPUs, pulls optimized container images, and runs models securely in rootless containers with enterprise-grade isolation.
- **LiteRT**: Google's production-ready on-device ML and GenAI deployment framework. Supports Android, iOS, Web, Desktop, and IoT targets with GPU/NPU acceleration via a unified edge-first runtime. Apache 2.0 licensed.
- **LiteRT-LM**: Production-ready runtime for deploying LLMs on edge devices with low-latency inference and optimized hardware paths for mobile and embedded platforms.
- **exo**: Run frontier AI locally by connecting all your devices into an AI cluster. Features automatic device discovery, RDMA over Thunderbolt for 99% latency reduction, topology-aware auto parallel, and tensor parallelism. Uses MLX backend for distributed in
- **omlx**: Apple-centric inference server for local-first AI workflows with model management, GPU orchestration, and OpenAI-compatible APIs for self-hosted deployment. Apache 2.0 licensed.

#### High-performance Serving & API Servers (29 tools)

- **llm-d**: Kubernetes-native distributed LLM inference framework. Donated to CNCF by RedHat, Google, and IBM. Intelligent scheduling, KV-cache optimization, and state-of-the-art performance across accelerators.
- **LMDeploy**: Toolkit for compressing, deploying, and serving LLMs from OpenMMLab. 4-bit inference with 2.4x higher performance than FP16, distributed multi-model serving across machines.
- **vLLM**: State-of-the-art serving engine with PagedAttention and continuous batching. Currently the fastest production-grade LLM server.
- **vLLM-Omni**: Multi-modal inference stack extending vLLM for image, audio, and video generation workloads with a unified serving interface. Apache 2.0 licensed.
- **LMCache**: Supercharge LLM inference with the fastest KV Cache layer. 3-10x delay savings and GPU cycle reduction for multi-round QA and RAG. Integrates seamlessly with vLLM for distributed, high-throughput deployments. Apache 2.0 licensed.
- **vLLM Production Stack**: Kubernetes-native production stack for vLLM inference. Automated deployment, autoscaling, and monitoring for enterprise-grade LLM serving. Built by the vLLM team for seamless integration.
- **Open Model Engine (OME)**: Kubernetes operator for LLM serving with GPU scheduling and model lifecycle management across vLLM, SGLang, and TensorRT-LLM.
- **nano-vLLM**: Minimalist vLLM implementation in ~1,200 lines of Python. Educational yet performant with prefix caching, tensor parallelism, and CUDA graph acceleration. Comparable inference speeds to full vLLM. MIT licensed.
- **SGLang**: Next-gen serving framework with RadixAttention. Powers xAI's production workloads at 100K+ GPUs scale.
- **TensorRT-LLM**: NVIDIA's official high-performance inference backend.
- **Aphrodite Engine**: vLLM fork optimized for role-play and creative writing. Supports extensive quantization methods (AQLM, AWQ, GPTQ, GGUF, FP8) and modern samplers. Active development with multi-LoRA and speculative decoding support.
- **AIBrix**: Cost-efficient and pluggable infrastructure components for GenAI inference. Kubernetes-native control plane for vLLM with distributed KV cache, heterogeneous GPU serving, and intelligent routing. Apache 2.0 licensed.
- **Triton Inference Server**: NVIDIA's production-grade open-source inference serving software. Supports multiple frameworks (TensorRT, PyTorch, ONNX) with optimized cloud and edge deployment.
- **mistral.rs**: Fast, flexible Rust-native LLM inference engine built on Candle. Supports text, vision, audio, image generation, and embeddings with hardware-aware auto-tuning.
- **KTransformers**: Flexible framework for heterogeneous CPU-GPU LLM inference and fine-tuning. Enables running large MoE models by offloading experts to CPU with BF16/FP8 precision support.
- **llamafile**: Mozilla's single-file distributable LLM solution. Bundle model weights, inference engine, and runtime into one portable executable that runs on six OSes without installation.
- **Xinference**: Unified, production-ready inference API for LLMs, speech, and multimodal models. Drop-in GPT replacement with single-line code changes. Supports thousands of models with auto-batching and distributed inference.
- **RTP-LLM (Alibaba)**: Alibaba's high-performance LLM inference acceleration engine. Powers production LLM services across Taobao, Tmall, and Alibaba's international AI platform. Supports PagedAttention, FlashAttention, FlashDecoding, INT8/INT4 quantization, and heterogene
- **LitServe (Lightning AI)**: Minimal Python framework for building custom AI inference servers with full control over logic, batching, and scaling. 2x faster than FastAPI with built-in batching, streaming, and multi-GPU autoscaling. Apache 2.0 licensed.
- **LightLLM**: Pure Python-based LLM inference and serving framework with lightweight design, easy extensibility, and high-speed performance. Integrates optimizations from FasterTransformer, TGI, vLLM, and SGLang.
- **TabbyAPI**: FastAPI-based API server for ExLlamaV2/V3 backends. OpenAI-compatible API with support for model loading/unloading, embeddings, speculative decoding, multi-LoRA, and streaming.
- **GPUStack**: GPU cluster manager that orchestrates inference engines like vLLM and SGLang. Automated engine selection, parameter optimization, and distributed multi-GPU deployment for high-performance AI workloads.
- **One-API**: LLM API management and key redistribution system. Unifies multiple providers (OpenAI, Anthropic, Azure, etc.) under a single OpenAI-compatible API with built-in rate limiting, quota management, and cost tracking. MIT licensed.
- **OpenLLM (BentoML)**: Production-grade platform for running any open-source LLMs as OpenAI-compatible API endpoints. Supports 50+ models with built-in streaming, batching, and auto-acceleration. Apache 2.0 licensed.
- **Higress (Alibaba)**: AI-native API gateway born from Alibaba's internal infrastructure with 2+ years of production validation. Provides unified LLM API and MCP (Model Context Protocol) management with enterprise-grade 99.99% availability. Apache 2.0 licensed.
- **NVIDIA Dynamo**: Datacenter-scale distributed inference serving framework from NVIDIA. Orchestration layer above vLLM/SGLang/TensorRT-LLM with disaggregated serving, KV-aware routing, and automatic scaling. Built in Rust with Python extensibility. Apache 2.0 licensed
- **Microsoft BitNet**: Official inference framework for 1-bit LLMs (BitNet b1.58). Enables running large models on CPU with minimal memory footprint. Features custom kernels for ternary weight quantization and efficient matmul operations. MIT licensed.
- **FreeLLMAPI**: OpenAI-compatible proxy gateway that stacks the free tiers of multiple LLM providers behind a single endpoint with automatic failover and rate tracking. MIT licensed.
- **OmniRoute**: Unified AI gateway and proxy supporting over 230 providers with token compression, automatic failover, and routing strategies. MIT licensed.

#### Additional Inference Engines (19 tools)

- **DeepEP**: Efficient expert-parallel communication library for large MoE models, improving throughput in distributed inference and training.
- **DeepGEMM**: CUDA FP8/FMA GEMM kernels for efficient LLM inference and training at reduced precision.
- **AirLLM**: Single-GPU 70B inference stack with strong memory/performance optimizations for local deployment on commodity hardware.
- **ThunderKittens**: High-performance GPU kernel primitives for fast attention and matmul workflows used by LLM stacks.
- **Mirage Persistent Kernel**: Compiler that fuses model execution into a single mega-kernel for tighter performance.
- **tt-metal**: Operator and kernel toolkit for efficient LLM inference and low-level optimization on Tenstorrent hardware.
- **vLLM-Ascend**: Hardware plugin for running vLLM on Huawei Ascend accelerators.
- **CTranslate2**: Fast inference engine for Transformer models supporting OpenNMT and Hugging Face models. Optimized for CPU and GPU with batching, quantization (INT8/FP16), and dynamic memory management. Powers faster-whisper and other production deployments. MIT lic
- **llama-swap**: Intelligent model swapping proxy for llama.cpp. Enables seamless hot-swapping between different GGUF models without restarting the server, with automatic model loading/unloading and OpenAI-compatible API. MIT licensed.
- **optillm**: Optimizing inference proxy for LLMs with load balancing, failover, and request routing across multiple providers and models. Improves reliability and performance for production deployments. Apache 2.0 licensed.
- **mllm**: Fast and lightweight multimodal LLM inference engine for mobile and edge devices. Optimized for running vision-language models on resource-constrained hardware with efficient memory management. MIT licensed.
- **shimmy**: Python-free Rust inference server with OpenAI API compatibility. Supports GGUF and SafeTensors formats with hot model swap, auto-discovery, and single binary deployment for zero-dependency inference. Apache 2.0 licensed.
- **PowerInfer**: High-speed LLM inference for local deployment on consumer GPUs. Achieves up to 11x speedup over llama.cpp on RTX 4090 by exploiting power-law neuron activation patterns. MIT licensed.
- **distributed-llama**: Distributed LLM inference connecting home devices into a powerful cluster. More devices means faster inference via tensor parallelism over Ethernet. Supports Linux, macOS, Windows, ARM, and x86_64 AVX2 CPUs. MIT licensed.
- **ik_llama.cpp**: High-performance llama.cpp fork with better CPU and hybrid GPU/CPU performance, SOTA quantization types, first-class Bitnet support, and improved DeepSeek performance via MLA, FlashMLA, and fused MoE operations. MIT licensed.
- **xLLM**: High-performance inference engine optimized for Chinese AI accelerators (Cambricon MLU, Hygon DCU, Huawei Ascend). Features service-engine decoupled architecture with elastic scheduling, PD disaggregation, and global KV cache management. Powers JD.co
- **Mooncake**: Production-grade serving platform for Kimi (Moonshot AI). Features distributed KV cache pool with intelligent offloading, prefill/decode disaggregation, and cross-instance KV reuse. Integrated with vLLM, SGLang, and TensorRT-LLM. Apache 2.0 licensed.
- **gemma.cpp**: Lightweight, standalone C++ inference engine for Google's Gemma models. Optimized for on-device deployment with minimal dependencies and efficient memory usage. Apache 2.0 licensed.
- **FlashInfer**: Kernel library for LLM serving. High-performance CUDA kernels for attention, sampling, and matrix multiplication. Powers vLLM, SGLang, and other inference engines with optimized GPU kernels. Apache 2.0 licensed.

#### Inference Kernels & Runtime Primitives (7 tools)

- **DeepEP**: Communication library for efficient expert-parallel training/inference pipelines, reducing MoE cross-device communication overhead. Apache 2.0 licensed.
- **DeepGEMM**: Clean, high-performance FP8 GEMM kernels with fine-grained scaling for modern inference workloads. Apache 2.0 licensed.
- **RAFT**: CUDA-accelerated algorithms and ANN building blocks for high-performance similarity search, clustering, and matrix learning workloads.
- **SageAttention**: Quantized attention kernels with reported 2-5x speedups versus FlashAttention across text, image, and video models. Apache 2.0 licensed.
- **ThunderKittens**: CUDA tile primitives and kernel templates for accelerating transformer attention blocks. MIT licensed.
- **tt-metal**: TT-Metalium + TT-NN operator stack for building and optimizing kernels on Tenstorrent AI accelerators. Apache 2.0 licensed.
- **mini-sglang**: Compact implementation of SGLang designed to demystify modern LLM serving systems. Educational yet production-quality with RadixAttention, continuous batching, and speculative decoding. MIT licensed.

#### Quantization, Distillation & Optimization (4 tools)

- **bitsandbytes**: 8-bit and 4-bit optimizers + quantization.
- **ExLlamaV2**: Highly optimized CUDA kernels for 4-bit/8-bit inference.
- **Optimum**: Hardware-specific acceleration and quantization.
- **HQQ**: Half-quadratic quantization toolkit for fast low-bit model quantization and efficient local inference.

## 4. Agentic AI & Multi-Agent Systems

#### Single-Agent Frameworks (31 tools)

- **AutoGPT**: The original autonomous AI agent framework that sparked the agent revolution. Vision of accessible AI for everyone with modular agent architecture, benchmark testing, and forge-based agent building. 183k+ stars.
- **BabyAGI**: Pioneering task-driven autonomous agent that inspired the AI agent movement. Simple, elegant implementation of an AI agent that creates, prioritizes, and executes tasks autonomously. 22k+ stars.
- **LangGraph**: Stateful, controllable agent orchestration.
- **CrewAI**: Role-based agent framework.
- **AutoGen (AG2)**: Flexible multi-agent conversation framework.
- **DSPy**: Framework for programming language model pipelines with modules, optimizers, and evaluation loops.
- **Semantic Kernel**: SDK for building and orchestrating AI agents and workflows across multiple programming languages.
- **smolagents**: Lightweight agent framework centered on tool use and code-executing workflows.
- **LangChain**: Foundational library for agents, chains, and memory.
- **Neuron AI**: PHP Agentic Framework for building production-ready AI driven applications. Connect components (LLMs, vector DBs, memory) to agents that can interact with your data. MIT licensed.
- **II-Agent (Intelligent Internet)**: New open-source framework to build and deploy intelligent agents with support for Claude, Gemini, and OpenAI models. Apache 2.0 licensed.
- **Hermes Agent (NousResearch)**: The agent that grows with you. Autonomous server-side agent with persistent memory that learns and improves over time.
- **Strands Agents**: Model-driven approach to building AI agents in just a few lines of code. Multi-agent systems, autonomous agents, and streaming support with built-in MCP. Apache 2.0 licensed.
- **Agno**: Build, run, and manage agentic software at scale. High-performance framework for multi-agent systems with memory, knowledge, and tools.
- **Upsonic**: Agent framework for fintech and banking with built-in MCP support, guardrails, and tool server architecture.
- **VoltAgent**: TypeScript-first AI agent engineering platform with memory, RAG, workflows, MCP integration, and voice support.
- **PocketFlow**: 100-line minimalist LLM framework for building agent workflows. Lightweight, extensible architecture for tool use and autonomous task execution.
- **Agent Development Kit (Google)**: Code-first Python toolkit for building sophisticated AI agents with multi-agent orchestration, built-in evaluation, and flexible deployment. Model-agnostic with tight Google ecosystem integration. Apache 2.0 licensed.
- **PydanticAI**: Type-safe AI agent framework from the creators of Pydantic. Model-agnostic with 20+ providers, built-in observability via Logfire, MCP/A2A protocol support, and YAML/JSON agent definitions. MIT licensed.
- **Qwen-Agent**: Agent framework built on Qwen models featuring function calling, MCP support, code interpreter, RAG, and Chrome extension. Powers Qwen Chat with advanced tool use and planning capabilities. Apache 2.0 licensed.
- **Griptape**: Modular Python framework for AI agents and workflows with chain-of-thought reasoning, tools, and memory. Enforces structures like sequential pipelines and DAG-based workflows for predictable AI systems. Apache 2.0 licensed.
- **Langroid**: Harness LLMs with multi-agent programming. Mature tool calling system based on Pydantic, supports hundreds of LLM providers including OpenAI and local servers. Built for robust agent behavior in real-world use cases. MIT licensed.
- **Octomind**: Model-agnostic AI agent runtime written in Rust with specialist agents, MCP support, multiple provider integrations, and zero-config setup. Apache 2.0 licensed.
- **Marvin**: Python framework for structured outputs and agentic AI workflows. Simplifies LLM interactions with type-safe interfaces, automatic schema generation, and built-in observability. From the creators of Prefect. Apache 2.0 licensed.
- **Burr**: Apache incubating framework for building stateful AI applications (chatbots, agents, simulations). Monitor, trace, persist, and execute on your own infrastructure with built-in UI and pluggable memory. Apache 2.0 licensed.
- **KaibanJS**: JavaScript-native framework for building and managing multi-agent systems with a Kanban-inspired approach. Visual task board for AI agents with real-time collaboration features. MIT licensed.
- **Jido**: Autonomous agent framework for Elixir. Built for distributed, autonomous behavior and dynamic workflows with actor-model concurrency. Apache 2.0 licensed.
- **Flue**: Programmable TypeScript harness and sandbox agent framework for building autonomous workflows and agents. Apache 2.0 licensed.
- **Agent-Native**: TypeScript-first framework for building agent-first applications featuring shared database state, real-time multiplayer editing, and action-driven tools. ISC licensed.
- **rlm**: General plug-and-play inference library for Recursive Language Models (RLMs) that programmatically execute sub-LM calls inside isolated code sandboxes.
- **Page Agent**: JavaScript-native, in-page GUI agent framework for controlling web interfaces with natural language without screenshots or external browser automation. MIT licensed.

#### Multi-Agent Orchestration (34 tools)

- **MetaGPT**: The Multi-Agent Framework: First AI Software Company. Assigns different roles to GPTs to form a collaborative software entity. Takes one-line requirements and outputs comprehensive software development artifacts including user stories, competitive an
- **ChatDev**: Multi-agent software development framework where AI agents collaborate as programmers, designers, and testers to build software. Apache 2.0 licensed.
- **CAMEL**: First and best multi-agent framework for building scalable agent systems. Apache 2.0 licensed with extensive tooling for agent communication and task automation.
- **DeepAgents**: Batteries-included LangChain agent harness for building and running structured multi-agent workflows with reusable runtime patterns.
- **Swarms**: Bleeding-edge enterprise multi-agent orchestration.
- **Mastra**: TypeScript-first agent framework with built-in RAG, workflows, tool integrations, observability and observational memory.
- **Deer-Flow (ByteDance)**: Open-source long-horizon SuperAgent harness that researches, codes, and creates. Handles tasks from minutes to hours with sandboxes, memories, tools, skills, subagents, and message gateway.
- **OpenAI Agents SDK**: Production-ready lightweight framework for multi-agent workflows. The evolution of Swarm with enhanced orchestration capabilities and enterprise-grade features.
- **Symphony**: Turns project work into isolated, autonomous implementation runs. Monitors work boards, spawns agents to handle tasks, and provides proof of work including CI status, PR reviews, and walkthrough videos. Engineering preview for managing work instead o
- **Paperclip**: AI agent company and orchestration framework with 55K+ stars. MIT licensed.
- **AgentScope**: Alibaba's production-ready multi-agent framework with 23K+ stars. Features built-in MCP and A2A support, message hub for flexible orchestration, and AgentScope Runtime for production deployment.
- **mcp-agent**: Build effective agents using Model Context Protocol and simple workflow patterns. Handles connection mechanics, LLM integration, and persistent state for production MCP-based agents. MIT licensed.
- **Microsoft Agent Framework**: Microsoft's official framework combining AutoGen's agent abstractions with Semantic Kernel's enterprise features. Supports Python and .NET with graph-based workflows.
- **Agency Swarm**: Reliable multi-agent orchestration framework built on top of the OpenAI Assistants API with organizational structure modeling.
- **elizaOS**: Autonomous multi-agent framework for building and deploying AI-powered applications. Features Discord/Telegram/Farcaster connectors, RAG support, and a modern web dashboard.
- **OpenManus**: Open-source framework for building general AI agents. Modular agent architecture with planning, tool use, and autonomous task execution. 56k+ stars. MIT licensed.
- **OpenAgents**: AI Agent Networks for Open Collaboration. Platform for building collaborative multi-agent systems with shared knowledge and distributed task execution. Apache 2.0 licensed.
- **Hive (Aden)**: Production-grade multi-agent orchestration framework with 10K+ stars. Apache 2.0 licensed.
- **Agent Squad (AWS Labs)**: Flexible multi-agent orchestration framework with intelligent intent classification and context management. Supports Python and TypeScript with pre-built agents for Bedrock, Lex, and custom integrations. Apache 2.0 licensed.
- **DeepResearchAgent**: Hierarchical multi-agent system for deep research tasks with automated task decomposition and execution across complex domains.
- **Composio Agent Orchestrator**: Agentic orchestrator for parallel coding agents. Plans tasks, spawns agents, and autonomously handles CI fixes, merge conflicts, and code reviews. MIT licensed.
- **Open Multi-Agent**: TypeScript-native multi-agent orchestration with multi-model teams and parallel execution. Automatically converts goals to task DAGs. MIT licensed.
- **BeeAI Framework (IBM)**: Production-ready multi-agent framework in Python and TypeScript. Features workflow orchestration, ACP/MCP protocol support, and deep watsonx integration. Part of Linux Foundation AI & Data program.
- **AI Town**: Deployable starter kit for building virtual towns where AI characters live, chat and socialize. Inspired by Stanford's Generative Agents research with persistent agent memory and social interactions. MIT licensed.
- **Conductor OSS**: Event-driven agentic orchestration platform providing durable and resilient execution engine for applications and AI agents. Battle-tested at Netflix, Tesla, LinkedIn, and J.P. Morgan with 30K+ stars. Apache 2.0 licensed.
- **A2A Protocol**: Agent2Agent (A2A) open protocol enabling communication and interoperability between opaque agentic applications. Donated to Linux Foundation by Google with 50+ technology partners. Apache 2.0 licensed.
- **777genius/agent-teams-ai**: Multi-agent orchestration runtime with Kanban-style team management, message review loops, and provider integrations for reusable agentic teams.
- **Panniantong/Agent-Reach**: Reusable search and web-ingestion layer for AI agents spanning Reddit, X/Twitter, YouTube, GitHub, Bilibili and more through one CLI.
- **xerrors/Yuxi**: Self-hosted multi-tenant agent harness combining retrieval, knowledge graph grounding, and workflow orchestration for production teams.
- **Sim Studio**: Open-source AI workspace for building, deploying, and orchestrating AI agents. Visual canvas with 1000+ integrations, multi-framework support (Agno, OpenAI, LangChain, Google ADK), and self-hosted or cloud deployment. Apache 2.0 licensed.
- **2FastLabs Agent Squad**: Flexible, lightweight open-source framework for orchestrating multiple AI agents to handle complex conversations with parallel execution capabilities. Apache 2.0 licensed.
- **SIA**: Self-improving framework that orchestrates meta, target, and feedback agents to autonomously optimize the performance of AI models and agents on benchmark tasks. MIT licensed.
- **Council of High Intelligence**: Multi-agent deliberation framework that routes specialized personas across different LLM providers to debate topics and reach consensus.
- **Gas Town**: Multi-agent workspace manager and orchestration system for Claude Code and other coding agents with persistent work tracking, mailboxes, and automated merge queues. MIT licensed.

#### Agent Protocols & Standards (5 tools)

- **Agent File**: Open file format (.af) for serializing stateful AI agents with persistent memory and behavior. Share, checkpoint, and version control agents across compatible frameworks. Apache 2.0 licensed.
- **Agent Gateway**: Next-generation proxy and routing layer for AI agents and MCP servers, with Kubernetes-native transport, protocol interoperability, and service-mesh-style isolation for reliable agent infrastructure. Apache 2.0 licensed.
- **Agent Governance Toolkit**: Policy, safety, and execution controls for autonomous AI agents, including governance guardrails, sandboxing, and reliability checks. Apache 2.0 licensed.
- **DESIGN.md (Google)**: A format specification for describing visual identity to coding agents, combining YAML tokens and markdown prose to give agents a structured understanding of design systems. Apache 2.0 licensed.
- **Agent Skills**: Standardized specification and document format for bundling and progressively loading AI agent capabilities, instructions, scripts, and resources. Apache 2.0 licensed.

#### Agent Context, Memory & Knowledge (8 tools)

- **Codegraph**: Local pre-indexed code knowledge graph for coding agents to reduce token usage and redundant tool calls across Claude, Codex, and other agents.
- **Gortex**: Local-first code knowledge graph and code intelligence engine built in Golang with multi-repository support and real-time graph actualisation. Built for AI coding agents aiming to expose only the needed information, reducing token usage by up to 50x.
- **Graphify**: AI coding assistant skill that indexes codebases, databases, and documents into a queryable knowledge graph for coding agents. MIT licensed.
- **Headroom**: Context compression proxy for tool outputs, logs, and RAG chunks, reducing token pressure while preserving intent for AI agents.
- **llmtrim**: Self-hosted Rust proxy, MCP server, CLI, and library that compresses LLM prompts, tool outputs, and replies to cut token usage, quality-gated so it never raises your bill. AGPL-3.0 licensed.
- **MemPalace**: High-performance, benchmarked AI memory system for persistent recall and retrieval in long-horizon autonomous workflows.
- **Supermemory**: Memory engine and API designed for long-lived AI agents to store, retrieve, and reuse long-horizon context with low latency.
- **codebase-memory-mcp**: High-performance C-based codebase intelligence engine and MCP server that indexes repositories into local type-resolved knowledge graphs. MIT licensed.

#### Autonomous Coding Agents (31 tools)

- **OpenHands (ex-OpenDevin)**: Full-featured open-source AI software engineer.
- **HEXStrike AI**: MCP-powered coding-focused cybersecurity agent framework for automated pentesting and bug-hunting workflows.
- **VulnClaw**: Autonomous penetration testing agent utilizing Model Context Protocol (MCP) toolchains, blackboard state space search, and structured reasoning.
- **Goose**: Extensible on-machine AI agent for development tasks.
- **OpenShell (NVIDIA)**: Safe and private runtime for autonomous AI agents with policy-driven execution boundaries and CLI integration.
- **CodeGraph**: Pre-indexed local code knowledge graph for Claude Code, Codex, Gemini, and other coding agents to reduce context churn and token spend in developer workflows.
- **OpenCode**: Terminal-native autonomous coding agent.
- **ECC**: Performance-oriented agent harness for coding agents with skills, memory, and security-aware orchestration across Claude Code, Codex, and more.
- **oh-my-pi**: Terminal coding agent with hash-anchored edits, subagents, LSP, browser integrations, and terminal-native workflows.
- **Pi (earendil-works)**: Modular agent toolkit with terminal-first CLI, unified model/provider layer, and runtime integrations for coding workflows and TUI/web UIs.
- **Aider**: Command-line pair-programming agent.
- **Pi (badlogic)**: Terminal coding agent with hash-anchored edits, LSP integration, subagents, MCP support, and package ecosystem.
- **Mistral-Vibe (Mistral)**: Minimal CLI coding agent by Mistral. Lightweight, fast, and designed for local development workflows.
- **Nanocoder (Nano-Collective)**: Beautiful local-first coding agent running in your terminal. Built for privacy and control with support for multiple AI providers via OpenRouter.
- **Gemini CLI (Google)**: Open-source AI agent that brings Gemini's power directly into your terminal. Supports code generation, shell execution, and file editing with full Apache 2.0 licensing.
- **Archon**: Workflow engine for deterministic AI coding agents. Define development processes as YAML workflows (planning → implementation → validation → review → PR) with isolated Git worktrees for parallel execution. MIT licensed.
- **mini-SWE-agent**: Lightweight coding agent for repository and issue-fixing workflows, designed for simple agentic software engineering experiments.
- **Trae Agent**: Software-engineering agent from ByteDance for autonomous coding tasks and repository-level development workflows.
- **Kilo Code**: Open-source agentic coding assistant with IDE workflows, tool use, and support for local or OpenAI-compatible models.
- **Open SWE**: Asynchronous coding agent from the LangChain ecosystem for background software engineering tasks.
- **Letta Code**: Memory-first coding harness designed for long-lived agents that learn from experience. Persistent agents with portable memory across models (Claude, GPT, Gemini, GLM, Kimi). CLI and desktop app for macOS, Windows, and Linux. Apache 2.0 licensed.
- **gptme**: Your agent in your terminal, equipped with local tools: writes code, uses the terminal, browses the web. Make your own persistent autonomous agent on top. MIT licensed.
- **Superpowers**: Composable skills framework and software development methodology for coding agents, structuring processes like planning, test-driven development, and code review.
- **Agent Skills**: Production-grade engineering skills and quality gates for AI coding agents, packaging developer workflows like spec refinement, planning, and testing.
- **Harness**: Team-architecture factory for C‍laude Code that designs domain-specific agent teams, defines specialized agents, and generates their skills. Apache 2.0 licensed.
- **jcode**: Performance-oriented, memory-efficient coding agent harness built for multi-session workflows and infinite customizability. MIT licensed.
- **DeepSeek-Reasonix**: DeepSeek-native AI coding agent for the terminal, designed around prefix-cache stability. MIT licensed.
- **gstack**: Multi-specialist agent skills framework for Claude Code and coding agents that structures development workflows into planning, design, QA, and release phases. MIT licensed.
- **taste-skill**: Anti-slop frontend design skills for coding agents that improve layout, typography, and design system alignment during generation. MIT licensed.
- **Agents CLI (Google)**: CLI and skills that turn coding assistants into experts at creating, evaluating, and deploying AI agents on Google Cloud. Apache 2.0 licensed.
- **Claude Code Skills & Plugins**: Modular instruction packages, custom commands, and utility scripts for Claude Code, Gemini CLI, Cursor, and other AI coding agents. MIT licensed.

#### Prompt Engineering & Structured Outputs (9 tools)

- **Outlines**: Structured outputs for LLMs. Guarantees valid JSON, regex-compliant text, and Pydantic model outputs during generation. Trusted by NVIDIA, Cohere, Hugging Face, and vLLM. Apache 2.0 licensed.
- **Promptify**: Task-based NLP engine with Pydantic structured outputs, built-in evaluation, and LiteLLM as the universal LLM backend. Think "scikit-learn for LLM-powered NLP". Apache 2.0 licensed.
- **LangGPT**: Pioneering framework for structured and meta-prompt design. Battle-tested by thousands of users worldwide with 10,000+ stars. The most popular prompt engineering paradigm for creating reusable, maintainable prompt templates. Apache 2.0 licensed.
- **Prompt Optimizer**: AI prompt optimization tool with multi-round iterative improvements, dual-mode optimization for system and user prompts, and multi-model support. Available as web app, desktop app, Chrome extension, and Docker deployment. AGPL-3.0 licensed.
- **Guidance**: Efficient programming paradigm for steering language models. Control output structure with loops, conditionals, and regex constraints inline. Reduces latency and cost vs conventional prompting. MIT licensed.
- **XGrammar**: Fast, flexible and portable structured generation engine. Default backend for vLLM, SGLang, TensorRT-LLM, and MLC-LLM with flexible grammar support and zero-overhead mask generation. Apache 2.0 licensed.
- **LM Format Enforcer**: Enforce output format (JSON Schema, Regex, etc) of language models by filtering allowed tokens at each generation step. Compatible with Hugging Face, llama-cpp-python, and vLLM. MIT licensed.
- **AdalFlow**: Library to build and auto-optimize LLM applications with LLM-AutoDiff for fine-tuning-free optimization. End-to-end workflow optimization with tracing and human-in-the-loop capabilities. MIT licensed.
- **PromptTools**: Open-source tools for prompt testing and experimentation with support for LLMs and vector databases. Test prompt variants across multiple providers (OpenAI, LLaMA) and vector stores (Chroma, Weaviate, LanceDB). Apache 2.0 licensed.

#### Domain-Specific Agents (28 tools)

- **Composio**: Tool integration layer for AI agents with 1000+ toolkits, authentication management, and sandboxed workbench. Powers tool use across major frameworks.
- **Langflow**: Visual low-code platform for agentic workflows.
- **Dify**: Production-ready agentic workflow platform.
- **OWL (camel-ai/owl)**: Advanced multi-agent collaboration system.
- **gpt-researcher**: Autonomous agent that conducts deep online research on any topic. Generates comprehensive reports with citations by orchestrating web searches, content scraping, and synthesis. Apache 2.0 licensed.
- **last30days-skill**: AI agent that researches and synthesizes topic trends from Reddit, X, YouTube, Hacker News, and prediction markets. MIT licensed.
- **pm-skills**: Marketplace of product management plugin skills and workflows for Claude Code, Codex, and Claude Cowork. MIT licensed.
- **claude-code-best-practice**: Custom subagents, skills, environment configurations, and best practices for the Claude Code developer agent.
- **PPT Master**: AI-driven multi-role agent skill for converting documents into editable PowerPoint presentations via SVG and DrawingML workflows. MIT licensed.
- **PraisonAI**: 24/7 AI employee team for automating complex challenges. Low-code multi-agent framework with handoffs, guardrails, memory, RAG, and 100+ LLM providers.
- **Agent-S (Simular AI)**: Open agentic framework that uses computers like a human. SOTA on OSWorld benchmark (72.6%) for GUI automation and computer control.
- **MobileAgent (Alibaba/X-PLUG)**: Powerful GUI agent family for autonomous mobile device control. Multimodal agent framework designed to operate smartphone apps through visual UI perception and reasoning. MIT licensed.
- **UI-TARS Desktop (ByteDance)**: Open-source multimodal AI agent stack with native GUI agent capabilities. Desktop application bringing GUI agent and vision power to your computer, browser, and terminal. Apache 2.0 licensed.
- **Browser Use**: Makes websites accessible for AI agents. Enables autonomous web automation, data extraction, and task completion with natural language instructions. MIT licensed.
- **Headroom**: Token and output compression middleware for AI agents and RAG workflows, reducing context footprint while preserving semantics (claims up to 60-95% fewer tokens). Apache 2.0 licensed.
- **Steel Browser**: Open-source browser API for AI agents and apps. Batteries-included browser sandbox for web automation without infrastructure worries. Apache 2.0 licensed.
- **Cua**: Open-source sandboxes, SDKs, and benchmarks for computer-use agents to control desktop environments. MIT licensed.
- **Webwright**: A terminal-style web agent framework that enables coding models to run as browser agents by writing and executing Playwright scripts. MIT licensed.
- **TradingAgents**: Multi-agent framework for financial trading. Simulates professional trading firm operations with 6+ specialized agent roles, backtesting, risk management, and portfolio optimization. Built with LangGraph, supports multiple LLM providers.
- **Parlant**: Conversational control layer for customer-facing AI agents. Enterprise-grade context engineering framework optimized for consistent, compliant, and on-brand B2C and sensitive B2B interactions. Apache 2.0 licensed.
- **n8n**: Self-hostable workflow automation platform with AI agent nodes, tool integrations, and production automation workflows.
- **Activepieces**: Open-source automation platform with AI agents, MCP integrations, and self-hosted workflow orchestration.
- **Julep**: Stateful agent workflow platform with memory, tools, branching, and long-running task execution.
- **uAgents (Fetch.ai)**: Fast and lightweight framework for creating decentralized agents with ease. Agents automatically join the network by registering on the Almanac smart contract. Supports agent-to-agent communication out of the box. Apache 2.0 licensed.
- **Tracecat**: Self-hostable security automation platform for building agentic workflows across alerts, cases, and operations.
- **ToolJet**: Self-hostable internal app builder with AI app and agent workflows for operations teams.
- **The Agency**: Extensive library of specialized developer and workflow agent personas with installer support for Claude Code, Cursor, Codex, and other coding assistants.
- **CubeSandbox (Tencent Cloud)**: High-performance, secure agent sandbox built on RustVMM and KVM, compatible with the E2B SDK. Apache 2.0 licensed.

#### Agent Memory & State (8 tools)

- **Letta (ex-MemGPT)**: Platform for building stateful agents with advanced memory that learn and self-improve over time.
- **Mem0**: Universal memory layer for AI agents. Persistent, multi-session memory across models and environments.
- **Rohitg (agentmemory)**: Open-source memory service for agents with benchmarked retrieval, structured entities, and API/SDK support for persistent personalized memory in tooling workflows.
- **Forgetful**: MCP server for persistent AI agent memory with atomic notes, semantic linking, and SQLite or PostgreSQL storage.
- **Hindsight**: State-of-the-art long-term memory for AI agents by Vectorize. Fully self-hosted, MIT-licensed, with integrations for LangChain, CrewAI, LlamaIndex, Vercel AI SDK, and more.
- **Supermemory**: Memory API and app for AI agents that provides fast, scalable, context-aware storage and retrieval across projects. MIT licensed.
- **TencentDB Agent Memory**: Fully local long-term memory layer for AI agents with a four-tier progressive pipeline and zero external dependencies. MIT licensed.
- **Cognee**: AI memory platform for agents that builds a self-hosted knowledge graph for persistent, long-term memory across sessions. Apache 2.0 licensed.

## 5. Retrieval-Augmented Generation (RAG) & Knowledge

#### Vector Databases & Search Engines (39 tools)

- **Chroma**: Most popular open-source embedding database.
- **Qdrant**: High-performance vector search engine in Rust.
- **Weaviate**: GraphQL-native vector search engine.
- **Milvus**: Scalable cloud-native vector database.
- **NornicDB**: Low-latency graph and vector hybrid retrieval database in Go with Neo4j and Qdrant-compatible drivers.
- **Faiss**: Similarity search and clustering library for dense vectors with CPU and GPU implementations.
- **LanceDB**: Serverless vector DB optimized for multimodal data.
- **Vespa**: AI + Data platform with hybrid search (vector + keyword) and real-time indexing at scale. Battle-tested serving billions of queries daily.
- **pgvector**: PostgreSQL extension for vector similarity search.
- **pgvectorscale**: PostgreSQL extension for scalable vector search with DiskANN algorithm. Complements pgvector with significantly faster search and higher recall at large scale. PostgreSQL licensed.
- **VectorChord**: Scalable, fast, and disk-friendly vector search in Postgres. Successor to pgvecto.rs with production-grade performance and efficient storage. AGPL-3.0 licensed.
- **Quickwit**: Cloud-native search engine for observability. Open-source alternative to Datadog, Elasticsearch, Loki, and Tempo with native vector search support.
- **Tantivy**: Full-text search engine library inspired by Apache Lucene and written in Rust. Powers Quickwit and other production search systems.
- **Manticore Search**: Easy to use open source fast database for search. Good alternative to Elasticsearch with SQL-like interface and vector search capabilities.
- **OpenSearch**: Open-source distributed and RESTful search and analytics suite with native vector search. Enterprise-grade fork of Elasticsearch with k-NN plugin for semantic search at scale.
- **Marqo**: Multimodal vector search for text, image, and structured data. End-to-end indexing and search with built-in embedding models. Apache 2.0 licensed.
- **Vald**: Highly scalable distributed vector search engine. Cloud-native architecture with automatic indexing, horizontal scaling, and multiple ANN algorithm support. Apache 2.0 licensed.
- **hnswlib**: Header-only C++ library for fast approximate nearest neighbors with Python bindings. Supports CRUD operations and concurrent read/write - unique among ANN libraries. Powers many production vector databases. Apache 2.0 licensed.
- **turbovec**: Rust-native high-performance vector index with Python bindings optimized for fast ANN search and SIMD acceleration on modern CPUs. MIT licensed.
- **sqlite-vec**: A vector search SQLite extension that runs anywhere. Extremely small, "fast enough" vector search written in pure C with no dependencies. Perfect for embedded and edge deployments. MIT/Apache-2.0 dual licensed.
- **zvec**: Lightweight, lightning-fast, in-process vector database from Alibaba. Built on Proxima (Alibaba's battle-tested vector search engine) for production-grade, low-latency similarity search. Apache 2.0 licensed.
- **Meilisearch**: Lightning-fast search engine API with AI-powered hybrid search. Features typo-tolerant full-text search combined with HNSW-based vector search for semantic retrieval. MIT licensed.
- **Typesense**: Open source alternative to Algolia + Pinecone. Fast, typo-tolerant, in-memory fuzzy search engine with native vector search capabilities. GPL-3.0 licensed.
- **Elasticsearch**: Distributed search and analytics engine with native k-NN vector search, hybrid search, and dense vector indexing. Industry-standard for full-text search now with powerful semantic search capabilities. AGPL-3.0/Elastic-2.0 dual licensed.
- **Apache Solr**: Mature Lucene-based search platform with dense vector search, filtering, faceting, and hybrid retrieval patterns for production search-heavy RAG systems.
- **RediSearch**: Full-text, secondary indexing, and vector similarity search for Redis deployments. Useful when retrieval needs low-latency Redis-native search.
- **ParadeDB**: Postgres-native search and analytics engine for full-text, faceted, and hybrid retrieval without moving data out of PostgreSQL.
- **Orama**: Lightweight search engine with full-text, vector, and hybrid search for browser, server, and edge applications.
- **HelixDB**: Graph-vector database for retrieval systems that need relationship traversal alongside semantic search.
- **USearch**: Fast single-file similarity search & clustering engine for vectors. Smaller and faster than FAISS with 20+ language bindings (C++, Python, JavaScript, Rust, Java, Go, etc.) and support for custom metrics. Apache 2.0 licensed.
- **Voyager (Spotify)**: Spotify's next-gen approximate nearest-neighbor search library for Python and Java. Up to 10x faster than Annoy with 4x less memory, designed for production use at billion-vector scale. Apache 2.0 licensed.
- **Deep Lake**: AI Data Runtime for Agents with serverless PostgreSQL and multimodal datalake. Store and search vectors, images, text, videos, and more with LangChain/LlamaIndex integrations. Used by Intel, Bayer, Yale, and Oxford. Apache 2.0 licensed.
- **DiskANN (Microsoft)**: Graph-structured indices for scalable, fast, fresh and filtered approximate nearest neighbor search. Handles billion-vector datasets on a single node with SSD-based indexing. MIT licensed.
- **SPTAG (Microsoft)**: Distributed approximate nearest neighbor search library with high-quality vector index build and online serving toolkits. Powers Bing's vector search at trillion-vector scale. MIT licensed.
- **nanoflann**: C++11 header-only library for fast nearest neighbor search with KD-trees. Zero dependencies, single-file integration, and 2-3x faster than FLANN with modern C++. BSD licensed.
- **NMSLIB**: Non-Metric Space Library for efficient similarity search in generic non-metric spaces. Comprehensive toolkit for evaluating k-NN methods with support for exotic distance functions. Apache 2.0 licensed.
- **Vearch**: Cloud-native distributed vector database for AI-native applications. Efficient similarity search of embedding vectors with horizontal scaling and real-time indexing. Apache 2.0 licensed.
- **JVector (DataStax)**: The most advanced embedded vector search engine for Java. DiskANN-based algorithm for billion-scale vector search with efficient memory mapping. Apache 2.0 licensed.
- **VectorDBBench (Zilliz)**: Industry-standard benchmark suite for vector databases. Test and compare performance of Milvus, Zilliz Cloud, and other vector DBs with your own datasets. MIT licensed.

#### Embedding Models (5 tools)

- **BGE (FlagEmbedding)**: BAAI's best-in-class embedding family.
- **E5 (Microsoft)**: High-performance text embeddings for retrieval.
- **FastEmbed (Qdrant)**: Lightweight, fast Python library for embedding generation with ONNX Runtime. Supports text, sparse (SPLADE), and late-interaction (ColBERT) embeddings without GPU dependencies. Apache 2.0 licensed.
- **EmbedAnything**: Minimalist, highly performant multimodal embedding pipeline built in Rust. Memory-safe, modular, and production-ready for text, image, and audio embeddings with seamless vector DB integration. Apache 2.0 licensed.
- **Text Embeddings Inference (Hugging Face)**: Blazing fast inference solution for text embedding models. High-performance extraction with token-based dynamic batching, Flash Attention, and support for FlagEmbedding, E5, GTE, and more. OpenAI-compatible API with Docker deployment. Apache 2.0 lice

#### Embedding Benchmarks (1 tools)

- **MTEB**: Massive Text Embedding Benchmark covering 1000+ languages and diverse tasks. The industry standard for evaluating and comparing embedding models.

#### RAG Frameworks & Advanced Retrieval Tools (39 tools)

- **EmbedChain**: Universal memory layer for AI agents. Simple API to create RAG applications over any dataset with support for multiple vector stores, embedding models, and LLM providers. Apache 2.0 licensed.
- **LlamaIndex**: Full-featured RAG pipeline with advanced indexing.
- **Haystack**: End-to-end NLP and RAG framework.
- **RAGFlow**: Deep-document-understanding RAG engine.
- **GraphRAG (Microsoft)**: Knowledge-graph-based RAG.
- **Docling**: Document processing toolkit for turning PDFs and other files into structured data for GenAI workflows.
- **Unstructured**: Best-in-class document preprocessing.
- **MinerU**: High-accuracy document parsing for LLM and RAG workflows. Converts PDFs, Word, PPTs, and images into structured Markdown/JSON with VLM+OCR dual engine.
- **Marker**: Fast, accurate PDF-to-markdown converter with table extraction, equation handling, and optional LLM enhancement for RAG pipelines.
- **ColPali / ColQwen**: Vision-language models for document retrieval.
- **LightRAG**: Graph-based RAG with dual-level retrieval system. Simple and fast with comprehensive knowledge discovery (EMNLP 2025).
- **RAG-Anything**: All-in-One Multimodal RAG system for seamless processing of text, images, tables, and equations. Built on LightRAG.
- **RAGLite (Superlinear)**: Python toolkit for RAG with DuckDB or PostgreSQL. Lightweight, efficient retrieval-augmented generation without heavy dependencies. MPL 2.0 licensed.
- **GPT-RAG (Azure)**: Enterprise RAG pattern for Azure OpenAI at scale. Secure, production-ready architecture using Azure Cognitive Search and Azure OpenAI LLMs for ChatGPT-style Q&A experiences. MIT licensed.
- **LangChain4j**: Java library for integrating LLMs into Java applications. Implements RAG, tool calling (including MCP support), and agents with seamless integration into enterprise Java frameworks like Spring Boot. Apache 2.0 licensed.
- **Kernel Memory (Microsoft)**: Memory solution for users, teams, and applications. RAG pipelines with document ingestion, vector indexing, and natural language querying with citations. Supports multiple LLM providers and vector stores. MIT licensed.
- **txtai**: All-in-one AI framework for semantic search, LLM orchestration and language model workflows. Embeddings database with customizable pipelines.
- **Infinity (Embeddings Server)**: High-throughput, low-latency serving engine for text-embeddings, reranking, CLIP, and ColPali. OpenAI-compatible API.
- **FlashRAG**: Efficient toolkit for RAG research with 40+ retrieval and reranking models, 20+ benchmark datasets, and optimized evaluation pipelines (WWW 2025 Resource). MIT licensed.
- **DocsGPT**: Private AI platform for building intelligent agents and assistants with enterprise search. Features Agent Builder, deep research tools, multi-format document analysis, and multi-model support. MIT licensed.
- **llmware**: Unified framework for building enterprise RAG pipelines with small, specialized models. Optimized for AI PC and local deployment with 300+ models in catalog. Apache 2.0 licensed.
- **AutoFlow**: Graph RAG-based conversational knowledge base tool built on TiDB Vector and LlamaIndex. Features Perplexity-style search with built-in website crawler. Apache 2.0 licensed.
- **KAG (OpenSPG)**: Knowledge Augmented Generation framework for logical reasoning and factual Q&A in professional domains. Builds on OpenSPG knowledge graph engine to overcome traditional RAG vector similarity limitations. Supports multi-hop reasoning with schema-const
- **Chonkie**: Lightweight document chunking library for fast, efficient RAG pipelines. Memory-safe with multiple chunking strategies (semantic, token, recursive) and direct vector DB integration. MIT licensed.
- **PageIndex (VectifyAI)**: Vectorless, reasoning-based RAG framework using document index structure. Achieves high accuracy without vector databases through intelligent context engineering and reasoning-based retrieval. MIT licensed.
- **Kotaemon (Cinnamon)**: Open-source RAG-based tool for chatting with your documents. Hybrid RAG pipeline with full-text and vector retriever, re-ranking, and multi-modal capabilities. Clean Gradio-based UI with support for local and API-based LLMs. Apache 2.0 licensed.
- **Reader (Jina AI)**: Convert any URL to LLM-friendly input with a simple prefix (r.jina.ai). Free service that extracts article content, removes clutter, and returns clean Markdown for RAG and agentic workflows. Apache 2.0 licensed.
- **UltraRAG (OpenBMB)**: First lightweight RAG framework based on Model Context Protocol (MCP) architecture. Low-code RAG pipeline builder with comprehensive evaluation system and DeepResearch capabilities. From Tsinghua THUNLP, NEUIR, OpenBMB, and AI9stars. Apache 2.0 licen
- **Semantic Router**: Superfast AI decision-making layer for LLMs and agents. Uses semantic vector space to route requests using semantic meaning rather than waiting for slow LLM generations. Cuts routing time from seconds to milliseconds. MIT licensed.
- **Neurite**: Fractal Graph-of-Thought mind-mapping for AI agents, web-links, notes, and code. Rhizomatic workspace blending chaos theory, graph theory, and fractal logic for creative thinking and RAG workflows. MIT licensed.
- **Pathway**: Python ETL framework for stream processing, real-time analytics, LLM pipelines, and RAG. Features 350+ connectors with always-in-sync data from SharePoint, Google Drive, S3, Kafka, PostgreSQL and more. BSL 1.1 license (becomes Apache 2.0 after 4 year
- **Infinity (AI Database)**: AI-native database built for LLM applications with incredibly fast hybrid search of dense vector, sparse vector, tensor (multi-vector), and full-text. Powers RAGFlow's document engine. Apache 2.0 licensed.
- **PrivateGPT**: Private document Q&A project for local and offline RAG workflows where data stays inside the user's environment.
- **FastGPT**: Knowledge-base platform with RAG retrieval, document processing, visual AI workflows, and self-hosted deployment options.
- **MaxKB**: Self-hostable knowledge-base and agent platform for document ingestion, RAG pipelines, and enterprise assistant workflows.
- **DB-GPT**: Self-hosted AI data assistant for private knowledge, database-aware conversations, and data-heavy RAG workflows.
- **localGPT**: Local document-chat project for private, on-device Q&A over files without sending data to external APIs.
- **SurfSense**: Privacy-focused NotebookLM-style workspace for teams to search, organize, and query knowledge with self-hosted RAG.
- **Morphik**: Open-source multimodal RAG framework for building AI apps over private knowledge. Handles text, images, and documents with built-in embedding generation and vector search. MIT licensed.

#### Knowledge Graphs for RAG (1 tools)

- **Graphiti**: Build real-time temporal knowledge graphs for AI agents. Tracks how facts change over time with provenance to source data. Supports prescribed and learned ontology for evolving real-world data. Apache 2.0 licensed.

#### Web Data Ingestion (6 tools)

- **Crawl4AI**: LLM-friendly web crawler that turns websites into clean Markdown for RAG and agentic workflows.
- **Scrapling**: Adaptive web scraping and crawling framework for robust structured extraction from pages to large-scale pipelines.
- **Lightpanda**: Machine-first headless browser in Zig; rendering-free and ultra-lightweight for AI agent browsing.
- **Paperless-AI**: Automated document analyzer for Paperless-ngx with RAG-powered semantic search across your document archive.
- **Firecrawl**: Web Data API for AI - search, scrape, and interact with the web at scale. Clean markdown/JSON output with proxy rotation and JS-blocking handled automatically.
- **invisible-playwright**: Playwright wrapper for a stealth-patched Firefox 150 binary. Drop-in Browser object for AI agents that need to ingest web data from sites with anti-bot guardrails (reCAPTCHA, FingerprintPro, Cloudflare). Spoofing happens in C++ source, not via JS ove

#### Document Conversion & Preprocessing (6 tools)

- **OpenDataLoader PDF**: Accessibility-aware PDF parser and conversion pipeline for AI-ready markdown and structured data workflows.
- **MarkItDown (Microsoft)**: Python tool for converting files and office documents to Markdown. Supports PDF, PowerPoint, Word, Excel, images, audio, HTML, and more with OCR and transcription capabilities. MIT licensed.
- **LiteParse**: Lightweight document parsing toolkit for AI and RAG pipelines with PDF/OCR extraction and clean preprocessing defaults.
- **PaddleOCR**: Large-scale OCR suite with detection, recognition, and layout analysis, used widely for document digitization and downstream RAG pipelines.
- **DocETL (UC Berkeley)**: Agentic LLM-powered data processing and ETL system for complex document processing. Query rewriting and evaluation for unstructured data analysis with 80% higher accuracy than baselines. MIT licensed.
- **olmOCR (Allen Institute for AI)**: Toolkit for reconstructing and linearizing PDF documents into clean text optimized for LLM datasets, training, and RAG pipelines. Apache 2.0 licensed.

#### LLM Application Frameworks (9 tools)

- **aisuite**: Simple, unified interface to multiple Generative AI providers. Use OpenAI, Anthropic, Google, and 10+ other providers with a standardized API similar to OpenAI's. Switch between models or providers with a single line of code. MIT licensed.
- **Spring AI**: Application framework for AI engineering in the Spring ecosystem. Unified API for LLMs, vector stores, and embedding models with seamless integration into Spring Boot applications. Supports RAG, tool calling, and structured outputs. Apache 2.0 licens
- **Rig**: Rust library for building scalable, modular LLM-powered applications. Type-safe agent framework with unified LLM interface, built-in vector store integrations, and ergonomic abstractions for production AI systems. MIT licensed.
- **Ax**: TypeScript framework for building reliable AI applications. "Official" DSPy-inspired framework for TypeScript with type-safe LLM interactions, chain-of-thought reasoning, and structured output validation. Apache 2.0 licensed.
- **Genkit**: Open-source framework for building full-stack AI-powered applications in JavaScript, Go, and Python. Built and used in production by Google's Firebase. Unified interface for integrating AI models from multiple providers with built-in RAG, tool callin
- **ContextGem**: Effortless LLM extraction framework for documents. Powerful abstractions for building extraction workflows with automated dynamic prompts, data modeling, validation, and precise reference mapping. Apache 2.0 licensed.
- **Eino**: The ultimate LLM/AI application development framework in Go. Drawing from LangChain and Google ADK, designed to follow Go conventions with composable components for chains, agents, and workflows. Apache 2.0 licensed.
- **ruby_llm**: One beautiful Ruby API for OpenAI, Anthropic, Gemini, Bedrock, Azure, OpenRouter, DeepSeek, Ollama, and 15+ providers. Agents, Chat, Vision, Audio, PDF, Images, Embeddings, Tools, Streaming and Rails integration. MIT licensed.
- **LangChain.rb**: Build LLM-powered applications in Ruby. Idiomatic Ruby library for building AI applications with support for multiple LLM providers, vector stores, and RAG pipelines. MIT licensed.

## 6. Generative Media Tools

#### Image Generation & Editing (10 tools)

- **ComfyUI**: Node-based visual workflow editor for Stable Diffusion, FLUX, etc.
- **Stable Diffusion WebUI Forge - Neo**: Actively maintained Forge-based Stable Diffusion web UI with the familiar extension-driven workflow.
- **Diffusers**: PyTorch library for diffusion pipelines spanning image, video, and audio generation.
- **InvokeAI**: Full-featured creative studio.
- **SD.Next**: All-in-one WebUI for AI generative image and video creation with multi-platform support, SDNQ quantization, and balanced CPU/GPU memory offload.
- **Qwen-Image (Alibaba)**: 20B MMDiT image foundation model with state-of-the-art complex text rendering and precise image editing. Strong performance in Chinese text generation. Apache 2.0 licensed.
- **stable-diffusion.cpp**: Production-ready C++ inference runtime for SD, Flux, and related diffusion models, optimized for CPU and GPU deployment.
- **Upscayl**: Free and open-source AI image upscaler for Linux, macOS, and Windows. Uses Real-ESRGAN and Vulkan architecture to enhance images by reconstructing high-resolution details. Cross-platform desktop app with batch processing. AGPL-3.0 licensed.
- **Z-Image (Tongyi)**: Powerful and efficient image generation model family with 6B parameters. Includes Z-Image-Turbo for sub-second inference and Z-Image-Omni-Base for both generation and editing. Strong bilingual text rendering and instruction adherence. Apache 2.0 lice
- **Krita AI Diffusion**: Streamlined AI image generation plugin for Krita. Inpaint and outpaint with optional text prompt, no tweaking required. Integrates ComfyUI backend for professional digital painting workflows. GPL-3.0 licensed.

#### Face Swap & Deepfake (1 tools)

- **Deep-Live-Cam**: Real-time face swap and one-click video deepfake with only a single image. High-quality face swapping for live video streaming and content creation. AGPL-3.0 licensed.

#### Portrait Animation (1 tools)

- **EchoMimic (Ant Group)**: Lifelike audio-driven portrait animations through editable landmark conditioning. High-quality talking head generation with precise lip synchronization and natural head movements. AAAI 2025. Apache 2.0 licensed.

#### Video Generation (12 tools)

- **Wan2.2 (Alibaba)**: Leading open Mixture-of-Experts text-to-video model.
- **SkyReels V2/V3 (Skywork)**: First open-source infinite-length film generative model using AutoRegressive Diffusion-Forcing.
- **Hyperframes (HeyGen)**: Open-source long video generation platform for cinematic and social video creation with timeline control, diffusion-based motion modules, and multimodal conditioning.
- **LTX-2 (Lightricks)**: Official Python inference and LoRA trainer package for the LTX-2 audio–video generative model.
- **Open-Sora-Plan (PKU-YuanGroup)**: Reproduction of Sora with full open-source pipeline for text-to-video generation. MIT licensed.
- **Helios (PKU-YuanGroup)**: Efficient long-video generation framework with 24GB VRAM support for up to 10,000 frames (5+ minutes) and 1280×768 resolution. Apache 2.0 licensed.
- **Pixelle-Video (AIDC-AI)**: Text-to-video foundation model optimized for long coherent scenes and controllable generation workflows. Apache 2.0 licensed.
- **ViralMint**: End-to-end short-video pipeline that scouts trends, transcribes competitors locally, and assembles captioned videos with AI scripts, voice, and stock footage. AGPL-3.0 licensed.
- **MoneyPrinterTurbo**: An end-to-end short-video generation pipeline that automates scripts, footage collection, voiceover, and subtitle synthesis. MIT licensed.
- **ViMax**: Multi-agent video generation framework that orchestrates scriptwriting, storyboarding, character design, and temporal visual consistency for end-to-end video synthesis. MIT licensed.
- **OpenMontage**: Agentic video production system utilizing pipelines, tools, and agent skills to generate scripts, footage, narration, and composition. AGPL-3.0 licensed.
- **WhisperLive**: Nearly-live implementation of OpenAI's Whisper for real-time speech-to-text transcription. Supports faster-whisper, tensorrt, and openvino backends with WebSocket streaming. MIT licensed.

#### Audio / Music / Voice Generation (8 tools)

- **ACE-Step 1.5**: Local-first music generation model with broad hardware support across Mac, AMD, Intel, and CUDA devices.
- **Magenta RealTime 2**: Open-weights live music model for streaming generation and real-time interaction. Apache 2.0 licensed.
- **Amphion**: Comprehensive toolkit for Audio, Music, and Speech Generation (9.7K stars).
- **Stable Audio Tools**: Stability AI's open-source audio and music generative models. Latent diffusion model for generating audio conditioned on metadata and timing, providing faster inference times and creative control for sound effects and music production. MIT licensed.
- **GPT-SoVITS**: Few-shot voice cloning with just 1 minute of voice data. Combines GPT and SoVITS architectures for high-quality TTS with cross-lingual support and emotional expression. MIT licensed.
- **Real-Time Voice Cloning**: Clone a voice in 5 seconds to generate arbitrary speech in real-time. SV2TTS implementation with speaker encoder and vocoder for instant voice synthesis. MIT licensed.
- **Supertonic**: Lightning-fast, on-device, multilingual text-to-speech system running natively via ONNX. MIT licensed.
- **Voicebox**: Local-first AI voice studio to clone voices, generate speech in multiple languages, and dictate text locally. MIT licensed.

#### 3D & Creative Tools (3 tools)

- **gsplat (3D Gaussian Splatting tools)**: High-performance 3D Gaussian Splatting library.
- **LichtFeld-Studio**: Native application for training, editing, and exporting 3D Gaussian Splatting scenes with MCMC optimization and timelapse generation. GPL-3.0 licensed.
- **OpenSplat**: Production-grade, portable implementation of 3D Gaussian Splatting with CPU/GPU support for Windows, Mac, and Linux. Creates 3D scenes from camera poses and sparse points. AGPL-3.0 licensed.

## 7. Training & Fine-tuning Ecosystem

#### Full Training Frameworks (32 tools)

- **Oumi**: Fully open-source platform for the complete foundation model lifecycle - from data preparation and training to evaluation and deployment. Supports 100+ models with 200+ recipes for fine-tuning gpt-oss, Qwen3, DeepSeek-R1, and more. Apache 2.0 license
- **Marin**: Open-source framework for foundation-model development with composable data, training, and evaluation pipelines for modern LLM research.
- **LLaMA-Factory**: One-stop unified framework for SFT, DPO, ORPO, KTO with web UI.
- **Axolotl**: YAML-driven full pipeline for SFT, DPO, GRPO.
- **ms-swift**: Unified training framework for 600+ LLMs and 300+ MLLMs with CPT/SFT/DPO/GRPO (AAAI 2025).
- **Unsloth**: 2× faster, 70% less memory fine-tuning.
- **LitGPT**: Clean from-scratch implementations of 20+ LLMs.
- **LLM Foundry**: Databricks' training framework for composable LLM training with StreamingDataset and Composer.
- **torchtune**: PyTorch-native library for post-training, fine-tuning, and experimentation with LLMs.
- **kohya_ss**: Gradio-based GUI and CLI for training Stable Diffusion models (LoRA, Dreambooth, fine-tuning, SDXL). Provides accessible interface to Kohya's powerful training scripts.
- **TRL (Transformers Reinforcement Learning)**: Official library for RLHF, SFT, DPO, ORPO.
- **verl**: Volcano Engine Reinforcement Learning for LLMs with PPO, GRPO, REINFORCE++, DAPO (EuroSys 2025).
- **NeMo-RL**: Scalable toolkit for efficient model reinforcement with DTensor and Megatron backends.
- **OpenRLHF**: Easy-to-use, scalable RLHF framework based on Ray. Supports PPO, GRPO, REINFORCE++, DAPO with vLLM integration and async training. Apache 2.0 licensed.
- **LMFlow**: Extensible toolkit for finetuning and inference of large foundation models. Features RAFT alignment algorithm and comprehensive model support. Apache 2.0 licensed.
- **XTuner**: A next-generation training engine built for ultra-large MoE models with efficient QLoRA and full-parameter fine-tuning. Apache 2.0 licensed.
- **Ludwig**: Low-code framework for building custom LLMs and deep neural networks. Declarative YAML configuration for training state-of-the-art models with PEFT/LoRA, 4-bit quantization, distributed training via Hugging Face Accelerate, and native Kubernetes supp
- **TorchTitan (PyTorch)**: PyTorch native platform for training generative AI models at scale. Showcases 4D parallelism (FSDP, tensor, pipeline, context) for LLM pretraining with 65%+ speedups over optimized baselines. BSD-3-Clause licensed.
- **VeOmni (ByteDance)**: Versatile framework for both single- and multi-modal pre-training and post-training. Model-centric distributed recipe zoo supporting text, vision, audio, and video models with unified training interface. Apache 2.0 licensed.
- **H2O LLM Studio**: No-code GUI framework for fine-tuning LLMs. Streamlined interface for SFT, reward modeling, and model deployment. Apache 2.0 licensed.
- **TinyZero**: Minimal reproduction of DeepSeek R1-Zero for countdown and multiplication tasks. Clean, accessible implementation for understanding RL-based reasoning training. Apache 2.0 licensed.
- **PRIME-RL**: Agentic RL Training at Scale from Prime Intellect. Framework for large-scale reinforcement learning capable of scaling to 1000+ GPUs with fully asynchronous RL, FSDP2 training, and vLLM inference. Apache 2.0 licensed.
- **slime**: LLM post-training framework for RL Scaling from THUDM. Supports SFT and RL training with multi-turn compilation feedback, powering projects like TritonForge for automated GPU kernel generation. Apache 2.0 licensed.
- **rLLM**: Democratizing Reinforcement Learning for LLMs. Framework for training AI agents with RL featuring near-zero code changes, CLI-first workflow, and 50+ built-in benchmarks. Supports GRPO, REINFORCE, RLOO with verl and tinker backends. Apache 2.0 licens
- **EasyR1**: Efficient, scalable, multi-modality RL training framework based on veRL. Extends veRL to support vision-language models with GRPO algorithm for efficient RL training. Apache 2.0 licensed.
- **LeRobot**: Making AI for robotics more accessible with end-to-end learning. State-of-the-art approaches for imitation learning and reinforcement learning with pretrained models, datasets, and simulated environments. Apache 2.0 licensed.
- **AI-Toolkit**: Ultimate training toolkit for finetuning diffusion models. Easy-to-use all-in-one training suite supporting FLUX.1, FLUX.2, Stable Diffusion, and video models with both GUI and CLI interfaces. Consumer-grade hardware friendly with comprehensive LoRA 
- **OneTrainer**: One-stop solution for all your Diffusion training needs. Supports FLUX, Stable Diffusion 1.5/2.x/3.x/SDXL, Würstchen, PixArt, Hunyuan Video and more. Features full fine-tuning, LoRA, embeddings, masked training, automatic backups, and TensorBoard int
- **FluxGym**: Dead simple FLUX LoRA training UI with LOW VRAM support (12GB/16GB/20GB). WebUI forked from AI-Toolkit with backend powered by Kohya Scripts. Combines simplicity of Gradio interface with flexibility of Kohya's powerful training scripts. GPL-3.0 licen
- **MiniMind**: Train a 64M-parameter LLM from scratch in just 2 hours for $3. Complete from-scratch implementation covering MoE, data cleaning, pretraining, SFT, LoRA, RLHF (DPO/PPO/GRPO), tool use, and model distillation. All core algorithms implemented in pure Py
- **FastChat**: Open platform for training, serving, and evaluating large language model chatbots. Powers Chatbot Arena (lmarena.ai) serving 10M+ requests for 70+ LLMs. Includes training code for Vicuna, MT-Bench evaluation, and distributed multi-model serving with 
- **PaddleNLP**: Easy-to-use and powerful LLM library built on Baidu's PaddlePaddle framework. Supports 100+ models with efficient training, compression, and high-performance inference on diverse hardware. Features RsLoRA+ algorithm, DeepSeek V3/R1 support with FP8/I

#### LoRA / PEFT Tools (3 tools)

- **PEFT (Parameter-Efficient Fine-Tuning)**: Official library with LoRA, QLoRA, DoRA, etc.
- **Liger Kernel**: Ultra-fast custom kernels for training speedup.
- **MergeKit**: Advanced model merging tools.

#### Synthetic Data Generation (7 tools)

- **distilabel**: End-to-end pipeline for synthetic instruction data.
- **Data-Juicer**: High-performance data processing for LLM training.
- **Argilla**: Open-source data labeling + synthetic data platform.
- **SDV (Synthetic Data Vault)**: High-fidelity tabular and relational synthetic data.
- **DataTrove (Hugging Face)**: Platform-agnostic data processing pipelines for LLM training at scale. Handles filtering, deduplication, and tokenization on local machines or SLURM clusters.
- **Bespoke Curator**: Synthetic data curation for post-training and structured data extraction. Makes it easy to build pipelines around LLMs with batching and progress tracking. Apache 2.0 licensed.
- **SDG (Harbin Institute)**: Specialized framework for generating high-quality structured tabular synthetic data with CTGAN models supporting billion-level data processing. Apache 2.0 licensed.

#### Distributed Training (9 tools)

- **DeepSpeed**: Extreme-scale training optimizations.
- **Colossal-AI**: Unified system for 100B+ models.
- **Megatron-LM**: Distributed training framework and reference codebase for large transformer models at scale.
- **Ray Train**: Scalable distributed training.
- **Nanotron (Hugging Face)**: Minimalistic 3D-parallelism LLM pretraining with tensor, pipeline, and data parallelism. Designed for simplicity and speed.
- **veScale (ByteDance)**: Hyperscale PyTorch distributed training with flexible FSDP implementation for LLMs and RL training at scale.
- **RLinf**: Scalable open-source RL infrastructure for post-training foundation models via reinforcement learning. Features M2Flow paradigm for embodied AI and agentic workflows with real-world robotics integrations. Apache 2.0 licensed.
- **dstack**: Vendor-agnostic orchestration for training, inference and agentic workloads across NVIDIA, AMD, TPU, and Tenstorrent on clouds, Kubernetes, and bare metal. MPL-2.0 licensed.
- **Streaming (MosaicML)**: High-performance data streaming library for efficient neural network training. Streams training data from cloud storage (S3, GCS, Azure) with local caching and deterministic shuffling. Apache 2.0 licensed.

#### Model Quantization & Optimization (2 tools)

- **LLM Compressor (vLLM)**: Transformers-compatible library for applying various compression algorithms to LLMs for optimized deployment with vLLM. Supports GPTQ, AWQ, SmoothQuant, AutoRound, and FP8/INT8 quantization with seamless Hugging Face integration.
- **NVIDIA Model Optimizer**: Unified library of SOTA model optimization techniques including quantization, pruning, distillation, and speculative decoding. Compresses deep learning models for deployment with TensorRT-LLM, TensorRT, and vLLM to optimize inference speed across NVI

## 8. MLOps / LLMOps & Production

#### Experiment Tracking & Versioning (8 tools)

- **MLflow**: End-to-end open platform for the ML/LLM lifecycle.
- **DVC (Data Version Control)**: Git-like versioning for data and models.
- **ClearML**: Open-source platform for experiment tracking, orchestration, data management, and model serving.
- **Weights & Biases Weave**: Open-source tracing and experiment tracking.
- **Aim**: Self-hosted ML experiment tracker designed to handle 10,000s of training runs with performant UI and SDK for programmatic access. Apache 2.0 licensed.
- **Feast**: Open source feature store for ML. Manages offline/online feature storage with point-in-time correctness to prevent data leakage. Apache 2.0 licensed.
- **OpenLineage**: Open standard for lineage metadata collection designed to instrument jobs as they run. Defines a generic model of run, job, and dataset entities for consistent data lineage tracking. Apache 2.0 licensed.
- **Marquez**: LF AI & Data Foundation Graduated project for metadata collection, aggregation, and visualization. Maintains provenance of how datasets are consumed and produced with global visibility into job runtime and dataset lifecycle management. Integrates wit

#### Model Hubs & Registries (13 tools)

- **Civitai**: Open-source AI model hub and community platform for sharing and discovering generative AI models, with focus on image generation models. Features model versioning, reviews, and integrated inference. Apache 2.0 licensed.
- **Hugging Face Hub**: Official Python client for the Hugging Face Hub. Download, upload, and manage 1M+ open-source ML models and datasets programmatically. The de facto standard for model sharing and distribution. Apache 2.0 licensed.
- **ModelScope**: Model-as-a-Service platform bringing together 700+ state-of-the-art ML models from the AI community. Covers NLP, CV, Audio, Multi-modality, and AI for Science with streamlined model inference, fine-tuning and evaluation. Apache 2.0 licensed.
- **OpenVINO Open Model Zoo**: Pre-trained deep learning models and demos optimized for Intel hardware. 200+ public pre-trained models for vision, speech, and NLP with benchmarking tools and accuracy metrics. Apache 2.0 licensed.
- **ONNX Model Zoo**: Collection of pre-trained, state-of-the-art models in the ONNX format. 80+ models spanning vision, NLP, and audio with validation data and reference implementations. Apache 2.0 licensed.
- **Transformers.js**: State-of-the-art Machine Learning for the web. Run Hugging Face Transformers directly in your browser with no server needed. Supports 1000+ models including BERT, GPT-2, T5, and more via ONNX Runtime Web. Apache 2.0 licensed.
- **DJL (Deep Java Library)**: Engine-agnostic deep learning framework for Java with built-in model zoo. Load and run PyTorch, TensorFlow, MXNet, and ONNX models with a unified API. Includes 80+ pre-trained models for CV and NLP. Apache 2.0 licensed.
- **PaddleSeg**: Easy-to-use image segmentation library with awesome pre-trained model zoo. Supports semantic segmentation, interactive segmentation, panoptic segmentation, image matting, and 3D segmentation with 200+ pre-trained models. Apache 2.0 licensed.
- **TorchVision Models**: PyTorch's official computer vision library with 50+ pre-trained model architectures including ResNet, EfficientNet, Vision Transformers (ViT), ConvNeXt, and more. The de facto standard model zoo for PyTorch computer vision. BSD-3-Clause licensed.
- **TensorFlow Model Garden**: Official TensorFlow repository of state-of-the-art (SOTA) models and modeling solutions. Contains reference implementations for BERT, ResNet, Transformer, and many more with pre-trained weights and training scripts. Apache 2.0 licensed.
- **PINTO Model Zoo**: Repository for storing models inter-converted between various frameworks. Supports TensorFlow, PyTorch, ONNX, OpenVINO, TFJS, TFTRT, TensorFlowLite (Float32/16/INT8), EdgeTPU, and CoreML. 4,100+ stars with extensive model conversion tools for edge de
- **Cerebras Model Zoo**: Collection of deep learning models and utilities optimized for Cerebras hardware. Includes reference implementations for Llama, Mixtral, DINOv2, and Llava with configuration files, data preprocessing tools, and checkpoint converters. 1,150+ stars. Ap
- **PaddleClas**: Comprehensive image recognition and classification toolkit with rich model zoo. 5,800+ stars featuring 24 series of classification networks, 122 pretrained models, and end-to-end image recognition systems including PP-ShiTuV2. Apache 2.0 licensed.

#### Model Packaging & Deployment (1 tools)

- **Cog (Replicate)**: Containerize and deploy ML models with production-grade inference servers. Packages models into standardized containers with automatic API generation, GPU support, and one-command deployment. Powers thousands of production AI models on Replicate. Apa

#### Deployment & Orchestration (23 tools)

- **BentoML**: Unified framework to build, ship, and scale AI apps.
- **ZenML**: Pipeline and orchestration framework for taking ML and LLM systems from development to production.
- **Kubeflow**: Kubernetes-native ML/LLM platform.
- **KServe**: Kubernetes-based model serving.
- **Seldon Core**: MLOps and LLMOps framework for deploying, managing and scaling AI systems in Kubernetes. Standardized deployment across model types with autoscaling, multi-model serving, and A/B experiments.
- **Metaflow**: Netflix's ML platform for building and managing real-world AI systems. Powers thousands of projects at Netflix, Amazon, and DoorDash. Apache 2.0 licensed.
- **Flyte**: Kubernetes-native workflow orchestration platform for AI/ML pipelines. Dynamic, resilient orchestration with strong type safety and reproducibility. Used by Lyft, Spotify, and Gojek. Apache 2.0 licensed.
- **Prefect**: Workflow orchestration framework for building resilient data and ML pipelines. Python-native with modern observability and 200+ integrations. Apache 2.0 licensed.
- **Dagster**: Cloud-native orchestration platform for developing and maintaining data assets including ML models. Declarative programming model with integrated lineage and observability. Apache 2.0 licensed.
- **Kubeflow Pipelines**: Machine Learning Pipelines for Kubeflow. Platform for building and deploying portable, scalable ML workflows using Kubernetes and Argo. Apache 2.0 licensed.
- **Argo Workflows**: CNCF graduated container-native workflow engine for orchestrating parallel jobs on Kubernetes. Powers Kubeflow Pipelines and widely used for ML/data processing at scale. Apache 2.0 licensed.
- **MLRun**: Open-source AI orchestration platform for quickly building and managing continuous ML and generative AI applications across their lifecycle. Automates data preparation, model tuning, and deployment. Apache 2.0 licensed.
- **Kestra**: Event-driven orchestration and scheduling platform for mission-critical workflows. Infrastructure-as-Code approach with declarative YAML, Git version control integration, and hundreds of plugins for data pipelines and ML workflows. Apache 2.0 license
- **KitOps**: CNCF open source DevOps tool for packaging, versioning, and securely sharing AI/ML models, datasets, code, and configuration. Packages everything into OCI artifacts stored in existing container registries. Apache 2.0 licensed.
- **Polyaxon**: MLOps Tools For Managing & Orchestrating The Machine Learning LifeCycle. Reproducible and scalable machine learning workflows on Kubernetes with experiment tracking, model management, and pipeline orchestration. Apache 2.0 licensed.
- **Netflix Maestro**: Netflix's next-generation workflow orchestrator for data and ML pipelines at massive scale. Highly scalable and flexible scheduler designed to handle millions of workflows across thousands of nodes. Apache 2.0 licensed.
- **HAMi**: Heterogeneous GPU Sharing on Kubernetes. CNCF sandbox project providing GPU virtualization, slicing, and scheduling for efficient AI workload management across heterogeneous accelerators (GPUs, NPUs, MLUs). Apache 2.0 licensed.
- **NVIDIA KAI Scheduler**: Kubernetes-native GPU scheduler for AI workloads at large scale. Originally developed by Run:ai, now open-sourced by NVIDIA. Optimizes GPU resource allocation with dynamic allocation and efficient queue management. Apache 2.0 licensed.
- **NVIDIA DeepOps**: Infrastructure automation tools for building GPU clusters with Kubernetes and Slurm. Deploys multi-node GPU clusters with monitoring, logging, and storage for AI/HPC workloads. BSD-3-Clause licensed.
- **SkyPilot**: Run, manage, and scale AI workloads on any AI infrastructure. Unified interface to access and manage compute across Kubernetes, Slurm, and 20+ cloud providers. Used by Shopify and research institutions for training and inference. Apache 2.0 licensed.
- **Volcano**: Cloud-native batch scheduling system for compute-intensive workloads. CNCF incubating project with gang scheduling, job dependency management, and topology-aware scheduling for AI/ML and deep learning. Apache 2.0 licensed.
- **Apache YuniKorn**: Kubernetes resource scheduler for batch, data, and ML workloads. Provides hierarchical resource queues, multi-tenancy fairness, and gang scheduling for big data and machine learning applications. Apache 2.0 licensed.
- **Kueue**: Kubernetes-native job queueing system for batch, HPC, AI/ML, and similar applications. Cloud-native job queueing with resource flavor fungibility, fair sharing, cohorts, and preemption policies. Integrates with Kubeflow, Ray, and JobSet. Apache 2.0 l

#### Feature Engineering & Data Preparation (5 tools)

- **Featuretools**: Open-source Python library for automated feature engineering. Transforms transactional and relational datasets into feature matrices for machine learning using Deep Feature Synthesis with reusable primitives. BSD-3-Clause licensed.
- **Kedro**: Toolbox for production-ready data science. Uses software engineering best practices to help you create data engineering and data science pipelines that are reproducible, maintainable, and modular. Apache 2.0 licensed.
- **Feature-engine**: Python library with multiple transformers to engineer and select features for machine learning models. scikit-learn compatible with fit() and transform() methods for encoding, imputation, variable transformation, and feature selection. BSD-3-Clause l
- **NVTabular**: GPU-accelerated feature engineering and preprocessing library for tabular data. Manipulates terabyte-scale datasets to train deep learning recommender systems. Component of NVIDIA Merlin framework. Apache 2.0 licensed.
- **OpenMLDB**: Open-source machine learning database providing a feature platform for consistent features between training and inference. Real-time relational data feature computation system for online ML applications. Apache 2.0 licensed.

#### Monitoring, Evaluation & Observability (18 tools)

- **Langfuse**: #1 open-source LLM observability platform.
- **Phoenix (Arize)**: AI observability & evaluation platform.
- **Evidently**: ML & LLM monitoring framework.
- **Opik (Comet)**: Production-ready LLM evaluation platform.
- **LiteLLM**: AI Gateway to call 100+ LLM APIs in OpenAI format with unified cost tracking, guardrails, load balancing, and logging.
- **OpenLIT**: OpenTelemetry-native LLM observability platform with GPU monitoring, evaluations, prompt management, and guardrails.
- **OpenLLMetry (Traceloop)**: Open-source observability for GenAI/LLM applications based on OpenTelemetry with 25+ integration backends.
- **Agenta**: Open-source LLMOps platform combining prompt playground, prompt management, LLM evaluation, and observability.
- **Latitude**: Open-source agent engineering platform with prompt management, evaluations, and optimization. Features prompt playground, LLM-as-judge evals, and GEPA prompt optimizer for production LLM features. LGPL-3.0 licensed.
- **Helicone**: Open-source LLM observability with request logging, caching, rate limiting, and cost analytics.
- **Giskard**: Open-source evaluation and testing library for LLM agents. Red teaming, vulnerability scanning, RAG evaluation, and safety testing with modular architecture. Apache 2.0 licensed.
- **Portkey Gateway**: Blazing fast AI Gateway to route 200+ LLMs with unified API. Integrated guardrails, load balancing, fallbacks, and cost tracking. MIT licensed.
- **Envoy AI Gateway**: Manages unified access to generative AI services built on Envoy Gateway. Kubernetes-native AI gateway for routing, load balancing, and managing LLM traffic with enterprise-grade reliability. Apache 2.0 licensed.
- **Pezzo**: Cloud-native LLMOps platform with prompt management, versioning, and observability. Features collaborative prompt editing, A/B testing, and cost analytics. Apache 2.0 licensed.
- **Microsoft PromptFlow**: Comprehensive suite for LLM-based AI app development from prototyping to production. Includes prompt engineering, evaluation, and deployment tools with VS Code integration. MIT licensed.
- **ChainForge**: Visual programming environment for battle-testing prompts and evaluating LLM outputs. Features node-based prompt chains, multi-model comparison, and hypothesis testing. MIT licensed.
- **Future AGI**: Open-source self-hostable end-to-end agent engineering and optimization platform that unifies tracing, evals, simulations, datasets, gateway, and guardrails. Built for shipping self-improving AI agents with one feedback loop from prototype to product
- **KubeStellar Console**: AI-powered multi-cluster Kubernetes dashboard with GPU workload monitoring, AI pipeline observability, and CNCF ecosystem integrations. Apache 2.0 licensed.

#### Guardrails & Safety Tools (5 tools)

- **PurpleLlama (Meta)**: Comprehensive set of tools to assess and improve LLM security. Includes Llama Guard safety classifiers, CyberSec Eval benchmarks, and Prompt Guard for prompt injection detection. BSD-3-Clause licensed.
- **Garak (NVIDIA)**: The LLM vulnerability scanner. Probes models for hallucinations, data leakage, prompt injection, misinformation, toxicity, and jailbreaks. Extensive plugin-based architecture with 100+ vulnerability probes. Apache 2.0 licensed.
- **Promptfoo**: Open-source LLM evaluation and red teaming framework. Test prompts, agents, and RAGs with automated security vulnerability scanning, side-by-side model comparison, and CI/CD integration. Now part of OpenAI. MIT licensed.
- **DeepTeam (Confident AI)**: Red teaming framework for LLM systems with 50+ vulnerabilities, 20+ adversarial attacks, and production-ready guardrails. Includes OWASP, NIST, and MITRE ATLAS framework mappings. Apache 2.0 licensed.
- **SkillSpector (NVIDIA)**: Security scanner for AI agent skills that detects vulnerabilities, malicious patterns, and security risks. Apache 2.0 licensed.

## 9. Evaluation, Benchmarks & Datasets

#### Benchmark Suites (15 tools)

- **LiveBench**: Contamination-free LLM benchmark with objective ground-truth scoring. ICLR 2025 spotlight paper featuring frequently-updated questions from recent sources. Tests math, coding, reasoning, language, instruction following, and data analysis.
- **lm-evaluation-harness (EleutherAI)**: De-facto standard for generative model evaluation.
- **HELM (Stanford)**: Holistic Evaluation of Language Models.
- **MMLU-Pro / GPQA**: More challenging MMLU-style benchmark suite for evaluating advanced language models with expert-level reasoning questions.
- **SWE-bench**: Evaluates LLMs on real-world GitHub issues from 15+ Python repositories.
- **GAIA**: Real-world multi-step agentic benchmark.
- **OpenCompass**: Evaluation platform for benchmarking language and multimodal models across large benchmark suites.
- **MLPerf Inference**: Industry-standard ML inference benchmarks with reference implementations for AI accelerators.
- **MLPerf Training**: Industry-standard ML training benchmarks from MLCommons. Reference implementations for training AI models at scale across image classification, object detection, NLP, and recommendation tasks. Apache 2.0 licensed.
- **VLMEvalKit**: Open-source evaluation toolkit for large multi-modality models (LMMs). Supports 220+ LMMs and 80+ benchmarks including MMMU, MathVista, and ChartQA. Powers the OpenVLM Leaderboard. Apache 2.0 licensed.
- **Vectara Hallucination Leaderboard**: Leaderboard comparing LLM performance at producing hallucinations when summarizing short documents. Systematic evaluation of factual consistency across major models. Apache 2.0 licensed.
- **SWE-rebench (Nebius)**: Continuously updated benchmark with 21,000+ real-world SWE tasks for evaluating agentic LLMs. Decontaminated, mined from GitHub.
- **AgentBench (THUDM)**: Comprehensive benchmark to evaluate LLMs as agents across 8 diverse environments including household, web shopping, OS interaction, and database tasks. ICLR 2024. Apache 2.0 licensed.
- **MLE-bench (OpenAI)**: Benchmark for measuring how well AI agents perform at machine learning engineering. Evaluates agents on 75 Kaggle competitions covering diverse ML tasks. MIT licensed.
- **PinchBench**: Benchmarking system for evaluating LLM models as OpenClaw coding agents. Built with Rust by the kilo.ai team. MIT licensed.

#### Evaluation Frameworks (15 tools)

- **DeepEval**: The "Pytest for LLMs".
- **Inspect AI**: Framework for large language model evaluations from the UK AI Security Institute.
- **RAGAs**: End-to-end RAG evaluation framework.
- **Lighteval**: Evaluation toolkit for LLMs across multiple backends with reusable tasks, metrics, and result tracking.
- **Hugging Face Evaluate**: Standardized evaluation metrics.
- **OpenAI Evals**: Framework for evaluating LLMs and LLM systems with an open-source registry of 100+ community-contributed benchmarks. MIT licensed.
- **LMMs-Eval**: Unified multimodal evaluation toolkit for text, image, video, and audio tasks with 100+ supported benchmarks.
- **BrowserGym**: Gym environment for web task automation and agent evaluation. Includes MiniWoB, WebArena, WorkArena, and more. Apache 2.0 licensed.
- **TruLens**: Evaluation and tracking for LLM experiments and AI agents. Provides feedback functions for measuring quality, relevance, and groundedness with LangChain and LlamaIndex integrations. MIT licensed.
- **OpenEvals**: Open-source evaluation library for LLM and agent applications. Built by LangChain with pre-built evaluators for common use cases including RAG, agents, and structured output validation. MIT licensed.
- **AutoRAG**: RAG AutoML tool for automatically finding optimal RAG pipelines. Evaluates and optimizes retrieval-augmented generation with AutoML-style automation for your own data and use-case. Apache 2.0 licensed.
- **E2B Code Interpreter**: Python & JS/TS SDK for running AI-generated code in secure isolated sandboxes. Essential infrastructure for evaluating code-generating LLMs with safe execution environments. Apache 2.0 licensed.
- **SimpleEvals (OpenAI)**: Lightweight library for evaluating language models with transparent accuracy numbers. Reference implementations for MMLU, GPQA, MATH, HumanEval, MGSM, DROP, and SimpleQA benchmarks. MIT licensed.
- **EvalScope (ModelScope)**: Streamlined and customizable framework for efficient large model (LLM, VLM, AIGC) evaluation and performance benchmarking. One-stop evaluation solution with 80+ benchmarks. Apache 2.0 licensed.
- **Harbor**: Framework for running agent evaluations and creating/using RL environments. Evaluate arbitrary agents like Claude Code, OpenHands, and Codex CLI. Build and share benchmarks and environments. Apache 2.0 licensed.

#### High-quality Open Datasets & Data Tools (4 tools)

- **Hugging Face Datasets**: Largest open repository of datasets.
- **Cleanlab**: Data-centric AI package for automatically finding and fixing issues in datasets. Detects label errors, outliers, and ambiguous examples in ML datasets. Apache 2.0 licensed.
- **FineWeb / FineWeb-2 (Hugging Face)**: Curated 15T+ token web dataset for pre-training.
- **OSWorld**: Multimodal agent benchmark dataset.

## 10. AI Safety, Alignment & Interpretability

#### Safety Evaluation Frameworks (2 tools)

- **AgentOps**: Python SDK for AI agent monitoring, LLM cost tracking, benchmarking, and evaluation. Integrates with CrewAI, Agno, OpenAI Agents SDK, LangChain, Autogen, AG2, and CamelAI. MIT licensed.
- **Bloom**: Open-source agentic framework for automated behavioral evaluations of frontier AI models. Generates targeted evaluation suites to probe LLMs for specific behaviors (sycophancy, self-preservation, political bias, etc.) with quantitative elicitation ra

#### Alignment & RLHF Tools (1 tools)

- **Alignment Handbook**: Complete recipes for full-stack alignment.

#### Interpretability & Explainability (9 tools)

- **interpret (Microsoft)**: Fit interpretable models and explain blackbox machine learning with state-of-the-art explainability techniques including Explainable Boosting Machines and SHAP-based explanations.
- **TransformerLens**: Gold-standard for mechanistic interpretability.
- **SAELens**: Sparse autoencoders for interpretable features.
- **nnsight**: Library for inspecting, tracing, and intervening on neural network internals at scale.
- **Captum**: PyTorch's official interpretability library.
- **EasyEdit**: Easy-to-use knowledge editing framework for LLMs. Enables precise modification of model knowledge and behavior to correct hallucinations or outdated information. ACL 2024. MIT licensed.
- **AIX360**: Comprehensive AI explainability toolkit with interpretability algorithms for data and machine learning models. Includes TED, BRCG, and ProtoNN methods for diverse explanation needs. Apache 2.0 licensed.
- **ELI5**: Library for debugging/inspecting machine learning classifiers and explaining their predictions. Supports scikit-learn, XGBoost, LightGBM, and more with feature importance and explanation visualizations. MIT licensed.
- **Shapash**: User-friendly explainability library for transparent ML models. Beautiful visualizations with explicit labels that everyone can understand. Generates web reports and integrates with SHAP/LIME. Apache 2.0 licensed.

#### Fairness & Bias Mitigation (2 tools)

- **AI Fairness 360**: Comprehensive toolkit for detecting, understanding, and mitigating unwanted algorithmic bias in datasets and ML models.
- **Fairlearn**: Python package to assess and improve fairness of machine learning models. Provides metrics for disparity assessment and algorithms for unfairness mitigation with scikit-learn integration. MIT licensed.

#### Adversarial & Red-teaming Tools (15 tools)

- **PyRIT (Microsoft)**: Python Risk Identification Tool for generative AI. Microsoft's open-source framework for automated red teaming with multi-modal attack support, crescendo strategies, and 100+ operations experience. MIT licensed.
- **Heretic**: Open-source system for automatic censorship and robustness suppression removal in language-model outputs.
- **Agentic Security**: Agentic LLM vulnerability scanner and AI red teaming kit with multi-step attack simulation and automated security probing. Apache 2.0 licensed.
- **NeMo Guardrails (NVIDIA)**: Programmable guardrails toolkit for LLM-based conversational systems. Uses Colang DSL to define safety rules, dialog flows, and content boundaries. Integrates with LangChain, LangGraph, and LlamaIndex for production deployments. Apache 2.0 licensed.
- **Guardrails AI**: Input/output validation framework for building reliable AI applications. Detects and mitigates risks through composable validators for PII, toxicity, prompt injection, and structured output validation. Features Guardrails Hub with 50+ pre-built valid
- **Detoxify**: Trained models and code to predict toxic comments on all 3 Jigsaw Toxic Comment Challenges. Built using PyTorch Lightning and Transformers for toxicity, severe toxicity, obscene, threat, insult, identity attack, and sexual explicit content detection.
- **RedAmon**: AI-powered agentic red team framework that automates offensive security operations from reconnaissance to exploitation to post-exploitation with zero human intervention. Integrates multiple security tools for comprehensive penetration testing. MIT li
- **CAI**: Cybersecurity AI framework for semi- and fully-automating offensive and defensive security tasks. Purpose-built for cybersecurity use cases with agent-based architecture for vulnerability assessment and security operations. MIT licensed.
- **AI-Infra-Guard (Tencent)**: Full-stack AI Red Teaming platform securing AI ecosystems via OpenClaw Security Scan, Agent Scan, Skills Scan, MCP scan, AI Infra scan and LLM jailbreak evaluation. Apache 2.0 licensed.
- **PentestAgent (GH05TCREW)**: AI agent framework for black-box security testing, supporting bug bounty, red-team, and penetration testing workflows. MIT licensed.
- **Superagent**: Protects AI applications against prompt injections, data leaks, and harmful outputs. Embed safety directly into your app and prove compliance to your customers. MIT licensed.
- **Anthropic Sandbox Runtime**: Portable sandbox execution environment for AI agents with constrained filesystem and network boundaries, designed to reduce blast radius in tool-use and LLM autonomy tests.
- **SchemaBrain**: An open-source schema intelligence and safety layer (like Cloudflare) between AI agents and databases. Exposes a read-only Model Context Protocol (MCP) interface with PII masking, structured query recovery, and tamper-evident SHA-256 audit logs. Apac
- **Anthropic Cybersecurity Skills**: Structured library of 754 cybersecurity skills mapped to five frameworks including MITRE ATT&CK and NIST CSF 2.0, compatible with Claude Code, Cursor, and agentskills.io. Apache 2.0 licensed.
- **Strix**: Autonomous AI-powered penetration testing agent that identifies vulnerabilities and validates them with proof-of-concept exploits. Apache 2.0 licensed.

#### Responsible AI Development (2 tools)

- **Responsible AI Toolbox**: Suite of tools providing model and data exploration, assessment interfaces and libraries for understanding AI systems. Enables developers to develop and monitor AI more responsibly with better data-driven actions. MIT licensed.
- **Agent Governance Toolkit**: Security and compliance toolkit for autonomous agents with policy enforcement, zero-trust identity, and sandboxed execution to reduce operational risk. MIT licensed.

#### Privacy-Preserving AI (1 tools)

- **Presidio (Microsoft)**: SDK for detecting, redacting, masking, and anonymizing sensitive personally identifiable information (PII) across text and images. MIT licensed.

## 11. Specialized Domains

#### Weather & Climate AI (1 tools)

- **GraphCast**: Deep learning weather forecasting model from Google DeepMind. State-of-the-art AI weather prediction with 10-day global forecasts matching or exceeding traditional numerical methods. Apache 2.0 licensed.

#### Scientific AI & Physics ML (3 tools)

- **NVIDIA Modulus**: Open-source deep learning framework for physics-informed machine learning (Physics-ML). Build, train, and fine-tune models for AI4science and engineering applications using state-of-the-art SciML methods. Apache 2.0 licensed.
- **TorchGeo**: PyTorch domain library for geospatial data. Datasets, samplers, transforms, and pre-trained models for multispectral satellite imagery and remote sensing. First library with pre-trained models for Sentinel-2 bands. MIT licensed.
- **Astropy**: Core library for astronomy and astrophysics in Python. Comprehensive tools for celestial coordinates, FITS I/O, cosmological calculations, and data analysis for professional astronomy. BSD-3-Clause licensed.

#### Scientific AI & Drug Discovery (3 tools)

- **Boltz**: Open-source biomolecular interaction prediction models. Boltz-1 was the first fully open source model to approach AlphaFold3 accuracy; Boltz-2 adds binding affinity prediction for drug discovery. MIT licensed.
- **Protenix**: High-accuracy open-source biomolecular structure prediction model from ByteDance. First fully open-source model to outperform AlphaFold3 across diverse benchmarks with Apache 2.0 licensing for both academic and commercial use.
- **DeepChem**: Democratizing deep learning for drug discovery, quantum chemistry, materials science, and biology. High-quality open-source toolchain with 50+ models and extensive tutorials. MIT licensed.

#### Probabilistic Programming & Bayesian ML (3 tools)

- **PyMC**: Modern, comprehensive probabilistic programming framework in Python. Bayesian modeling with advanced MCMC sampling, variational inference, and seamless integration with ArviZ for visualization. Apache 2.0 licensed.
- **ArviZ**: Exploratory analysis of Bayesian models with Python. Comprehensive visualization and diagnostics for probabilistic models, supporting PyMC, Pyro, Stan, and other PPLs. Apache 2.0 licensed.
- **Stanza**: Stanford NLP Python library for 100+ human languages. State-of-the-art neural pipelines for tokenization, NER, parsing, and sentiment analysis with pre-trained models. Apache 2.0 licensed.

#### Medical Imaging & Healthcare AI (3 tools)

- **MONAI**: Medical Open Network for AI. End-to-end framework for healthcare imaging with state-of-the-art, production-ready training workflows. Apache 2.0 licensed.
- **nnU-Net**: Self-configuring deep learning method for medical image segmentation. Automatically adapts to any dataset without manual parameter tuning. Widely adopted as the standard baseline for biomedical segmentation challenges. Apache 2.0 licensed.
- **OpenMed**: Local-first healthcare AI framework and application for clinical text de-identification, entity extraction, and on-device specialized model serving. Apache 2.0 licensed.

#### Game AI & Simulations (6 tools)

- **Unity ML-Agents**: Toolkit for training intelligent agents in games and simulations using deep reinforcement learning. Enables NPC behavior control, automated testing, and game design evaluation. Apache 2.0 licensed.
- **Tianshou**: An elegant PyTorch deep reinforcement learning library with clean API design and comprehensive algorithm implementations. Supports both single-agent and multi-agent RL with GPU acceleration. MIT licensed.
- **RL Baselines3 Zoo**: A training framework for Stable Baselines3 reinforcement learning agents with hyperparameter optimization, pre-trained agents, and extensive benchmark environments. MIT licensed.
- **skrl**: Modular reinforcement learning library implemented in PyTorch, JAX, and NVIDIA Warp with support for Gymnasium, NVIDIA Isaac Lab, MuJoCo Playground, and other environments. MIT licensed.
- **Finetrainers**: Scalable and memory-optimized training of diffusion models from Hugging Face. Supports LoRA and full fine-tuning for video and image generation models. Apache 2.0 licensed.
- **OpenSpiel**: Collection of environments and algorithms for research in general reinforcement learning and search/planning in games from Google DeepMind. Apache 2.0 licensed.

#### Finance & Quantitative AI (8 tools)

- **OpenBB**: Financial data platform for analysts, quants and AI agents. Open-source investment research infrastructure with extensive data integrations. AGPL-3.0 licensed.
- **FinGPT**: Open-source financial large language models. Democratizing financial AI with data-centric training pipeline and multiple model releases for trading, analysis, and robo-advising. MIT licensed.
- **FinRL**: Financial reinforcement learning framework for quantitative trading. Deep RL library for stock trading, portfolio allocation, and market execution with pre-built environments and benchmarks. MIT licensed.
- **Qlib**: AI-oriented quantitative investment platform from Microsoft. Supports diverse ML modeling paradigms including supervised learning, market dynamics modeling, and RL. Now equipped with RD-Agent for automated R&D process. MIT licensed.
- **FinRobot**: Open-source AI agent platform for financial analysis using LLMs. Multi-agent system with specialized agents for trading, analysis, and research. Apache 2.0 licensed.
- **Kronos**: Foundation model for financial candlesticks (K-lines) pre-trained on multi-dimensional market data across global exchanges. MIT licensed.
- **Daily Stock Analysis**: LLM-powered multi-market stock analysis system providing automated decision dashboard reports and real-time market insights. MIT licensed.
- **Vibe-Trading**: Open-source personal trading agent and research autopilot platform featuring multi-agent swarms, quantitative backtesting, and broker connectors. MIT licensed.

#### Computer Vision (10 tools)

- **OpenCV**: World's most widely used computer vision library.
- **Ultralytics YOLO**: State-of-the-art real-time object detection.
- **Detectron2**: High-performance object detection library.
- **CVAT**: Industry-leading data annotation platform for computer vision. Interactive video and image annotation tool used by tens of thousands of teams for machine learning at any scale.
- **SAM 2**: Promptable image and video segmentation model with released checkpoints and training code.
- **Kornia**: Differentiable computer vision library.
- **Roboflow Supervision**: Reusable computer-vision utilities for detection, tracking, and segmentation pipelines in Python.
- **torchaudio**: PyTorch audio processing library. Comprehensive toolkit for audio I/O, transformations, and deep learning with support for speech recognition, TTS, and audio classification. BSD-2-Clause licensed.
- **MediaPipe**: Cross-platform multimodal pipelines.
- **OpenEyes**: Hardware-agnostic robot vision framework with world models for predictive intelligence on edge devices.

#### 3D Vision & Point Cloud Processing (6 tools)

- **Open3D**: Modern library for 3D data processing with Python and C++ APIs. Core features include 3D data structures, processing algorithms, scene reconstruction, surface alignment, 3D visualization, and GPU acceleration. MIT licensed.
- **Point Cloud Library (PCL)**: Standalone, large-scale open project for 2D/3D image and point cloud processing. Comprehensive algorithms for filtering, feature estimation, surface reconstruction, registration, model fitting, and segmentation. BSD licensed.
- **PyTorch3D**: FAIR's library of reusable components for deep learning with 3D data. Provides efficient 3D operators, differentiable rendering, and mesh processing tools integrated with PyTorch. BSD licensed.
- **RTAB-Map**: Real-Time Appearance-Based Mapping library for RGB-D, Stereo and LiDAR SLAM. Graph-based SLAM approach with incremental appearance-based loop closure detection for large-scale and long-term operation. BSD licensed.
- **MoveIt 2**: Open source robotics manipulation framework for ROS 2. Motion planning, manipulation, 3D perception, kinematics, control, and navigation for robotic arms. BSD-3-Clause licensed.
- **LingBot-Map**: Feed-forward 3D foundation model for transforming and reconstructing streaming 3D scenes. Apache 2.0 licensed.

#### Reinforcement Learning & Robotics (6 tools)

- **Stable-Baselines3**: Production-ready RL algorithms.
- **Isaac Lab**: GPU-accelerated robot learning framework.
- **MuJoCo**: General-purpose physics simulator for robotics, biomechanics, and ML research. High-fidelity contact dynamics with native Python and C++ bindings. Apache 2.0 licensed.
- **Gymnasium (ex-OpenAI Gym)**: Standard RL environment API.
- **OpenEnv**: End-to-end sandbox execution environment framework for agentic reinforcement learning training built on Gymnasium-compatible APIs.
- **JaxMARL**: Multi-agent reinforcement learning library with JAX-accelerated environments and baselines.

#### Time Series & Scientific AI (5 tools)

- **Time Series Library (TSLib)**: Comprehensive benchmark for time-series models.
- **Chronos (Amazon)**: Pretrained foundation models for time-series forecasting.
- **GluonTS (AWS Labs)**: Probabilistic time series modeling with deep learning. Powers Amazon SageMaker forecasting with PyTorch and MXNet backends. Apache 2.0 licensed.
- **AutoTS**: Automated time series forecasting with broad model selection, ensembling, anomaly detection, and holiday effects. Designed for production deployment with minimal setup.
- **TimesFM (Google Research)**: Pretrained decoder-only foundation model developed by Google Research for time-series forecasting, supporting up to 16k context length, covariate support, and Flax / PyTorch backends. Apache 2.0 licensed.

#### Edge / On-device AI (6 tools)

- **ExecuTorch**: PyTorch runtime and toolchain for deploying AI models on mobile, embedded, and edge devices.
- **OpenVINO**: Intel's toolkit for edge deployment.
- **Apache TVM**: Open Machine Learning Compiler Framework. Universal deployment to bring models into minimum deployable modules that can be embedded and run everywhere from datacenter to edge devices. Apache 2.0 licensed.
- **NCNN**: High-performance neural network inference framework optimized for mobile platforms. No third-party dependencies, cross-platform, and runs faster than all known open-source frameworks on mobile CPU. Powers Tencent apps including QQ, WeChat, and Pitu. 
- **MNN**: Blazing-fast, lightweight inference engine battle-tested by Alibaba. Supports inference and training with industry-leading on-device performance. Powers high-performance LLMs and Edge AI with MNN-LLM runtime. Apache 2.0 licensed.
- **RuView**: Real-time spatial intelligence, vital sign monitoring, and human pose estimation using commodity WiFi signals and neural networks. MIT licensed.

#### Legal AI & Contract Analysis (1 tools)

- **OpenContracts**: Self-hosted document annotation platform for legal AI. Semantic search, contract analysis, version control, and MCP integration for building legal knowledge bases. AGPL-3.0 licensed.

#### Autonomous Driving & Robotics Simulators (6 tools)

- **CARLA**: Open-source simulator for autonomous driving research. High-fidelity simulation of urban environments with realistic physics, sensors, and traffic scenarios. Widely used for training and validating self-driving algorithms. MIT licensed.
- **Webots**: Open-source multi-platform robot simulator providing a complete development environment for modeling, programming, and simulating robots, vehicles, and mechanical systems. Used in education, research, and industry. Apache 2.0 licensed.
- **Habitat-Sim**: High-performance physics-enabled 3D simulator for embodied AI research. Supports 3D scans of indoor/outdoor spaces, CAD models, and configurable sensors. Powers Meta's embodied AI research. MIT licensed.
- **Genesis World**: General-purpose simulation platform for embodied AI and robotics research with flexible scenes, sensors, and agent workflows. Apache 2.0 licensed.
- **OpenPilot**: Operating system for robotics. Currently upgrades driver assistance systems on 300+ supported cars. End-to-end autonomous driving stack with open-source hardware and software. MIT licensed.
- **Autoware**: World's leading open-source software project for autonomous driving. Complete stack from localization and object detection to route planning and control. Used by 50+ companies globally. Apache 2.0 licensed.

## 12. User Interfaces & Self-hosted Platforms

#### Local AI Chat UIs & Personal Assistants (19 tools)

- **OpenClaw**: Local-first personal AI assistant with multi-channel integrations and full agentic task execution.
- **Open WebUI**: Most popular self-hosted ChatGPT-style interface.
- **text-generation-webui**: Web UI for running local LLMs with multiple backends, extensions, and model formats.
- **LobeChat**: Sleek modern chat UI.
- **LibreChat**: Feature-packed multi-LLM interface.
- **HuggingChat (self-hosted)**: Official open-source codebase for HuggingChat.
- **Khoj**: Self-hostable personal AI assistant for search, chat, automation, and workflows over local and web data.
- **Newelle**: GNOME/Linux desktop virtual assistant with integrated file editor, global hotkeys, and profile manager.
- **NextChat**: Light and fast AI assistant supporting Web, iOS, macOS, Android, Linux, and Windows. One-click deploy with multi-model support. MIT licensed.
- **big-AGI**: AI suite for power users with multi-model "Beam" chats, AI personas, voice, text-to-image, code execution, and PDF import. MIT licensed.
- **Morphic**: AI-powered search engine with a generative UI. Supports multiple AI providers (OpenAI, Anthropic, Google, Ollama) and search providers (Tavily, SearXNG, Brave). Features smart search modes, widgets, and image/video search. Apache 2.0 licensed.
- **Leon**: Your open-source personal assistant. Built around tools, context, memory, and agentic execution. Self-hosted, privacy-focused, and extensible. MIT licensed.
- **Willow**: Open source, local, and self-hosted Amazon Echo/Google Home competitive voice assistant alternative with hardware support. Apache-2.0 licensed.
- **CoPaw**: Your Personal AI Assistant; easy to install, deploy on your own machine or on the cloud; supports multiple chat apps with easily extensible capabilities. Apache-2.0 licensed.
- **Smart2Brain**: Privacy-focused Obsidian plugin for AI-powered second brain functionality. Chat with your notes using local or remote LLMs including Ollama and OpenAI. MIT licensed.
- **Casibase**: Open-source enterprise-level AI knowledge base and agent management platform. Supports multiple LLM providers, RAG, and team collaboration. Apache-2.0 licensed.
- **BionicGPT**: On-prem ChatGPT replacement for teams with assistants, RAG, access controls, auditing, and enterprise deployment features.
- **OpenHuman**: A local-first personal assistant and memory harness with Obsidian integration, model routing, and automatic integration sync. GPL-3.0 licensed.
- **Open-LLM-VTuber**: Talk to any LLM with hands-free voice interaction, voice interruption, and Live2D talking face running locally across platforms. MIT licensed.

#### Full Self-hosted AI Platforms (10 tools)

- **AnythingLLM**: All-in-one RAG + agents platform.
- **Flowise**: Drag-and-drop LLM app builder.
- **LocalAI**: Open-source AI engine running LLMs, vision, voice, image, and video models on any hardware. Self-hosted OpenAI-compatible API. MIT licensed.
- **Onyx**: Full-featured AI platform with Chat, RAG, Agents, and Actions. 40+ document connectors and every LLM support. MIT licensed (Community Edition).
- **biniou**: Self-hosted webUI for 30+ generative AI models. Generate multimedia content with AI on your own computer, even without dedicated GPU (8GB RAM minimum). Works offline once deployed. GPL-3.0 licensed.
- **Self-hosted AI Starter Kit (n8n)**: Open-source Docker Compose template to quickly set up a local AI environment. Curated by n8n, combines self-hosted n8n with Ollama, Qdrant, and PostgreSQL for secure, self-hosted AI workflows. Apache 2.0 licensed.
- **CoAI**: Next-generation multi-tenant AI one-stop solution with built-in admin and billing system. Enterprise-grade unified LLM gateway supporting 200+ models and 35+ providers. Apache-2.0 licensed.
- **Plane**: Open-source Jira, Linear, Monday, and ClickUp alternative. AI-powered project management platform with intelligent task triage, sprint planning, and automated workflows. AGPL-3.0 licensed.
- **RAG Web UI**: Intelligent dialogue system based on RAG technology. Build intelligent Q&A systems on your own knowledge base with modern web interface. Apache-2.0 licensed.
- **LibreTranslate**: Self-hosted machine translation API powered by Argos Translate, offering a free and offline-capable alternative to proprietary translation services. AGPL-3.0 licensed.

#### Desktop & Mobile AI Apps (13 tools)

- **Jan**: Local-first AI app framework.
- **Cherry Studio**: AI productivity studio with smart chat, autonomous agents, and 300+ assistants. Unified access to frontier LLMs. AGPL-3.0 licensed.
- **DeepChat**: A smart assistant that connects powerful AI to your personal world. Built-in MCP and ACP support, multiple search engines, privacy-focused with local data storage. Apache-2.0 licensed.
- **SillyTavern**: Highly customizable role-playing frontend.
- **ChatALL**: Concurrently chat with multiple AI bots to discover the best answers. Desktop app for comparing ChatGPT, Claude, Gemini, and 20+ LLMs side-by-side. Apache 2.0 licensed.
- **Chatbox**: Powerful desktop AI client for ChatGPT, Claude, and other LLMs. Cross-platform with modern UI. GPLv3 licensed (Community Edition).
- **Maid**: Free and open-source Android app for interfacing with llama.cpp models locally and remote APIs (Anthropic, DeepSeek, Mistral, Ollama, OpenAI). MIT licensed.
- **Dive**: Open-source MCP Host Desktop Application with dual Tauri/Electron architecture. Seamlessly integrates with any LLMs supporting function calling. MIT licensed.
- **PocketPal AI**: Open-source app that brings small language models directly to your phone. Run AI 100% privately on iOS and Android with no cloud required. MIT licensed.
- **Hermes Desktop**: Desktop companion application for installing, configuring, and chatting with Hermes Agent. MIT licensed.
- **Craft Agents**: Open-source desktop and web interface for agentic workflows, featuring built-in MCP support, customizable API connections, and session sharing. Apache-2.0 licensed.
- **Meetily**: Privacy-first local AI meeting assistant for real-time transcription and summary generation. MIT licensed.
- **OpenSuperWhisper**: macOS dictation application providing real-time audio transcription and drag-and-drop file transcription using Whisper and Parakeet models. MIT licensed.

#### Agent & Voice Infrastructure (3 tools)

- **LiveKit Agents**: Framework for building realtime voice AI agents with WebRTC transport, STT-LLM-TTS pipelines, and production-grade orchestration. Used by Salesforce Agentforce and Tesla. Apache-2.0 licensed.
- **Pipecat**: Open-source framework for voice and multimodal conversational AI. Build real-time voice agents with support for speech-to-text, LLMs, text-to-speech, and live video. BSD-2-Clause licensed.
- **Agent Chat UI**: Web app for interacting with any LangGraph agent (Python & TypeScript) via a chat interface. Stream messages, handle interruptions, and view agent state. MIT licensed.

## 13. Developer Tools & Integrations

#### AI-Native IDEs & Development Environments (12 tools)

- **Ralph**: Autonomous AI development loop for Claude Code with intelligent exit detection. Automates iterative coding workflows with self-monitoring capabilities. MIT licensed.
- **Nimbalyst**: Desktop app for running multiple Codex and Claude Code AI sessions in parallel Git worktrees. Test, compare approaches and manage AI-assisted development workflows in one unified interface. MIT licensed.
- **Nezha**: Code editor for the AI agents era. Run multiple Claude Code and Codex agents across projects on your machine with an intuitive interface. GPL-3.0 licensed.
- **Aider Desk**: Platform for AI-powered software engineers. Desktop application that enhances the aider terminal experience with a modern UI. Apache 2.0 licensed.
- **Zed**: High-performance, multiplayer code editor with built-in AI features. From the creators of Atom and Tree-sitter. Native AI agentic editing with support for any LLM provider. GPL licensed.
- **Code Server**: Run VS Code on any machine anywhere and access it in the browser. Self-hosted cloud IDE with full extension support. MIT licensed.
- **Gitpod**: Cloud development environment platform with automated prebuilds, ephemeral workspaces, and support for any IDE. Self-hostable with open-source core. AGPL-3.0 licensed.
- **Onlook**: Open-source AI-first design and React editing environment for visually building and modifying frontend applications.
- **Daytona**: Secure elastic infrastructure for running AI-generated code. Self-hosted alternative to GitHub Codespaces with support for multiple IDEs, prebuilds, and any cloud provider. AGPL-3.0 licensed.
- **AI Workdeck**: Open-source AI-native IDE workspace for legal and document-heavy workflows — "VS Code for lawyers." Self-hosted with MCP agent orchestration, OCR, due-diligence risk flagging, evidence-chain management, WPS WebOffice integration, smart clipboard. Sup
- **Orca**: An agentic development environment (ADE) for running and orchestrating coding agents in parallel Git worktrees on desktop and mobile. MIT licensed.
- **Terax**: Lightweight terminal-first AI-native dev workspace (ADE) featuring multi-tab terminals, a code editor with AI edit diffs, source control, and agentic workflows. Apache 2.0 licensed.

#### AI Coding Assistants (open-source) (9 tools)

- **Continue**: Open-source AI coding autopilot for VS Code & JetBrains.
- **Tabby**: Self-hosted AI coding assistant.
- **Cline**: Open-source IDE coding agent that can edit files, run commands, and use tools with user approval.
- **Open Interpreter**: Lets LLMs run code locally.
- **Aider**: Terminal-based AI pair programmer. Edit code in your local editor and aider implements the changes. Supports multiple LLMs, voice coding, and automatic Git commits. Top scores on SWE Bench. Apache 2.0 licensed.
- **Kimi CLI**: Kimi Code CLI agent from Moonshot AI. Terminal-based coding assistant with advanced context understanding and multi-file editing capabilities. Apache 2.0 licensed.
- **Qwen Code**: Open-source AI agent for the terminal, optimized for Qwen series models. Multi-protocol provider support including OpenAI, Anthropic, Gemini, Alibaba Cloud, OpenRouter. Features agentic workflow with Skills and SubAgents. Apache 2.0 licensed.
- **DeepCode**: Transforms research papers and natural language into production-ready code. AI-powered research-to-code automation tool. MIT licensed.
- **OpenSpec**: Spec-driven development (SDD) framework and CLI tool for AI coding assistants, providing structured workflows for proposing, implementing, and archiving code changes. MIT licensed.

#### Notebooks & Interactive Computing (7 tools)

- **Open Notebook**: Open-source implementation of Notebook LM with multi-modal content support (PDFs, videos, audio, web pages). Features multi-speaker podcast generation, 18+ AI provider integrations, and full-text + vector search. Self-hosted with complete data sovere
- **Deta Surf**: Personal AI notebook for organizing files and webpages with AI-generated notes. Local-first data storage, open data formats, and open model choice including local models. Cross-platform desktop app for research and thinking workflows. Apache 2.0 lice
- **FilePilot AI**: Local-first file intelligence app, CLI, and MCP server for searching, summarizing, tagging, deduplicating, and safely organizing local files for AI agent workflows. MIT licensed.
- **Quarto**: Open-source scientific and technical publishing system built on Pandoc. Create dynamic content with Python, R, Julia, and Observable. MIT licensed.
- **Drawdata**: Draw datasets from within Python notebooks. Interactive data visualization tool for creating and editing datasets directly in Jupyter environments. MIT licensed.
- **Deepnote**: Drop-in replacement for Jupyter with AI-first design, sleek UI, and native data integrations. Use Python, R, and SQL locally, then scale to Deepnote cloud for collaboration and deployable data apps. Apache 2.0 licensed.
- **Zasper**: High-performance IDE for Jupyter Notebooks built with Go. Up to 5x less CPU and 40x less RAM than JupyterLab. Implements Jupyter's wire protocol with massive concurrency support. AGPL-3.0 licensed.

#### IDE Plugins & Extensions (23 tools)

- **llama.vim**: Local LLM-powered code completion plugin for Vim/Neovim using llama.cpp. Fast, privacy-first, no API key needed.
- **CodeCompanion.nvim**: AI-powered coding assistant for Neovim. Inline code generation, chat, actions, and tool use with support for multiple LLM providers.
- **ProxyAI**: Leading open-source AI copilot for JetBrains IDEs. Connect to any model in any environment with auto-apply, image chat, file references, web search, and customizable personas. Apache 2.0 licensed.
- **avante.nvim**: Neovim plugin that brings Cursor-like AI IDE features to Vim. Edit code with natural language, generate code from context, and chat with AI about your codebase. Apache 2.0 licensed.
- **Serena**: Powerful MCP toolkit for coding agents providing semantic retrieval and editing capabilities. Integrates language servers for IDE-level code understanding. MIT licensed.
- **vim-ai**: AI-powered code assistant for Vim and Neovim. Generate code, edit text, and have interactive conversations with GPT models. Supports custom roles, vision capabilities, and any OpenAI-compatible API. MIT licensed.
- **windsurf.vim**: Free, ultrafast Copilot alternative for Vim and Neovim. AI-powered code completion with low latency and large context window. MIT licensed.
- **Jupyter AI**: Chat and code generation inside notebooks.
- **Minuet AI**: Neovim plugin offering code completion as-you-type from popular LLMs including OpenAI, Gemini, Claude, Ollama, Llama.cpp, Codestral, and more. GPL-3.0 licensed.
- **Peekaboo**: macOS CLI & MCP server enabling AI agents to capture screenshots and automate UI interactions. Visual question answering through local or remote AI models. MIT licensed.
- **Skills**: A collection of custom productivity and engineering skills for Claude Code and other AI coding agents. MIT licensed.
- **planning-with-files**: Persistent file-based planning skill for AI coding agents to survive context loss and restarts with a deterministic completion gate. MIT licensed.
- **Stop Slop**: A skill file for Claude Code and other agents to remove AI writing patterns and tells from generated prose. MIT licensed.
- **Understand Anything**: Turns subdirectories, codebases, or knowledge bases into an interactive, AI-navigable knowledge graph and dashboard. MIT licensed.
- **Knowledge Work Plugins (Anthropic)**: Collection of role-specific plugins and sub-agents for Claude Cowork and Claude Code. Apache 2.0 licensed.
- **Cursor Plugins**: Official Cursor plugins for developer tools, workflows, and SaaS integrations. MIT licensed.
- **Claude Plugins Marketplace**: Official, Anthropic-managed directory of high-quality plugins for Claude Code. Apache 2.0 licensed.
- **Agent Toolkit for AWS**: Official AWS-supported MCP servers, skills, and plugins to help AI coding agents build, deploy, and manage applications on AWS. Apache 2.0 licensed.
- **Caveman**: Skill and setup script for Claude Code, Codex, Gemini, Cursor, and other coding agents that reduces token output by instructing agents to communicate in concise, caveman-style prose. MIT licensed.
- **Chrome DevTools MCP**: Official Model Context Protocol (MCP) server from Google that enables coding agents to control and inspect a live Chrome browser for automation, debugging, and web performance analysis. Apache 2.0 licensed.
- **Codex Plugin for Claude Code**: Official integration plugin for Claude Code that enables developers to run Codex code reviews, delegate tasks, and manage background coding jobs. Apache 2.0 licensed.
- **Unity MCP**: Model Context Protocol (MCP) server bridging AI assistants with the Unity Editor to automate asset, scene, and script workflows. MIT licensed.
- **.NET Agent Skills**: Curated set of skills, custom agents, and plugins to assist AI coding agents with .NET and C# development. MIT licensed.

#### UI Components & Chat Libraries (3 tools)

- **Assistant UI**: React/TypeScript library for building production-grade AI chat interfaces. Drop-in components for streaming messages, tool calls, and multi-modal inputs.
- **Deep Chat**: Fully customizable AI chatbot component for your website. Supports OpenAI, direct API services, and custom endpoints. MIT licensed.
- **CopilotKit**: Best-in-class SDK for building full-stack agentic applications, Generative UI, and chat applications. Creators of the AG-UI Protocol adopted by Google, LangChain, AWS, and Microsoft. MIT licensed.

#### CLI Tools & API Clients (19 tools)

- **Ruler**: Central AI agent rule registry. Manages and distributes rules for AI coding agents across projects. MIT licensed.
- **PR-Agent (Qodo)**: AI-powered code review agent for GitHub, GitLab, Bitbucket, and Azure DevOps. Automated PR analysis, improvement suggestions, and multi-platform deployment via CLI, GitHub Actions, or webhooks. AGPL-3.0 licensed.
- **LLM (Simon Willison)**: CLI tool and Python library for interacting with dozens of LLMs via remote APIs or locally. Extensible plugin ecosystem, SQLite logging. Apache 2.0 licensed.
- **AIChat**: All-in-one LLM CLI in Rust featuring Shell Assistant, Chat-REPL, RAG, AI Tools & Agents. Supports 20+ providers. MIT/Apache 2.0 licensed.
- **aicommits**: CLI that writes your Git commit messages for you with AI. Never write a commit message again. Supports multiple providers including OpenAI, Groq, xAI, Ollama, and LM Studio. MIT licensed.
- **Codex CLI**: OpenAI's lightweight coding agent that runs in your terminal. Code generation, file editing, and command execution with approval. Apache 2.0 licensed.
- **Repomix**: Powerful tool that packs your entire repository into a single AI-friendly file. Perfect for feeding codebases to LLMs with smart filtering and token counting. MIT licensed.
- **GitIngest**: Replace 'hub' with 'ingest' in any GitHub URL to get a prompt-friendly extract of a codebase. Optimized for Python ecosystem and data science workflows. MIT licensed.
- **Instructor**: Python library for extracting structured, validated data from LLMs using Pydantic models. Handles validation, retries, and error handling with 15+ provider support. MIT licensed.
- **Mirascope**: Python toolkit for building LLM applications with automatic versioning, tracing, and cost tracking. The "LLM Anti-Framework" for developers who want control. MIT licensed.
- **Context7**: Up-to-date code documentation for LLMs and AI code editors. Fetches latest docs and code examples directly into LLM context via MCP. Eliminates hallucinated APIs. MIT licensed.
- **Claude Squad**: Manage multiple AI terminal agents like Claude Code, Codex, OpenCode, and Amp. Terminal multiplexer for AI coding agents with session management and parallel execution. AGPL-3.0 licensed.
- **Herdr**: Terminal agent multiplexer and workspace manager with mouse-native split-panes and automatic agent state detection. AGPL-3.0 licensed.
- **agenttrace**: Local-first TUI for observing AI coding agent sessions across Claude Code, Codex CLI, Gemini CLI, Aider, Cursor exports, OpenCode, and more.
- **agentsview**: Local-first session intelligence and cost analytics dashboard for AI coding agents, supporting Claude Code, Codex, and other tools. MIT licensed.
- **Uni-CLI**: Self-repairing CLI catalog that exposes web, desktop, Electron, and bridge tools as deterministic commands for AI agents.
- **OpenChamber Mobile Bridge**: OpenCode/OpenChamber helper for exposing devcontainer-based coding sessions to private Tailscale mobile access through a host bridge. MIT licensed.
- **DesktopCommander MCP**: MCP server for Claude providing terminal control, file system search, and diff file editing capabilities. Enables autonomous code editing through Model Context Protocol. MIT licensed.
- **Claude Code Action**: GitHub Action for running Claude Code in PR and issue workflows with approval-aware automation and coding assistance.

#### SDKs & API Development Tools (4 tools)

- **Vercel AI SDK**: Provider-agnostic TypeScript toolkit for building AI-powered applications and agents. Unified API for OpenAI, Anthropic, Google, and 20+ providers with first-class streaming, tool-calling, and structured output support. Apache 2.0 licensed.
- **GitHub Copilot SDK**: Multi-platform SDK for integrating GitHub Copilot Agent into apps and services. Production-tested agent runtime with planning, tool invocation, and context management. Build Copilot-style agents without writing your own orchestration. MIT licensed.
- **IBM MCP Context Forge**: Gateway and registry for MCP/A2A/REST APIs with unified discovery, routing, and guardrails for production agent integrations.
- **Fern**: Open-source SDK generator for REST APIs. Generate type-safe API clients in TypeScript, Python, Go, Java, and more from OpenAPI specs. Powers SDKs for companies like OpenAI, Anthropic, and Cloudflare. Apache 2.0 licensed.

#### Testing & Debugging Tools (1 tools)

- **no-mistakes**: A local Git proxy and validation pipeline that runs AI-driven checks and applies fixes in a temporary worktree before forwarding pushes and opening clean PRs. MIT licensed.

#### Prompt Engineering & Management (2 tools)

- **Helicone**: Open-source LLM observability platform with prompt management, versioning, and experimentation. One-line integration, YC W23 company. Apache 2.0 licensed.
- **GEPA**: Reflective prompt evolution optimizer using natural language reflection and Pareto frontier learning. Outperforms reinforcement learning for prompt optimization. Integrated with DSPY and MLflow. MIT licensed.

## 14. Resources & Learning

#### Papers with Open Implementations (3 tools)

- **Papers with Code**: Definitive database linking papers to open code and datasets.
- **Hugging Face Papers**: Daily-updated feed of the latest arXiv papers with open weights.
- **Open LLM Leaderboard (Hugging Face)**: Real-time ranking of open models.

#### Communities, Forums & Newsletters (1 tools)

- **Hugging Face Discussions**: Largest open AI forum.

#### Educational Resources & Courses (5 tools)

- **AI Engineering from Scratch (rohitg00)**: Comprehensive curriculum covering machine learning, deep learning, NLP, computer vision, and agents by implementing them from scratch. MIT licensed.
- **Prompt Engineering Guide (DAIR-AI)**: Comprehensive guides, papers, lessons, and notebooks for prompt engineering, context engineering, RAG, and AI Agents. The definitive open-source resource for learning prompt engineering with 3M+ learners. MIT licensed.
- **Start Machine Learning (louisfb01)**: A complete guide to start and improve in machine learning and AI in 2026 without any background. Curated learning path with the latest news, state-of-the-art techniques, and comprehensive resources for beginners. MIT licensed.
- **Claude How To**: Comprehensive learning path and template guide for Claude Code, covering setup, hooks, custom skills, and MCP server integrations. MIT licensed.
- **r/LocalLLaMA**: Go-to subreddit for local/open-source LLM topics.

#### Courses & Interactive Playgrounds (17 tools)

- **Hugging Face Course**: Free hands-on courses using only open models.
- **ML For Beginners (Microsoft)**: 12-week, 26-lesson, 52-quiz classic machine learning course for beginners. Comprehensive curriculum covering regression, classification, clustering, and NLP with practical projects.
- **LLM Course (Maxime Labonne)**: End-to-end course for getting into Large Language Models with roadmaps and Colab notebooks. Covers pre-training, fine-tuning, RLHF, quantization, and prompt engineering.
- **AI For Beginners (Microsoft)**: 12-week, 24-lesson curriculum on Artificial Intelligence. Covers symbolic AI, neural networks, computer vision, NLP, and reinforcement learning with hands-on labs.
- **Generative AI for Beginners (Microsoft)**: 21 lessons covering generative AI fundamentals, prompt engineering, RAG applications, fine-tuning, and LLM app deployment with practical exercises.
- **LangChain Academy**: Free courses on agents and RAG.
- **Data Science for Beginners (Microsoft)**: 10-week, 20-lesson curriculum on data science fundamentals. Covers data preparation, visualization, modeling, and deployment with practical projects.
- **Learn PyTorch for Deep Learning (Zero to Mastery)**: Comprehensive PyTorch deep learning course with hundreds of exercises and real-world projects.
- **The Incredible PyTorch**: Curated list of PyTorch tutorials, papers, projects, and communities for deep learning researchers.
- **Deep RL Class (Hugging Face)**: Free deep reinforcement learning course with hands-on exercises and trained agent publishing to the Hugging Face Hub.
- **Practical RL (Yandex Data School)**: Comprehensive reinforcement learning course covering RL fundamentals, deep RL, policy gradients, actor-critic methods, and practical applications in the wild. The Unlicense.
- **NLP Course (Yandex Data School)**: YSDA course in Natural Language Processing with 2025 materials covering text classification, language models, transformers, and modern NLP techniques. MIT licensed.
- **Large Language Model Notebooks Course**: Practical hands-on course about Large Language Models and their applications. Covers Chatbots, Code Generation, OpenAI API, Hugging Face, Vector databases, LangChain, Fine Tuning, PEFT, LoRA, QLoRA. MIT licensed.
- **Transformers Tutorials (Niels Rogge)**: Comprehensive tutorials and demos using the Hugging Face Transformers library for NLP, vision, and multimodal tasks.
- **Made With ML (Goku Mohandas)**: End-to-end course on building production-grade ML systems with MLOps fundamentals, from design to deployment and iteration.
- **AI Engineering Hub**: 93+ production-ready projects with in-depth tutorials on LLMs, RAG, and real-world AI agent applications. Comprehensive resources for all skill levels from beginner to advanced. MIT licensed.
- **Complete Agentic AI Engineering Course**: 6-week comprehensive course on Agentic AI covering autonomous agents, multi-agent systems, and practical agent development. MIT licensed.

#### Starter Projects & Examples (2 tools)

- **TensorFlow Tutorials**: Official guides for beginners to advanced users.
- **Hugging Face Transformers Notebooks**: Run Transformers, Datasets, and more in Colab.

#### Curated Resource Lists (3 tools)

- **Awesome Machine Learning**: The definitive curated list of machine learning frameworks, libraries and software organized by language. Covers Python, C++, Java, JavaScript, and more with comprehensive coverage of the ML ecosystem. CC0-1.0 licensed.
- **Awesome Artificial Intelligence**: Curated list of artificial intelligence courses, books, video lectures, and papers for developers and researchers. MIT licensed.
- **Andrej Karpathy Skills**: A single CLAUDE.md file to improve Claude Code behavior, derived from Andrej Karpathy's observations on LLM coding pitfalls. Principles: Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution. MIT licensed.

