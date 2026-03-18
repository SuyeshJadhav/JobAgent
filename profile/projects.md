# Technical Projects

## Project 1: TweetScape -- Social Media Analytics Platform

ROLE: Full-Stack ML Engineer
STACK: React 19, FastAPI, D3.js, Transformers, SQLite
CORE_FEATURES:

- 10-Stage NLP Pipeline: Processed tweets end-to-end at 75ms/tweet across a 5-model inference stack (SentenceTransformers at 484 texts/sec, RoBERTa, KeyBERT).
- Interactive Visualization: React 19 + D3 force-directed simulation utilizing UMAP dimensionality reduction, collision physics, and dynamic glow effects.
- Smart Caching & Orchestration: SQLite caching with 24-hr TTL alongside Ollama Gemma LLM query expansion to short-circuit redundant inferences.

## Project 2: Personal AI Agent

ROLE: Custom Agentic Framework Architect
STACK: Python, FastAPI, SQLite, ChromaDB, Ollama, React Native
CORE_FEATURES:

- Decoupled Agentic Runtime: 6-tool ReAct system with decorator-based auto-registration, parameter coercion, and strict loop-detection guards across 9 intents.
- High-Performance Retrieval: Dual-tier memory utilizing SQLite (2.61ms avg via 15+ strategic indexes) and ChromaDB (190ms semantic search over 384D vectors).
- Hardware-Optimized Inference: Multi-provider backend pushing 90 tokens/sec on an RTX 3050 with quantized Whisper voice I/O and low-latency personality caching.

## Project 3: WolfCafe+ -- Scalable Full-Stack Dining Platform

ROLE: Backend Architecture Lead
STACK: React, Node.js, MongoDB, Socket.IO, GitHub Actions
CORE_FEATURES:

- Enterprise-Grade Backend: Architected 45+ REST endpoints with JWT/RBAC security, driving MongoDB aggregation pipelines achieving 2.17ms avg API latency.
- ML Recommendation Engine: Hybrid algorithm spanning collaborative filtering, temporal scoring, and content similarity, loaded with 20% exploration injection.
- Real-Time Group Sessions: WebSocket integration via Socket.IO for live group ordering (6-char share codes) with non-blocking async notification dispatch.

## Project 4: Academic Integrity Platform

ROLE: ML Systems Engineer
STACK: Python, FastAPI, Next.js 14, PyTorch, MongoDB, Transformers
CORE_FEATURES:

- Hybrid AI Detection: Dual-engine implementation fusing RoBERTa sequence classification with DetectGPT perturbation analysis using a resilient 400-word chunking strategy.
- Advanced Semantic Matching: Weighted plagiarism detection blending TF-IDF and BERT semantic embeddings (all-MiniLM-L6-v2) achieving precise 0.60-0.70 confidence thresholds.
- Scalable Event Pipeline: 8-stage asyncio architecture with singleton model caching to fully decouple heavy NLP inference from Next.js 14 client uploads.

## Project 5: AI Resume Tailoring Engine

ROLE: Backend / ML Systems Engineer
STACK: Python, FastAPI, SQLite, Ollama/Groq, JavaScript, pytest
CORE_FEATURES:

- Multi-Source Ingestion Engine: Designed a parallel job discovery pipeline spanning 3 source families (Simplify, ATS APIs, Serper) using ThreadPoolExecutor (max_workers=12), source-specific timeouts (10s/12s/15s), and fallback handling to keep runs resilient during partial source outages.
- LLM Scoring and Tailoring Guardrails: Built a hybrid scoring and tailoring layer combining deterministic gates with LLM evaluation (0-10 rubric, 5 deduction stages), plus senior-role auto-reject, quant cap, JSON-mode fallback (max_tokens=400), and numeric-claim validation with retry-and-revert protection.
- Concurrent Resume Automation Pipeline: Delivered an async FastAPI architecture (8 routers) with Semaphore(3)-gated background scraping/scoring and an automated pdflatex pipeline (60s timeout, 2-pass overflow recovery), backed by 11 pytest contracts for stable refactoring.
