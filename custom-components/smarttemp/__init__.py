import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .hub import SmartTempHub
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# List of platforms to support (we'll add climate once the hub is tested)
PLATFORMS = []

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartTemp from a config entry."""
    
    # 1. Get the port from the configuration entry (defaults to 2223)
    port = entry.data.get("port", 2223)
    
    # 2. Initialize the Hub (TCP Server)
    hub = SmartTempHub(hass, port=port)
    
    # 3. Initialize the Coordinator (State Manager)
    coordinator = SmartTempCoordinator(hass, hub)
    
    # 4. Link them: Hub needs coordinator to push data; 
    # Coordinator needs hub to send commands.
    hub.coordinator = coordinator

    # 5. Start the TCP Server
    await hub.start_server()

    # Store for platform (climate.py) access
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "hub": hub,
        "coordinator": coordinator,
    }

    # 6. Forward to platforms (Update this once climate.py is ready)
    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])

    # Register shutdown
    entry.async_on_unload(hub.stop_server)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.stop_server()
        
    return unload_ok
