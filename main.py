from fastapi import FastAPI
from ai.config import settings
from ai.routes import chat_routes
from ai.routes import cycle_routes

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
)

app.include_router(cycle_routes.router, prefix="/api", tags=["App_api's"])
app.include_router(chat_routes.router, prefix="/api", tags=["Chatbot_api's"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}
