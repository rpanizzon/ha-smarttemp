import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL

_LOGGER = logging.getLogger(__name__)

class SmartTempCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SmartTemp data from the Hub."""

    def __init__(self, hass, hub=None):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No update_interval because the Hub pushes data to us
        )
        self.hub = hub
        self.hass = hass
        self.data = {}  # Store: { "MAC_ADDRESS": { "field": value, ... } }
        self.discovered_macs = set() # Track discovered devices

    async def async_process_json(self, mac, payload):
        """Handle incoming JSON from the Hub."""
        if mac not in self.data:
            self.data[mac] = {}

        # 1. Always merge data so we don't miss status changes
        self.data[mac].update(payload)

        # 2. Extract specific fields from pair_key if present
        if "pair_key" in payload:
            _LOGGER.debug("Processing identity/config data for %s", mac)
            # You can add logic here to explicitly parse zone names if provided in JSON

        # 3. Only signal DISCOVERY if this is the first time we see pair_key
        if "pair_key" in payload and mac not in self.discovered_macs:
            _LOGGER.info("First-time discovery for %s. Signaling platforms.", mac)
            self.discovered_macs.add(mac)
            async_dispatcher_send(self.hass, NEW_DEVICE_SIGNAL, mac)
        else:
            # Standard update for existing entities
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

    def get_zone_temp(self, mac, idx):
        """Fetcher for the 'dis_zonetemp' array with safety checks."""
        data = self.data.get(mac, {})
        val = data.get("dis_zonetemp")
    
        # Check if dis_zonetemp exists, is a list, and has the required index
        if not isinstance(val, list) or len(val) <= idx:
            return None
            
        try:
            # Convert raw hardware value (e.g., 225) to float (22.5)
            return float(val[idx]) / 10.0
        except (TypeError, ValueError):
            return None