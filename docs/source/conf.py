from pathlib import Path
import os
import sys
import django

sys.path.insert(0, str(Path("..", "..").resolve()))
os.environ["DJANGO_SETTINGS_MODULE"] = "instance.settings"
django.setup()

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Django-Caps"
copyright = "2025, Thomas"
author = "Thomas"
release = "1.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx_autodoc_typehints",
    "sphinx_rtd_theme",
]

templates_path = ["_templates"]
exclude_patterns = []

add_module_names = False
autodoc_typehints = "description"

root_doc = "index"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# html_theme = 'alabaster'
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

suppress_warnings = ["misc.highlighting_failure"]


# -- Types alias
autodoc_type_aliases = {
    "CanOne": "CanOne",
    "CanMany": "CanMany",
}

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "typed-members": True,
}
