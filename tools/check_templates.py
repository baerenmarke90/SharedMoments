#!/usr/bin/env python3
"""Statische Pruefungen, die ohne laufende App auskommen.

- Jinja-Bloecke sauber verschachtelt
- jedes {% include %} zeigt auf eine existierende Datei
- <style>-Bloecke haben ausgeglichene Klammern
- jedes benutzte --sm-Token ist in couple.css definiert
- jedes "from <lokales modul> import name" existiert wirklich

Der letzte Punkt ist der wichtigste: genau dieser Fehler hat die Produktion
lahmgelegt (run.py importierte eine geloeschte Funktion).
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / 'app' / 'templates'
COUPLE_CSS = ROOT / 'app' / 'static' / 'css' / 'couple.css'

BLOCKS = {
    'if': 'endif', 'for': 'endfor', 'block': 'endblock', 'macro': 'endmacro',
    'call': 'endcall', 'filter': 'endfilter', 'with': 'endwith',
    'raw': 'endraw', 'trans': 'endtrans', 'autoescape': 'endautoescape',
}
TAG = re.compile(r'{%-?\s*(\w+)')
INCLUDE = re.compile(r"""{%-?\s*include\s+['"]([^'"]+)['"]""")
STYLE = re.compile(r'<style[^>]*>(.*?)</style>', re.S)

problems = []


def check_templates():
    files = sorted(TEMPLATES.rglob('*.html'))
    for path in files:
        text = path.read_text()
        rel = path.relative_to(ROOT)

        stack = []
        for match in TAG.finditer(text):
            keyword = match.group(1)
            line = text[:match.start()].count('\n') + 1
            if keyword in BLOCKS:
                stack.append((keyword, line))
            elif keyword in BLOCKS.values():
                if not stack:
                    problems.append(f'{rel}:{line}: {{% {keyword} %}} ohne offenen Block')
                    break
                opened, opened_line = stack.pop()
                if BLOCKS[opened] != keyword:
                    problems.append(
                        f'{rel}:{line}: {{% {keyword} %}} schliesst '
                        f'{{% {opened} %}} aus Zeile {opened_line}'
                    )
                    break
        else:
            if stack:
                names = ', '.join(f'{k} (Zeile {l})' for k, l in stack)
                problems.append(f'{rel}: nicht geschlossen: {names}')

        for match in INCLUDE.finditer(text):
            if not (TEMPLATES / match.group(1)).exists():
                problems.append(f'{rel}: include auf fehlende Datei {match.group(1)}')

        css = '\n'.join(STYLE.findall(text))
        if css and css.count('{') != css.count('}'):
            problems.append(f'{rel}: <style> hat unausgeglichene Klammern')

    return files


def check_tokens(files):
    defined = set(re.findall(r'(--sm-[\w-]+)\s*:', COUPLE_CSS.read_text()))
    for path in list(files) + [COUPLE_CSS]:
        used = set(re.findall(r'var\((--sm-[\w-]+)\)', path.read_text()))
        for token in sorted(used - defined):
            problems.append(f'{path.relative_to(ROOT)}: {token} ist nirgends definiert')


def module_names(path):
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split('.')[0] for a in node.names}
    return names


def check_imports():
    modules = {}
    for path in ROOT.rglob('*.py'):
        if any(part in ('.git', '__pycache__', 'node_modules') for part in path.parts):
            continue
        name = '.'.join(path.relative_to(ROOT).with_suffix('').parts)
        if name.endswith('.__init__'):
            name = name[:-len('.__init__')]
        modules[name] = path

    cache = {}
    for path in modules.values():
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError as exc:
            problems.append(f'{rel}: Syntaxfehler: {exc}')
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            target = modules.get(node.module)
            if target is None:
                continue
            if target not in cache:
                cache[target] = module_names(target)
            for alias in node.names:
                if alias.name == '*' or alias.name in cache[target]:
                    continue
                # "from app import scheduler" holt ein Untermodul, keinen Namen.
                if f'{node.module}.{alias.name}' in modules:
                    continue
                problems.append(
                    f'{rel}:{node.lineno}: {node.module} hat kein {alias.name}'
                )


def main():
    files = check_templates()
    check_tokens(files)
    check_imports()

    if problems:
        print('Probleme gefunden:')
        for problem in problems:
            print('  -', problem)
        return 1

    print(f'{len(files)} Templates, Tokens und Importe in Ordnung')
    return 0


if __name__ == '__main__':
    sys.exit(main())
