"""HTTP API for external projects to call the fault knowledge base QA.

Exposes the same end-to-end pipeline as the Streamlit frontend
(route, parse, retrieve, generate) so other backends (e.g. PLD) can
query the knowledge base over HTTP.

Endpoints:
    GET  /health  - liveness probe
    POST /query   - {"question": "..."} -> {"answer": "..."}

Notes:
    - engine.query() is a blocking call that may take tens of seconds for
      data-heavy questions; endpoints are plain `def` so uvicorn runs them
      in its threadpool. Callers should set a timeout >= 300s (aligned
      with LLM_TIMEOUT).
    - No clarify multi-round: if the question lacks time info, the
      clarify text from the engine is returned as the answer as-is.

Usage (from project root):
    env_fault/bin/python3 src/interface/api.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import API_HOST, API_PORT
from core.engine import query

app = FastAPI(title="故障知识库 API", version="1.0")


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query_api(req: QueryRequest) -> QueryResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    try:
        return QueryResponse(answer=query(question))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    uvicorn.run(app, host=API_HOST, port=API_PORT)
