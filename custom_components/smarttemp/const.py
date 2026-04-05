"""Constants for the SmartTemp AC integration."""

DOMAIN = "smarttemp"

# Connection Constants
DEFAULT_PORT = 2223  #
BUFFER_LIMIT = 8096  # bytes 
HEARTBEAT_PAYLOAD = b"__heartbeat__\n"  
SUB_FRAME_PREFIX = b"SUB "  
TIMEOUT_SECONDS = 30.0  # seconds for read timeouts

# Protocol Scaling
# Time adjustment in hours to shift server to diffeent time zone
TIME_ADJUST = 0
# All temperatures are scaled integers (x10)
TEMP_SCALE_FACTOR = 10.0 

# Signal name
NEW_DEVICE_SIGNAL = "smarttemp_new_device"

# Operating Modes (equip_mode) 
# Value 0: Off, 1: Heat, 3: Cool, 4: Auto
MODE_OFF = 0
MODE_HEAT = 1
MODE_COOL = 3
MODE_AUTO = 4

MAP_HA_TO_SMARTTEMP = {
    "off": MODE_OFF,
    "heat": MODE_HEAT,
    "cool": MODE_COOL,
    "auto": MODE_AUTO,
}

MAP_SMARTTEMP_TO_HA = {v: k for k, v in MAP_HA_TO_SMARTTEMP.items()}

# Zone Definitions [cite: 12]
# 1 = enabled, 0 = disabled
ZONE_ON = 1
ZONE_OFF = 0

# Command Keys [cite: 7]
CONF_MAC = "mac"
CONF_MSG_ID = "MsgID"
CONF_TIME = "time"
CONF_END = "end"
CONF_EQUIP_MODE = "equip_mode"