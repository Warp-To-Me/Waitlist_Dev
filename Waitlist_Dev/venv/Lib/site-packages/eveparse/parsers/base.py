from abc import ABC, abstractmethod

from eveparse.errors import ParserError


class Parser(ABC):
    @classmethod
    @abstractmethod
    def parse(cls, string: str) -> tuple[str, int]:
        raise NotImplementedError("Required method not implemented")


class TabbedParser(Parser):
    @classmethod
    def parse(cls, string: str):
        if "\t" not in string:
            raise ParserError("Required '\t' not found")


class UnTabbedParser(Parser):
    @classmethod
    def parse(cls, string: str):
        if "\t" in string:
            raise ParserError("Prohibited '\t' found")
