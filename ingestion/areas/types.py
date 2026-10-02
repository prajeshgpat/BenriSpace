"""Small shared data types for the neighborhood-polygon prototype.

All geometry is in a local planar metric frame (meters, see osm_source.Projector);
shapely objects are stored as-is on Block/Cluster.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry.base import BaseGeometry

# Hard-barrier weight sentinel for railways (above any road class).
RAIL_WEIGHT = 10.0


@dataclass(frozen=True)
class RoadWay:
    """One OSM way that is part of the barrier network."""

    id: int
    highway: str  # OSM highway value, or "rail" for railway=rail
    name: str | None
    nodes: tuple[int, ...]  # OSM node ids, parallel to coords
    coords: tuple[tuple[float, float], ...]  # meters
    bridge: bool = False


@dataclass
class Block:
    id: int
    geom: BaseGeometry
    kind: str = "block"  # block | park | rural
    members: tuple[int, ...] = ()  # raw face ids merged into this block

    @property
    def area(self) -> float:
        return self.geom.area


@dataclass(frozen=True)
class EdgeInfo:
    """Shared boundary between two blocks (a < b)."""

    a: int
    b: int
    length: float
    weight: float  # highest road-class weight along the shared edge (RAIL_WEIGHT for rail)
    highway: str | None
    name: str | None


@dataclass(frozen=True)
class AreaName:
    title: str
    subtitle: str = ""
    streets: tuple[str, ...] = ()


@dataclass
class Cluster:
    id: int
    block_ids: tuple[int, ...]
    geom: BaseGeometry
    kind: str = "neighborhood"  # neighborhood | rural
    name: AreaName | None = None
    district: int = -1
    stats: dict = field(default_factory=dict)

    @property
    def area(self) -> float:
        return self.geom.area


@dataclass(frozen=True)
class ClusterParams:
    min_blocks: int = 5  # stop growing at this many blocks ...
    stop_area_m2: float = 0.06 * 2_589_988.11  # ... or this area (0.06 sq mi)
    max_blocks: int = 10
    max_area_m2: float = 2_589_988.11  # 1 sq mi
    absorb_below: int = 3  # clusters smaller than this are absorbed ...
    absorb_max_blocks: int = 14  # ... into a neighbor up to this size
    soft_absorb_below: int = 5  # extra pass: <5 merged into a neighbor if result <= max_blocks
    hard_weight: float = 3.0  # secondary and above never crossed
    tertiary_weight: float = 2.0
    tertiary_penalty: float = 0.5
    w_compact: float = 1.0
    w_shared: float = 0.5
    min_contact_m: float = 10.0  # shorter shared edges are noding artefacts, not adjacency
    min_hard_contact_m: float = 3.0
    min_block_area_m2: float = 2_000.0
    thin_thickness_m: float = 15.0
    park_cover: float = 0.7
    water_cover: float = 0.5
