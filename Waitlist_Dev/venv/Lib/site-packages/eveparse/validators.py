import functools

from eveparse.constants import TYPE_NAMES

ILLEGAL_STRINGS = [
    "minerals",
    "components",
    "item	required	available	est. unit price	typeid",
]


def is_int(string: str) -> bool:
    # these patterns indicate a float value such as 1,000.00
    if "," in string and "." in string:
        return False
    if " " in string and "." in string:
        return False
    if " " in string and "," in string:
        return False

    # indicates a decimal less than 1 such as 0.5
    if string.startswith("0"):
        return False

    # numbers may be separated with period, comma, or space
    # https://docs.oracle.com/cd/E19455-01/806-0169/overview-9/index.html
    normalized = string.replace(" ", "").replace(",", "").replace(".", "")
    return normalized.isdigit()


def is_legal_string(string: str) -> bool:
    if string in ILLEGAL_STRINGS:
        return False
    return True


# slightly more than number of currently published invTypes at 23623
@functools.lru_cache(maxsize=25000)
def is_valid_name(string: str) -> bool:
    return string in TYPE_NAMES
