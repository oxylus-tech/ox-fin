import yaml
from pathlib import Path
from typing import Any


__all__ = ("SchemaLoader", "resolve_attr", "load", "dump")


dump = yaml.dump


def load(stream):
    return yaml.load(stream, SchemaLoader)


def load_all(stream):
    return yaml.load_all(stream, SchemaLoader)


class SchemaLoader(yaml.SafeLoader):
    """
    YAML loader supporting:
    - ``!include``: include another YAML file
    - ``!ref``: reference a named section loaded from includes
    """

    def __init__(self, stream, base_path=None, registry=None):
        if isinstance(stream, Path):
            base_path = stream
            stream = stream.read_text()

        super().__init__(stream)
        self.base_path = Path(base_path or ".")
        self.registry = registry if registry is not None else {}

    @staticmethod
    def construct_include(loader, node):
        """
        Load and register a YAML file.

        Example:

        .. code-block:: yaml

            includes:
            - !include immobilisations sections/immobilisations.yaml

        """
        name, filename = loader.construct_scalar(node).split(" ", 1)
        if name in loader.registry:
            raise ValueError(f"A reference already exists for `{name}`.")

        path = (loader.base_path.parent / filename).resolve()
        if path == loader.base_path:
            raise ValueError("You can include a file in itself")

        data = load(path)
        loader.registry[name] = data
        return data

    @staticmethod
    def construct_ref(loader, node):
        """
        Reference a section previously registered.

        Example:

        .. code-block:: yaml

            - !ref immobilisations.sections

        """
        key = loader.construct_scalar(node)
        return resolve_attr(loader.registry, key)


SchemaLoader.add_constructor("!include", SchemaLoader.construct_include)
SchemaLoader.add_constructor("!ref", SchemaLoader.construct_ref)


def resolve_attr(obj: object | dict[str, Any], key: str) -> Any | None:
    """
    For a provided object and key return the targetted object.

    This function provide a real simple implementation, that only support
    access through objects and dicts.

    Members are separated by a dot.

    Example:

    .. code-block::

        obj = {"foo": {"bar": 123 }}
        assert resolve(obj, "foo.bar") == 123
        assert resolve(obj, "foo.tee") == None

    :param obj: the object from which to get the attribute.
    :param key: the attribute path.
    :yield AttributeError: a member does not exists.
    """
    attrs = key.split(".")
    for i, attr in enumerate(attrs):
        try:
            if isinstance(obj, dict):
                obj = obj[attr]
            elif isinstance(obj, list) and attr.isnumeric():
                obj = obj[int(attr)]
            else:
                obj = getattr(obj, attr)
        except (AttributeError, KeyError):
            raise AttributeError(f"The member `{attr}` was not found on `{attrs[:i]}`")
    return obj
