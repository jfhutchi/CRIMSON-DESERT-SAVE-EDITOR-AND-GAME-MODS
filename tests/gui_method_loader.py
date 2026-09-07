"""Execute a GUI handler against a small widget harness without starting the app.

The production method body is compiled unchanged. This isolates asynchronous
state transitions from application startup, game databases and native plugins.
"""
import ast
from pathlib import Path


def load_method(relative_path, class_name, method_name, namespace):
    path = Path(__file__).resolve().parents[1] / relative_path
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    method.decorator_list = []
    code = ast.Module(body=[method], type_ignores=[])
    exec(compile(code, str(path), "exec"), namespace)
    return namespace[method_name]
