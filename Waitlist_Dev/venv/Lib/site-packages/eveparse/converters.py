def normalize_string(string: str) -> str:
    """Remove errant characters to standardize string for parsing.
    Called once immediately upon parsing.
    """

    stripped_string = string.strip()
    return stripped_string.casefold()


def to_int(string: str) -> int:
    """Convert a string to an integer.
    Supports the following formats:
        1,200
        1.200
        1 200

    Strings must be validated as an int prior to conversion

    >>> from ..validators import is_int
    >>> quantity_str = '1,200'
    >>> if is_int(quantity_str):
    >>>    quantity = to_int(quantity_str)
    """

    normalized = string.replace(" ", "").replace(",", "").replace(".", "")
    return int(normalized)
