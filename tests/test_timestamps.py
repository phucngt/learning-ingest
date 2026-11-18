import json

import pytest

from learning_ingest.extract import run_extract
from learning_ingest.timeutil import format_clock, format_srt, format_vtt, parse_timestamp, segment_id_for
from learning_ingest.transcript import build_segments, clip_cues, parse_subtitle_text
from conftest import FakeTranscriber, asr_manifest


@pytest.mark.parametrize("value,expected", [
    ("01:02:03.450", 3723450), ("01:02:03,450", 3723450),
    ("02:03.450", 123450), ("3723.45", 3723450), (62, 62000),
    (62.125, 62125), ("12:00:00.001", 43200001), ("00:00:00.1", 100),
])
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == expected


@pytest.mark.parametrize("value", [True, False, -1, -0.5, "-1", "00:60:00", "60:00", "00:00:60", "bad", "1:2:3:4"])
def test_bad_timestamp(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


@pytest.mark.parametrize("ms", [0, 1, 62125, 3723450, 43200001])
def test_format_round_trip(ms):
    assert parse_timestamp(format_vtt(ms)) == ms
    assert parse_timestamp(format_srt(ms)) == ms
    assert parse_timestamp(format_clock(ms)) == ms // 1000 * 1000


def test_segment_id():
    assert segment_id_for(723120) == "seg-001203-120"
    assert segment_id_for(3910500) == "seg-010510-500"


def test_vtt_and_srt():
    text = "WEBVTT\n\nNOTE\nComment only\n\ncue-id\n00:01:02.000 --> 00:01:09.800 align:start position:10%\n<v Teacher>Hello &amp; welcome</v>\nsecond line\n"
    assert parse_subtitle_text(text) == [(62000, 69800, "Hello & welcome second line")]
    assert parse_subtitle_text("1\n00:01:02,000 --> 00:01:09,800\n<i>Xin chào</i>\n") == [(62000, 69800, "Xin chào")]


def test_clip_preserves_original_times():
    assert clip_cues([(500, 1500, "cross"), (1500, 2500, "inside"), (3000, 4000, "out")], 1000, 3000) == [(500, 1500, "cross"), (1500, 2500, "inside")]


def test_build_sort_dedupe_and_suffix():
    segments = build_segments([
        (2000, 3000, "later"),
        (1000, 2000, " a  b "),
        (1000, 2000, "a b"),
        (1000, 2000, "a b"),
        (1000, 2200, "other"),
        (0, 100, " "),
    ])
    assert [(segment.segment_id, segment.text) for segment in segments] == [
        (segment_id_for(1000), "a b"),
        (segment_id_for(1000) + "-2", "other"),
        (segment_id_for(2000), "later"),
    ]


def test_asr_absolute_clip_chunks(tmp_path):
    fake = FakeTranscriber()
    out = tmp_path / "out"
    manifest = asr_manifest(tmp_path, declared_clip=False)
    run_extract(manifest, out, transcriber=fake, clip_start_ms=600_000,
                clip_end_ms=1_500_000, log=lambda _: None)
    assert fake.calls == [(600000, 1200000), (1200000, 1500000)]
    rows = [json.loads(line) for line in (out / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["segment_id"] for r in rows] == ["seg-001000-000", "seg-002000-000"]
    assert [r["start_ms"] for r in rows] == [600000, 1200000]
    assert all(r["segment_id"] == segment_id_for(r["start_ms"]) for r in rows)
