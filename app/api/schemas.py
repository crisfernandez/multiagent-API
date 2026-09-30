from pydantic import BaseModel, Field
from typing import Optional, Any

class ChatRequest(BaseModel):
    thread_id: str = Field(..., example="sesion_01", description="ID de sesión para persistencia")
    mensaje: str = Field(..., example="Transfiere 100€ a Carlos")


class ResumeRequest(BaseModel):
    thread_id: str = Field(..., example="sesion_01")
    aprobado: bool = Field(..., description="True para ejecutar la acción, False para rechazarla")

class ChatResponse(BaseModel):
    status: str = Field(..., example="SUCCESS")  # SUCCESS, PENDING_APPROVAL, REJECTED
    respuesta: Optional[str] = None
    accion_pendiente: Optional[dict[str, Any]] = None