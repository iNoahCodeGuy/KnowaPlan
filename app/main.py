"""FastAPI entrypoint.

Run: .venv/bin/uvicorn app.main:app --reload
"""
from fastapi import FastAPI

app = FastAPI(title="KnowaPlan")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
