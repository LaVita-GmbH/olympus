from decimal import Decimal
from typing import Optional


def calculate_gross_net(product_price: Decimal, price_selling_type: str, tax_percentage: Optional[Decimal] = None, price_includes_tax: Optional[bool] = None):
    tax_rate = Decimal(1)

    if tax_percentage:
        tax_rate = Decimal(1) + (tax_percentage / 100)

    if (price_selling_type == 'B2C' and price_includes_tax in [None, True]) \
        or (price_selling_type == 'B2B' and price_includes_tax is True):
        gross = product_price
        net = product_price / tax_rate

    elif (price_selling_type == 'B2B' and price_includes_tax in [None, False]) \
        or (price_selling_type == 'B2C' and price_includes_tax is False):
        gross = product_price * tax_rate
        net = product_price

    else:
        raise NotImplementedError

    return {
        'gross': gross,
        'net': net,
    }
