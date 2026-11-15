"""Cross-check what the app uses of anki-addons-mcp against a newer release: the breaking changes /update-mcp must fix.

Usage: uv run python .claude/skills/update-mcp/impact.py <base> <target>   (versions X.Y.Z, e.g. 0.11.0 0.12.0)
Run from the repository root. Parses the MCP's tools.py at both tags (from GitHub) and the app's code, and prints:
- "PASS|FAIL <check>: <detail>" for what the app relies on: every tool in the default `ai_tools`, in
  FILTERED_TOOLS/THIN_CARD_TOOLS and named in SYSTEM_PROMPT still exists; every tool the app calls itself still takes
  the arguments it passes (`SearchFilters.tool_args` included); every `from anki_addons_mcp... import` still resolves;
  every field of the result models (domain/models.py) that the target removes or retypes is not named in the app's
  code or templates (a name match is a hint: read the places it prints);
- "NEW <what>: <detail>" for tools, tool parameters and result fields the target adds (candidates for the app);
- "INFO <what>: <detail>" for removed tools and fields the app doesn't name, changed field descriptions of fields
  the app names (a changed meaning), and the dataset tag the server pins.
Exits 0 when nothing FAILs, 1 otherwise (a FAIL is a change the upgrade must fix, not a reason to stop the run).
"""
import ast
import re
import sys
from pathlib import Path

from mcp_repo import Check, file_at, hf_revision, mcp_imports, module_files

TOOLS_FILE = "src/anki_addons_mcp/interface/mcp/tools.py"
MODELS_FILE = "src/anki_addons_mcp/domain/models.py"
CONFIG_FILE = "src/anki_addons_mcp/config.py"
FILTER_TOOLS = ("search_addons", "filter_addons")  # the tools SearchFilters.tool_args goes to

Tools = dict[str, set[str]]  # tool name -> parameter names
Fields = dict[str, tuple[str, str]]  # "Model.field" -> (type, description)


def tools(source: str) -> Tools:
    """The MCP tools a tools.py registers: functions decorated with `@<server>.tool(...)`, by name or `name=`."""
    found: Tools = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            call = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(call, ast.Attribute) and call.attr == "tool":
                name = next((k.value.value for k in getattr(decorator, "keywords", [])
                             if k.arg == "name" and isinstance(k.value, ast.Constant)), node.name)
                found[str(name)] = {a.arg for a in [*node.args.args, *node.args.kwonlyargs]}
    return found


def top_level_names(source: str) -> set[str]:
    """The names a module defines or imports at its top level (what `from module import name` can find)."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
    return names


def _constants(tree: ast.Module) -> dict[str, str]:
    """The module's string constants, e.g. shared Field descriptions."""
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue
            if isinstance(value, str):
                constants[node.targets[0].id] = value
    return constants


def model_fields(source: str) -> Fields:
    """The annotated fields of every class in a models module, with their type and `Field(description=...)`."""
    tree = ast.parse(source)
    constants = _constants(tree)
    fields: Fields = {}
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for node in cls.body:
            if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
                continue
            description = ""
            if isinstance(node.value, ast.Call):
                for keyword in node.value.keywords:
                    if keyword.arg == "description":
                        value = keyword.value
                        try:
                            description = str(ast.literal_eval(value))
                        except ValueError:
                            description = constants.get(value.id, ast.unparse(value)) if isinstance(value, ast.Name) \
                                else ast.unparse(value)
            fields[f"{cls.name}.{node.target.id}"] = (ast.unparse(node.annotation), description)
    return fields


def mentions(name: str, files: dict[str, str]) -> list[str]:
    """Where the app's code or templates name a field: "file:line" for each line with the word."""
    word = re.compile(rf"\b{re.escape(name)}\b")
    return [f"{path}:{i}" for path, text in files.items() for i, line in enumerate(text.splitlines(), 1)
            if word.search(line)]


def field_findings(base: Fields, target: Fields, files: dict[str, str]) -> tuple[list[tuple[str, Check]], list[str]]:
    """Checks for removed or retyped fields the app names, and NEW/INFO lines for the rest."""
    checks: list[tuple[str, Check]] = []
    lines = [f"NEW field {f}: {target[f][0]}" for f in sorted(target.keys() - base.keys())]
    for field in sorted(base.keys()):
        name = field.split(".", 1)[1]
        places = mentions(name, files)
        where = f"the app names '{name}' in {', '.join(places[:5])}" + (" ..." if len(places) > 5 else "")
        if field not in target:
            change = "removed"
        elif base[field][0] != target[field][0]:
            change = f"type {base[field][0]} -> {target[field][0]}"
        else:
            if base[field][1] != target[field][1] and places:
                lines.append(f"INFO field {field} description changed, {where}: {target[field][1]!r}")
            continue
        if places:
            checks.append((f"field {field}", (False, f"{change}; {where}")))
        else:
            lines.append(f"INFO field {field} {change} (the app doesn't name '{name}')")
    return checks, lines


def direct_calls(sources: list[str]) -> Tools:
    """The tools the app calls itself, `call("tool", arg=...)` or `call_tool("tool", {"arg": ...})`, with the
    argument names written out (not those passed with **)."""
    calls: Tools = {}
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("call", "call_tool") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                continue
            arguments = calls.setdefault(node.args[0].value, set())
            arguments.update(k.arg for k in node.keywords if k.arg)
            if len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
                arguments.update(str(k.value) for k in node.args[1].keys if isinstance(k, ast.Constant))
    return calls


def filter_arguments(source: str) -> set[str]:
    """The argument names `SearchFilters.tool_args` produces: `args["name"] = ...` and dict literal keys in it."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "tool_args":
            names = {str(n.slice.value) for n in ast.walk(node)
                     if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.ctx, ast.Store)}
            names.update(str(k.value) for n in ast.walk(node) if isinstance(n, ast.Dict)
                         for k in n.keys if isinstance(k, ast.Constant))
            return names
    return set()


def prompt_tools(prompt: str, known: set[str]) -> set[str]:
    """The tool names (of `known`) the system prompt mentions."""
    return {word for word in re.findall(r"[a-z_]+", prompt) if word in known}


def tool_checks(label: str, names: set[str], target: Tools) -> list[tuple[str, Check]]:
    missing = sorted(names - target.keys())
    return [(label, (not missing, f"missing at the target: {', '.join(missing)}" if missing
                     else f"{len(names)} tools exist"))]


def argument_checks(calls: Tools, target: Tools) -> list[tuple[str, Check]]:
    checks = []
    for tool, arguments in sorted(calls.items()):
        if tool not in target:
            checks.append((f"call {tool}", (False, "the tool is gone")))
            continue
        unknown = sorted(arguments - target[tool])
        checks.append((f"call {tool}", (not unknown, f"unknown arguments: {', '.join(unknown)}" if unknown
                                        else f"arguments {', '.join(sorted(arguments)) or 'none'} exist")))
    return checks


def import_checks(imports: dict[str, set[str]], sources: dict[str, str | None]) -> list[tuple[str, Check]]:
    """`sources` maps every candidate file of `module_files` to its text at the target (None: no such file)."""
    checks = []
    for module, names in sorted(imports.items()):
        source = next((sources[f] for f in module_files(module) if sources.get(f) is not None), None)
        if source is None:
            checks.append((f"import {module}", (False, "the module is gone")))
            continue
        missing = sorted(names - top_level_names(source))
        checks.append((f"import {module}", (not missing, f"missing names: {', '.join(missing)}" if missing
                                            else ", ".join(sorted(names)) or "module")))
    return checks


def news(base: Tools, target: Tools, used: set[str]) -> list[str]:
    lines = [f"NEW tool {t}: not in ai_tools, so the AI can't call it" for t in sorted(target.keys() - base.keys())]
    lines += [f"NEW parameters of {t}: {', '.join(sorted(target[t] - base[t]))}"
              for t in sorted(target.keys() & base.keys()) if target[t] - base[t]]
    lines += [f"INFO removed parameters of {t}: {', '.join(sorted(base[t] - target[t]))}"
              for t in sorted(target.keys() & base.keys()) if base[t] - target[t]]
    lines += [f"INFO tool {t} removed (the app doesn't use it)" for t in sorted(base.keys() - target.keys() - used)]
    return lines


def main(base: str, target: str) -> int:
    from anki_addons_catalog.application.ask import FILTERED_TOOLS, SYSTEM_PROMPT, THIN_CARD_TOOLS
    from anki_addons_catalog.config import Settings

    base_tools, target_tools = (tools(file_at(TOOLS_FILE, f"v{v}") or "") for v in (base, target))
    if not target_tools:
        print(f"FAIL tools: no tools found in {TOOLS_FILE} at v{target}; read the changes by hand")
        return 1
    ai_tools = set(Settings.model_fields["ai_tools"].default)
    in_prompt = prompt_tools(SYSTEM_PROMPT, set(base_tools) | set(target_tools))
    calls = direct_calls([p.read_text() for p in sorted(Path("src").rglob("*.py"))])
    filter_args = filter_arguments(Path("src/anki_addons_catalog/domain/models.py").read_text())
    for tool in FILTER_TOOLS:
        calls.setdefault(tool, set()).update(filter_args)
    imports = mcp_imports()
    sources = {f: file_at(f, f"v{target}") for module in imports for f in module_files(module)}
    app_files = {str(p): p.read_text() for p in sorted(Path("src").rglob("*")) if p.suffix in (".py", ".html")}
    base_fields, target_fields = (model_fields(file_at(MODELS_FILE, f"v{v}") or "") for v in (base, target))
    field_checks, field_lines = field_findings(base_fields, target_fields, app_files)
    checks = [*tool_checks("ai_tools", ai_tools, target_tools),
              *tool_checks("FILTERED_TOOLS, THIN_CARD_TOOLS", set(FILTERED_TOOLS) | set(THIN_CARD_TOOLS),
                           target_tools),
              *tool_checks("SYSTEM_PROMPT", in_prompt, target_tools),
              *argument_checks(calls, target_tools),
              *import_checks(imports, sources),
              *field_checks]
    for name, (ok, detail) in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    for line in [*news(base_tools, target_tools, ai_tools | in_prompt | set(calls)), *field_lines]:
        print(line)
    before, after = (hf_revision(file_at(CONFIG_FILE, f"v{v}")) for v in (base, target))
    print(f"INFO dataset tag: {before} -> {after}" + (" (unchanged)" if before == after else ""))
    return 0 if all(ok for _, (ok, _) in checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
