from vision.detect import Box
from vision.track import IouTracker


def box(x, h=100):
    return Box(x, 50, x + 40, 50 + h, 0.9)


def test_same_person_keeps_id_across_frames():
    t = IouTracker()
    a = t.update([box(100)], 0.0)
    b = t.update([box(104)], 0.125)
    assert a[0].id == b[0].id
    assert [h for _, h in b[0].heights] == [100, 100]


def test_new_person_gets_new_id():
    t = IouTracker()
    first = t.update([box(100)], 0.0)[0].id
    tracks = t.update([box(100), box(250)], 0.125)
    assert sorted(tr.id for tr in tracks) == [first, first + 1]


def test_track_survives_one_missed_frame():
    t = IouTracker(max_age_s=0.7)
    first = t.update([box(100)], 0.0)[0].id
    assert t.update([], 0.125) == []
    assert t.update([box(102)], 0.25)[0].id == first


def test_track_expires_after_max_age():
    t = IouTracker(max_age_s=0.7)
    first = t.update([box(100)], 0.0)[0].id
    t.update([], 1.0)
    assert t.update([box(100)], 1.1)[0].id != first


def test_height_history_is_trimmed():
    t = IouTracker(history_s=1.0)
    for i in range(20):
        tracks = t.update([box(100, h=100 + i)], i * 0.125)
    assert tracks[0].heights[0][0] >= 19 * 0.125 - 1.0
