#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""testar_valores_especiais.py — Regressão dos códigos especiais do dicionário.

O dicionário do INEP lista, junto das categorias, códigos que NÃO são
categorias: marcas de tratamento de consistência (o 88888 de "valor extremo")
e de ausência de declaração (o 9 de "Não informado", o 99999999999999 de "Sem
declaração"). Eles precisam sair de `var_catgry` e entrar em `var_invalrng`,
senão a média de "quantidade de televisões" é calculada com 88888 dentro. Os
dois tipos são descritos também em `var_imputation` — decisão registrada em
reunião: o valor especial é resultado do processamento do INEP.

Quem decide é o RÓTULO, não o número — e é isso que este teste fixa. O caso
crítico é o par `8`/`9` de largura 1 no dicionário de 2025: o `8` é categoria
real ("Área onde se localizam povos e comunidades tradicionais") e o `9` é
"Não informado". Qualquer regra baseada na forma do número classifica os dois
igual e corrompe metade das variáveis TP_.

Não depende de nenhum insumo em disco: só de rótulos. Rode com

    python testar_valores_especiais.py
"""
from __future__ import annotations

import sys

from censo_lib import (
    classificar_codigo_especial,
    descrever_imputacao,
    parece_sentinela,
    separar_codigos_especiais,
)

falhas: list[str] = []


def checar(rotulo: str, obtido, esperado) -> None:
    if obtido != esperado:
        falhas.append(f"{rotulo}\n      esperado: {esperado!r}\n      obtido:   {obtido!r}")


# ---------------------------------------------------------------------------
# 1. Rótulos reais do dicionário 2025
# ---------------------------------------------------------------------------
REAIS_2025 = {
    "registro com marcação de valor extremo (valor superior ao limite máximo de "
    "4 equipamentos para cada 3 salas existentes - foram marcados apenas valores>3)":
        "imputacao",
    "registro com marcação de valor extremo (valor superior ao limite máximo* "
    "definido com base na distribuição da razão de profissionais por matrícula)":
        "imputacao",
    "Sem declaração":  "nao_resposta",
    "Não informado":   "nao_resposta",
    # Categorias reais que convivem com as de cima nas mesmas abas.
    "Área onde se localizam povos e comunidades tradicionais": None,
    "Federal":          None,
    "Estadual e Municipal": None,
    "A escola não está em área de localização diferenciada": None,
    "Não":              None,
    "Não oferece":      None,
    "Não exclusivamente": None,
    "Não há rede local interligando computadores": None,
    "A escola não possui projeto político pedagógico/proposta pedagógica": None,
}
for rotulo, esperado in REAIS_2025.items():
    checar(f"rótulo 2025 “{rotulo[:52]}”", classificar_codigo_especial(rotulo), esperado)

# As negativas acima são o ponto sensível: "Não oferece" e "Não há rede local"
# começam com "Não" e continuam sendo categoria. O marcador é "nao informad",
# não "nao".

# ---------------------------------------------------------------------------
# 2. Generalização — outras redações plausíveis do INEP
# ---------------------------------------------------------------------------
OUTRAS_REDACOES = {
    # imputação / tratamento pelo produtor
    "Valor extremo":                                   "imputacao",
    "VALORES EXTREMOS TRATADOS":                       "imputacao",
    "valor imputado pelo Inep":                        "imputacao",
    "Registro submetido a imputação":                  "imputacao",
    "marcado com o código 8888":                       "imputacao",
    "outlier identificado na crítica de consistência": "imputacao",
    "valor substituído por marcação de consistência":  "imputacao",
    # não-resposta
    "Não declarado":              "nao_resposta",
    "Não respondeu":              "nao_resposta",
    "Sem informação":             "nao_resposta",
    "Sem resposta":               "nao_resposta",
    "Não aplicável":              "nao_resposta",
    "Não se aplica":              "nao_resposta",
    "Ignorado":                   "nao_resposta",
    "NÃO INFORMADA":              "nao_resposta",
    "Não consta":                 "nao_resposta",
    # categorias reais que NÃO podem ser capturadas
    "Ensino Regular":             None,
    "Urbana":                     None,
    "Sim":                        None,
    "Não possui":                 None,
    "Extinta em Anos Anteriores": None,
    "":                           None,
}
for rotulo, esperado in OUTRAS_REDACOES.items():
    checar(f"redação “{rotulo[:52]}”", classificar_codigo_especial(rotulo), esperado)

# Acento, caixa e espaço não podem alterar a decisão.
for variante in ("Não informado", "NAO INFORMADO", "nao informado", "  Não   informado  "):
    checar(f"insensível a caixa/acento: “{variante}”",
           classificar_codigo_especial(variante), "nao_resposta")

# Imputação vence não-resposta: um rótulo que descreve tratamento do produtor
# é imputação mesmo citando ausência, porque `var_imputation` precisa dele.
checar("imputação tem precedência",
       classificar_codigo_especial("valor extremo, sem informação do valor original"),
       "imputacao")

# ---------------------------------------------------------------------------
# 3. Separação por variável
# ---------------------------------------------------------------------------
# QT_ com só o código de valor extremo: nenhuma categoria real sobra.
reais, esp = separar_codigos_especiais({88888: "registro com marcação de valor extremo (...)"})
checar("QT_: sem categoria real", reais, {})
checar("QT_: 88888 é imputação", esp, {88888: ("imputacao", "registro com marcação de valor extremo (...)")})

# TP_ com categorias reais + "Não informado": só o 9 sai.
tp = {1: "Federal", 2: "Estadual", 3: "Municipal", 8: "Área tradicional", 9: "Não informado"}
reais, esp = separar_codigos_especiais(tp)
checar("TP_: categorias reais preservadas", sorted(reais), [1, 2, 3, 8])
checar("TP_: só o 9 é especial", sorted(esp), [9])
checar("TP_: 9 é não-resposta", esp[9][0], "nao_resposta")

checar("sem códigos", separar_codigos_especiais({}), ({}, {}))
checar("None não quebra", separar_codigos_especiais(None), ({}, {}))

# ---------------------------------------------------------------------------
# 4. var_imputation descreve TODOS os códigos especiais
# ---------------------------------------------------------------------------
# Decisão registrada em reunião: todo valor especial é resultado do
# processamento do INEP, não só o de valor extremo. Os dois tipos entram em
# var_imputation; o que a redação preserva é a natureza de cada um.
misto = {
    88888: ("imputacao", "registro com marcação de valor extremo"),
    9:     ("nao_resposta", "Não informado"),
}
texto = descrever_imputacao(misto)
checar("var_imputation cita o código de imputação", "88888" in texto, True)
checar("var_imputation cita também o de não-resposta", "Não informado" in texto, True)
checar("var_imputation cita o código 9", "Código 9" in texto, True)
checar("var_imputation distingue tratamento de consistência",
       "tratamento de consistência" in texto, True)
checar("var_imputation distingue ausência de declaração",
       "ausência de declaração" in texto, True)
# A abertura foi retirada: o texto é só a lista de códigos, sem frase
# introdutória nem remissão a var_invalrng (que já declara os mesmos códigos).
checar("var_imputation começa pelo código", texto.startswith("Código "), True)
checar("var_imputation sem remissão a var_invalrng",
       "var_invalrng" in texto, False)

# Só não-resposta também preenche — antes ficava vazio.
so_nr = descrever_imputacao({9: ("nao_resposta", "Não informado")})
checar("só não-resposta preenche var_imputation", bool(so_nr), True)

# Sem abertura, não há mais concordância de singular/plural a manter: o texto
# é a lista de códigos e nada mais.
checar("só não-resposta começa pelo código", so_nr.startswith("Código 9: "), True)
checar("sem frase de abertura", "valor observado" in so_nr, False)

checar("var_imputation vazio sem códigos", descrever_imputacao({}), "")
checar("var_imputation vazio com None", descrever_imputacao(None), "")

# ---------------------------------------------------------------------------
# 5. `parece_sentinela` — só auditoria, e o piso de 2 dígitos
# ---------------------------------------------------------------------------
for codigo in (88, 99, 888, 999, 8888, 88888, 99999999999999, -99):
    checar(f"{codigo} parece sentinela", parece_sentinela(codigo), True)
# Um dígito nunca: é onde 8 (categoria) e 9 (não-resposta) colidem.
for codigo in (0, 1, 8, 9, -8, 12, 89, 98, 980, 899, 100, 2025):
    checar(f"{codigo} NÃO parece sentinela", parece_sentinela(codigo), False)
checar("aceita string", parece_sentinela("8888"), True)

# ---------------------------------------------------------------------------
if falhas:
    print(f"\n{len(falhas)} FALHA(S):\n")
    for f in falhas:
        print(f"  ✗ {f}")
    sys.exit(1)
print("Valores especiais do dicionário: todos os casos passaram.")
