"""As seis tabelas do Censo Escolar, descritas num registro único.

A ordem de `TABELAS` é a ordem canônica: define a ordem das abas lidas, dos
JSONs gerados e o desempate da identificação por nome.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tabela:
    chave: str
    fid: str                                # file_id no Metadata Editor
    rotulo: str                             # nome de exibição
    base_saida: str                         # ceb<ano>_microdados_<base_saida>
    assinatura: frozenset[str]              # tokens que identificam CSV/aba
    assinatura_questionario: frozenset[str] # tokens que identificam o PDF
    secoes_caderno: tuple[str, ...]         # seções do Caderno de Conceitos


TABELAS: tuple[Tabela, ...] = (
    Tabela("escola", "F1", "Escola", "tabela_escola",
           frozenset({"escola"}), frozenset({"escola"}), ("escola",)),
    Tabela("matricula", "F2", "Matrícula", "tabela_matricula",
           frozenset({"matricula"}), frozenset({"aluno"}), ("pessoa_fisica",)),
    Tabela("docente", "F3", "Docente", "tabela_docente",
           frozenset({"docente"}), frozenset({"profissional"}), ("pessoa_fisica",)),
    Tabela("turma", "F4", "Turma", "tabela_turma",
           frozenset({"turma"}), frozenset({"turma"}), ("turma",)),
    # Grafia do INEP nos arquivos: "gestor_escolar", não "gestor".
    Tabela("gestor", "F5", "Gestor Escolar", "tabela_gestor_escolar",
           frozenset({"gestor"}), frozenset({"gestor"}), ("pessoa_fisica",)),
    # Exige os dois tokens (não casa "Curso Superior") e usa o questionário de Turma.
    Tabela("curso_tecnico", "F6", "Curso Técnico", "tabela_curso_tecnico",
           frozenset({"curso", "tecnico"}), frozenset({"turma"}), ("turma",)),
)

POR_CHAVE: dict[str, Tabela] = {t.chave: t for t in TABELAS}
CHAVES: tuple[str, ...] = tuple(POR_CHAVE)


def rotulo(chave: str) -> str:
    return POR_CHAVE[chave].rotulo if chave in POR_CHAVE else chave
