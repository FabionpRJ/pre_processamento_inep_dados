"""Ferramentas standalone de `.sav`, fora do serviço: partem dos JSONs gerados
e, para popular, dos CSVs de microdados.

Toda largura do formato SPSS é medida em BYTES; todo `tamanho` do dicionário
do INEP, em caracteres. Com acentos os dois divergem — ver docs/operacao.md.
"""
import pandas as pd

# Com as strings apoiadas em pyarrow (padrão do pandas 3) a gravação com
# pyreadstat já deu segfault em libarrow.so. Não remover.
pd.set_option("future.infer_string", False)
