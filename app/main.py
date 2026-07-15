"""FastAPI entrypoint.

Run: .venv/bin/uvicorn app.main:app --reload
"""
from fastapi import FastAPI

from app.web import router

app = FastAPI(title="KnowaPlan")
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
