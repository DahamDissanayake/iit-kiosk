"""Minimal IoU tracker: enough for the few people in front of a kiosk."""

from collections import deque
from dataclasses import dataclass, field

from vision.detect import Box


@dataclass
class Track:
    id: int
    box: Box
    last_seen: float
    heights: deque = field(default_factory=deque)


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0 else 0.0


class IouTracker:
    def __init__(self, iou_min: float = 0.3, max_age_s: float = 0.7, history_s: float = 3.0):
        self.iou_min = iou_min
        self.max_age_s = max_age_s
        self.history_s = history_s
        self.tracks: list[Track] = []
        self._next_id = 1

    def update(self, boxes: list[Box], now: float) -> list[Track]:
        self.tracks = [t for t in self.tracks if now - t.last_seen <= self.max_age_s]
        pairs = sorted(
            (
                (iou(t.box, b), ti, bi)
                for ti, t in enumerate(self.tracks)
                for bi, b in enumerate(boxes)
            ),
            reverse=True,
        )
        used_t, used_b = set(), set()
        for score, ti, bi in pairs:
            if score < self.iou_min:
                break
            if ti in used_t or bi in used_b:
                continue
            used_t.add(ti)
            used_b.add(bi)
            self._observe(self.tracks[ti], boxes[bi], now)
        for bi, b in enumerate(boxes):
            if bi not in used_b:
                track = Track(self._next_id, b, now)
                self._next_id += 1
                self._observe(track, b, now)
                self.tracks.append(track)
        return [t for t in self.tracks if t.last_seen == now]

    def _observe(self, track: Track, box: Box, now: float) -> None:
        track.box = box
        track.last_seen = now
        track.heights.append((now, box.y2 - box.y1))
        while track.heights and now - track.heights[0][0] > self.history_s:
            track.heights.popleft()
