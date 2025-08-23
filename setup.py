from setuptools import setup, find_packages

setup(
    name="rendergit",
    version="0.1.0",
    description="Flatten a GitHub repo into a single static HTML page for fast skimming and Ctrl+F",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    license="0BSD",
    author="Andrej Karpathy",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=[
        "markdown>=3.8.2",
        "pygments>=2.19.2",
        "mcp>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "rendergit=rendergit_package.rendergit:main",
            "rendergit-mcp=rendergit_package.mcp_server:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Utilities",
    ],
)