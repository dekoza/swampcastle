"""Tests for swampcastle.errors — exception hierarchy."""

from swampcastle.errors import (
    CastleError,
    EmbedderError,
    NoCastleError,
    StorageError,
    SyncConflictError,
    ValidationError,
)


class TestCastleErrorHierarchy:
    def test_all_subclass_castle_error(self):
        for cls in (NoCastleError, StorageError, ValidationError,
                    EmbedderError, SyncConflictError):
            assert issubclass(cls, CastleError)

    def test_all_subclass_exception(self):
        for cls in (CastleError, NoCastleError, StorageError):
            assert issubclass(cls, Exception)

    def test_each_has_distinct_code(self):
        codes = set()
        for cls in (CastleError, NoCastleError, StorageError,
                    ValidationError, EmbedderError, SyncConflictError):
            codes.add(cls.code)
        assert len(codes) == 6

    def test_str_preserves_message(self):
        err = NoCastleError("castle not found at /x")
        assert "castle not found at /x" in str(err)

    def test_catch_by_base(self):
        with __import__("pytest").raises(CastleError):
            raise StorageError("disk full")

    def test_code_attribute(self):
        assert NoCastleError.code == "NO_CASTLE"
        assert StorageError.code == "STORAGE"
        assert ValidationError.code == "VALIDATION"
        assert EmbedderError.code == "EMBEDDER"
        assert SyncConflictError.code == "SYNC_CONFLICT"
