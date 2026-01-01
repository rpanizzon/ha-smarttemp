"""Constants for the SmartTemp AC integration."""

DOMAIN = "smarttemp"

# Connection Constants
DEFAULT_PORT = 2223  # 
HEARTBEAT_PAYLOAD = "__heartbeat__\n"  # [cite: 5]
SUB_FRAME_PREFIX = "SUB"  # [cite: 5]

# Protocol Scaling
# All temperatures are scaled integers (x10) [cite: 22]
TEMP_SCALE_FACTOR = 10.0 

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