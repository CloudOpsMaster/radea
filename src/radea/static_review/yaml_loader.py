"""Safe YAML loading that remembers where every mapping, key and list item came from."""

import re
from typing import Any

import yaml

MAX_NODES = 200_000
MAX_DOCUMENTS = 500


class LDict(dict):
    """A mapping that knows its own line and the line of each key (1-based)."""

    line: int = 1
    key_lines: dict

    def key_line(self, key: str) -> int:
        return getattr(self, "key_lines", {}).get(key, self.line)


class LList(list):
    line: int = 1
    item_lines: list

    def item_line(self, index: int) -> int:
        return self.item_lines[index] if index < len(self.item_lines) else self.line


class Ref(LList):
    """A GitLab `!reference [job, key]` pointer: structure, not content to be reviewed."""


class _Loader(yaml.SafeLoader):
    pass


def _map(loader: _Loader, node: yaml.MappingNode) -> LDict:
    if isinstance(loader, _StrictLoader) and any(
        key.tag == "tag:yaml.org,2002:merge" for key, _ in node.value
    ):
        raise yaml.constructor.ConstructorError(
            None, None, "merge keys are unsupported", node.start_mark
        )
    loader.flatten_mapping(node)
    result = LDict()
    result.line = node.start_mark.line + 1
    result.key_lines = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            hash(key)
        except TypeError:
            raise yaml.constructor.ConstructorError(
                None, None, "unhashable mapping key", key_node.start_mark
            ) from None
        if isinstance(loader, _StrictLoader) and key in result:
            raise yaml.constructor.ConstructorError(
                None, None, "duplicate mapping key", key_node.start_mark
            )
        result[key] = loader.construct_object(value_node, deep=True)
        result.key_lines[key] = key_node.start_mark.line + 1
    return result


def _seq(loader: _Loader, node: yaml.SequenceNode) -> LList:
    result = LList()
    result.line = node.start_mark.line + 1
    result.item_lines = []
    for child in node.value:
        result.append(loader.construct_object(child, deep=True))
        result.item_lines.append(child.start_mark.line + 1)
    return result


def _tagged(loader: _Loader, suffix: str, node: yaml.Node) -> Any:
    """Accept any custom tag (GitLab !reference, CloudFormation !Ref, ...) as plain data.

    The tag name is ignored except for !reference; nothing is ever instantiated or executed.
    """
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        items = _seq(loader, node)
        if suffix != "reference":
            return items
        ref = Ref(items)
        ref.line, ref.item_lines = items.line, items.item_lines
        return ref
    return _map(loader, node)


_Loader.add_multi_constructor("!", _tagged)
_Loader.add_constructor("tag:yaml.org,2002:map", _map)
_Loader.add_constructor("tag:yaml.org,2002:seq", _seq)


class _StrictLoader(_Loader):
    pass


_StrictLoader.yaml_multi_constructors = {}
_StrictLoader.yaml_implicit_resolvers = {
    first: [
        (tag, pattern)
        for tag, pattern in rules
        if tag not in ("tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp")
    ]
    for first, rules in _Loader.yaml_implicit_resolvers.items()
}
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _check_size(value: Any) -> None:
    """Aliases share objects, so count each object once: an alias bomb cannot blow this up."""
    seen: set[int] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, (dict, list)):
            if id(item) in seen:
                continue
            seen.add(id(item))
            if len(seen) > MAX_NODES:
                raise ValueError("YAML document is too large or deeply aliased")
            stack.extend(item.values() if isinstance(item, dict) else item)


def load_all(text: str, *, strict: bool = False) -> list[Any]:
    """Parse every document. Raises ValueError with a safe, short message on any problem."""
    try:
        documents: list[Any] = []
        loader = _StrictLoader if strict else _Loader
        for document in yaml.load_all(text, Loader=loader):  # noqa: S506 - SafeLoader subclass
            if len(documents) >= MAX_DOCUMENTS:
                raise ValueError("Too many YAML documents")
            _check_size(document)
            documents.append(document)
        return documents
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        raise ValueError(f"Invalid YAML{where}") from None
    except RecursionError:
        raise ValueError("YAML nesting is too deep") from None


def get(node: Any, *path: Any) -> Any:
    """Safe nested lookup that returns None instead of raising on a shape mismatch."""
    for step in path:
        if isinstance(node, dict) and isinstance(step, str):
            node = node.get(step)
        elif isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
            node = node[step]
        else:
            return None
    return node


def line_of(node: Any, key: str | None = None) -> int | None:
    if isinstance(node, LDict):
        return node.key_line(key) if key is not None else node.line
    if isinstance(node, LList):
        return node.line
    return None


def section(node: Any, key: str) -> LDict:
    """The mapping under `key`, or an empty mapping when it is absent or the wrong shape."""
    value = node.get(key) if isinstance(node, dict) else None
    return value if isinstance(value, LDict) else LDict()
