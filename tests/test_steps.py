from custom_components.strom_assistent.logic.steps import StepDetector


def feed(det, series):
    return [s for t, v in series if (s := det.update(t, v))]


def test_detects_held_step():
    det = StepDetector(300, 60)
    steps = feed(det, [(0, 100), (10, 100), (20, 2100), (40, 2105), (70, 2100), (90, 2100)])
    assert len(steps) == 1
    assert steps[0].delta_w == 2000 and steps[0].before_w == 100


def test_ignores_short_spike():
    det = StepDetector(300, 60)
    assert feed(det, [(0, 100), (10, 2100), (20, 100), (100, 100)]) == []


def test_detects_off_step():
    det = StepDetector(300, 30)
    steps = feed(det, [(0, 2100), (10, 100), (50, 100)])
    assert len(steps) == 1 and steps[0].delta_w == -2000
