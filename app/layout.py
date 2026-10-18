"""Where text sits on a document: the boxes an OCR engine returns and how they relate in space.

Pure geometry with no OCR imports, so the parser built on it is unit-tested with hand-placed boxes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class TextBox:
    """One run of text the engine recognised, with its bounding box in pixels."""

    text: str
    left: float
    top: float
    right: float
    bottom: float
    # Recognition confidence, from 0 to 1
    score: float = 1.0

    @property
    def height(self) -> float:
        return self.bottom - self.top


class Direction(Enum):
    RIGHT = "right"
    BELOW = "below"
    ABOVE = "above"


# Words on a line are a few letters apart; lines of print are less than a line height apart
_MAX_GAP_IN_HEIGHTS = {Direction.RIGHT: 3.0, Direction.BELOW: 1.0, Direction.ABOVE: 1.0}


def _overlap(start: float, end: float, other_start: float, other_end: float) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))


def same_row(box: TextBox, other: TextBox) -> bool:
    """On one line of print: the boxes share at least half the height of the shorter one."""
    return _overlap(box.top, box.bottom, other.top, other.bottom) >= min(box.height, other.height) / 2


def same_column(box: TextBox, other: TextBox) -> bool:
    return _overlap(box.left, box.right, other.left, other.right) > 0


def gap(origin: TextBox, other: TextBox, direction: Direction) -> float | None:
    """Distance from origin to other in the direction, or None when other does not lie that way."""
    if direction is Direction.RIGHT:
        distance = other.left - origin.right if same_row(origin, other) else None
    elif direction is Direction.BELOW:
        distance = other.top - origin.bottom if same_column(origin, other) else None
    else:
        distance = origin.top - other.bottom if same_column(origin, other) else None
    # Boxes may touch or overlap slightly, but not lie on the wrong side
    if distance is None or distance < -origin.height / 2:
        return None
    return max(distance, 0.0)


def neighbours(origin: TextBox, boxes: list[TextBox], direction: Direction) -> Iterator[TextBox]:
    """Boxes close to origin in one direction, nearest first."""
    limit = origin.height * _MAX_GAP_IN_HEIGHTS[direction]
    near = [
        (distance, box)
        for box in boxes
        if box is not origin and (distance := gap(origin, box, direction)) is not None and distance <= limit
    ]
    yield from (box for _, box in sorted(near, key=lambda item: item[0]))


def rows(boxes: list[TextBox]) -> list[list[TextBox]]:
    """Groups boxes into lines of print, top to bottom, each read left to right."""
    lines: list[list[TextBox]] = []
    for box in sorted(boxes, key=lambda box: (box.top + box.bottom) / 2):
        if lines and any(same_row(box, other) for other in lines[-1]):
            lines[-1].append(box)
        else:
            lines.append([box])
    return [sorted(line, key=lambda box: box.left) for line in lines]
