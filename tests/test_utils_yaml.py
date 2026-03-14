import pytest

from fin.utils import yaml


@pytest.fixture
def yaml_including_path(data_dir):
    return data_dir / "yaml_loader_test_including.yaml"


@pytest.fixture
def yaml_included_path(data_dir):
    return data_dir / "yaml_loader_test_included.yaml"


@pytest.fixture
def yaml_including(yaml_including_path):
    return yaml.load(yaml_including_path)


@pytest.fixture
def yaml_included(yaml_included_path):
    return yaml.load(yaml_included_path)


class TestSchemaLoader:
    def test_load(self, yaml_including_path, yaml_included):
        data = yaml.load(yaml_including_path)

        children = [
            {"name": "child-1", "value": 456},
            {"name": "child-2", "value": 678},
        ]
        assert data["items"] == [{"name": "first-item", "value": 1}, {"name": "parent", "value": 123}, *children]


def test_resolve_attr(yaml_including):
    assert yaml.resolve_attr(yaml_including, "items") == yaml_including["items"]
    assert yaml.resolve_attr(yaml_including, "items.1.name") == "parent"
    assert yaml.resolve_attr(yaml, "SchemaLoader.__name__") == "SchemaLoader"


def test_resolve_attr_raises_attribute_error_on_key_error(yaml_included):
    with pytest.raises(AttributeError):
        yaml.resolve_attr(yaml_included, "not_an_attribute")


def test_resolve_attr_raises_attribute_error_on_attribute_error():
    with pytest.raises(AttributeError):
        yaml.resolve_attr(yaml, "not_an_attribute")
