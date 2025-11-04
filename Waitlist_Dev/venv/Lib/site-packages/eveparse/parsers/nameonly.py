from eveparse.parsers.base import UnTabbedParser


class NameOnly(UnTabbedParser):
    @classmethod
    def parse(cls, string: str) -> tuple[str, int]:
        super().parse(string)
        return string, 1
