from fastapi import FastAPI

app = FastAPI(title="Tripletex AI Agent")


@app.get("/")
async def root():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    from src.config import settings

    uvicorn.run("src.main:app", host="0.0.0.0", port=settings.port, reload=True)
