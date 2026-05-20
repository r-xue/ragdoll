# Sphinx configuration for Ragdoll documentation.
#
# For a full list of options see:
#   https://www.sphinx-doc.org/en/master/usage/configuration.html

import importlib.metadata

# -- Project information -----------------------------------------------------

project = "Ragdoll"
copyright = "2026, Rui Xue"
author = "Rui Xue"
release = importlib.metadata.version("ragdoll")

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

# MyST-Parser settings (allows Markdown in Sphinx).
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "tasklist",
]
myst_heading_anchors = 3

# Autodoc settings.
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autosummary_generate = True

# Napoleon settings (Google / NumPy docstrings).
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_use_param = True
napoleon_use_rtype = True

# Intersphinx mapping.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# Source file suffixes.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------

html_theme = "furo"
html_title = "🧶 Ragdoll"
html_static_path = ["_static"]
html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#6C5CE7",
        "color-brand-content": "#6C5CE7",
    },
    "dark_css_variables": {
        "color-brand-primary": "#A29BFE",
        "color-brand-content": "#A29BFE",
    },
}
