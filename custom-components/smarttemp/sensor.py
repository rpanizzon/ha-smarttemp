import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect # Missing import added
from .const import DOMAIN, NEW_DEVICE_SIGNAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartTemp sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    known_devices = set()

    def add_new_sensors(mac=None):
        """Callback to add sensors when pair_key is received."""
        
        # Define a small internal function to actually do the adding
        async def _async_add():
            new_entities = []
            target_macs = [mac] if mac else [
                m for m, d in coordinator.data.items() if "pair_key" in d
            ]

            for device_mac in target_macs:
                if device_mac not in known_devices:
                    _LOGGER.info("Registering sensors for %s", device_mac)
                    
                    # Main Sensors
                    new_entities.append(SmartTempTempSensor(coordinator, entry.entry_id, device_mac, "dis_room_temp", "Main Temperature"))
                    new_entities.append(SmartTempHumiditySensor(coordinator, entry.entry_id, device_mac))
                    
                    # Zone Sensors
                    zone_count = coordinator.data[device_mac].get("zone_no", 0)
                    if isinstance(zone_count, list): zone_count = zone_count[0]
                    for i in range(zone_count):
                        new_entities.append(SmartTempZoneTempSensor(coordinator, entry.entry_id, device_mac, i))

                    known_devices.add(device_mac)

            if new_entities:
                # REMOVE 'await' here. async_add_entities handles the scheduling.
                _LOGGER.info("Adding %d sensors to Home Assistant", len(new_entities))
                async_add_entities(new_entities)

        # Ensure this is wrapped in add_job to stay on the MainThread
        hass.add_job(_async_add())            
            
    # Listen for discovery signal
    entry.async_on_unload(
        async_dispatcher_connect(hass, NEW_DEVICE_SIGNAL, add_new_sensors)
    )

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
        # FIX: For the main sensor, use get_room_temp to handle the [244, 0, 0, 0] format 
        if self._field == "dis_room_temp":
            return self.coordinator.get_room_temp(self._mac)
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
        # Uses dis_room_humi[0] 
        return self.coordinator.get_humidity(self._mac)

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
