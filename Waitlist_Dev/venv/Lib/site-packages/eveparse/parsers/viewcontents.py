from eveparse.converters import to_int
from eveparse.errors import ParserError
from eveparse.parsers.base import TabbedParser
from eveparse.validators import is_int


class ViewContents(TabbedParser):
    """Burned Logic Circuit	Salvaged Materials	Cargo Hold	26"""

    @classmethod
    def parse(cls, string: str) -> tuple[str, int]:
        super().parse(string)
        if string.count("\t") != 3:
            raise ParserError("Not 3 tabs")
        parts = string.split("\t")

        quantity_str = parts[3]
        if not is_int(quantity_str):
            raise ParserError("Quantity is not int")
        quantity = to_int(quantity_str)

        name = parts[0]
        return name, quantity
