"""Reading a compose file the way the tests need it: plain data.

Compose has its own merge tags (``!override``, ``!reset``) that PyYAML's
safe loader refuses. The tests check what a file says, not how compose
merges it, so a tag is read as the value it carries.
"""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


class _ComposeLoader(yaml.SafeLoader):
    pass


def _untagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_multi_constructor("!", _untagged)


def load_compose(name: str) -> dict[str, Any]:
    """The compose file ``name`` at the project root, as data ({} if empty)."""
    return yaml.load((ROOT / name).read_text(), Loader=_ComposeLoader) or {}
