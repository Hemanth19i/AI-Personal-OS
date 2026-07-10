"""Behaviour tests for workspace export/import (T6.3).

Real SQLiteStorage (lightweight, no external binary) and real filesystem
directories standing in for the LanceDB vector store — vector_store.py itself
is never imported here (backup.py never touches the LanceDB client), so a
handful of plain files in a temp "vectors" directory is a faithful stand-in
for what export/import actually operate on (raw bytes on disk).
"""

import tempfile
import unittest
import zipfile
from pathlib import Path

from aipos.backup import export_workspace, import_workspace
from aipos.storage import DEFAULT_WORKSPACE_ID, SQLiteStorage


def _make_vector_files(root: Path, contents: dict[str, bytes]) -> None:
    """Create a stand-in LanceDB directory with the given relative files."""
    for relative, data in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class ExportWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = SQLiteStorage(self.root / "aipos.db")
        self.storage.connect()
        self.vectors_dir = self.root / "vectors"

    def tearDown(self) -> None:
        self.storage.close()
        self._tmp.cleanup()

    def test_rejects_unknown_workspace(self) -> None:
        with self.assertRaises(ValueError):
            export_workspace(
                "not-default", self.storage, self.vectors_dir, self.root / "out.zip"
            )

    def test_creates_a_zip_archive(self) -> None:
        destination = self.root / "backup.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, self.storage, self.vectors_dir, destination)
        self.assertTrue(destination.exists())
        self.assertTrue(zipfile.is_zipfile(destination))

    def test_archive_contains_the_database_member(self) -> None:
        self.storage.add_file(path="/a.pdf", file_hash="h1")
        destination = self.root / "backup.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, self.storage, self.vectors_dir, destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertIn("aipos.db", archive.namelist())

    def test_archive_contains_vector_directory_contents(self) -> None:
        _make_vector_files(self.vectors_dir, {"chunk_vectors.lance/data.bin": b"vec-bytes"})
        destination = self.root / "backup.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, self.storage, self.vectors_dir, destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertIn("vectors/chunk_vectors.lance/data.bin", archive.namelist())
            self.assertEqual(
                archive.read("vectors/chunk_vectors.lance/data.bin"), b"vec-bytes"
            )

    def test_missing_vector_directory_still_exports_the_database(self) -> None:
        # No vectors/ ever created (e.g. nothing was ever ingested) — export
        # must not fail, and must simply omit vector entries.
        destination = self.root / "backup.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, self.storage, self.vectors_dir, destination)
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
            self.assertIn("aipos.db", names)
            self.assertFalse(any(n.startswith("vectors/") for n in names))

    def test_creates_destination_parent_directory(self) -> None:
        destination = self.root / "nested" / "dir" / "backup.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, self.storage, self.vectors_dir, destination)
        self.assertTrue(destination.exists())

    def test_exported_database_is_independently_openable_and_matches_source(self) -> None:
        # The SQLite backup round-trip: the archived db, opened on its own,
        # must contain exactly the same rows as the live source.
        file_id = self.storage.add_file(path="/a.pdf", file_hash="h1")
        destination = self.root / "backup.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, self.storage, self.vectors_dir, destination)

        extract_dir = self.root / "extracted"
        with zipfile.ZipFile(destination) as archive:
            archive.extractall(extract_dir)

        copy = SQLiteStorage(extract_dir / "aipos.db")
        copy.connect()
        try:
            record = copy.get_file(file_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.path, "/a.pdf")
            self.assertEqual(record.hash, "h1")
        finally:
            copy.close()

    def test_export_does_not_mutate_the_source_database(self) -> None:
        self.storage.add_file(path="/a.pdf", file_hash="h1")
        before = self.storage.get_file_by_hash("h1")
        export_workspace(DEFAULT_WORKSPACE_ID, self.storage, self.vectors_dir, self.root / "out.zip")
        after = self.storage.get_file_by_hash("h1")
        self.assertEqual(before, after)


class ImportWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _export_fixture_archive(self, *, with_vectors: bool = True) -> Path:
        """Build a real export archive to use as an import fixture."""
        source_storage = SQLiteStorage(self.root / "source.db")
        source_storage.connect()
        source_storage.add_file(path="/a.pdf", file_hash="h1")
        source_vectors = self.root / "source_vectors"
        if with_vectors:
            _make_vector_files(source_vectors, {"table.lance/data.bin": b"vec-bytes"})
        archive_path = self.root / "backup.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, source_storage, source_vectors, archive_path)
        source_storage.close()
        return archive_path

    def test_round_trip_restores_database_rows(self) -> None:
        archive_path = self._export_fixture_archive()
        target_db = self.root / "clean" / "aipos.db"
        target_vectors = self.root / "clean" / "vectors"

        import_workspace(archive_path, target_db, target_vectors)

        restored = SQLiteStorage(target_db)
        restored.connect()
        try:
            record = restored.get_file_by_hash("h1")
            self.assertIsNotNone(record)
            self.assertEqual(record.path, "/a.pdf")
        finally:
            restored.close()

    def test_round_trip_restores_vector_directory(self) -> None:
        archive_path = self._export_fixture_archive(with_vectors=True)
        target_db = self.root / "clean" / "aipos.db"
        target_vectors = self.root / "clean" / "vectors"

        import_workspace(archive_path, target_db, target_vectors)

        restored_file = target_vectors / "table.lance" / "data.bin"
        self.assertTrue(restored_file.exists())
        self.assertEqual(restored_file.read_bytes(), b"vec-bytes")

    def test_import_with_no_vectors_in_archive_creates_empty_directory(self) -> None:
        archive_path = self._export_fixture_archive(with_vectors=False)
        target_db = self.root / "clean" / "aipos.db"
        target_vectors = self.root / "clean" / "vectors"

        import_workspace(archive_path, target_db, target_vectors)

        self.assertTrue(target_vectors.is_dir())
        self.assertEqual(list(target_vectors.iterdir()), [])

    def test_refuses_when_database_already_exists(self) -> None:
        archive_path = self._export_fixture_archive()
        target_db = self.root / "clean" / "aipos.db"
        target_vectors = self.root / "clean" / "vectors"
        target_db.parent.mkdir(parents=True, exist_ok=True)
        target_db.write_bytes(b"already here")

        with self.assertRaises(RuntimeError):
            import_workspace(archive_path, target_db, target_vectors)

        # Refusal must not touch the existing file.
        self.assertEqual(target_db.read_bytes(), b"already here")

    def test_refuses_when_vector_directory_already_has_data(self) -> None:
        archive_path = self._export_fixture_archive()
        target_db = self.root / "clean" / "aipos.db"
        target_vectors = self.root / "clean" / "vectors"
        _make_vector_files(target_vectors, {"existing.bin": b"pre-existing"})

        with self.assertRaises(RuntimeError):
            import_workspace(archive_path, target_db, target_vectors)

        self.assertFalse(target_db.exists())  # db was never written either

    def test_empty_existing_vector_directory_does_not_block_import(self) -> None:
        # An empty, freshly-created directory (e.g. from ensure_app_directories)
        # is not "existing data" and must not trigger a refusal.
        archive_path = self._export_fixture_archive()
        target_db = self.root / "clean" / "aipos.db"
        target_vectors = self.root / "clean" / "vectors"
        target_vectors.mkdir(parents=True)  # exists, but empty

        import_workspace(archive_path, target_db, target_vectors)  # must not raise

        self.assertTrue(target_db.exists())

    def test_invalid_archive_raises_value_error(self) -> None:
        bogus = self.root / "not-a-workspace.zip"
        with zipfile.ZipFile(bogus, "w") as archive:
            archive.writestr("readme.txt", "not a workspace export")
        target_db = self.root / "clean" / "aipos.db"
        target_vectors = self.root / "clean" / "vectors"

        with self.assertRaises(ValueError):
            import_workspace(bogus, target_db, target_vectors)


class ExportImportRoundTripTests(unittest.TestCase):
    """End-to-end: export a populated workspace, import into a clean install,
    and confirm the restored install is fully, independently queryable."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_full_round_trip_into_a_clean_temporary_install(self) -> None:
        original_install = self.root / "original"
        storage = SQLiteStorage(original_install / "aipos.db")
        storage.connect()
        file_id = storage.add_file(path="/docs/a.pdf", file_hash="abc123")
        storage.update_status(file_id, storage.get_file(file_id).status)  # no-op touch
        vectors_dir = original_install / "vectors"
        _make_vector_files(vectors_dir, {"chunk_vectors.lance/manifest.json": b"{}"})

        archive_path = self.root / "exported.zip"
        export_workspace(DEFAULT_WORKSPACE_ID, storage, vectors_dir, archive_path)
        storage.close()

        clean_install = self.root / "clean_install"
        clean_db = clean_install / "aipos.db"
        clean_vectors = clean_install / "vectors"
        self.assertFalse(clean_db.exists())  # genuinely a clean install

        import_workspace(archive_path, clean_db, clean_vectors)

        restored = SQLiteStorage(clean_db)
        restored.connect()
        try:
            record = restored.get_file(file_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.path, "/docs/a.pdf")
            self.assertEqual(record.hash, "abc123")
        finally:
            restored.close()
        self.assertEqual(
            (clean_vectors / "chunk_vectors.lance" / "manifest.json").read_bytes(), b"{}"
        )


if __name__ == "__main__":
    unittest.main()
