# Essay Bank

## What is your most ambitious project and what was the most difficult technical hurdle?
My most ambitious project is **AI Assistant**, a custom agentic framework built to orchestrate local LLMs. The most difficult hurdle was mitigating **infinite reasoning recursion** during multi-step tool use. I solved this by engineering a **deterministic tool-execution engine** with a decorator-based registry and state-aware loop-detection guards. To keep the system performant on consumer hardware (RTX 3050), I architected a **hierarchical memory tier** (SQLite WAL for state + ChromaDB for semantic recall), achieving sub-10ms retrieval and a throughput of **90 tokens/sec**.

## Describe a complex technical problem you solved and the specific tools you used.
In **TweetScape**, I faced a massive bottleneck in the real-time NLP pipeline when processing high-frequency data. Generating 384D embeddings for every incoming event was redundant and high-latency. I engineered a specialized **feature-caching layer** using **SQLite**, which reduced redundant inference and achieved **<1ms lookups**. I coupled this with **UMAP dimensionality reduction** and **D3.js** to project these embeddings into interactive clusters, maintaining a pipeline throughput of **500+ events/sec**.

## What technical achievement are you most proud of?
I am most proud of my work on the **Plagiarism & Semantic Intelligence Engine**, specifically the **DetectGPT-inspired curvature algorithm** implementation. Detecting AI-generated text is a probabilistic game, so I built a **multi-signal ensemble** using **RoBERTa classifiers** and log-probability curvature Analysis. I’m proud of successfully bridging the gap between research-level NLP and a production-ready **FastAPI/Next.js** application that handles the entire document lifecycle, from **PDF-to-Markdown conversion (Marker)** to concurrent **arXiv API** benchmarking.

## Tell us about a time you optimized a systems's performance.
During my internship at the **KJSCE Software Development Cell**, I was tasked with fixing high latency in a course management platform for **1,000+ users**. By profiling the **MongoDB aggregation pipelines**, I identified unoptimized query patterns and refactored them for better index utilization. This resulted in a **~40% reduction in API latency**. I subsequently established **reusable component standards in React** to eliminate frontend render-blocking issues, significantly improving the overall p99 user experience.

## What was a difficult architectural decision you had to make?
While building **WolfCafe+**, I had to decide between a simple request-response model and a more complex **stateless JWT-based authentication** system integrated with a **Jest/Supertest CI/CD pipeline**. Despite the initial overhead, I chose the latter to ensure the system could scale to **~450 req/sec** under synthetic load while maintaining **>85% test coverage**. This decision was difficult because it limited early-stage velocity, but it ensured the **System Integrity** and architectural resilience needed for an enterprise-grade e-commerce backend.
