from api.explain import FACTOR_LABELS


def test_noise_corridor_label_is_user_facing_name():
    label = FACTOR_LABELS["emergency_corridor"]
    assert "noise corridor" in label
    assert "emergency" not in label.lower()
