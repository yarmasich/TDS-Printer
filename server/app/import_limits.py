"""Per-workbook resource quotas, configurable with positive integer env values.

TDS_IMPORT_MAX_FILE_BYTES: 25 MiB compressed/uploaded bytes.
TDS_IMPORT_MAX_UNCOMPRESSED_BYTES: 100 MiB across all ZIP entries.
TDS_IMPORT_MAX_ARCHIVE_ENTRIES: 1,000 ZIP entries.
TDS_IMPORT_MAX_SHEETS: 100 worksheets.
TDS_IMPORT_MAX_ROWS: 100,000 visited rows (including blank/header rows).

Invalid configuration fails closed. Limits apply to uploads and server scans.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


class ImportLimitError(ValueError):
    """A workbook exceeds a configured resource quota."""


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(f'TDS_IMPORT_{name}', default))
    if value <= 0:
        raise ValueError(f'TDS_IMPORT_{name} must be a positive integer')
    return value


@dataclass(frozen=True)
class ImportLimits:
    file_bytes: int
    uncompressed_bytes: int
    archive_entries: int
    sheets: int
    rows: int

    @classmethod
    def from_env(cls) -> ImportLimits:
        return cls(
            _positive_int('MAX_FILE_BYTES', 25 * 1024 * 1024),
            _positive_int('MAX_UNCOMPRESSED_BYTES', 100 * 1024 * 1024),
            _positive_int('MAX_ARCHIVE_ENTRIES', 1000),
            _positive_int('MAX_SHEETS', 100),
            _positive_int('MAX_ROWS', 100000),
        )


def copy_upload(source: BinaryIO, target: BinaryIO, limits: ImportLimits) -> None:
    """Read at most the byte budget plus one sentinel byte, in bounded chunks."""
    total = 0
    while chunk := source.read(min(64 * 1024, limits.file_bytes - total + 1)):
        total += len(chunk)
        if total > limits.file_bytes:
            raise ImportLimitError(f'XLSX file size exceeds {limits.file_bytes} bytes')
        target.write(chunk)


def validate_archive(path: Path, limits: ImportLimits) -> None:
    """Check ZIP budgets before openpyxl materializes shared strings/styles.

    Also stream every member to validate actual decompression and CRC; bounded
    chunks avoid allocating a whole member during this preflight.
    """
    if path.stat().st_size > limits.file_bytes:
        raise ImportLimitError(f'XLSX file size exceeds {limits.file_bytes} bytes')
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > limits.archive_entries:
            raise ImportLimitError(f'XLSX archive entries exceed {limits.archive_entries}')
        if sum(entry.file_size for entry in entries) > limits.uncompressed_bytes:
            raise ImportLimitError(f'XLSX uncompressed size exceeds {limits.uncompressed_bytes} bytes')
        total = 0
        for entry in entries:
            if entry.flag_bits & 1 or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                raise ValueError("Encrypted or unsupported XLSX archive member")
            with archive.open(entry) as member:
                while chunk := member.read(min(64 * 1024, limits.uncompressed_bytes - total + 1)):
                    total += len(chunk)
                    if total > limits.uncompressed_bytes:
                        raise ImportLimitError(f'XLSX uncompressed size exceeds {limits.uncompressed_bytes} bytes')
