from collections import deque

from vision.detect import Box
from vision.presence import ZoneConfig, presence
from vision.track import Track

ZONE = ZoneConfig(
    min_box_height_frac=0.25,
    approach_growth=0.15,
    approach_window_s=1.5,
    centre_band=0.5,
    mirror=False,
)


def track(tid, x1, x2, heights, now):
    """heights: box heights in pixels over time, newest last, one every 0.25 s."""
    h = heights[-1]
    t = Track(tid, Box(x1, 240 - h, x2, 240, 0.9), now)
    t.heights = deque((now - 0.25 * (len(heights) - 1 - i), hh) for i, hh in enumerate(heights))
    return t


def test_small_far_person_is_not_in_zone():
    p = presence([track(1, 150, 170, [40], 10.0)], 320, 240, ZONE, 10.0)
    assert p["count"] == 0


def test_people_outside_centre_band_are_not_in_zone():
    p = presence([track(1, 0, 40, [120], 10.0)], 320, 240, ZONE, 10.0)
    assert p["count"] == 0


def test_close_centred_person_is_in_zone_with_gaze():
    p = presence([track(1, 140, 180, [120] * 7, 10.0)], 320, 240, ZONE, 10.0)
    assert p["count"] == 1
    t = p["tracks"][0]
    assert t["approaching"] is False
    assert t["cx"] == 0.0
    assert t["h"] == 0.5
    # gaze aims at the face area: 20% down from the top of the box (y = 120 + 24 = 144)
    assert t["cy"] == 0.2


def test_growing_box_is_approaching():
    p = presence([track(1, 140, 180, [70, 75, 80, 88, 95, 100, 110], 10.0)], 320, 240, ZONE, 10.0)
    assert p["tracks"][0]["approaching"] is True


def test_short_history_is_not_approaching_yet():
    p = presence([track(1, 140, 180, [70, 100], 10.0)], 320, 240, ZONE, 10.0)
    assert p["tracks"][0]["approaching"] is False


def test_mirror_flips_gaze():
    zone = ZoneConfig(0.25, 0.15, 1.5, 0.8, mirror=True)
    p = presence([track(1, 200, 240, [120], 10.0)], 320, 240, zone, 10.0)
    assert p["tracks"][0]["cx"] < 0
