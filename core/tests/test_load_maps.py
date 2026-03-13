import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command


def _run_load_maps(tmp_path, filename, payload):
    """Write a map JSON file and call the management command with mocked ORM."""
    map_path = tmp_path / filename
    map_path.write_text(json.dumps(payload), encoding="utf-8")

    captured_map = {}
    captured_nodes = []

    fake_code_map = SimpleNamespace(pk=1, map_code=filename.removesuffix(".json"), code_name="")

    with (
        patch("core.management.commands.load_maps.CodeMap") as mock_cm,
        patch("core.management.commands.load_maps.CodeMapNode") as mock_cmn,
        patch("core.management.commands.load_maps.CodeEdition"),
        patch("core.management.commands.load_maps.transaction") as mock_tx,
    ):
        mock_tx.atomic.return_value.__enter__ = lambda s: None
        mock_tx.atomic.return_value.__exit__ = lambda s, *a: False
        # CodeMap.objects.update_or_create returns (instance, created)
        def fake_update_or_create(map_code, defaults=None):
            fake_code_map.map_code = map_code
            fake_code_map.code_name = (defaults or {}).get("code_name", map_code)
            captured_map["map_code"] = map_code
            captured_map["code_name"] = fake_code_map.code_name
            return fake_code_map, True

        mock_cm.objects.update_or_create.side_effect = fake_update_or_create

        # CodeMapNode.objects.filter().delete() — no-op
        filter_qs = MagicMock()
        filter_qs.delete.return_value = (0, {})
        mock_cmn.objects.filter.return_value = filter_qs

        # CodeMapNode(...) — capture constructor calls by returning real SimpleNamespace
        original_fields = {}

        def fake_node_init(**kwargs):
            node = SimpleNamespace(**kwargs)
            return node

        mock_cmn.side_effect = fake_node_init

        # CodeMapNode.objects.bulk_create — capture the created nodes
        def fake_bulk_create(nodes, batch_size=1000):
            captured_nodes.extend(nodes)
            return nodes

        mock_cmn.objects.bulk_create.side_effect = fake_bulk_create

        call_command("load_maps", source=str(tmp_path))

    return captured_map, captured_nodes


def test_load_maps_command(tmp_path):
    payload = {
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

    captured_map, nodes = _run_load_maps(tmp_path, "OBC_Vol1.json", payload)

    assert captured_map["map_code"] == "OBC_Vol1"
    assert captured_map["code_name"] == "OBC_2024"
    assert len(nodes) == 2

    node = next(n for n in nodes if n.node_id == "1.1.1.1")
    assert node.html == "<p>General</p>"
    assert node.notes_html == "<div>Notes</div>"
    assert node.keywords == ["general", "scope"]
    assert node.page == 7
    assert node.page_end == 9
    assert node.initial_page_top == 640.0
    assert node.final_page_bottom == 88.0


def test_load_maps_allows_missing_span_bounds(tmp_path):
    payload = {
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

    _captured_map, nodes = _run_load_maps(tmp_path, "NBC.json", payload)

    assert len(nodes) == 1
    node = nodes[0]
    assert node.node_id == "B-3.2.9.1."
    assert node.page == 120
    assert node.page_end == 120
    assert node.initial_page_top is None
    assert node.final_page_bottom is None


def test_load_maps_imports_notes_html(tmp_path):
    payload = {
        "code_name": "NBC_2025",
        "sections": [
            {
                "id": "3.1.1",
                "title": "Notes Section",
                "page": 50,
                "page_end": 50,
                "notes_html": "<div>Notes</div>",
            }
        ],
    }

    _captured_map, nodes = _run_load_maps(tmp_path, "NBC_notes.json", payload)

    assert len(nodes) == 1
    assert nodes[0].notes_html == "<div>Notes</div>"


def test_load_maps_legacy_bbox_fallback(tmp_path):
    payload = {
        "code_name": "OBC_2012",
        "sections": [
            {
                "id": "9.10.1",
                "title": "Legacy Bbox",
                "page": 200,
                "page_end": 201,
                "bbox": {"t": 700.0, "b": 50.0},
            }
        ],
    }

    _captured_map, nodes = _run_load_maps(tmp_path, "OBC_legacy.json", payload)

    assert len(nodes) == 1
    node = nodes[0]
    assert node.initial_page_top == 700.0
    assert node.final_page_bottom == 50.0


def test_load_maps_populates_provision_transitions_on_matching_node(tmp_path):
    """_populate_provision_transitions stamps annotations on matching nodes."""
    from core.management.commands.load_maps import _populate_provision_transitions

    fake_node = SimpleNamespace(provision_transitions=None, save=MagicMock())

    with (
        patch("core.management.commands.load_maps.load_transitions") as mock_load,
        patch("core.management.commands.load_maps.CodeEdition") as mock_edition_cls,
        patch("core.management.commands.load_maps.CodeMapNode") as mock_node_cls,
    ):
        mock_load.return_value = [
            {
                "old_edition": "OBC_2012_v08",
                "new_edition": "OBC_2012_v09",
                "overlap_start": "2017-01-01",
                "overlap_end": "2017-07-01",
                "transition_type": "in_stream_project",
                "applicability_text": "Certain provisions apply.",
                "citation_text": "O. Reg. 332/12, s. 4.1.3",
                "scope": "provisions",
                "provisions": [
                    {
                        "new_section_id": "B-8.6.2.2.",
                        "old_provision_ref": "Sentence 8.6.2.2.(5)",
                        "as_read_on": "2016-12-31",
                    }
                ],
            }
        ]

        fake_edition = SimpleNamespace(
            code_name="OBC_2012_v09",
            map_codes=["OBC_Vol1", "OBC_Vol2"],
        )
        mock_edition_cls.objects.filter.return_value.select_related.return_value.first.return_value = (
            fake_edition
        )

        # First filter call (exact match) returns the node
        mock_node_cls.objects.filter.return_value.first.return_value = fake_node

        count = _populate_provision_transitions()

    assert count == 1
    assert fake_node.provision_transitions == [
        {
            "old_provision_ref": "Sentence 8.6.2.2.(5)",
            "as_read_on": "2016-12-31",
            "old_edition": "OBC_2012_v08",
            "citation_text": "O. Reg. 332/12, s. 4.1.3",
            "applicability_text": "Certain provisions apply.",
            "overlap_end": "2017-07-01",
            "transition_type": "in_stream_project",
        }
    ]
    fake_node.save.assert_called_once_with(update_fields=["provision_transitions"])


def test_load_maps_does_not_set_provision_transitions_on_unmatched_node(tmp_path):
    """Nodes not matching a provision-scoped section_id are left untouched."""
    from core.management.commands.load_maps import _populate_provision_transitions

    with (
        patch("core.management.commands.load_maps.load_transitions") as mock_load,
        patch("core.management.commands.load_maps.CodeEdition") as mock_edition_cls,
        patch("core.management.commands.load_maps.CodeMapNode") as mock_node_cls,
    ):
        mock_load.return_value = [
            {
                "old_edition": "OBC_2012_v08",
                "new_edition": "OBC_2012_v09",
                "overlap_start": "2017-01-01",
                "overlap_end": "2017-07-01",
                "transition_type": "in_stream_project",
                "applicability_text": "Applies.",
                "citation_text": "Reg.",
                "scope": "provisions",
                "provisions": [
                    {
                        "new_section_id": "99.99.99",
                        "old_provision_ref": "Sentence 99.99.99.(1)",
                        "as_read_on": "2016-12-31",
                    }
                ],
            }
        ]

        fake_edition = SimpleNamespace(code_name="OBC_2012_v09", map_codes=["OBC_Vol1"])
        mock_edition_cls.objects.filter.return_value.select_related.return_value.first.return_value = (
            fake_edition
        )

        # No node found for any lookup attempt
        mock_node_cls.objects.filter.return_value.first.return_value = None

        count = _populate_provision_transitions()

    assert count == 0


def test_load_maps_span_fields_take_precedence_over_bbox(tmp_path):
    payload = {
        "code_name": "OBC_2012",
        "sections": [
            {
                "id": "9.10.2",
                "title": "Span wins",
                "page": 200,
                "page_end": 200,
                "initial_page_top": 640.0,
                "final_page_bottom": 88.0,
                "bbox": {"t": 999.0, "b": 1.0},
            }
        ],
    }

    _captured_map, nodes = _run_load_maps(tmp_path, "OBC_span.json", payload)

    node = nodes[0]
    assert node.initial_page_top == 640.0
    assert node.final_page_bottom == 88.0
