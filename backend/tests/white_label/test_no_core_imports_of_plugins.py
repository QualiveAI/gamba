import ast
import os


def test_no_core_imports_of_plugins():
    base = os.path.join(os.getcwd(), "core")
    for root, _, files in os.walk(base):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", None) or ""
                    names = [n.name for n in getattr(node, "names", [])]
                    if "plugins" in mod or any("plugins" in n for n in names):
                        raise AssertionError(f"core imports plugins in {path}")  # noqa: B904
