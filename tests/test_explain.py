from api.explain import FACTOR_LABELS


def test_noise_corridor_label_is_user_facing_name():
    label = FACTOR_LABELS["emergency_corridor"]
    assert "noise corridor" in label
    assert "emergency" not in label.lower()


def test_v2_1_factor_labels_are_the_pill_names():
    assert FACTOR_LABELS["gas_convenience"] == "gas & convenience"
    assert FACTOR_LABELS["traffic"] == "traffic"
    assert FACTOR_LABELS["shopping"] == "shopping"
    assert FACTOR_LABELS["recreation"] == "recreation"
    assert FACTOR_LABELS["emergency_corridor"] == "noise corridor"
    assert FACTOR_LABELS["bar"] == "bars"
    assert len(FACTOR_LABELS) == 13


def test_explanation_text_uses_the_new_labels():
    from api.explain import build_explanation
    from api.schemas import SubScores

    text = build_explanation(SubScores(shopping=95, traffic=10, gas_convenience=50))
    assert "strongest factor is shopping (95/100)" in text
    assert "weakest factor is traffic (10/100)" in text
    assert "gas & convenience 50/100" in text
