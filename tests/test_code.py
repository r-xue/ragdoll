"""Tests for Python AST code ingestion."""

from ragdoll.ingest.code import _extract_nodes


def test_extract_nodes():
    source = '''"""Module docstring."""

def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"

class Greeter:
    """A greeter class."""
    def greet(self):
        return "hi"
'''
    docs = _extract_nodes(source, "src/example.py")
    assert len(docs) == 3
    doc_types = {d.metadata["node_type"] for d in docs}
    assert doc_types == {"module_doc", "function", "class"}

    func_doc = next(d for d in docs if d.metadata["node_type"] == "function")
    assert func_doc.metadata["name"] == "hello"
    assert "def hello(name: str) -> str:" in func_doc.text

    class_doc = next(d for d in docs if d.metadata["node_type"] == "class")
    assert class_doc.metadata["name"] == "Greeter"
    assert "class Greeter:" in class_doc.text
