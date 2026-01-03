import asyncio
import json
import logging
from datetime import datetime, timedelta
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL

_LOGGER = logging.getLogger(__name__)

SUB_FRAME_PREFIX = b"SUB "

class SmartTempHub:
    """The Socket Hub handling raw TCP communication with controllers."""

    def __init__(self, hass, port, coordinator=None):
        self.hass = hass
        self.port = port
        self.coordinator = coordinator
        self.active_connections = {}  # MAC: writer
        self.server = None
        self._serve_task = None

    async def start_server(self):
        """Start the TCP Server."""
        self.server = await asyncio.start_server(self.handle_client, '0.0.0.0', self.port)
        _LOGGER.info("SmartTemp Server started on port %s", self.port)
        self._serve_task = asyncio.create_task(self.server.serve_forever())

    async def stop_server(self):
        """Stop the TCP Server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self._serve_task:
            self._serve_task.cancel()
            self._serve_task = None

    async def handle_client(self, reader, writer):
        """Main connection handler."""
        address = writer.get_extra_info('peername')
        _LOGGER.info(f"New connection from {address}")
        
        current_mac = None
        buffer = b""

        try:
            # 1. Handshake Phase: Wait for SUB command
            while True:
                data = await reader.read(1024)
                if not data:
                    return
                buffer += data
                
                if buffer.startswith(SUB_FRAME_PREFIX) and b"\x0a" in buffer:
                    line_end = buffer.find(b"\x0a")
                    line = buffer[:line_end].decode('ascii').strip()
                    current_mac = line.split()[1]
                    
                    # Store connection for outgoing commands
                    self.active_connections[current_mac] = writer
                    
                    # Immediate definitive handshake (Time + Weather)
                    await self.send_protocol_response(writer, "handshake")
                    
                    # Advance buffer past the SUB line
                    buffer = buffer[line_end+1:]
                    _LOGGER.info(f"Handshake complete for MAC: {current_mac}")
                    break

            # 2. Operational Phase: JSON Processing loop
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                buffer += data

                # Bracket counting for cross-packet reassembly
                while b"{" in buffer:
                    start_index = buffer.find(b"{")
                    bracket_count = 0
                    json_found = False
                    
                    for i in range(start_index, len(buffer)):
                        if buffer[i] == ord("{"):
                            bracket_count += 1
                        elif buffer[i] == ord("}"):
                            bracket_count -= 1
                        
                        if bracket_count == 0:
                            # Full JSON object reassembled
                            json_bytes = buffer[start_index:i+1]
                            try:
                                payload = json.loads(json_bytes.decode('utf-8'))
                                await self.process_payload(current_mac, payload, writer)
                            except json.JSONDecodeError:
                                _LOGGER.error(f"Malformed JSON from {current_mac}")
                            
                            buffer = buffer[i+1:]
                            json_found = True
                            break
                    
                    if not json_found:
                        # Fragmented JSON; wait for more data
                        break

        except Exception as err:
            _LOGGER.error(f"Connection error for {address}: {err}")
        finally:
            if current_mac:
                self.active_connections.pop(current_mac, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                _LOGGER.debug("Error closing connection for %s", address)

    async def process_payload(self, mac, payload, writer):
        """Filter protocol noise vs state data."""
        
        # 1. Handle Protocol Heartbeats (Internal reply)
        if "heartbeat" in payload or "hb" in payload:
            await self.send_protocol_response(writer, "heartbeat")
            return

        # 2. Handle Protocol Time/Weather Requests
        if "get_time" in payload or "get_weather" in payload:
            await self.send_protocol_response(writer, "handshake")
            return

        # 3. Route state/config data to Coordinator
        # This includes "pair_key" which triggers discovery
        await self.coordinator.async_process_json(mac, payload)

    async def send_protocol_response(self, writer, resp_type):
        """Send standardized JSON responses for protocol maintenance."""
        now = datetime.now()
        
        if resp_type == "handshake":
            data = {
                "local_time": now.strftime("%Y%m%d%H%M"),
                "MsgID": (now + timedelta(hours=1)).strftime("%Y%m%d%H%M%S"),
                "weather_code": 1,
                "out_temp": 220,
                "out_humi": 450,
                "day1_high": 260,
                "day1_low": 140,
                "day1_weather": 1
            }
        else:  # Heartbeat ACK
            data = {"heartbeat": "ok", "time": now.strftime("%Y%m%d%H%M%S")}

        try:
            resp = json.dumps(data, separators=(',', ':')).encode('ascii')
            writer.write(resp)
            await writer.drain()
        except Exception as e:
            _LOGGER.error(f"Failed to send {resp_type}: {e}")

    async def send_smarttemp_command(self, mac, cmd_dict):
        """Send a command from HA to the controller."""
        if mac not in self.active_connections:
            _LOGGER.error(f"Cannot send command: {mac} not connected")
            return

        writer = self.active_connections[mac]
        try:
            # Most SmartTemp controllers expect a MsgID in commands too
            cmd_dict["MsgID"] = datetime.now().strftime("%Y%m%d%H%M%S")
            payload = json.dumps(cmd_dict, separators=(',', ':')).encode('ascii')
            writer.write(payload)
            await writer.drain()
        except Exception as e:
            _LOGGER.error(f"Error sending command to {mac}: {e}")