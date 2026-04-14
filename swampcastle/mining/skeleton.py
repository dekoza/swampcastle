import ast
import re
from pathlib import Path
from typing import Optional


class SkeletonExtractor:
    """Base class for code skeleton extractors."""

    def extract(self, code: str) -> str:
        raise NotImplementedError


class PythonSkeletonExtractor(SkeletonExtractor):
    """AST-based Python skeleton extractor.

    Preserves imports, classes, functions, and their docstrings.
    Drops method/function bodies.
    """

    def extract(self, code: str) -> str:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Fallback for invalid syntax or files that don't look like python
            return ""

        lines = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                lines.append(ast.unparse(node))
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                lines.append(self._process_node(node, level=0))
                lines.append("")
        return "\n".join(lines).strip()

    def _process_node(self, node, level: int) -> str:
        indent = "    " * level
        lines = []

        if isinstance(node, ast.ClassDef):
            # Class signature: class X(Y):
            bases = [ast.unparse(b) for b in node.bases]
            bases_str = f"({', '.join(bases)})" if bases else ""
            lines.append(f"{indent}class {node.name}{bases_str}:")
            
            # process docstring
            doc = ast.get_docstring(node)
            if doc:
                lines.append(f'{indent}    """{doc}"""')
            
            # process children
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.append(self._process_node(child, level + 1))
                    lines.append("")
                elif isinstance(child, ast.ClassDef):
                    lines.append(self._process_node(child, level + 1))
                    lines.append("")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Function signature: [async] def X(Y):
            is_async = isinstance(node, ast.AsyncFunctionDef)
            prefix = "async " if is_async else ""
            args = ast.unparse(node.args)
            lines.append(f"{indent}{prefix}def {node.name}({args}):")
            
            # process docstring
            doc = ast.get_docstring(node)
            if doc:
                lines.append(f'{indent}    """{doc}"""')
            
            # No body: use pass if no docstring
            if not doc:
                lines.append(f"{indent}    pass")

        return "\n".join(lines).strip()


class RegexSkeletonExtractor(SkeletonExtractor):
    """Regex-based skeleton extractor for languages without simple AST (JS/TS/etc).

    Extracts class/function signatures using common patterns.
    """

    def __init__(self, patterns: list[str]):
        self.patterns = [re.compile(p, re.MULTILINE) for p in patterns]

    def extract(self, code: str) -> str:
        matches = []
        for p in self.patterns:
            for match in p.finditer(code):
                matches.append(match.group(0).strip())
        return "\n".join(matches)


# JS/TS signatures: function foo(), class Foo, const bar = () =>
JS_PATTERNS = [
    r"^(?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)",
    r"^(?:export\s+)?class\s+\w+\s*(?:extends\s+\w+)?",
    r"^(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
    r"^(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*function\s*\([^)]*\)",
]


def get_skeleton_extractor(filename: str) -> Optional[SkeletonExtractor]:
    """Return appropriate skeleton extractor based on filename extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".py":
        return PythonSkeletonExtractor()
    if ext in (".js", ".ts", ".jsx", ".tsx"):
        return RegexSkeletonExtractor(JS_PATTERNS)
    return None
