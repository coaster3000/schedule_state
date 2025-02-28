"""Tests the schedule_state sensor."""
from datetime import date, datetime, time, timedelta
import logging
from typing import Any
from unittest.mock import patch

from homeassistant import setup
from homeassistant.components import input_boolean
from homeassistant.components.sensor import DOMAIN as SENSOR
from homeassistant.const import (
    CONF_ICON,
    CONF_ID,
    CONF_STATE,
    SERVICE_TOGGLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt
import yaml

from custom_components.schedule_state.const import (
    CONF_DURATION,
    CONF_END,
    CONF_EXTRA_ATTRIBUTES,
    CONF_START,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

TIME_FUNCTION_PATH = "custom_components.schedule_state.sensor.dt_now"

DATE_FUNCTION_PATH = "homeassistant.components.workday.binary_sensor.get_date"

test_tz = dt.get_time_zone("America/Toronto")
dt.set_default_time_zone(test_tz)


async def setup_test_entities(hass: HomeAssistant, config_dict: dict[str, Any]) -> None:
    """Set up a test schedule_state sensor entity."""
    ret = await setup.async_setup_component(
        hass,
        SENSOR,
        {
            SENSOR: [
                {**config_dict},
            ]
        },
    )
    await hass.async_block_till_done()
    assert ret, "Setup failed"


async def test_blank_setup(hass: HomeAssistant) -> None:
    await setup_test_entities(hass, {"platform": DOMAIN})


def basic_test(
    configfile: str,
    overrides: dict = {},
    check_icon: bool = False,
    check_midnight: bool = False,
):
    sensorname = configfile.replace("tests/", "").replace(".yaml", "")

    async def fn(hass: HomeAssistant) -> None:
        """Test basic schedule_state setup."""

        with open(configfile) as f:
            config = yaml.safe_load(f)

        now = make_testtime(4, 0)
        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await setup_test_entities(
                hass,
                config[0],
            )

            assert p.called, "Time patch was not applied"
            assert p.return_value == now, "Time patch was wrong"

        def check_override(phase, expected):
            if phase in overrides:
                # overrides are due to errors, so check that they are identified as such
                assert expected in sensor._attributes["errors"]
                return overrides[phase]
            return expected

        # get the "Sleep Schedule" sensor
        sensor = [e for e in hass.data["sensor"].entities][-1]

        now += timedelta(minutes=10)  # 4:10
        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await sensor.async_update_ha_state(force_refresh=True)

            entity_state = check_state(
                hass,
                f"sensor.{sensorname}",
                check_override("asleep1", "asleep"),
                p,
                now,
            )
            assert (
                entity_state.attributes["friendly_name"] == sensorname
            ), "Friendly name was wrong"

        now += timedelta(hours=16)  # 20:10
        await check_state_at_time(hass, sensor, now, "awake")
        if check_icon:
            assert sensor._attr_icon == "mdi:run", "Icon is wrong"
        assert sensor._attributes["friendly_start"] == "05:30:00"
        assert sensor._attributes["friendly_end"] == "22:30:00"

        # add an override
        now += timedelta(minutes=10)  # 20:20
        await set_override(
            hass, f"sensor.{sensorname}", now, "drowsy", duration=15, icon="mdi:cog"
        )

        # check that override state is en effect
        now += timedelta(minutes=10)  # 20:30
        await check_state_at_time(hass, sensor, now, "drowsy")
        if check_icon:
            assert sensor._attr_icon == "mdi:cog", "Icon was wrong"

        # check that override has expired
        now += timedelta(minutes=10)  # 20:40
        await check_state_at_time(hass, sensor, now, "awake")
        if check_icon:
            assert sensor._attr_icon == "mdi:run", "Icon was wrong"

        # check that we have reverted back to normal schedule
        now += timedelta(hours=2)  # 22:40
        await check_state_at_time(
            hass, sensor, now, check_override("asleep2", "asleep")
        )
        if check_icon:
            assert sensor._attr_icon == "mdi:sleep", "Icon was wrong"

        if check_midnight:
            assert sensor._attributes["friendly_end"] == "midnight"
            assert sensor._attributes["end"] == time.max
        else:
            # check that reported end time has wrapped
            assert sensor._attributes["friendly_end"] == "05:30:00"

        # check toggle - this should be ignored because the schedule does not have on/off states
        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_TOGGLE,
                # service_data=data,
                blocking=True,
                target={
                    "entity_id": f"sensor.{sensorname}",
                },
            )
            await hass.async_block_till_done()

        now += timedelta(minutes=2)  # 22:42
        await check_state_at_time(hass, sensor, now, "asleep")

    return fn


test_basic_setup = basic_test("tests/test000.yaml", check_icon=True)

test_basic_setup_timestamps = basic_test("tests/test006.yaml")

test_basic_setup_isoformat = basic_test("tests/test007.yaml")

test_basic_setup_with_errors = basic_test(
    "tests/test008.yaml", overrides=dict(asleep1="default"), check_midnight=True
)

test_basic_setup_isoformat2 = basic_test("tests/test009.yaml")


async def test_basic_setup_with_error(hass: HomeAssistant) -> None:
    """Test basic schedule_state setup."""
    now = make_testtime(4, 0)

    with open("tests/test005.yaml") as f:
        config = yaml.safe_load(f)

    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            config[0],
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now, "Time patch was wrong"

    # get the "test005" sensor
    sensor = [e for e in hass.data["sensor"].entities][-1]

    # check that the state with the error is detected
    assert "awake" in sensor._attributes["errors"]

    now += timedelta(minutes=10)  # 4:10
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(hass, "sensor.test005", "asleep", p, now)
        assert (
            entity_state.attributes["friendly_name"] == "test005"
        ), "Friendly name was wrong"

    # awake state was not loaded - the default state should be seen
    now += timedelta(hours=16)  # 20:10
    await check_state_at_time(hass, sensor, now, "default")

    # check that the rest of the schedule is ok
    now += timedelta(hours=2, minutes=30)  # 22:40
    await check_state_at_time(hass, sensor, now, "asleep")


async def test_overrides(hass: HomeAssistant) -> None:
    """Test schedule_state overrides."""
    now = make_testtime(4, 0)

    with open("tests/test000.yaml") as f:
        config = yaml.safe_load(f)

    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            config[0],
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now

    # get the "test000" sensor
    sensor = [e for e in hass.data["sensor"].entities][-1]

    now += timedelta(minutes=10)  # 4:10
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(hass, "sensor.test000", "asleep", p, now)
        assert entity_state.attributes["friendly_name"] == "test000"

    now += timedelta(hours=16)  # 20:10
    await check_state_at_time(hass, sensor, now, "awake")

    # add an invalid override
    await set_override(hass, "sensor.test000", now, "drowsy")
    now += timedelta(minutes=1)  # 20:11
    await check_state_at_time(hass, sensor, now, "awake")

    # add an override
    now += timedelta(minutes=9)  # 20:20
    await set_override(hass, "sensor.test000", now, "drowsy", duration=15)

    # check that override state is en effect
    now += timedelta(minutes=10)  # 20:30
    await check_state_at_time(hass, sensor, now, "drowsy")

    # clear the override and check that we are back to normal
    now += timedelta(minutes=1)  # 20:31
    await clear_overrides(hass, "sensor.test000", now)
    now += timedelta(minutes=1)  # 20:32
    await check_state_at_time(hass, sensor, now, "awake")

    # recalculate the schedule - no change expected - this service is not so useful anymore
    now += timedelta(minutes=1)  # 20:33
    await recalculate(hass, "sensor.test000", now)
    now += timedelta(minutes=1)  # 20:34
    await check_state_at_time(hass, sensor, now, "awake")

    now += timedelta(minutes=1)  # 20:35
    await set_override(hass, "sensor.test000", now, "testing", end="22:15")
    now += timedelta(hours=1)  # 21:35
    await check_state_at_time(hass, sensor, now, "testing")
    now += timedelta(hours=1)  # 22:35
    await check_state_at_time(hass, sensor, now, "asleep")

    await clear_overrides(hass, "sensor.test000", now)
    now += timedelta(minutes=1)  # 22:36
    await clear_overrides(hass, "sensor.test000", now)

    # add an override that goes into the next day
    await set_override(
        hass, "sensor.test000", now, "feisty", duration=120, id="override123"
    )
    now += timedelta(minutes=4)  # 22:40
    await check_state_at_time(hass, sensor, now, "feisty")

    # check wraparound
    now = make_testtime(0, 30)
    await check_state_at_time(hass, sensor, now, "feisty")
    now = make_testtime(0, 36)
    await check_state_at_time(hass, sensor, now, "asleep")

    # edit split override, check that split disappears
    now = make_testtime(22, 45)
    await set_override(
        hass, "sensor.test000", now, "feisty", duration=20, id="override123"
    )
    await check_state_at_time(hass, sensor, now, "feisty")
    now += timedelta(minutes=21)
    await check_state_at_time(hass, sensor, now, "asleep")
    now = make_testtime(0, 30)
    await check_state_at_time(hass, sensor, now, "asleep")

    now = make_testtime(22, 45)
    await set_override(
        hass,
        "sensor.test000",
        now,
        "feisty",
        start="22:40",
        end="23:59:59",
        id="override123",
    )

    # add a zero-length override
    await set_override(
        hass,
        "sensor.test000",
        now,
        "ignored",
        start=now.time().isoformat(),
        end=now.time().isoformat(),
    )
    await check_state_at_time(hass, sensor, now, "feisty")

    # add invalid override (all start/end/duration)
    await set_override(
        hass, "sensor.test000", now, "ignored", start="22:50", end="23:10", duration=5
    )
    await check_state_at_time(hass, sensor, now, "feisty")

    # add invalid override (only start)
    await set_override(hass, "sensor.test000", now, "ignored", start="22:50")
    await check_state_at_time(hass, sensor, now, "feisty")

    # add invalid override (start>end, same day)
    await set_override(
        hass, "sensor.test000", now, "ignored", end="22:50", start="23:10"
    )
    await check_state_at_time(hass, sensor, now, "feisty")


async def test_overrides_with_id(hass: HomeAssistant) -> None:
    """Test schedule_state overrides with ids."""
    now = make_testtime(4, 0)

    with open("tests/test000.yaml") as f:
        config = yaml.safe_load(f)

    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            config[0],
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now

    # get the "test000" sensor
    sensor = [e for e in hass.data["sensor"].entities][-1]

    now += timedelta(minutes=10)  # 4:10
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(hass, "sensor.test000", "asleep", p, now)
        assert entity_state.attributes["friendly_name"] == "test000"

    # test editing and removal of overrides
    # add an override for the work day (state=work id=work)
    await set_override(
        hass, "sensor.test000", now, "work", start="9:00", end="17:00", id="work"
    )
    now = make_testtime(9, 0)
    await check_state_at_time(hass, sensor, now, "work")

    # shift the work day to start at 10
    await set_override(
        hass, "sensor.test000", now, "work", start="10:00", duration=8 * 60, id="work"
    )
    await check_state_at_time(hass, sensor, now, "awake")

    # create a lunch break (state=awake id=lunch)
    await set_override(
        hass, "sensor.test000", now, "awake", duration=60, end="13:00", id="lunch"
    )
    now = make_testtime(12, 30)
    await check_state_at_time(hass, sensor, now, "awake")

    # extend lunch break by an hour from now (12:30-13:30)
    await set_override(hass, "sensor.test000", now, "lunch", duration=60, id="lunch")
    now = make_testtime(13, 25)
    await check_state_at_time(hass, sensor, now, "lunch")

    # back to work
    now = make_testtime(13, 30)
    await check_state_at_time(hass, sensor, now, "work")

    # remove override by id
    await remove_override(hass, "sensor.test000", now, id="work")
    await check_state_at_time(hass, sensor, now, "awake")

    # try to remove with invalid id
    await remove_override(hass, "sensor.test000", now, id="work")

    # backtrack to lunch time
    now = make_testtime(13, 25)
    await check_state_at_time(hass, sensor, now, "lunch")

    # clear all overrides
    await clear_overrides(hass, "sensor.test000", now)
    await recalculate(hass, "sensor.test000", now)
    await check_state_at_time(hass, sensor, now, "awake")


def schedule_modified_by_template(configfile: str):
    sensorname = configfile.replace("tests/", "").replace(".yaml", "")

    async def fn(hass: HomeAssistant) -> None:

        mode_switch = "input_boolean.mode"
        assert await setup.async_setup_component(
            hass, input_boolean.DOMAIN, {"input_boolean": {"mode": None}}
        )

        with open(configfile) as f:
            config = yaml.safe_load(f)

        now = make_testtime(4, 0)
        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await setup_test_entities(
                hass,
                config[0],
            )

            sensor = [e for e in hass.data["sensor"].entities][-1]
            check_state(hass, f"sensor.{sensorname}", "off", p, now)

        assert len(sensor._attributes["errors"]) == 0

        hass.states.async_set(mode_switch, "on")
        await hass.async_block_till_done()

        now += timedelta(hours=8, minutes=1)  # 12:01
        await check_state_at_time(hass, sensor, now, "on")

        hass.states.async_set(mode_switch, "off")
        await hass.async_block_till_done()

        await check_state_at_time(hass, sensor, now, "off")

        now += timedelta(hours=2)  # 14:01
        await check_state_at_time(hass, sensor, now, "off")

        # check toggle/turn on/turn off
        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_TOGGLE,
                # service_data=data,
                blocking=True,
                target={
                    "entity_id": f"sensor.{sensorname}",
                },
            )
            await hass.async_block_till_done()

        now += timedelta(minutes=2)  # 14:03
        await check_state_at_time(hass, sensor, now, "on")

        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_TURN_OFF,
                # service_data=data,
                blocking=True,
                target={
                    "entity_id": f"sensor.{sensorname}",
                },
            )
            await hass.async_block_till_done()

        now += timedelta(minutes=2)  # 14:05
        await check_state_at_time(hass, sensor, now, "off")

        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_TURN_ON,
                # service_data=data,
                blocking=True,
                target={
                    "entity_id": f"sensor.{sensorname}",
                },
            )
            await hass.async_block_till_done()

        now += timedelta(minutes=2)  # 14:07
        await check_state_at_time(hass, sensor, now, "on")

        await remove_override(hass, f"sensor.{sensorname}", now, id="turn_on_off")
        now += timedelta(minutes=2)  # 14:09
        await check_state_at_time(hass, sensor, now, "off")

    return fn


def schedule_modified_by_template_with_error(configfile: str):
    sensorname = configfile.replace("tests/", "").replace(".yaml", "")

    async def fn(hass: HomeAssistant) -> None:

        mode_switch = "input_boolean.mode"
        assert await setup.async_setup_component(
            hass, input_boolean.DOMAIN, {"input_boolean": {"mode": None}}
        )

        with open(configfile) as f:
            config = yaml.safe_load(f)

        now = make_testtime(4, 0)
        with patch(TIME_FUNCTION_PATH, return_value=now) as p:
            await setup_test_entities(
                hass,
                config[0],
            )

            sensor = [e for e in hass.data["sensor"].entities][-1]
            check_state(hass, f"sensor.{sensorname}", "off", p, now)

        assert "on" in sensor._attributes["errors"]

        hass.states.async_set(mode_switch, "off")
        await hass.async_block_till_done()

        now += timedelta(hours=8, minutes=1)  # 12:01
        await check_state_at_time(hass, sensor, now, "off")

        hass.states.async_set(mode_switch, "off")
        await hass.async_block_till_done()

        await check_state_at_time(hass, sensor, now, "off")

        now += timedelta(hours=2)  # 14:01
        await check_state_at_time(hass, sensor, now, "off")

    return fn


test_schedule_modified_by_template1 = schedule_modified_by_template(
    "tests/test001.yaml"
)

test_schedule_modified_by_template2 = schedule_modified_by_template(
    "tests/test002.yaml"
)

test_schedule_modified_by_template3 = schedule_modified_by_template(
    "tests/test003.yaml"
)

test_schedule_modified_by_template4_with_error = (
    schedule_modified_by_template_with_error("tests/test004.yaml")
)


async def test_schedule_using_condition(hass: HomeAssistant):
    workday = "binary_sensor.workday_sensor"

    configfile = "tests/test011.yaml"
    with open(configfile) as f:
        config = yaml.safe_load(f)

    # no workday sensor, not a holiday, early morning
    now = make_testtime(4, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            config[0],
        )

        sensor = [e for e in hass.data["sensor"].entities][-1]
        check_state(hass, "sensor.test011", "nighttime", p, now)

    with patch(DATE_FUNCTION_PATH, return_value=date(2021, 11, 19)) as p:
        # now install workday sensor
        await setup.async_setup_component(
            hass,
            "binary_sensor",
            {
                "binary_sensor": {
                    "platform": "workday",
                    "country": "CA",
                    # "province": "ON",
                }
            },
        )
        await hass.async_block_till_done()
        await sensor.async_update_ha_state(force_refresh=True)

        assert p.called, "Time patch was not applied"

        workday_sensor = [e for e in hass.data["binary_sensor"].entities][-1]
        _LOGGER.warn("workday sensor is %r", workday_sensor)

        check_state(hass, workday, "on")

        now += timedelta(minutes=10)  # 4:10
        await check_state_at_time(hass, sensor, now, "nighttime")

        now += timedelta(hours=3)  # 7:10
        await check_state_at_time(hass, sensor, now, "daybreak")

        now += timedelta(hours=3)  # 10:10
        await check_state_at_time(hass, sensor, now, "working")

        now += timedelta(hours=6)  # 16:10
        await check_state_at_time(hass, sensor, now, "afternoon")

    with patch(DATE_FUNCTION_PATH, return_value=date(2021, 12, 25)) as p:
        await hass.async_block_till_done()
        await workday_sensor.async_update_ha_state(force_refresh=True)

        assert p.called, "Time patch was not applied"

        check_state(hass, workday, "off")

        now = make_testtime(4, 0)
        await check_state_at_time(hass, sensor, now, "nighttime")

        now += timedelta(hours=3)  # 7:00
        await check_state_at_time(hass, sensor, now, "nighttime")

        now += timedelta(hours=2)  # 9:00
        await check_state_at_time(hass, sensor, now, "daybreak")

        now += timedelta(hours=13, minutes=28)  # 22:28
        await check_state_at_time(hass, sensor, now, "evening")


async def test_extra_attributes(hass: HomeAssistant):
    configfile = "tests/../.devcontainer/schedules/fan-coil.yaml"
    sensorname = "fan_coil_heating_schedule"

    # switch used to toggle template values
    mode_switch = "input_boolean.mode"
    assert await setup.async_setup_component(
        hass, input_boolean.DOMAIN, {"input_boolean": {"mode": None}}
    )

    with open(configfile) as f:
        config = yaml.safe_load(f)

    now = make_testtime(4, 0)
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await setup_test_entities(
            hass,
            config[0],
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now, "Time patch was wrong"

        sensor = [e for e in hass.data["sensor"].entities][-1]
        check_state(hass, f"sensor.{sensorname}", "temp_night", p, now)

        assert len(sensor._attributes["errors"]) == 0
        assert sensor._attributes["fan_mode"] == "low"

    hass.states.async_set(mode_switch, "on")
    await hass.async_block_till_done()

    now += timedelta(minutes=10)  # 4:10
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(
            hass,
            f"sensor.{sensorname}",
            "temp_night",
            p,
            now,
        )
        assert (
            entity_state.attributes["friendly_name"] == "Fan coil heating schedule"
        ), "Friendly name was wrong"

        assert entity_state.attributes["swing_mode"] == "off"
        assert entity_state.attributes["fan_mode"] == "low"

    now += timedelta(hours=9)  # 13:10
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(
            hass,
            f"sensor.{sensorname}",
            "temp_day",
            p,
            now,
        )

        assert entity_state.attributes["swing_mode"] == "default-off"
        assert entity_state.attributes["fan_mode"] == "high"

    # flick the switch off - check that default value changes
    hass.states.async_set(mode_switch, "off")
    await hass.async_block_till_done()

    now += timedelta(minutes=1)  # 13:11
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)
        assert entity_state.attributes["swing_mode"] == "default-off"
    now -= timedelta(minutes=1)  # 13:10

    # switch is on again
    hass.states.async_set(mode_switch, "on")
    await hass.async_block_till_done()

    now += timedelta(hours=10)  # 23:10
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(
            hass,
            f"sensor.{sensorname}",
            "temp_evening",
            p,
            now,
        )

        assert entity_state.attributes["swing_mode"] == "vertical"
        assert entity_state.attributes["fan_mode"] == "mid"

    # flick the switch off
    hass.states.async_set(mode_switch, "off")
    await hass.async_block_till_done()

    now += timedelta(minutes=5)  # 23:15
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)

        entity_state = check_state(
            hass,
            f"sensor.{sensorname}",
            "temp_evening",
            p,
            now,
        )

        assert entity_state.attributes["swing_mode"] == "wavy"
        assert entity_state.attributes["fan_mode"] == "very-high"

    # flick the switch back on
    hass.states.async_set(mode_switch, "on")
    await hass.async_block_till_done()

    now += timedelta(minutes=5)  # 23:20
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)
        assert sensor._attributes["swing_mode"] == "horizontal"
        assert sensor._attributes["fan_mode"] == "mid"

    # add an override for an attribute
    now += timedelta(minutes=5)  # 23:25
    await set_override(
        hass,
        f"sensor.{sensorname}",
        now,
        "temp_evening",
        duration=15,
        extra_attributes=dict(fan_mode="override", bogus_attribute="should_be_ignored"),
    )

    # check that it took effect
    now += timedelta(minutes=5)  # 23:30
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)
        assert sensor._attributes["swing_mode"] == "horizontal"
        assert sensor._attributes["fan_mode"] == "override"
        assert "bogus_attribute" not in sensor._attributes

    # check that it's cleared
    now += timedelta(minutes=16)  # 23:46
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)
        assert sensor._attributes["swing_mode"] == "horizontal"
        assert sensor._attributes["fan_mode"] == "mid"


async def check_state_at_time(hass, sensor, now, value):
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await sensor.async_update_ha_state(force_refresh=True)
        return check_state(hass, sensor.entity_id, value, p, now)


def check_state(hass, name, value, p=None, now=None):
    entity_state = hass.states.get(name)
    assert entity_state, f"Entity {name} does not exist"
    if p is not None:
        assert p.called, "Time patch was not applied"
        if now is not None:
            assert p.return_value == now, "Time patch was wrong"
    assert (
        entity_state.state == value
    ), f"State was wrong (actual={entity_state.state} vs expected={value})"
    return entity_state


async def set_override(
    hass,
    target,
    now,
    state,
    start=None,
    end=None,
    duration=None,
    icon=None,
    extra_attributes=None,
    id=None,
):
    data = {CONF_STATE: state}
    if id is not None:
        data[CONF_ID] = id
    if start is not None:
        data[CONF_START] = start
    if end is not None:
        data[CONF_END] = end
    if duration is not None:
        data[CONF_DURATION] = duration
    if icon is not None:
        data[CONF_ICON] = icon
    if extra_attributes is not None:
        data[CONF_EXTRA_ATTRIBUTES] = extra_attributes

    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await hass.services.async_call(
            DOMAIN,
            "set_override",
            service_data=data,
            blocking=True,
            target={
                "entity_id": target,
            },
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now


async def remove_override(hass, target, now, id):
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await hass.services.async_call(
            DOMAIN,
            "remove_override",
            blocking=True,
            target={
                "entity_id": target,
                "id": id,
            },
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now


async def clear_overrides(hass, target, now):
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await hass.services.async_call(
            DOMAIN,
            "clear_overrides",
            blocking=True,
            target={
                "entity_id": target,
            },
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now


async def recalculate(hass, target, now):
    with patch(TIME_FUNCTION_PATH, return_value=now) as p:
        await hass.services.async_call(
            DOMAIN,
            "recalculate",
            blocking=True,
            target={
                "entity_id": target,
            },
        )

        assert p.called, "Time patch was not applied"
        assert p.return_value == now


def make_testtime(h: int, m: int):
    return datetime(2021, 11, 20, h, m)
