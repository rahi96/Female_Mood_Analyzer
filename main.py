from fastapi import FastAPI
from ai.config import settings
from ai.routes import chat_routes
from ai.routes import cycle_routes
from ai.routes import movement_routes
from ai.routes import summarize_pdf_routes
from ai.routes import skin_scan_routes

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
)

app.include_router(cycle_routes.router, prefix="/api", tags=["App_api's"])
app.include_router(movement_routes.router, prefix="/api", tags=["Cycle_Movement_api's"])
app.include_router(chat_routes.router, prefix="/api", tags=["Chatbot_api's"])
app.include_router(summarize_pdf_routes.router, prefix="/api", tags=["PDF_summary_api's"])
app.include_router(skin_scan_routes.router, prefix="/api", tags=["Skin_scan_api's"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
