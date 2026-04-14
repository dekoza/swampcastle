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

    Preserves:
    - Imports
    - Module-level assignments and annotated assignments (constants, __all__)
    - Class and function definitions with decorators, signatures, return types
    - Class-level annotated assignments (dataclass fields, TypedDict keys)
    - Docstrings

    Drops function/method bodies.
    """

    def extract(self, code: str) -> str:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ""

        lines = []
        for node in tree.body:
            rendered = self._render_top_level(node)
            if rendered is not None:
                lines.append(rendered)
                lines.append("")
        return "\n".join(lines).strip()

    def _render_top_level(self, node) -> Optional[str]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return ast.unparse(node)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            return ast.unparse(node)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._render_node(node, level=0)
        return None

    def _render_node(self, node, level: int) -> str:
        indent = "    " * level
        lines = []

        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                lines.append(f"{indent}@{ast.unparse(dec)}")
            bases = [ast.unparse(b) for b in node.bases]
            bases_str = f"({', '.join(bases)})" if bases else ""
            lines.append(f"{indent}class {node.name}{bases_str}:")

            body_lines = []
            doc = ast.get_docstring(node)
            if doc:
                body_lines.append(f'{indent}    """{doc}"""')

            for child in node.body:
                if isinstance(child, ast.AnnAssign):
                    body_lines.append(f"{indent}    {ast.unparse(child)}")
                elif isinstance(child, ast.Assign):
                    body_lines.append(f"{indent}    {ast.unparse(child)}")
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    body_lines.append(self._render_node(child, level + 1))
                    body_lines.append("")

            if not body_lines:
                body_lines.append(f"{indent}    pass")
            lines.extend(body_lines)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                lines.append(f"{indent}@{ast.unparse(dec)}")
            is_async = isinstance(node, ast.AsyncFunctionDef)
            prefix = "async " if is_async else ""
            args = ast.unparse(node.args)
            returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            lines.append(f"{indent}{prefix}def {node.name}({args}){returns}:")

            doc = ast.get_docstring(node)
            if doc:
                lines.append(f'{indent}    """{doc}"""')
            else:
                lines.append(f"{indent}    pass")

        return "\n".join(lines)


class RegexSkeletonExtractor(SkeletonExtractor):
    """Regex-based skeleton extractor for languages without simple AST (JS/TS/etc).

    Extracts top-level class/function signatures using common patterns.
    Only captures signatures that appear at the start of a line (top-level).
    Returns empty string when no signatures match rather than an unusable fragment.
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
