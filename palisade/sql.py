from __future__ import annotations

import ast
import re
from dataclasses import dataclass


class SQLError(Exception):
    pass


@dataclass
class CreateTable:
    table: str
    columns: list[dict]


@dataclass
class Insert:
    table: str
    values: list[object]


@dataclass
class Select:
    table: str
    where: tuple[str, str, object] | None


@dataclass
class Delete:
    table: str
    where: tuple[str, str, object]


IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def split_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    escape = False
    depth = 0
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if quote:
            if ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def parse_literal(token: str):
    token = token.strip()
    if re.fullmatch(r"[-+]?\d+", token):
        return int(token)
    if len(token) >= 2 and token[0] in "'\"" and token[-1] == token[0]:
        try:
            value = ast.literal_eval(token)
        except Exception as exc:
            raise SQLError(f"invalid string literal: {token}") from exc
        if not isinstance(value, str):
            raise SQLError("only integer and text literals are supported")
        return value
    raise SQLError(f"unsupported literal: {token}")


def parse_where(text: str) -> tuple[str, str, object]:
    m = re.fullmatch(rf"\s*({IDENT})\s*(<=|>=|!=|=|<|>)\s*(.+?)\s*", text, flags=re.I | re.S)
    if not m:
        raise SQLError("WHERE must look like: column = value")
    return m.group(1), m.group(2), parse_literal(m.group(3))


def parse(sql: str):
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise SQLError("empty statement")

    m = re.fullmatch(rf"CREATE\s+TABLE\s+({IDENT})\s*\((.*)\)", sql, flags=re.I | re.S)
    if m:
        columns = []
        for raw in split_commas(m.group(2)):
            cm = re.fullmatch(rf"({IDENT})\s+(INTEGER|TEXT)(\s+PRIMARY\s+KEY)?", raw.strip(), flags=re.I)
            if not cm:
                raise SQLError(f"invalid column definition: {raw}")
            columns.append({
                "name": cm.group(1),
                "type": cm.group(2).upper(),
                "primary_key": bool(cm.group(3)),
            })
        return CreateTable(m.group(1), columns)

    m = re.fullmatch(rf"INSERT\s+INTO\s+({IDENT})\s+VALUES\s*\((.*)\)", sql, flags=re.I | re.S)
    if m:
        return Insert(m.group(1), [parse_literal(v) for v in split_commas(m.group(2))])

    m = re.fullmatch(rf"SELECT\s+\*\s+FROM\s+({IDENT})(?:\s+WHERE\s+(.+))?", sql, flags=re.I | re.S)
    if m:
        return Select(m.group(1), parse_where(m.group(2)) if m.group(2) else None)

    m = re.fullmatch(rf"DELETE\s+FROM\s+({IDENT})\s+WHERE\s+(.+)", sql, flags=re.I | re.S)
    if m:
        return Delete(m.group(1), parse_where(m.group(2)))

    raise SQLError("unsupported SQL statement")
