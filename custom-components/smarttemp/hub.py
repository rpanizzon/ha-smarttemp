import asyncio
import json
import logging
from datetime import datetime, timedelta
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL, TIME_ADJUST, TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)

SUB_FRAME_PREFIX = b"SUB "

class SmartTempHub:
    """The Socket Hub handling raw TCP communication with controllers."""

    def __init__(self, hass, port, coordinator=None):
        self.hass = hass
        self.port = port
        self.coordinator = coordinator
        self.active_connections = {}  # MAC: writer
        self.command_queues = {}     # MAC: asyncio.Queue()
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
        """Sequential handler with high-resolution trace logging for debugging timeouts."""
        address = writer.get_extra_info('peername')
        _LOGGER.info(f"New connection from {address}")
        
        current_mac = None
        buffer = b""

        try:
            # Phase 1: Handshake (Wait for SUB)
            while True:
                # 30s timeout for handshake
                data = await asyncio.wait_for(reader.read(4096), timeout=TIMEOUT_SECONDS)
                if not data: break
                
                buffer += data
                                    
                if buffer.startswith(SUB_FRAME_PREFIX) and b"\x0a" in buffer:
                    line_end = buffer.find(b"\x0a")
                    line = buffer[:line_end].decode('ascii').strip()
                    current_mac = line.split()[1]
                    
                    self.active_connections[current_mac] = writer
                    await self.send_protocol_response(writer, "handshake")
                    
                    buffer = buffer[line_end+1:]
                    _LOGGER.info(f"Handshake complete for MAC: {current_mac}")
                    break
            
            # Phase 2: We have JSON package  - Process JSON
            while True:
                # Increased read size to attempt to catch the large AA6 pair_key
                data = await asyncio.wait_for(reader.read(4096), timeout=TIMEOUT_SECONDS)
                if not data:
                    _LOGGER.debug(f"TRACE: {current_mac} closed the connection.")
                    break
                
                buffer += data
                # _LOGGER.debug("TRACE [%s]: Received %d bytes. Total Buffer: %d bytes. Starts with: %s", 
                #              current_mac, len(data), len(buffer), buffer[:30])

                while b"{" in buffer:
                    start_index = buffer.find(b"{")
                    
                    # Log if we have junk leading data before the first bracket
                    # This is probably __heartbeat__
                    if start_index > 0:
                        buffer = buffer[start_index:]
                        continue

                    bracket_count = 0
                    json_found = False
                    
                    # Scan buffer for matching closing bracket
                    for i in range(len(buffer)):
                        if buffer[i] == ord("{"):
                            bracket_count += 1
                        elif buffer[i] == ord("}"):
                            bracket_count -= 1
                        
                        if bracket_count == 0:
                            json_bytes = buffer[:i+1]
                            try:
                                payload = json.loads(json_bytes.decode('utf-8'))
                                
                                # ONLY call process_payload. 
                                # DO NOT wrap this in async_create_task here.
                                await self.process_payload(current_mac, payload, writer)
                                
                                buffer = buffer[i+1:]
                                json_found = True
                                break
                            except json.JSONDecodeError as e:
                                _LOGGER.info("TRACE [%s]: JSON Error: %s", current_mac, e.msg)
                                break
    
                            except json.JSONDecodeError as e:
                                _LOGGER.error("TRACE [%s]: JSON Decode Error at byte %d: %s", current_mac, e.pos, e.msg)
                                # Break and wait for more data to complete the fragment
                                break 
                    
                    if not json_found:
                        # _LOGGER.debug("TRACE [%s]: Incomplete JSON. Brackets still open: %d. Waiting for next packet.", 
                        #             current_mac, bracket_count)
                        break

        except asyncio.TimeoutError:
            _LOGGER.warning(f"Device {current_mac} timed out.")
        except Exception as err:
            _LOGGER.error(f"TRACE [%s]: Socket Error: %s", current_mac, err)
        finally:
            if current_mac:
                self.active_connections.pop(current_mac, None)
                
                # Force the status to False
                if self.coordinator:
                    if current_mac not in self.coordinator.data:
                        self.coordinator.data[current_mac] = {}
                    
                    self.coordinator.data[current_mac]["online"] = False
                    self.coordinator.async_set_updated_data(self.coordinator.data)
            
            # 3. Socket Cleanup
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            
    async def process_payload(self, mac, payload, writer):
        """Process incoming JSON and respond with either a stacked command or an ACK."""
        
        # 1. Handle Time Sync (Always priority handshake)
        if payload.get("cmd") == "time":
            await self.send_protocol_response(writer, "handshake")
            return

        # 2. Send response - either from stacked command or standard ACK
        queue = self.command_queues.get(mac)

        if queue and not queue.empty():
            try:
                # Get the next command from the stack
                cmd_dict = queue.get_nowait()
                cmd_dict["MsgID"] = datetime.now().strftime("%Y%m%d%H%M%S")
                
                payload_to_send = json.dumps(cmd_dict, separators=(',', ':')).encode('ascii')
                writer.write(payload_to_send)
                await writer.drain()
                
                _LOGGER.debug("TRACE [%s]: Sent STACKED command instead of ACK: %s", mac, cmd_dict)
                command_sent = True
            except asyncio.QueueEmpty:
                pass
            except Exception as e:
                _LOGGER.error("TRACE [%s]: Error sending stacked command: %s", mac, e)
        else:
        # 3. Fallback to standard ACK
            try:
                ack = json.dumps({"result": "ok"}, separators=(',', ':')).encode('ascii')
                writer.write(ack)
                await writer.drain()
            except Exception as e:
                _LOGGER.error("TRACE [%s]: ACK failed: %s", mac, e)

        # 4. Offload the incoming data to the coordinator
        self.hass.async_create_task(self.coordinator.async_process_json(mac, payload))

    async def send_protocol_response(self, writer, resp_type):
        """Send standardized JSON response for SUB and cmd:time."""
        now = datetime.now()
        
        # Consistent response format for both handshake and time requests
        data = {
            "local_time": now.strftime("%Y%m%d%H%M"),
            "MsgID": (now + timedelta(hours=TIME_ADJUST)).strftime("%Y%m%d%H%M%S")
        }

        try:
            resp = json.dumps(data, separators=(',', ':')).encode('ascii')
            writer.write(resp)
            await writer.drain()
            _LOGGER.debug("Sent %s response", resp_type)
        except Exception as e:
            _LOGGER.error(f"Failed to send {resp_type}: {e}")

    async def send_smarttemp_command(self, mac, cmd_dict):
        """Add a command to the stack instead of sending it immediately."""
        if mac not in self.command_queues:
            self.command_queues[mac] = asyncio.Queue()
        
        # Add to stack
        await self.command_queues[mac].put(cmd_dict)
        _LOGGER.debug("TRACE [%s]: Command added to stack: %s", mac, cmd_dict)
    
    async def send_raw_command(self, mac, raw_json_string):
        """
        Wraps a naked command string into valid JSON with a MsgID.
        Input Example: "cmd":"read","type":"all"
        Output Sent: {"cmd":"read","type":"all","MsgID":"20260108120000"}
        """
        try:
            # Clean up the string if the user sent a 'naked' command
            if not raw_json_string.startswith("{"):
                raw_json_string = "{" + raw_json_string + "}"
            
            cmd_dict = json.loads(raw_json_string)
            
            # RE-USE the main engine to handle the queue logic
            await self.send_smarttemp_command(mac, cmd_dict)
            
            _LOGGER.debug("TRACE [%s]: Successfully stacked raw injection", mac)
        except json.JSONDecodeError as e:
            _LOGGER.error("TRACE [%s]: Invalid JSON injected: %s", mac, e)   
        
        if mac not in self.active_connections:
            _LOGGER.error(f"Injection failed: {mac} not connected")
            return False
