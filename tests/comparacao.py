"""Compara pastas de saída do pipeline (referência × nova).

JSONs e app-data do censo.html como objeto (inclusive ordem das chaves) e em
bytes; relatório em bytes; caches só em `dados`; logs só pelos avisos.

    python tests/comparacao.py <pasta_referencia> <pasta_nova>
"""
import json
import re
import sys
from pathlib import Path

APP = re.compile(r'(<script id="app-data" type="application/json">)(.*?)(</script>)', re.S)


def primeira_diferenca(a, b, caminho="$"):
    if type(a) is not type(b):
        return f"{caminho}: tipo {type(a).__name__} × {type(b).__name__}"
    if isinstance(a, dict):
        if list(a) != list(b):
            return f"{caminho}: chaves {list(a)[:8]} × {list(b)[:8]}"
        for k in a:
            if (d := primeira_diferenca(a[k], b[k], f"{caminho}.{k}")):
                return d
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{caminho}: len {len(a)} × {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            if (d := primeira_diferenca(x, y, f"{caminho}[{i}]")):
                return d
    elif a != b:
        return f"{caminho}: {str(a)[:120]!r} × {str(b)[:120]!r}"
    return None


def avisos(texto: str) -> list[str]:
    """Linhas de aviso, sem etiqueta, caixa, espaço extra nem caminho absoluto."""
    saida = []
    for linha in texto.splitlines():
        if not re.search(r"\[aviso\]", linha, re.I):
            continue
        linha = re.sub(r"^.*?\[aviso\]\s*", "", linha, flags=re.I)
        linha = re.sub(r'"/[^"]*"', '"<caminho>"', linha)
        saida.append(" ".join(linha.lower().split()))
    return sorted(saida)


def comparar(ref: Path, nova: Path, somente: set[str] | None = None) -> list[str]:
    """Diferenças entre os cenários de `ref` e os de mesmo nome em `nova`."""
    problemas: list[str] = []
    for pasta_ref in sorted(p for p in ref.iterdir() if p.is_dir()):
        if somente is not None and pasta_ref.name not in somente:
            continue
        pasta_nova = nova / pasta_ref.name
        if not pasta_nova.is_dir():
            problemas.append(f"{pasta_ref.name}: cenário ausente")
            continue
        arqs_ref = {p.name for p in pasta_ref.iterdir()}
        arqs_nova = {p.name for p in pasta_nova.iterdir()}
        if arqs_ref != arqs_nova:
            problemas.append(f"{pasta_ref.name}: arquivos {sorted(arqs_ref ^ arqs_nova)}")
        for nome in sorted(arqs_ref & arqs_nova):
            a, b = pasta_ref / nome, pasta_nova / nome
            rot = f"{pasta_ref.name}/{nome}"
            if nome == "_log.txt":
                ra, rb = avisos(a.read_text()), avisos(b.read_text())
                faltam = [x for x in ra if x not in rb]
                if faltam:
                    problemas.append(f"{rot}: avisos ausentes na nova: {faltam}")
                continue
            if nome.endswith(".json"):
                ja, jb = json.loads(a.read_text()), json.loads(b.read_text())
                if isinstance(ja, dict) and "_fingerprint" in ja:
                    ja, jb = ja["dados"], jb.get("dados")
                elif a.read_bytes() != b.read_bytes() and ja == jb:
                    problemas.append(f"{rot}: bytes diferentes (objeto igual)")
                if (d := primeira_diferenca(ja, jb)):
                    problemas.append(f"{rot}: {d}")
            elif nome.endswith(".html"):
                ta, tb = a.read_text(), b.read_text()
                ma, mb = APP.search(ta), APP.search(tb)
                da = json.loads(ma.group(2).replace("<\\/", "</"))
                db = json.loads(mb.group(2).replace("<\\/", "</"))
                if (d := primeira_diferenca(da, db)):
                    problemas.append(f"{rot}: app-data {d}")
                if APP.sub("", ta) != APP.sub("", tb):
                    problemas.append(f"{rot}: HTML fora do app-data difere")
                elif ta != tb:
                    problemas.append(f"{rot}: bytes do app-data diferem (objeto igual)")
            elif a.read_bytes() != b.read_bytes():
                la, lb = a.read_text(encoding="utf-8-sig").splitlines(), b.read_text(encoding="utf-8-sig").splitlines()
                i = next((i for i, (x, y) in enumerate(zip(la, lb, strict=False)) if x != y), min(len(la), len(lb)))
                problemas.append(f"{rot}: bytes diferem (linha {i}: {la[i:i+1]} × {lb[i:i+1]})")

    return problemas


if __name__ == "__main__":
    problemas = comparar(Path(sys.argv[1]), Path(sys.argv[2]))
    if problemas:
        print("\n".join(problemas))
        print(f"\n{len(problemas)} diferença(s).")
        sys.exit(1)
    print("Paridade: nenhuma diferença.")
