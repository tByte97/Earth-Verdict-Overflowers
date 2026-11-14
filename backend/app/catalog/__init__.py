"""Variable whitelist loaded from variables.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml

from ..models import Variable

CATALOG_FILE = Path(__file__).with_name("variables.yaml")


@dataclass(frozen=True)
class VariableDef:
    id: str
    label: str
    units: str
    decimals: int
    agg: Literal["mean", "sum"]
    per_day: bool
    source_kind: Literal["power", "giovanni"]
    source_param: str
    product: str
    witness: Optional[str]
    first_year: int
    last_year: int
    definition: str
    caveat: Optional[str]

    def public(self) -> Variable:
        return Variable(id=self.id, label=self.label, units=self.units,
                        definition=self.definition, caveat=self.caveat)


@lru_cache(maxsize=1)
def load_variables() -> dict[str, VariableDef]:
    raw = yaml.safe_load(CATALOG_FILE.read_text(encoding="utf-8"))
    out: dict[str, VariableDef] = {}
    for vid, v in raw.items():
        if v["agg"] not in ("mean", "sum") or v["source"]["kind"] not in ("power", "giovanni"):
            raise ValueError(f"bad catalog entry {vid!r}")
        out[vid] = VariableDef(
            id=vid, label=v["label"], units=v["units"], decimals=int(v["decimals"]),
            agg=v["agg"], per_day=bool(v["per_day"]),
            source_kind=v["source"]["kind"], source_param=v["source"]["param"],
            product=v["source"]["product"], witness=v.get("witness"),
            first_year=int(v["years"][0]), last_year=int(v["years"][1]),
            definition=v["definition"], caveat=v.get("caveat"),
        )
    return out


def get_variable(variable_id: str) -> Optional[VariableDef]:
    return load_variables().get(variable_id)
