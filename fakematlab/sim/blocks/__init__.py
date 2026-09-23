"""
The block library.

Importing this package registers every block. :func:`fakematlab.sim.block.create`
and the canvas palette both read from that registry, so a new block becomes
available everywhere as soon as its module is imported here.
"""

from ..block import block_types, by_category, create  # noqa: F401
from . import (  # noqa: F401
               continuous,
               discrete,
               math_blocks,
               nonlinear,
               sources,
               subsystem,
)

__all__ = ["block_types", "by_category", "create"]
