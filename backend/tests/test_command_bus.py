from app.commands.command_bus import CommandBus, Layer


def test_no_fire_before_dwell_elapsed():
    bus = CommandBus(dwell_sec=0.5, refractory_sec=0.2)
    assert bus.feed("calm", now=0.0) is None
    assert bus.feed("calm", now=0.2) is None  # still within dwell window


def test_fires_after_dwell_elapsed():
    bus = CommandBus(dwell_sec=0.5, refractory_sec=0.2)
    bus.feed("calm", now=0.0)
    assert bus.feed("calm", now=0.6) == "calm"


def test_refractory_blocks_immediate_refire():
    bus = CommandBus(dwell_sec=0.1, refractory_sec=0.5)
    bus.feed("calm", now=0.0)
    assert bus.feed("calm", now=0.2) == "calm"
    # Still within refractory period even though dwell would be satisfied again.
    assert bus.feed("calm", now=0.25) is None


def test_none_label_resets_dwell():
    bus = CommandBus(dwell_sec=0.5, refractory_sec=0.1)
    bus.feed("calm", now=0.0)
    bus.feed(None, now=0.2)  # user looked away / low confidence
    assert bus.feed("calm", now=0.3) is None  # dwell restarts


def test_switch_layer_resets_and_enters_refractory():
    bus = CommandBus(dwell_sec=0.5, refractory_sec=0.3)
    bus.switch_layer(Layer.TRANSPORT)
    assert bus.layer == Layer.TRANSPORT
    assert bus.feed("play_pause", now=0.0) is None  # blocked by post-switch refractory
