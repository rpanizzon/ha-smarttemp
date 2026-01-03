import logging
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import (
    DOMAIN,
    MAP_HA_TO_SMARTTEMP,
    MAP_SMARTTEMP_TO_HA,
    TEMP_SCALE_FACTOR,
    NEW_DEVICE_SIGNAL
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Climate entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    hub = data["hub"]
    known_devices = set()

    async def async_add_new_entities(mac=None):
        """Triggered by the dispatcher when pair_key is received."""
        new_entities = []
        # Only process MACs that have sent their pair_key info
        target_macs = [mac] if mac else [
            m for m, d in coordinator.data.items() if "pair_key" in d
        ]

        for device_mac in target_macs:
            # Use a unique identifier for the set of entities for this MAC
            if f"{device_mac}_registered" not in known_devices:
                _LOGGER.info("Triggering discovery via pair_key for %s", device_mac)

                # 1. Add Main Controller
                new_entities.append(SmartTempAC(coordinator, entry.entry_id, hub, device_mac))

                # 2. Add Zones based on the now-guaranteed zone_no
                device_data = coordinator.data.get(device_mac, {})
                zone_count = device_data.get("zone_no", 0)

                # Handle potential list wrap [8] vs 8
                if isinstance(zone_count, list):
                    zone_count = zone_count[0] if zone_count else 0

                for i in range(zone_count):
                    _LOGGER.info("Creating zone %d for %s", i + 1, device_mac)
                    new_entities.append(SmartTempZone(coordinator, entry.entry_id, hub, device_mac, i))

                # Mark this entire hardware set as registered
                known_devices.add(f"{device_mac}_registered")

        if new_entities:
            async_add_entities(new_entities)

    # Listen for the signal from the Coordinator
    entry.async_on_unload(
        async_dispatcher_connect(hass, NEW_DEVICE_SIGNAL, async_add_new_entities)
    )

    # Initial check for devices already discovered by the Hub
    if coordinator.data:
        await async_add_new_entities()


class SmartTempBase(CoordinatorEntity, ClimateEntity):
    """Base class for SmartTemp climate entities."""
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, entry_id, hub, mac):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.hub = hub
        self._mac = mac
        self._entry_id = entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=f"SmartTemp {mac}"
        )

    @property
    def available(self):
        """Return True if the device is connected and coordinator has data."""
        return bool(
            self.coordinator.last_update_success
            and self._mac in self.coordinator.data
        )

    @property
    def should_poll(self):
        return False

    @property
    def current_temperature(self):
        # The main unit uses the controller's built-in sensor
        return self.coordinator.get_temp(self._mac, "dis_room_temp")


class SmartTempAC(SmartTempBase):
    """Representation of the Main AC Unit."""

    def __init__(self, coordinator, entry_id, hub, mac):
        super().__init__(coordinator, entry_id, hub, mac)
        self._attr_unique_id = f"{entry_id}_{mac}_main"
        self._attr_name = "Main Controller"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.PRESET_MODE
        )
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.AUTO
        ]

        # Mapping to 'fan_speed' (0:Auto, 1:Low, 2:Med, 3:High)
        self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]

        # Mapping to 'fan_mode' (0:Auto/Cycle, 1:Continuous)
        self._attr_preset_modes = ["Auto Fan", "Continuous Fan"]

    @property
    def hvac_mode(self):
        mode = self.coordinator.get_field(self._mac, "equip_mode", 0)
        if isinstance(mode, list):
            mode = mode[0] if mode else 0
        return MAP_SMARTTEMP_TO_HA.get(mode, HVACMode.OFF)

    async def async_set_hvac_mode(self, hvac_mode):
        mode_val = MAP_HA_TO_SMARTTEMP.get(hvac_mode, 0)
        await self.hub.send_smarttemp_command(self._mac, {"equip_mode": mode_val})

    @property
    def current_temperature(self):
        return self.coordinator.get_temp(self._mac, "dis_room_temp")

    @property
    def current_humidity(self):
        return self.coordinator.get_humidity(self._mac)

    @property
    def target_temperature(self):
        mode = self.hvac_mode
        field = "heatset" if mode == HVACMode.HEAT else "coolset"
        return self.coordinator.get_temp(self._mac, field)

    async def async_set_temperature(self, **kwargs):
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        mode = self.hvac_mode
        field = "heatset" if mode == HVACMode.HEAT else "coolset"
        await self.hub.send_smarttemp_command(self._mac, {field: int(temp * 10)})

    @property
    def fan_mode(self):
        """Report Fan Speed."""
        speed = self.coordinator.get_field(self._mac, "fan_speed", 0)
        if isinstance(speed, list):
            speed = speed[0] if speed else 0
        mapping = {0: FAN_AUTO, 1: FAN_LOW, 2: FAN_MEDIUM, 3: FAN_HIGH}
        return mapping.get(speed, FAN_AUTO)

    async def async_set_fan_mode(self, fan_mode):
        """Set Fan Speed (fan_speed)."""
        mapping = {FAN_AUTO: 0, FAN_LOW: 1, FAN_MEDIUM: 2, FAN_HIGH: 3}
        await self.hub.send_smarttemp_command(
            self._mac, {"fan_speed": mapping.get(fan_mode, 0)}
        )

    @property
    def preset_mode(self):
        """Report Fan Policy (Auto vs Continuous)."""
        policy = self.coordinator.get_field(self._mac, "fan_mode", 0)
        if isinstance(policy, list):
            policy = policy[0] if policy else 0
        return "Continuous Fan" if policy == 1 else "Auto Fan"

    async def async_set_preset_mode(self, preset_mode):
        """Set Fan Policy (fan_mode)."""
        val = 1 if preset_mode == "Continuous Fan" else 0
        await self.hub.send_smarttemp_command(self._mac, {"fan_mode": val})


class SmartTempZone(SmartTempBase):
    """Representation of an Individual Zone as a Climate Entity."""

    def __init__(self, coordinator, entry_id, hub, mac, zone_idx):
        super().__init__(coordinator, entry_id, hub, mac)
        self._zone_idx = zone_idx  # 0-indexed for data, 1-indexed for commands
        self._zone_num = zone_idx + 1
        self._attr_unique_id = f"{entry_id}_{mac}_zone_{self._zone_num}"
        self._attr_name = f"Zone {self._zone_num}"

        # Zones usually only support toggling On/Off and setting Temp
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def hvac_mode(self):
        """Return FAN_ONLY if zone is open, OFF if closed."""
        status = self.coordinator.get_field(self._mac, f"zone{self._zone_num}_status", 0)
        return HVACMode.FAN_ONLY if status == 1 else HVACMode.OFF

    @property
    def current_temperature(self):
        # Each zone uses its index in the dis_zonetemp array
        return self.coordinator.get_zone_temp(self._mac, self._zone_idx)

    @property
    def target_temperature(self):
        """Target temp for this specific zone."""
        return self.coordinator.get_temp(self._mac, f"zone{self._zone_num}_set")

    async def async_set_hvac_mode(self, hvac_mode):
        """Open or close the zone damper."""
        new_status = 1 if hvac_mode == HVACMode.FAN_ONLY else 0

        # Feature: If turning a zone ON, ensure the Main Unit is also powered up
        if new_status == 1:
            main_mode = self.coordinator.get_field(self._mac, "equip_mode", 0)
            if main_mode == 0:  # If system is currently OFF
                _LOGGER.info("Opening zone %d: powering up main unit to Auto.", self._zone_num)
                await self.hub.send_smarttemp_command(self._mac, {"equip_mode": 3})

        await self.hub.send_smarttemp_command(
            self._mac, {f"zone{self._zone_num}_status": new_status}
        )

    async def async_set_temperature(self, **kwargs):
        """Set the target temperature for this zone."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.hub.send_smarttemp_command(
            self._mac, {f"zone{self._zone_num}_set": int(temp * 10)}
        )
