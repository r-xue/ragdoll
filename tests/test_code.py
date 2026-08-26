"""Tests for multi-language source code ingestion."""

from pathlib import Path
from ragdoll.ingest.code import _extract_nodes, ingest_code


def test_extract_python_nodes():
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
    assert func_doc.metadata["language"] == "python"
    assert "def hello(name: str) -> str:" in func_doc.text

    class_doc = next(d for d in docs if d.metadata["node_type"] == "class")
    assert class_doc.metadata["name"] == "Greeter"
    assert class_doc.metadata["language"] == "python"
    assert "class Greeter:" in class_doc.text


def test_extract_cpp_nodes():
    source = '''#include <iostream>
#include <vector>

class ImageCleaner {
public:
    ImageCleaner(int niter) : niter_(niter) {}
    void clean();
private:
    int niter_;
};

void ImageCleaner::clean() {
    std::cout << "Cleaning..." << std::endl;
}

double calculate_distance(double x1, double y1, double x2, double y2) {
    double dx = x2 - x1;
    double dy = y2 - y1;
    return dx * dx + dy * dy;
}
'''
    # Test with chunk_size small enough to trigger block extraction
    docs = _extract_nodes(source, "src/cleaner.cpp", chunk_size=100)
    assert len(docs) >= 2
    languages = {d.metadata["language"] for d in docs}
    assert languages == {"cpp"}

    names = {d.metadata["name"] for d in docs}
    assert "ImageCleaner" in names


def test_extract_fortran_nodes():
    source = '''subroutine matrix_mult(a, b, c, n)
    integer, intent(in) :: n
    real, intent(in) :: a(n,n), b(n,n)
    real, intent(out) :: c(n,n)
    c = 0.0
end subroutine matrix_mult

real function dot_product(x, y, n)
    integer, intent(in) :: n
    real, intent(in) :: x(n), y(n)
    dot_product = sum(x * y)
end function dot_product
'''
    docs = _extract_nodes(source, "src/math.f90", chunk_size=100)
    assert len(docs) >= 1
    languages = {d.metadata["language"] for d in docs}
    assert languages == {"fortran"}


def test_extract_generic_nodes():
    source = '''#!/usr/bin/env bash
set -euo pipefail

echo "Deploying service..."
docker compose up -d
'''
    docs = _extract_nodes(source, "scripts/deploy.sh")
    assert len(docs) == 1
    assert docs[0].metadata["language"] == "shell"
    assert docs[0].metadata["source"] == "code"


def test_ingest_code_filtering(tmp_path: Path):
    # Create sample files
    (tmp_path / "main.py").write_text("def run(): pass\n")
    (tmp_path / "util.cpp").write_text("void init() {}\n")
    (tmp_path / "calc.f90").write_text("subroutine calc() \nend subroutine calc\n")
    (tmp_path / "build.sh").write_text("echo 'building'\n")
    (tmp_path / "ignore.bin").write_bytes(b"\x00\x01\x02")

    # Ingest all supported
    all_docs, skipped = ingest_code([tmp_path])
    assert len(all_docs) >= 4
    assert skipped == 0
    all_langs = {d.metadata["language"] for d in all_docs}
    assert {"python", "cpp", "fortran", "shell"}.issubset(all_langs)

    # Ingest with extension filter
    filtered_docs, _ = ingest_code([tmp_path], extensions={".cpp", ".f90"}, force=True)
    filtered_langs = {d.metadata["language"] for d in filtered_docs}
    assert filtered_langs == {"cpp", "fortran"}

def test_extract_latex_and_markdown(tmp_path: Path):
    (tmp_path / "paper.tex").write_text(r"\documentclass{article}\n\begin{document}\nHello LaTeX!\n\end{document}\n")
    (tmp_path / "spec.md").write_text("# Design Spec\n\nThis is a markdown specification.\n")
    (tmp_path / "refs.bib").write_text("@article{key,\n  title={Sample}\n}\n")

    docs, skipped = ingest_code([tmp_path])
    assert len(docs) >= 3
    assert skipped == 0
    langs = {d.metadata["language"] for d in docs}
    assert {"latex", "markdown", "bibtex"}.issubset(langs)


def test_extract_python_nodes_suppresses_syntax_warnings():
    # Source with legacy unescaped regex characters (which trigger SyntaxWarning in Python 3.12+)
    source = r"""
def clean_names(val):
    field = '3,4C\*'
    antPat = '^VA\d+$'
    pattern = "^.+(\,.+)+$"
    return field
"""
    docs = _extract_nodes(source, "src/casa_cleaner.py")
    assert len(docs) >= 1
    func_doc = next(d for d in docs if d.metadata["node_type"] == "function")
    assert func_doc.metadata["name"] == "clean_names"


def test_ingest_code_incremental(tmp_path: Path):
    from unittest.mock import MagicMock, patch
    from ragdoll.ingest.code import _compute_file_hash

    f1 = tmp_path / "mod1.py"
    f1.write_text("def fn1(): pass\n")
    h1 = _compute_file_hash(f1)

    f2 = tmp_path / "mod2.py"
    f2.write_text("def fn2(): pass\n")

    with patch("ragdoll.store.vectordb._get_client") as mock_client:
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "ids": ["code:dummy"],
            "metadatas": [{"file_hash": h1}],
        }
        mock_client.return_value.get_or_create_collection.return_value = mock_col

        docs, skipped = ingest_code([tmp_path])
        assert skipped == 1
        assert len(docs) >= 1
        assert docs[0].metadata["name"] == "fn2"


def test_ingest_code_paginated_hash_lookup(tmp_path: Path):
    from unittest.mock import MagicMock, patch
    from ragdoll.ingest.code import _compute_file_hash

    f1 = tmp_path / "mod1.py"
    f1.write_text("def fn1(): pass\n")
    h1 = _compute_file_hash(f1)

    f2 = tmp_path / "mod2.py"
    f2.write_text("def fn2(): pass\n")
    h2 = _compute_file_hash(f2)

    with patch("ragdoll.store.vectordb._get_client") as mock_client:
        mock_col = MagicMock()
        # Simulate 2 pages of results: page 1 has 2000 items, page 2 has 1 item
        page1_metas = [{"file_hash": f"hash_{i}"} for i in range(2000)]
        page1_metas.append({"file_hash": h1})
        page2_metas = [{"file_hash": h2}]

        def side_effect(where=None, include=None, limit=None, offset=0):
            if offset == 0:
                return {"metadatas": page1_metas[:2000]}
            elif offset == 2000:
                return {"metadatas": page1_metas[2000:] + page2_metas}
            return {"metadatas": []}

        mock_col.get.side_effect = side_effect
        mock_client.return_value.get_or_create_collection.return_value = mock_col

        docs, skipped = ingest_code([tmp_path])
        assert skipped == 2
        assert len(docs) == 0

