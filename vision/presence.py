"""Turns tracks into the `presence` message (baseline 4.2 and 7.2)."""

from dataclasses import dataclass

from vision.track import Track


@dataclass(frozen=True)
class ZoneConfig:
    min_box_height_frac: float = 0.25
    approach_growth: float = 0.15
    approach_window_s: float = 1.5
    centre_band: float = 0.5
    mirror: bool = True

    @classmethod
    def from_config(cls, v: dict) -> "ZoneConfig":
        return cls(
            v["min_box_height_frac"],
            v["approach_growth"],
            v["approach_window_s"],
            v["centre_band"],
            v["mirror"],
        )


def _approaching(track: Track, now: float, zone: ZoneConfig) -> bool:
    window = [(t, h) for t, h in track.heights if now - t <= zone.approach_window_s]
    if len(window) < 3 or now - window[0][0] < zone.approach_window_s * 0.6:
        return False
    first, last = window[0][1], window[-1][1]
    return first > 0 and (last - first) / first >= zone.approach_growth


def presence(tracks: list[Track], frame_w: int, frame_h: int, zone: ZoneConfig, now: float) -> dict:
    out = []
    for t in tracks:
        b = t.box
        h = (b.y2 - b.y1) / frame_h
        cx = ((b.x1 + b.x2) / 2 / frame_w) * 2 - 1
        if h < zone.min_box_height_frac or abs(cx) > zone.centre_band:
            continue
        face_y = b.y1 + 0.2 * (b.y2 - b.y1)
        cy = (face_y / frame_h) * 2 - 1
        out.append(
            {
                "id": t.id,
                "cx": round(-cx if zone.mirror else cx, 3),
                "cy": round(cy, 3),
                "h": round(h, 3),
                "approaching": _approaching(t, now, zone),
            }
        )
    return {"ts": now, "count": len(out), "tracks": out}
