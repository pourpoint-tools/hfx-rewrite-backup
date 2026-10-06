from pathlib import Path

import hfx


def test_package_imports_from_python_source():
    assert hfx.__file__ is not None
    package_path = Path(hfx.__file__)
    assert package_path.name == "__init__.py"
    assert package_path.parent.name == "hfx"
    assert package_path.with_name("py.typed").is_file()
