"""
Session save / load.
====================
A session is the four block transfer functions plus enough metadata to warn
about a file from a different version. Kept deliberately small and explicit:
JSON that a human can read and edit by hand.
"""

from __future__ import annotations

from typing import Any

import control as ctl
import numpy as np

from .architecture import BLOCK_IDS, CourseArchitecture
from .tf_utils import from_coefficients

#: Bumped when the on-disk shape changes in a way older readers cannot handle.
SESSION_VERSION = 2


def session_dict(arch: CourseArchitecture) -> dict[str, Any]:
    """Serialise an architecture to a plain JSON-safe dict."""
    return {
        "format": "fakematlab-session",
        "version": SESSION_VERSION,
        "architecture": "course-2dof",
        "blocks": {
            bid: {
                "num": [float(c) for c in np.atleast_1d(arch.block_tf(bid).num[0][0])],
                "den": [float(c) for c in np.atleast_1d(arch.block_tf(bid).den[0][0])],
            }
            for bid in BLOCK_IDS
        },
    }


def load_session_dict(arch: CourseArchitecture, data: dict[str, Any]) -> None:
    """
    Load a session into an existing architecture, in place.

    Accepts both the v2 layout above and the v1 layout, which had the blocks
    at the top level with no version marker.

    Every block is validated before *any* is applied, so a corrupt file leaves
    the architecture exactly as it was rather than half-loaded.
    """
    blocks = data.get("blocks", data)      # v1 files had no "blocks" wrapper
    if not isinstance(blocks, dict):
        raise ValueError("not a FakeMatlab session: no block definitions found")

    version = data.get("version", 1)
    if version > SESSION_VERSION:
        raise ValueError(
            f"this session was written by a newer version "
            f"(file format {version}, this build reads {SESSION_VERSION})"
        )

    parsed: dict[str, ctl.TransferFunction] = {}
    for bid in BLOCK_IDS:
        entry = blocks.get(bid)
        if entry is None:
            continue
        try:
            num, den = entry["num"], entry["den"]
        except (TypeError, KeyError) as exc:
            raise ValueError(
                f"block {bid!r} is malformed: expected 'num' and 'den' "
                f"coefficient lists, got {entry!r}"
            ) from exc
        if not den or all(abs(float(c)) < 1e-300 for c in den):
            raise ValueError(f"block {bid!r} has an all-zero denominator")
        parsed[bid] = from_coefficients([float(c) for c in num],
                                        [float(c) for c in den])

    if not parsed:
        raise ValueError(
            f"no recognisable blocks in this file "
            f"(expected any of {', '.join(BLOCK_IDS)})"
        )

    for bid, tf in parsed.items():
        arch.set_block(bid, tf)


def architecture_from_session(data: dict[str, Any]) -> CourseArchitecture:
    """Build a fresh architecture from a session dict."""
    arch = CourseArchitecture()
    load_session_dict(arch, data)
    return arch
