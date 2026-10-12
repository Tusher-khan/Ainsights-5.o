"""Upload crash-safety: no orphaned files, friendly errors, no wasted memory.

These cover the gap that let the dev server die mid-upload instead of
returning a clean error: each pipeline stage in file_service.process_upload
now catches its own failures, logs which stage failed, and removes the file
it already wrote to disk rather than leaving it behind with no dataset record.
"""

from __future__ import annotations

import inspect
import io
from pathlib import Path
from unittest.mock import patch

import pytest
from werkzeug.datastructures import FileStorage

import app.files.csv_loader as csv_loader
from app.files.csv_loader import detect_encoding
from app.services import file_service
from app.utils.exceptions import FileProcessingError


def _file_storage(content: bytes, filename: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(content), filename=filename, content_type="text/csv")


def test_detect_encoding_does_not_read_the_whole_file_into_memory():
    # `Path.read_bytes()` would load the entire upload into memory just to
    # look at the first 200KB of it — real memory pressure on a large file,
    # right before pandas does its own full read of the same file. The fix
    # reads a bounded sample via open()+.read(n) instead; check the source
    # directly rather than mocking a method every Path instance shares
    # (which also fires on unrelated calls made by the test fixtures).
    source = inspect.getsource(csv_loader.detect_encoding)
    assert ".read_bytes(" not in source  # the call, not just a comment mentioning it
    assert ".read(200_000)" in source


def test_detect_encoding_still_works_correctly(tmp_path):
    path = tmp_path / "big.csv"
    path.write_text("a,b\n" + "1,2\n" * 500_000, encoding="utf-8")  # a few MB
    assert detect_encoding(path) in {"utf-8", "ascii"}


def test_process_upload_cleans_up_file_when_profiling_fails(tmp_path):
    storage = _file_storage(b"Country,Revenue\nUS,100\nDE,250\n", "orphan_test.csv")

    with patch.object(file_service, "build_profile", side_effect=RuntimeError("boom")):
        with pytest.raises(FileProcessingError) as exc_info:
            file_service.process_upload(storage)

    assert "could not be analyzed" in exc_info.value.user_message.lower()
    # The file saved by save_upload() before the failure must not be left behind.
    leftovers = list(Path(file_service.Config.UPLOAD_DIR).glob("orphan_test*"))
    assert leftovers == []


def test_process_upload_reports_memory_error_distinctly(tmp_path):
    storage = _file_storage(b"Country,Revenue\nUS,100\n", "oom_test.csv")

    with patch.object(file_service, "load_any", side_effect=MemoryError()):
        with pytest.raises(FileProcessingError) as exc_info:
            file_service.process_upload(storage)

    assert "memory" in exc_info.value.user_message.lower()
    leftovers = list(Path(file_service.Config.UPLOAD_DIR).glob("oom_test*"))
    assert leftovers == []


def test_process_upload_still_succeeds_on_the_happy_path(tmp_path):
    storage = _file_storage(b"Country,Revenue\nUS,100\nDE,250\n", "fine.csv")
    dataset = file_service.process_upload(storage)
    assert dataset["row_count"] == 2
    assert Path(dataset["file_path"]).exists()
