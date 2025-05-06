from setuptools import setup, find_packages

setup(
    name="chutes-miner-cli",
    version="0.0.15",
    description="Chutes miner CLI",
    long_description="Command line interface for managing chutes miners -- add/delete nodes, etc.",
    long_description_content_type="text/markdown",
    url="https://github.com/rayonlabs/chutes-miner/tree/main/cli",
    author="Jon Durbin",
    license_expression="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "aiohttp[speedups]>=3.10,<4",
        "loguru==0.7.2",
        "pydantic>=2.9,<3",
        "setuptools>=0.75",
        "substrate-interface>=1.7.10",
        "rich>=13.0.0",
        "typer>=0.12.5",
    ],
    extras_require={
        "dev": [
            "ruff",
            "wheel",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.10",
    ],
    entry_points={
        "console_scripts": [
            "chutes-miner=chutes_miner.cli:app",
        ],
    },
)
