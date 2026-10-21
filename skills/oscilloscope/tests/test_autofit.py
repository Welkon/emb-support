import pytest


def test_snap_uses_the_1_2_5_sequence(scope):
    assert scope.snap(0.037) == pytest.approx(0.05)
    assert scope.snap(0.11) == pytest.approx(0.1)
    assert scope.snap(2.5e-4) == pytest.approx(2e-4)
    assert scope.snap(None) is None


def test_clipping_doubles_scale_and_centers_the_trace(scope):
    stats = {"vmin": 0.0, "vmax": 4.0, "vpp": 4.0}
    adjustment = scope.suggest(stats, [{"code": "CLIPPING"}], scale=0.5,
                               timebase=1e-3, offset_for_center=lambda v: -v)
    assert adjustment.scale == pytest.approx(1.0)
    assert adjustment.offset == pytest.approx(-2.0)


def test_low_resolution_uses_a_finer_scale(scope):
    stats = {"vmin": 0.0, "vmax": 0.1, "vpp": 0.1}
    adjustment = scope.suggest(stats, [{"code": "LOW_RESOLUTION"}], scale=1.0,
                               timebase=1e-3, offset_for_center=lambda v: v)
    assert adjustment.scale == pytest.approx(0.02)


def test_dc_offset_centers_without_touching_scale(scope):
    stats = {"vmin": 3.0, "vmax": 4.0, "vpp": 1.0}
    adjustment = scope.suggest(stats, [{"code": "DC_OFFSET"}], scale=0.5,
                               timebase=1e-3, offset_for_center=lambda v: -v)
    assert adjustment.offset == pytest.approx(-3.5)
    assert adjustment.scale is None


def test_aliasing_speeds_up_the_timebase(scope):
    stats = {"vmin": 0.0, "vmax": 3.3, "vpp": 3.3, "period": 1e-3}
    adjustment = scope.suggest(stats, [{"code": "ALIASING"}], scale=1.0,
                               timebase=1e-3, offset_for_center=lambda v: v)
    assert adjustment.timebase < 1e-3


def test_trigger_level_outside_the_signal_moves_to_mid(scope):
    stats = {"vmin": 0.0, "vmax": 3.3, "vpp": 3.3}
    adjustment = scope.suggest(stats, [], scale=1.0, timebase=1e-3,
                               offset_for_center=lambda v: v, trigger_level=4.0)
    assert adjustment.trigger_level == pytest.approx(1.65)


def test_a_clean_capture_needs_no_adjustment(scope):
    stats = {"vmin": 0.0, "vmax": 3.3, "vpp": 3.3, "period": 1e-3}
    assert scope.suggest(stats, [], scale=0.5, timebase=1e-3,
                         offset_for_center=lambda v: v) is None


def test_apply_to_plan_creates_the_channel(scope):
    plan = scope.Plan()
    scope.apply_to_plan(plan, scope.Adjustment("x", scale=0.2, offset=-1.0,
                                               timebase=1e-3, trigger_level=1.2), 1)
    assert plan.channels[0].n == 1
    assert plan.channels[0].scale == pytest.approx(0.2)
    assert plan.channels[0].offset == pytest.approx(-1.0)
    assert plan.timebase == pytest.approx(1e-3)
    assert plan.trigger.level == pytest.approx(1.2)
