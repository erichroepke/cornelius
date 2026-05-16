"""Setup for the zeus_brain SDK.

Install editable from the repo root:
    pip install -e resources/brain-graph/sdk/
"""
from setuptools import setup, find_packages

setup(
    name="zeus-brain",
    version="0.1.0",
    description="Python SDK for the Brain Dependency Graph (Cornelius BDG + Neo4j)",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "neo4j>=5.20",
    ],
    extras_require={
        "dotenv": ["python-dotenv>=1.0"],
    },
)
