"""FastAPI entrypoint.

Run: .venv/bin/uvicorn app.main:app --reload
"""
from fastapi import FastAPI, Request, Response

from app.web import router, templates

app = FastAPI(title="KnowaPlan")
app.include_router(router)


@app.exception_handler(Exception)
async def _unhandled_error(
    request: Request, exc: Exception
) -> Response:
    # The audience is someone tapping a texted link: a bare
    # "Internal Server Error" reads as broken-and-gone. Starlette
    # re-raises after sending, so the traceback still reaches the
    # server log. The copy makes NO claim about money — a crash
    # mid-settle can land after a charge (record-first keeps that
    # queryable), so "nothing was charged" could be a lie. The
    # heading matters for the same reason: error.html defaults to
    # "Can't do that" (refusal framing), which after a mid-settle
    # crash would read as "nothing happened".
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "heading": "Something went wrong",
            "message": (
                "Something went wrong on our end. Give it a "
                "moment and try again — if it keeps happening, "
                "text the planner."
            ),
        },
        status_code=500,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
