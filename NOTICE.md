# Source and attribution

Agent Hub is an independently written implementation for this project. Its design is informed by Victor Taelin's UniiChat specification (formerly OptChat) and the related OptMem project. No upstream implementation source or compactor prompt is vendored here. The source audit and observed revisions are in `docs/UPSTREAM_ANALYSIS.md` and `docs/SOURCES.json`.

Runtime dependencies include the official Model Context Protocol Python SDK, FastAPI, Uvicorn, HTTPX, Pydantic, and TOML Kit. Each dependency remains subject to its own license. Dependency versions and package hashes are recorded in `requirements.lock`.

This repository is intended to be created privately in its owner's GitHub account. No public distribution license has been selected for the application in this initial delivery.
