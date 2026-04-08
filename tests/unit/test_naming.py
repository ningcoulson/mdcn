from __future__ import annotations

from mdcn.output.naming import build_folder_name, build_image_filename, preview_folder_name, sanitize_path_component


def test_sanitize_path_component_removes_reserved_chars():
    assert sanitize_path_component('MD:001/标题?') == "MD 001 标题"


def test_build_folder_name_combines_number_and_title():
    assert build_folder_name("MD-001", "示例 标题") == "MD-001 示例 标题"


def test_build_folder_name_supports_folder_template():
    assert build_folder_name("MD-001", "示例标题", "{studio}/{number} {title}", studio="Madou") == "Madou/MD-001 示例标题"


def test_preview_folder_name_uses_template_tokens():
    assert preview_folder_name("{studio}/{number} {title}", title="Warm Up") == "Madou/MD-001 Warm Up"


def test_build_image_filename_defaults_to_jpg_and_adds_index():
    assert build_image_filename("MD001", "poster") == "MD001_poster.jpg"
    assert build_image_filename("MD001", "extrafanart", index=2, url="https://a/b.png?x=1") == "MD001_extrafanart_2.png"
