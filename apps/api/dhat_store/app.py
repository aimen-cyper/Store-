from .main import app
from .management_routes import router as management_router

app.include_router(management_router)
