from decimal import Decimal
from typing import Optional


def calculate_gross_net(product_price: Decimal, tax_type: str, tax_percentage: Optional[float] = None):
    tax_rate = 1

    if tax_percentage:
        tax_rate = 1 + (tax_percentage / 100)


    if tax_type == 'B2C':
        gross = product_price
        net = product_price / tax_rate

    elif tax_type == 'B2B':
        gross = product_price * tax_rate
        net = product_price

    else:
        raise NotImplementedError

    return {
        'gross': gross,
        'net': net,
    }
