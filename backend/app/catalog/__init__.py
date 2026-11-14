"""Variable whitelist loaded from variables.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml

from ..models import Compound, Variable

CATALOG_FILE = Path(__file__).with_name("variables.yaml")
COMPOUNDS_FILE = Path(__file__).with_name("compounds.yaml")


@dataclass(frozen=True)
class VariableDef:
    id: str
    label: str
    units: str
    decimals: int
    agg: Literal["mean", "sum"]
    per_day: bool
    source_kind: Literal["power", "giovanni", "cag"]
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
        if v["agg"] not in ("mean", "sum") or v["source"]["kind"] not in ("power", "giovanni", "cag"):
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


@dataclass(frozen=True)
class CompoundDef:
    id: str
    label: str
    units: str
    decimals: int
    definition: str
    caveat: Optional[str]
    product: str
    first_year: int
    last_year: int
    giovanni_id: str
    factor: float
    min_valid_days: int
    local_signal: bool

    def public(self) -> Compound:
        return Compound(
            id=self.id,
            label=self.label,
            units=self.units,
            definition=self.definition,
            caveat=self.caveat,
            product=self.product,
            first_year=self.first_year,
            last_year=self.last_year,
            local_signal=self.local_signal,
        )


@lru_cache(maxsize=1)
def load_compounds() -> dict[str, CompoundDef]:
    raw = yaml.safe_load(COMPOUNDS_FILE.read_text(encoding="utf-8"))
    out: dict[str, CompoundDef] = {}
    for cid, c in raw.items():
        out[cid] = CompoundDef(
            id=cid,
            label=c["label"],
            units=c["units"],
            decimals=int(c["decimals"]),
            definition=c["definition"],
            caveat=c.get("caveat"),
            product=c["product"],
            first_year=int(c["years"][0]),
            last_year=int(c["years"][1]),
            giovanni_id=c["giovanni_id"],
            factor=float(c.get("factor", 1.0)),
            min_valid_days=int(c.get("min_valid_days", 10)),
            local_signal=bool(c.get("local_signal", True)),
        )
    return out


def get_compound(compound_id: str) -> Optional[CompoundDef]:
    return load_compounds().get(compound_id)
