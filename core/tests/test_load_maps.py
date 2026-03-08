import json

import pytest
from django.core.management import call_command

from core.models import CodeMap, CodeMapNode


@pytest.mark.django_db
def test_load_maps_command(tmp_path):
    map_payload = {
        "code_name": "OBC_2024",
        "sections": [
            {
                "id": "1.1.1.1",
                "title": "General",
                "page": 7,
                "page_end": 9,
                "initial_page_top": 640.0,
                "final_page_bottom": 88.0,
                "html": "<p>General</p>",
                "markdown": "**General**",
                "keywords": ["general", "scope"],
                "notes_html": "<div>Notes</div>",
            },
            {
                "id": "1.1.1.2",
                "title": "Definitions",
                "page": 12,
                "page_end": 12,
                "keywords": ["definitions"],
            },
        ],
    }

    map_path = tmp_path / "OBC_Vol1.json"
    map_path.write_text(json.dumps(map_payload), encoding="utf-8")

    call_command("load_maps", source=str(tmp_path))

    code_map = CodeMap.objects.get(map_code="OBC_Vol1")
    assert code_map.code_name == "OBC_2024"
    assert CodeMapNode.objects.filter(code_map=code_map).count() == 2

    node = CodeMapNode.objects.get(code_map=code_map, node_id="1.1.1.1")
    assert node.html == "<p>General</p>"
    assert node.notes_html == "<div>Notes</div>"
    assert node.keywords == ["general", "scope"]
    assert node.page == 7
    assert node.page_end == 9
    assert node.initial_page_top == 640.0
    assert node.final_page_bottom == 88.0


@pytest.mark.django_db
def test_load_maps_allows_missing_span_bounds(tmp_path):
    map_payload = {
        "code_name": "NBC_2025",
        "sections": [
            {
                "id": "B-3.2.9.1.",
                "title": "No Bounds",
                "page": 120,
                "page_end": 120,
            }
        ],
    }

    map_path = tmp_path / "NBC.json"
    map_path.write_text(json.dumps(map_payload), encoding="utf-8")

    call_command("load_maps", source=str(tmp_path))

    node = CodeMapNode.objects.get(node_id="B-3.2.9.1.")
    assert node.page == 120
    assert node.page_end == 120
    assert node.initial_page_top is None
    assert node.final_page_bottom is None
