from setuptools import setup, find_packages
import os

long_description = """SherlockFog: Setup Random Topology on Commodity Hardware"""

setup(
    name = "sherlockfog",
    version = "2.0",
    author = "Maximiliano Geier",
    author_email = "mgeier@dc.uba.ar",
    url = "https://gitlab.licar.exp.dc.uba.ar/sherlockfog/sherlockfog/",
    description = "SherlockFog",
    long_description = long_description,
    license = "GPL3",
    platforms = ['linux'],

    classifiers = [
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Network Researchers",
        "License :: OSI Approved :: GNU General Public License (GPL)",
        "Operating System :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: System :: Networking",
        ],

    packages=find_packages(exclude=['sherlockfog', 'setuptopo', 'test']),
    scripts=[os.path.join("bin", p) for p in ["sherlockfog"]],
    data_files=[('helpers/', ['helpers/ns-sshd'])],

    install_requires=[
        'pexpect',
        'matplotlib',
        'networkx>=2.0',
        'paramiko>=2.7',
    ]
)
