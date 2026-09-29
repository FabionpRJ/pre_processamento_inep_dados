#!/usr/bin/env python3
"""JSONs do Metadata Editor + censo.html + relatório — atalho para `python -m censo_etl gerar`, com os mesmos argumentos."""
import sys

from censo_etl.cli import main

sys.exit(main(["gerar", *sys.argv[1:]]))
