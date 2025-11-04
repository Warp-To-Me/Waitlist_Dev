import json
import pathlib

INV_TYPES_JSON_FILE_PATH = str(pathlib.Path(__file__).parent / "data/invTypes.json")

with open(INV_TYPES_JSON_FILE_PATH, "r", encoding="utf-8") as json_file:
    TYPES = json.load(json_file)
    TYPE_NAMES = set(TYPES.keys())
