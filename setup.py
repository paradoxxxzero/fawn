#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
fawn aka flask async uwsgi websocket postgresql notify is a flask extension
allowing websocket uwsgi broadcasting from postgresql notify channels.

"""

from setuptools import setup

VERSION = "1.0.0"

options = dict(
    name="fawn",
    version=VERSION,
    description="flask async uwsgi websocket postgresql notify",
    long_description=__doc__,
    author="Florian Mounier",
    author_email="paradoxxx.zero@gmail.com",
    license="MIT",
    platforms="Any",
    py_modules=['fawn'],
    provides=['fawn'],
    install_requires=['flask', 'uwsgi', 'sqlalchemy', 'psycopg2'],
    keywords=['flask', 'async', 'uwsgi', 'websocket', 'postgresql', 'notify'],
    url='https://github.com/paradoxxxzero/fawn',
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries :: Python Modules"])

setup(**options)
