"""
The block library.

Importing this package registers every block. :func:`fakematlab.sim.block.create`
and the canvas palette both read from that registry, so a new block becomes
available everywhere as soon as its module is imported here.
"""

from . import (continuous, discrete, math_blocks, nonlinear, sources,  # noqa: F401
               subsystem)
from ..block import block_types, by_category, create  # noqa: F401

__all__ = ["block_types", "by_category", "create"]
