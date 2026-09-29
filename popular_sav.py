#!/usr/bin/env python3
""".sav com os dados dos CSVs — atalho para `python -m censo_etl popular-sav`, com os mesmos argumentos."""
import sys

from censo_etl.cli import main

sys.exit(main(["popular-sav", *sys.argv[1:]]))
