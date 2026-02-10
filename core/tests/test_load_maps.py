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
                "html": "<p>General</p>",
                "markdown": "**General**",
                "keywords": ["general", "scope"],
                "bbox": {"l": 1, "t": 2, "r": 3, "b": 0},
            },
            {
                "id": "1.1.1.2",
                "title": "Definitions",
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
    assert node.notes_html is None
    assert node.keywords == ["general", "scope"]
    assert node.bbox == {"l": 1, "t": 2, "r": 3, "b": 0}
