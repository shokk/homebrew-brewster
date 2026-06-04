"""
diff.py — Set-logic comparison of packages between two machines.

Returns structured diff objects that cli.py renders via rich.
Also handles version mismatch detection for packages present on both machines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PackageRow:
    """Normalised view of a formula or cask row from the DB."""
    name: str
    version: str
    tap: Optional[str] = None


@dataclass
class DiffResult:
    """
    Full diff between two machines for one package type (formulae or casks).

    Attributes:
        only_a      — packages present on machine A but not B
        only_b      — packages present on machine B but not A
        common      — packages present on both (same version)
        version_diff — packages present on both but with different versions;
                       list of (PackageRow_a, PackageRow_b)
    """
    machine_a: str
    machine_b: str
    kind: str  # "formulae" or "casks"

    only_a: list[PackageRow] = field(default_factory=list)
    only_b: list[PackageRow] = field(default_factory=list)
    common: list[PackageRow] = field(default_factory=list)
    version_diff: list[tuple[PackageRow, PackageRow]] = field(default_factory=list)

    @property
    def has_differences(self) -> bool:
        return bool(self.only_a or self.only_b or self.version_diff)

    def missing_on_b(self) -> list[PackageRow]:
        """Packages that machine B would need to install to match A."""
        return self.only_a

    def missing_on_a(self) -> list[PackageRow]:
        """Packages that machine A would need to install to match B."""
        return self.only_b


def _rows_to_map(rows) -> dict[str, PackageRow]:
    """Convert DB rows (or dicts) to a name→PackageRow mapping."""
    result = {}
    for r in rows:
        # Support both sqlite3.Row and plain dict
        if hasattr(r, "keys"):
            name = r["name"]
            version = r["version"]
            tap = r["tap"] if "tap" in r.keys() else None
        else:
            name = r["name"]
            version = r["version"]
            tap = r.get("tap")
        result[name] = PackageRow(name=name, version=version, tap=tap)
    return result


def compute_diff(
    machine_a: str,
    machine_b: str,
    rows_a,
    rows_b,
    kind: str = "formulae",
) -> DiffResult:
    """
    Compute the full diff between two sets of package rows.

    Args:
        machine_a / machine_b — display names (label or hostname)
        rows_a / rows_b       — iterable of DB rows or dicts with name/version/tap
        kind                  — "formulae" or "casks"
    """
    map_a = _rows_to_map(rows_a)
    map_b = _rows_to_map(rows_b)

    names_a = set(map_a)
    names_b = set(map_b)

    only_a = sorted([map_a[n] for n in names_a - names_b], key=lambda p: p.name)
    only_b = sorted([map_b[n] for n in names_b - names_a], key=lambda p: p.name)

    common_names = names_a & names_b
    common = []
    version_diff = []

    for name in sorted(common_names):
        pa, pb = map_a[name], map_b[name]
        if pa.version == pb.version:
            common.append(pa)
        else:
            version_diff.append((pa, pb))

    return DiffResult(
        machine_a=machine_a,
        machine_b=machine_b,
        kind=kind,
        only_a=only_a,
        only_b=only_b,
        common=common,
        version_diff=sorted(version_diff, key=lambda t: t[0].name),
    )
