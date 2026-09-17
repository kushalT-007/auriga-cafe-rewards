from pydantic import BaseModel, Field


class RegistrationRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=6, max_length=128)


class MemberRegistrationRequest(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=80)
    last_name: str = Field(..., min_length=2, max_length=80)
    phone: str = Field(..., min_length=7, max_length=30)
    email: str | None = Field(default=None, max_length=120)


class PurchaseRequest(BaseModel):
    member_id: int | str | None = None
    phone: str | None = None
    amount: float = Field(..., gt=0)
    notes: str | None = None


class RedemptionRequest(BaseModel):
    member_id: int | str | None = None
    phone: str | None = None
    item_name: str = Field(..., min_length=2, max_length=120)
    points: float = Field(..., gt=0)
    notes: str | None = None


class ClockRequest(BaseModel):
    days: int | None = None
    timestamp: str | None = None


UserAuthRequest = RegistrationRequest
