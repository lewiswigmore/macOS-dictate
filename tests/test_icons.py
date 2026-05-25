from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from dictate import icons


def test_catalog_has_required_keys():
    required = {
        "app",
        "state.idle",
        "state.recording",
        "state.cleaning",
        "state.pasting",
        "health.ok",
        "health.bad",
    }
    assert required <= icons.CATALOG.keys()


def test_catalog_values_are_non_empty_strings():
    for k, v in icons.CATALOG.items():
        assert isinstance(v, str) and v, f"empty symbol for {k}"


def test_symbol_returns_none_without_appkit():
    with patch.object(icons, "_AVAILABLE", False):
        assert icons.symbol("app") is None
        assert icons.symbol("state.recording") is None


def test_apply_returns_false_without_appkit():
    with patch.object(icons, "_AVAILABLE", False):
        item = MagicMock()
        assert icons.apply_to_menu_item(item, "app") is False
        assert icons.apply_to_app(MagicMock(), "app") is False
        item._menuitem.setImage_.assert_not_called()


def test_apply_to_menu_item_with_image_succeeds():
    fake_img = MagicMock()
    item = MagicMock()
    with patch.object(icons, "symbol", return_value=fake_img):
        assert icons.apply_to_menu_item(item, "app") is True
        item._menuitem.setImage_.assert_called_once_with(fake_img)


def test_apply_to_menu_item_swallows_objc_error():
    fake_img = MagicMock()
    item = MagicMock()
    item._menuitem.setImage_.side_effect = RuntimeError("private api gone")
    with patch.object(icons, "symbol", return_value=fake_img):
        assert icons.apply_to_menu_item(item, "app") is False


def test_apply_to_app_sets_template_and_clears_title():
    fake_img = MagicMock()
    fake_img.isTemplate.return_value = False
    app = MagicMock()
    button = app._nsapp.nsstatusitem.button.return_value
    with (
        patch.object(icons, "brand_template_image", return_value=None),
        patch.object(icons, "symbol", return_value=fake_img),
    ):
        assert icons.apply_to_app(app, "app") is True
    fake_img.setTemplate_.assert_called_once_with(True)
    button.setImage_.assert_called_once_with(fake_img)
    button.setTitle_.assert_called_once_with("")


def test_apply_to_app_prefers_brand_template_for_app_key():
    brand_img = MagicMock()
    brand_img.isTemplate.return_value = True  # already a template
    app = MagicMock()
    button = app._nsapp.nsstatusitem.button.return_value
    with (
        patch.object(icons, "brand_template_image", return_value=brand_img),
        patch.object(icons, "symbol") as fake_symbol,
    ):
        assert icons.apply_to_app(app, "app") is True
        fake_symbol.assert_not_called()
    brand_img.setTemplate_.assert_not_called()  # already template
    button.setImage_.assert_called_once_with(brand_img)
    button.setTitle_.assert_called_once_with("")


def test_module_imports_without_appkit(monkeypatch):
    # Simulate AppKit absence and re-import.
    monkeypatch.setitem(sys.modules, "AppKit", None)
    sys.modules.pop("dictate.icons", None)
    try:
        import dictate.icons as fresh  # noqa: PLC0415

        assert fresh._AVAILABLE is False
        assert fresh.symbol("app") is None
    finally:
        sys.modules.pop("dictate.icons", None)
        import dictate.icons  # noqa: F401, PLC0415  # restore real module
