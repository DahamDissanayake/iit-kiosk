import numpy as np
import pytest

from voice.wav import mix_at_snr, read_wav, write_wav


def test_wav_round_trip(tmp_path):
    audio = (np.sin(np.linspace(0, 200, 16000)) * 0.5).astype(np.float32)
    path = tmp_path / "a.wav"
    write_wav(path, audio)
    back = read_wav(path)
    assert back.dtype == np.float32
    assert np.max(np.abs(back - audio)) < 1e-3


def test_other_sample_rates_are_rejected(tmp_path):
    path = tmp_path / "b.wav"
    write_wav(path, np.zeros(100, np.float32), rate=44100)
    with pytest.raises(ValueError, match="16000"):
        read_wav(path)


def test_mix_at_snr_sets_noise_level():
    rng = np.random.default_rng(0)
    clean = rng.standard_normal(16000).astype(np.float32) * 0.1
    noise = rng.standard_normal(8000).astype(np.float32)
    mixed = mix_at_snr(clean, noise, snr_db=10)
    added = mixed - clean
    snr = 10 * np.log10(np.mean(clean**2) / np.mean(added**2))
    assert len(mixed) == len(clean)
    assert abs(snr - 10) < 0.5
