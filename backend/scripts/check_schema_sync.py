"""Check that database/schema.sql and the SQLAlchemy models describe the same
tables and columns, and that every foreign key in the SQL points at an
existing column of the same type.

It parses the files as text, so it runs without a database or SQLAlchemy:

    python backend/scripts/check_schema_sync.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sql_tables() -> tuple[dict[str, dict[str, str]], list[tuple[str, str, str, str]], list[str]]:
    text = (ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
    text = re.sub(r"--[^\n]*", "", text)
    tables: dict[str, dict[str, str]] = {}
    fks: list[tuple[str, str, str, str]] = []
    order: list[str] = []
    for match in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\) ENGINE", text, re.S):
        name, body = match.group(1), match.group(2)
        order.append(name)
        columns: dict[str, str] = {}
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            fk = re.match(r"CONSTRAINT \w+ FOREIGN KEY \((\w+)\) REFERENCES (\w+) \((\w+)\)", line)
            if fk:
                fks.append((name, fk.group(1), fk.group(2), fk.group(3)))
                continue
            if re.match(r"(PRIMARY KEY|UNIQUE KEY|KEY|CONSTRAINT)\b", line):
                continue
            col = re.match(r"(\w+)\s+([A-Z]+(?:\([^)]*\))?(?: UNSIGNED)?)", line)
            if col:
                columns[col.group(1)] = col.group(2)
        tables[name] = columns
    for alter in re.finditer(r"ALTER TABLE (\w+)\s+ADD CONSTRAINT \w+ FOREIGN KEY \((\w+)\) REFERENCES (\w+) \((\w+)\)", text):
        fks.append(alter.groups())  # added after both tables exist
    return tables, fks, order


def model_tables() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for path in (ROOT / "backend" / "app" / "models").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ClassDef):
                continue
            name, columns = None, set()
            for item in node.body:
                if isinstance(item, ast.Assign) and getattr(item.targets[0], "id", "") == "__tablename__":
                    name = item.value.value
                elif isinstance(item, ast.AnnAssign) and isinstance(item.value, ast.Call) and getattr(item.value.func, "id", "") == "mapped_column":
                    columns.add(item.target.id)
            if name:
                tables[name] = columns
    return tables


def main() -> int:
    sql, fks, order = sql_tables()
    orm = model_tables()
    problems: list[str] = []
    for table in sorted(set(sql) | set(orm)):
        if table not in orm:
            problems.append(f"table '{table}' is in schema.sql but has no model")
        elif table not in sql:
            problems.append(f"model table '{table}' is missing from schema.sql")
        else:
            for col in sorted(set(sql[table]) ^ orm[table]):
                where = "schema.sql only" if col in sql[table] else "model only"
                problems.append(f"{table}.{col}: {where}")
    created: set[str] = set()
    inline_fk_tables = {t for t in order}
    for table in order:
        for src, col, ref_table, ref_col in fks:
            if src != table:
                continue
            if ref_table not in sql or ref_col not in sql[ref_table]:
                problems.append(f"FK {src}.{col} references missing {ref_table}.{ref_col}")
            elif col not in sql[src]:
                problems.append(f"FK column {src}.{col} does not exist")
            elif sql[src][col] != sql[ref_table][ref_col]:
                problems.append(f"FK {src}.{col} ({sql[src][col]}) differs in type from {ref_table}.{ref_col} ({sql[ref_table][ref_col]})")
        created.add(table)
    # creation order: an inline FK may only reference a table created earlier (or itself)
    text = re.sub(r"--[^\n]*", "", (ROOT / "database" / "schema.sql").read_text(encoding="utf-8"))
    seen: set[str] = set()
    for match in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\) ENGINE", text, re.S):
        seen.add(match.group(1))
        for ref in re.findall(r"REFERENCES (\w+)", match.group(2)):
            if ref not in seen and ref in inline_fk_tables:
                problems.append(f"{match.group(1)} references {ref} before it is created")
    print(f"schema.sql: {len(sql)} tables, {sum(len(c) for c in sql.values())} columns, {len(fks)} foreign keys; models: {len(orm)} tables")
    for problem in problems:
        print("  PROBLEM:", problem)
    print("OK - schema.sql and the models agree" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
