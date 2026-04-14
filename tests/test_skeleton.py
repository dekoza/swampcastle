import ast

import pytest
import yaml
from pathlib import Path
from swampcastle.mining.miner import mine
from swampcastle.mining.skeleton import PythonSkeletonExtractor, get_skeleton_extractor


def make_project(tmp_path: Path):
    cfg = {"wing": "test", "rooms": [{"name": "general", "description": "All files"}]}
    (tmp_path / ".swampcastle.yaml").write_text(yaml.dump(cfg))


def test_python_skeleton_extractor_logic():
    code = """
import os

class MyClass:
    def __init__(self, x):
        self.x = x
    
    def method_one(self):
        # implementation
        pass

def top_level_func(a, b):
    \"\"\"Docstring.\"\"\"
    return a + b
"""
    extractor = PythonSkeletonExtractor()
    skeleton = extractor.extract(code)

    assert "class MyClass:" in skeleton
    assert "def __init__(self, x):" in skeleton
    assert "def method_one(self):" in skeleton
    assert "def top_level_func(a, b):" in skeleton
    assert "# implementation" not in skeleton
    assert "return a + b" not in skeleton
    assert '"""Docstring."""' in skeleton


def test_skeleton_output_is_valid_python():
    """Extracted skeleton must be parseable as valid Python."""
    code = """
import os
from typing import Optional

MAX_RETRIES = 3
DEFAULT_TIMEOUT: int = 30

class MyClass:
    id: int
    name: str

    def __init__(self, x: int) -> None:
        self.x = x

    def method_one(self) -> Optional[str]:
        return None

def top_level_func(a: int, b: int) -> int:
    return a + b
"""
    extractor = PythonSkeletonExtractor()
    skeleton = extractor.extract(code)
    # Must not raise SyntaxError
    ast.parse(skeleton)


def test_skeleton_preserves_dataclass_fields():
    """Class-level annotated assignments (dataclass fields, TypedDict keys) must be preserved."""
    code = """
from dataclasses import dataclass

@dataclass
class User:
    id: int
    name: str
    email: str

    def greet(self) -> str:
        return f"Hello {self.name}"
"""
    extractor = PythonSkeletonExtractor()
    skeleton = extractor.extract(code)

    assert "id: int" in skeleton
    assert "name: str" in skeleton
    assert "email: str" in skeleton
    assert "return" not in skeleton
    ast.parse(skeleton)


def test_skeleton_preserves_decorators():
    """Decorators on classes and functions must be preserved."""
    code = """
import dataclasses

@dataclasses.dataclass
class Config:
    host: str
    port: int = 8080

@staticmethod
def helper():
    pass
"""
    extractor = PythonSkeletonExtractor()
    skeleton = extractor.extract(code)

    assert "@dataclasses.dataclass" in skeleton
    ast.parse(skeleton)


def test_skeleton_preserves_return_type_annotations():
    """Return type annotations must survive extraction."""
    code = """
from typing import Optional

def get_user(user_id: int) -> Optional[str]:
    return None
"""
    extractor = PythonSkeletonExtractor()
    skeleton = extractor.extract(code)

    assert "-> Optional[str]" in skeleton
    ast.parse(skeleton)


def test_skeleton_preserves_module_constants():
    """Module-level assignments and annotated constants must be preserved."""
    code = """
MAX_RETRIES = 3
TIMEOUT: int = 30
BASE_URL = 'https://api.example.com'

def fetch():
    return BASE_URL
"""
    extractor = PythonSkeletonExtractor()
    skeleton = extractor.extract(code)

    assert "MAX_RETRIES" in skeleton
    assert "TIMEOUT" in skeleton
    assert "return BASE_URL" not in skeleton
    ast.parse(skeleton)


def test_get_skeleton_extractor():
    assert isinstance(get_skeleton_extractor("test.py"), PythonSkeletonExtractor)
    assert get_skeleton_extractor("test.txt") is None


def test_miner_uses_skeleton(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    make_project(project)

    # Large python file > 2000 lines with substantial bodies (10 lines each)
    # so skeleton (definition + pass) reduces size by >50%.
    large_py = project / "large.py"
    func_blocks = []
    for i in range(300):
        body = "\n".join([f"    line_{j} = {j} * 2  # padding" for j in range(10)])
        func_blocks.append(f"def func_{i}(x, y=None):\n{body}\n    return x")
    large_py.write_text("\n\n".join(func_blocks))

    # Small python file
    (project / "small.py").write_text("def small(): pass")

    fake_coll = FakeCollection()
    fake_factory = FakeFactory(fake_coll)

    mine(str(project), str(tmp_path / "palace"), dry_run=False, storage_factory=fake_factory)

    skeleton_upserts = [
        up for up in fake_coll.upserts if any(m.get("is_skeleton") for m in up["metadatas"])
    ]
    assert len(skeleton_upserts) >= 1

    # Skeleton must omit bodies but retain all function names
    large_py_docs = []
    for up in fake_coll.upserts:
        for doc, meta in zip(up["documents"], up["metadatas"]):
            if meta.get("source_file") == str(large_py):
                large_py_docs.append(doc)

    full_skeleton = "\n".join(large_py_docs)
    assert "func_299" in full_skeleton
    assert "line_0 = 0 * 2" not in full_skeleton


class FakeCollection:
    def __init__(self):
        self.upserts = []

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def get(self, *, ids=None, where=None, limit=None, offset=None, include=None):
        return {"ids": [], "documents": [], "metadatas": []}

    def delete(self, *, ids=None, where=None):
        return None


class FakeFactory:
    def __init__(self, coll):
        self.coll = coll

    def open_collection(self, name):
        return self.coll
