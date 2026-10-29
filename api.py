"""Brief entry point: the FastAPI app. Run with `uvicorn api:app` (or `make up`)."""

from app.main import create_app

app = create_app()
