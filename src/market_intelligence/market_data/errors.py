from __future__ import annotations


class SeriesRevisionConflict(ValueError):
    """Provider changed a previously stored bar inside one immutable series."""

