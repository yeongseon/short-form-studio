"""FastAPI entrypoint for shorts_api."""

from fastapi import FastAPI

from shorts_api.routes import creator_router

app = FastAPI(title="short-form-pipeline API")

# Mount creator router at /api/creator
app.include_router(creator_router, prefix="/api/creator")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
