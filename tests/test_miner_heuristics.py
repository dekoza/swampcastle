import pytest
from pathlib import Path

from swampcastle.mining import miner


def make_content(line_len=10, lines=10, whitespace_ratio=0.2):
    # create content with specified average line length roughly
    line = "a" * line_len
    return "\n".join(line for _ in range(lines))


def test_reject_long_line_unconditional():
    content = "a" * 501 + "\nrest"
    assert miner.is_probably_minified(Path("foo.js"), content) is True


def test_json_not_rejected_by_whitespace_heuristic():
    # minified-looking JSON: few spaces but no super-long line
    content = '{"key":"' + ('x' * 100) + '"}\n'
    assert miner.is_probably_minified(Path("data.json"), content) is False


def test_minified_js_rejected_by_whitespace():
    # simulate minified JS: very few whitespace
    content = "".join(["var a=0;" for _ in range(200)])
    assert miner.is_probably_minified(Path("app.js"), content) is True


def test_generated_signature_rejected():
    content = "/* For license information please see https://example.com */\ncode()"
    assert miner.is_probably_minified(Path("bundle.js"), content) is True


def test_minified_filename_rejected():
    content = "function good() { return 1 }\n" * 20
    assert miner.is_probably_minified(Path("app.min.js"), content) is True
