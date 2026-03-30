"""FastAPI entrypoint for shorts_api."""

from fastapi import FastAPI

app = FastAPI(title="short-form-pipeline API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
