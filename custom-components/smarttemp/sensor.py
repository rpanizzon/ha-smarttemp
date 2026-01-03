import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    entities = []
    for mac in coordinator.data:
        # Main Controller Sensors
        entities.append(
            SmartTempTempSensor(coordinator, entry.entry_id, mac, "dis_room_temp", "Main Temperature")
        )
        entities.append(SmartTempHumiditySensor(coordinator, entry.entry_id, mac))

        # Zone Sensors
        zone_count = coordinator.data[mac].get("zone_no", 0)
        for i in range(zone_count):
            entities.append(SmartTempZoneTempSensor(coordinator, entry.entry_id, mac, i))

    async_add_entities(entities)


class SmartTempTempSensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, entry_id, mac, field, name):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._mac = mac
        self._field = field
        self._attr_name = f"SmartTemp {name}"
        self._attr_unique_id = f"{entry_id}_{mac}_{field}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")

    @property
    def available(self):
        return bool(self.coordinator.last_update_success and self._mac in self.coordinator.data)

    @property
    def native_value(self):
        # Use the standard get_temp for room_temp
        return self.coordinator.get_temp(self._mac, self._field)


class SmartTempZoneTempSensor(SmartTempTempSensor):
    def __init__(self, coordinator, entry_id, mac, zone_idx):
        super().__init__(coordinator, entry_id, mac, "dis_zonetemp", f"Zone {zone_idx+1} Temperature")
        self._zone_idx = zone_idx
        self._attr_unique_id = f"{entry_id}_{mac}_zone_{zone_idx+1}_temp"

    @property
    def native_value(self):
        # Use the specific zone index method for dis_zonetemp
        return self.coordinator.get_zone_temp(self._mac, self._zone_idx)


class SmartTempHumiditySensor(CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator, entry_id, mac):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._mac = mac
        self._attr_name = "SmartTemp Humidity"
        self._attr_unique_id = f"{entry_id}_{mac}_humidity"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")

    @property
    def available(self):
        return bool(self.coordinator.last_update_success and self._mac in self.coordinator.data)

    @property
    def native_value(self):
        val = self.coordinator.get_field(self._mac, "dis_room_humi")
        return val / 10.0 if val is not None else None

    
class SmartTempFanPolicySensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry_id, mac):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._mac = mac
        self._attr_name = "SmartTemp Fan Policy"
        self._attr_unique_id = f"{entry_id}_{mac}_fan_policy"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")

    @property
    def available(self):
        return bool(self.coordinator.last_update_success and self._mac in self.coordinator.data)

    @property
    def native_value(self):
        policy = self.coordinator.get_field(self._mac, "fan_mode", 0)
        return "Continuous" if policy == 1 else "Auto"
