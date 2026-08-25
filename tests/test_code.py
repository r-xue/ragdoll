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
    all_docs = ingest_code([tmp_path])
    assert len(all_docs) >= 4
    all_langs = {d.metadata["language"] for d in all_docs}
    assert {"python", "cpp", "fortran", "shell"}.issubset(all_langs)

    # Ingest with extension filter
    filtered_docs = ingest_code([tmp_path], extensions={".cpp", ".f90"})
    filtered_langs = {d.metadata["language"] for d in filtered_docs}
    assert filtered_langs == {"cpp", "fortran"}

def test_extract_latex_and_markdown(tmp_path: Path):
    (tmp_path / "paper.tex").write_text(r"\documentclass{article}\n\begin{document}\nHello LaTeX!\n\end{document}\n")
    (tmp_path / "spec.md").write_text("# Design Spec\n\nThis is a markdown specification.\n")
    (tmp_path / "refs.bib").write_text("@article{key,\n  title={Sample}\n}\n")

    docs = ingest_code([tmp_path])
    assert len(docs) >= 3
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
