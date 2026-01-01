import asyncio
import json
import logging
import time
from .const import (
    DOMAIN, DEFAULT_PORT, HEARTBEAT_PAYLOAD, 
    SUB_FRAME_PREFIX, TEMP_SCALE_FACTOR
)

_LOGGER = logging.getLogger(__name__)

class SmartTempHub:
    def __init__(self, hass, port=DEFAULT_PORT):
        self.hass = hass
        self.port = port
        self.server = None
        self.coordinator = None
        self.active_connections = {}  # { mac_address: writer }
        self._closing = False

    async def start_server(self):
        """Start the TCP Server."""
        self.server = await asyncio.start_server(self.handle_client, '0.0.0.0', self.port)
        _LOGGER.info(f"SmartTemp Server listening on port {self.port}")
        self.hass.loop.create_task(self.server.serve_forever())

    async def stop_server(self, event=None):
        """Shutdown the server and close connections."""
        self._closing = True
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in self.active_connections.values():
            writer.close()
            await writer.wait_closed()

    async def handle_client(self, reader, writer):
        """Handle individual AC controller connections."""
        addr = writer.get_extra_info('peername')
        _LOGGER.debug(f"New connection from {addr}")
        
        buffer = ""
        mac_address = None

        try:
            while not self._closing:
                data = await reader.read(4096)
                if not data:
                    break
                
                raw_chunk = data.decode('utf-8', errors='ignore')
                buffer += raw_chunk

                # 1. Check for known non-JSON frames first
                if buffer.startswith(SUB_FRAME_PREFIX) or buffer.startswith(HEARTBEAT_PAYLOAD):
                    # TRACE LOG: Only occurs for raw control frames [cite: 26, 36]
                    _LOGGER.debug(f"[RAW DATA TRACE] Non-JSON frame detected: {raw_chunk.strip()}")
                    
                    if buffer.startswith(SUB_FRAME_PREFIX):
                        lines = buffer.split('\n', 1)
                        if len(lines) > 1:
                            mac_address = lines[0].replace(SUB_FRAME_PREFIX, "").strip()
                            self.active_connections[mac_address] = writer
                            buffer = lines[1]
                            _LOGGER.info(f"Device registered: {mac_address} [cite: 28]")
                        continue

                    if buffer.startswith(HEARTBEAT_PAYLOAD):
                        buffer = buffer[len(HEARTBEAT_PAYLOAD):]
                        _LOGGER.debug(f"Heartbeat handled for {mac_address} [cite: 36]")
                        continue

                # 2. Process JSON with Bracket Counting
                json_found_in_this_chunk = False
                while "{" in buffer:
                    start_index = buffer.find("{")
                    bracket_count = 0
                    for i in range(start_index, len(buffer)):
                        if buffer[i] == "{": bracket_count += 1
                        elif buffer[i] == "}": bracket_count -= 1
                        
                        if bracket_count == 0:
                            json_str = buffer[start_index:i+1]
                            try:
                                payload = json.loads(json_str)
                                json_found_in_this_chunk = True
                                # TRACE LOG: Valid JSON processed [cite: 11]
                                _LOGGER.debug(f"[JSON TRACE] Decoded payload: {json_str}")
                                
                                if self.coordinator:
                                    self.coordinator.async_set_updated_data(payload)
                                    
                            except json.JSONDecodeError:
                                _LOGGER.error(f"Failed to decode fragmented JSON [cite: 46]")
                            
                            buffer = buffer[i+1:].lstrip()
                            break
                    else:
                        break # Incomplete JSON, wait for more data [cite: 14]
                
                # 3. Final Fallback: Trace anything else that isn't a known frame or valid JSON
                if not json_found_in_this_chunk and len(buffer) > 0 and "{" not in buffer:
                    _LOGGER.debug(f"[RAW DATA TRACE] Unrecognized or Fragmented Non-JSON: {buffer.strip()}")
                # TRACE LOG: Raw non-JSON data (Control Frames)
                if SUB_FRAME_PREFIX in buffer or HEARTBEAT_PAYLOAD in buffer:
                    _LOGGER.debug(f"[RAW DATA TRACE] Received control frame: {raw_chunk.strip()}")

        except Exception as e:
            _LOGGER.error(f"Error handling SmartTemp client {addr}: {e}")
        finally:
            if mac_address and mac_address in self.active_connections:
                del self.active_connections[mac_address]
            writer.close()
            await writer.wait_closed()

    async def send_command(self, mac, payload):
        """Send a JSON payload to the specific device."""
        writer = self.active_connections.get(mac)
        if not writer:
            _LOGGER.error(f"Cannot send command: Device {mac} not connected")
            return

        json_cmd = json.dumps(payload) + "\n"
        writer.write(json_cmd.encode())
        await writer.drain()
        
    import time

    async def send_smarttemp_command(self, mac, payload):
        """Executes the two-phase Intent + Commit sequence."""
        # 1. Generate unique MsgID (timestamp based) [cite: 60, 72]
        msg_id = time.strftime("%Y%m%d%H%M%S")
        
        # Phase 1: Intent Payload
        intent = payload.copy()
        intent.update({
            "mac": mac,
            "MsgID": msg_id [cite: 72]
        })
        
        # Phase 2: Commit Payload
        commit = payload.copy()
        commit.update({
            "mac": mac,
            "time": int(time.time()), [cite: 67]
            "end": 1 [cite: 68]
        })

        # Send sequence
        await self.send_command(mac, intent)
        await asyncio.sleep(0.1) # Small gap between phases
        await self.send_command(mac, commit)