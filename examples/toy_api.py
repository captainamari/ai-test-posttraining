"""Independent synthetic functions used only to learn the training workflow."""
def reserve(stock, quantity):
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("quantity")
    if quantity > stock:
        raise ValueError("stock")
    return stock - quantity


def normalize_tag(value):
    return value.strip().lower()


def is_positive_integer(value):
    return type(value) is int and value > 0


def parse_quantity(text):
    if not isinstance(text, str) or not text.isdigit():
        raise ValueError("quantity must be digits")
    return int(text)
