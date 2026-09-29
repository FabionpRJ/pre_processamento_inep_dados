#!/usr/bin/env python3
""".sav vazios a partir dos JSONs — atalho para `python -m censo_etl criar-sav-vazio`, com os mesmos argumentos."""
import sys

from censo_etl.cli import main

sys.exit(main(["criar-sav-vazio", *sys.argv[1:]]))
