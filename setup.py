from __future__ import annotations

import re
from pathlib import Path

from setuptools import find_namespace_packages, setup


source = Path("fluxer/ext/menus/__init__.py").read_text(encoding="utf-8")
match = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', source, re.MULTILINE)
if match is None:
    raise RuntimeError("version is not set")


setup(
    name="fluxer-ext-menus",
    author="Fer2G",
    version=match.group(1),
    packages=find_namespace_packages(include=["fluxer.ext.menus"]),
    url="https://github.com/FluxerDevs/fluxer-ext-menus",
    license="None-Yet",
    description="Reaction-based menu helpers for fluxer.py",
    long_description=Path("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    install_requires=["fluxer.py>=0.4.2"],
    python_requires=">=3.14",
)
