from dots.admin_demo_dataset import build_admin_demo_dataset


def test_admin_demo_dataset_is_deterministic_and_cross_referenced():
    first = build_admin_demo_dataset()
    second = build_admin_demo_dataset()
    assert first.model_dump() == second.model_dump()
    assert first.provenance.status == "synthetic_demo"
    assert [section.key for section in first.sections] == ["what", "market", "competitors", "profit", "feasibility"]
    assert {item.category for item in first.competitors} == {"direct", "indirect", "alternative"}
    assert first.financials.break_even_sales == 3
    assert all(item.project_id == first.adopted_project_id for item in first.knowledge_assets)
    assert all(decision.project_id == first.adopted_project_id for decision in first.decisions)


def test_demo_provenance_prevents_real_data_misinterpretation():
    dataset = build_admin_demo_dataset()
    serialized = dataset.model_dump_json()
    assert "synthetic_demo" in serialized
    assert "実在の人物・企業・取引を表しません" in serialized
    assert "bank" not in serialized.lower()
    assert "password" not in serialized.lower()
