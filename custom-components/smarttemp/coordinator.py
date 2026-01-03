import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL

_LOGGER = logging.getLogger(__name__)

class SmartTempDataCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SmartTemp data from the Hub."""

    def __init__(self, hass):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No update_interval because the Hub pushes data to us
        )
        self.data = {}  # Store: { "MAC_ADDRESS": { "field": value, ... } }

    async def async_process_json(self, mac, payload):
        """Handle incoming JSON from the Hub."""
        if mac not in self.data:
            self.data[mac] = {}

        # Merge the new payload into our state dictionary
        self.data[mac].update(payload)

        # TRIGGER DISCOVERY
        # We only signal climate.py to create entities if 'pair_key' is present
        # This ensures zone_no and equip_mode are available before entities exist.
        if "pair_key" in payload:
            _LOGGER.info(f"Full hardware profile for {mac} received. Triggering discovery.")
            async_dispatcher_send(self.hass, NEW_DEVICE_SIGNAL, mac)
        else:
            # Standard update: Tell existing entities that data has changed
            self.async_set_updated_data(self.data)

    def get_field(self, mac, field, default=None):
        """Safe fetch for raw fields (handles lists automatically)."""
        val = self.data.get(mac, {}).get(field, default)
        if isinstance(val, list) and len(val) > 0:
            return val[0]
        return val

    def _scale_val(self, val):
        """Helper to handle list vs int and scale by 10.0."""
        if val is None:
            return None
            
        # Unwrapping quirk: Zoned controllers often wrap integers in a list [210]
        if isinstance(val, list):
            if not val: return None
            val = val[0]
            
        try:
            return float(val) / 10.0
        except (TypeError, ValueError):
            return None

    def get_temp(self, mac, field):
        """Scales raw values (210 -> 21.0) and handles list unwrapping."""
        val = self.get_field(mac, field)
        try:
            return float(val) / 10.0 if val is not None else None
        except (TypeError, ValueError):
            return None

    def get_humidity(self, mac):
        """Return humidity without scaling."""
        val = self.get_field(mac, "dis_room_humi")
        try:
            # If the controller sends 72, this returns 72.0
            # If it sends [72], get_field unwraps it and this returns 72.0
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def get_zone_temp(self, mac, zone_idx):
        """Specifically extracts index from dis_zonetemp array."""
        val = self.data.get(mac, {}).get("dis_zonetemp")
        if isinstance(val, list) and len(val) > zone_idx:
            zone_val = val[zone_idx]
            return float(zone_val) / 10.0 if zone_val is not None else None
        return None