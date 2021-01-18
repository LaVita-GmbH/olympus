from decimal import Decimal
from pydantic import BaseModel, validator


TWO_PLACES = Decimal(10) ** -2


class Amount(BaseModel):
    gross: Decimal
    net: Decimal

    @validator('gross', 'net')
    def _round_amount(cls, value: Decimal):
        return value.quantize(TWO_PLACES)
