from .main import app
from .management_routes import router as management_router
from .payment_routes import router as payment_router

app.include_router(management_router)
app.include_router(payment_router)
