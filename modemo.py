#!/usr/bin/env python3
"""
Cellular Modem Diagnostic & Configuration Tool
A comprehensive cross-platform terminal application for managing cellular modems

Supports:
- Windows (COM ports)
- Linux/Raspberry Pi (USB, ACM, UART serial ports)
- Auto-detection with optimized two-phase baud rate testing
- Multiple modem vendors (Quectel, Sierra Wireless, u-blox, Telit, SimCom, etc.)
"""

import serial
import time
import re
import json
import glob
import subprocess
import platform
import os
import threading
import socket
import struct
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.prompt import Prompt, Confirm

# Optional import for advanced HTTP requests
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
from rich.tree import Tree
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'

# Port blacklist - can be set via environment variable
# Example: export MODEMO_SKIP_PORTS="/dev/ttyUSB1,/dev/ttyUSB0"
SKIP_PORTS = set(os.environ.get('MODEMO_SKIP_PORTS', '').split(',')) if os.environ.get('MODEMO_SKIP_PORTS') else set()

# Debug mode - set MODEMO_DEBUG=1 for verbose output
DEBUG_MODE = os.environ.get('MODEMO_DEBUG', '').lower() in ('1', 'true', 'yes')


class ModemManagerHelper:
    """Helper to detect and manage ModemManager interference on Linux"""

    @staticmethod
    def is_running() -> bool:
        """Check if ModemManager is running"""
        if not IS_LINUX:
            return False

        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'ModemManager'],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.returncode == 0 and 'active' in result.stdout
        except Exception:
            return False

    @staticmethod
    def is_blocking_port(port: str) -> bool:
        """Check if ModemManager is using a specific port"""
        if not IS_LINUX:
            return False

        try:
            # Check using lsof
            result = subprocess.run(
                ['lsof', port],
                capture_output=True,
                text=True,
                timeout=2
            )
            return 'ModemManager' in result.stdout
        except Exception:
            return False

    @staticmethod
    def get_managed_ports() -> List[str]:
        """Get list of ports managed by ModemManager"""
        ports = []
        if not IS_LINUX:
            return ports

        try:
            # Use mmcli to list modems
            result = subprocess.run(
                ['mmcli', '-L'],
                capture_output=True,
                text=True,
                timeout=2
            )
            # Parse output for device paths
            for line in result.stdout.split('\n'):
                if 'device' in line.lower():
                    match = re.search(r'/dev/tty\w+', line)
                    if match:
                        ports.append(match.group(0))
        except Exception:
            pass

        return ports

    @staticmethod
    def stop_temporarily() -> bool:
        """Temporarily stop ModemManager (requires sudo)"""
        if not IS_LINUX:
            return False

        try:
            result = subprocess.run(
                ['systemctl', 'stop', 'ModemManager'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def restart() -> bool:
        """Restart ModemManager"""
        if not IS_LINUX:
            return False

        try:
            result = subprocess.run(
                ['systemctl', 'start', 'ModemManager'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False


@dataclass
class ATResponse:
    """Store AT command response with metadata"""
    command: str
    raw_response: str
    parsed_data: Dict
    timestamp: datetime
    success: bool
    error: Optional[str] = None


class ModemConnection:
    """Handle serial communication with cellular modem"""

    def __init__(self, port: str = "/dev/ttyUSB2", baudrate: int = 115200, timeout: int = 5):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection: Optional[serial.Serial] = None
        self.rtscts = None  # Will be auto-detected

    def connect(self, quick_test: bool = False) -> bool:
        """Establish serial connection to modem

        Args:
            quick_test: If True, use minimal retries and faster timeouts for detection
        """
        # For quick testing, only try one rtscts setting and minimal retries
        rtscts_settings = [False] if quick_test else [False, True]
        max_attempts = 1 if quick_test else 3
        init_sleep = 0.1 if quick_test else 0.5
        test_sleep = 0.2 if quick_test else 0.5

        for rtscts_setting in rtscts_settings:
            try:
                self.connection = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    write_timeout=self.timeout,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    rtscts=rtscts_setting,
                    xonxoff=False,
                    dsrdtr=False,
                    exclusive=False  # Allow shared access to prevent blocking on Linux
                )
                time.sleep(init_sleep)

                # Clear any pending data
                self.connection.reset_input_buffer()
                self.connection.reset_output_buffer()
                if not quick_test:
                    time.sleep(0.2)

                # Test with AT command - try multiple times for broken pipe issues
                for attempt in range(max_attempts):
                    try:
                        self.connection.write(b'AT\r\n')
                        self.connection.flush()
                        time.sleep(test_sleep)
                        response = self.connection.read(self.connection.in_waiting or 100).decode('utf-8',
                                                                                                  errors='ignore')

                        if 'OK' in response or 'AT' in response:
                            # Connection works with this flow control setting
                            self.rtscts = rtscts_setting
                            # Clear buffers again for clean slate
                            self.connection.reset_input_buffer()
                            self.connection.reset_output_buffer()
                            return True

                    except (BrokenPipeError, OSError) as e:
                        if attempt < max_attempts - 1 and not quick_test:
                            time.sleep(0.3)
                            continue
                        else:
                            if not quick_test:
                                raise
                            break

                # No response, try next setting
                self.connection.close()

            except Exception as e:
                if self.connection and self.connection.is_open:
                    self.connection.close()
                # Only show error if not quick test and this was the last attempt
                if rtscts_setting == rtscts_settings[-1] and not quick_test:
                    console.print(f"[red]Connection Error: {e}[/red]")
                continue

        return False

    def disconnect(self):
        """Close serial connection"""
        if self.connection and self.connection.is_open:
            self.connection.close()

    def send_at_command(self, command: str, wait_time: float = 1.0) -> ATResponse:
        """Send AT command and return parsed response"""
        if not self.connection or not self.connection.is_open:
            return ATResponse(
                command=command,
                raw_response="",
                parsed_data={},
                timestamp=datetime.now(),
                success=False,
                error="No connection"
            )

        try:
            # Ensure command ends with \r\n
            if not command.endswith('\r\n'):
                command = command + '\r\n'

            # Clear buffers
            self.connection.reset_input_buffer()

            # Send command
            self.connection.write(command.encode('utf-8'))
            time.sleep(wait_time)

            # Read response
            response = ""
            while self.connection.in_waiting:
                response += self.connection.read(self.connection.in_waiting).decode('utf-8', errors='ignore')
                time.sleep(0.1)

            # Parse response
            success = "OK" in response and "ERROR" not in response
            error = "ERROR" if "ERROR" in response else None

            return ATResponse(
                command=command.strip(),
                raw_response=response,
                parsed_data=self._parse_response(command.strip(), response),
                timestamp=datetime.now(),
                success=success,
                error=error
            )

        except Exception as e:
            return ATResponse(
                command=command,
                raw_response="",
                parsed_data={},
                timestamp=datetime.now(),
                success=False,
                error=str(e)
            )

    def _parse_response(self, command: str, response: str) -> Dict:
        """Parse AT command response into structured data"""
        parsed = {"raw": response}

        # Remove echo and OK/ERROR
        lines = [line.strip() for line in response.split('\n') if line.strip()]
        lines = [line for line in lines if line not in [command, 'OK', 'ERROR', '']]

        if not lines:
            return parsed

        # Parse based on command type
        if '+COPS' in command:
            parsed.update(self._parse_cops(lines))
        elif '+CREG' in command or '+CGREG' in command or '+CEREG' in command:
            parsed.update(self._parse_registration(lines))
        elif '+CSQ' in command:
            parsed.update(self._parse_csq(lines))
        elif '+CGDCONT' in command:
            parsed.update(self._parse_cgdcont(lines))
        elif '+CPIN' in command:
            parsed.update(self._parse_cpin(lines))
        elif '+CIMI' in command:
            parsed['imsi'] = lines[0] if lines else ''
        elif '+CCID' in command or '+ICCID' in command or '+QCCID' in command:
            parsed['iccid'] = re.sub(r'[^0-9]', '', lines[0]) if lines else ''
        elif '+CGMI' in command:
            parsed['manufacturer'] = lines[0] if lines else ''
        elif '+CGMM' in command:
            parsed['model'] = lines[0] if lines else ''
        elif '+CGMR' in command:
            parsed['firmware'] = lines[0] if lines else ''
        elif '+CGSN' in command:
            parsed['imei'] = lines[0] if lines else ''
        elif 'I' == command or 'ATI' in command:
            parsed['info'] = '\n'.join(lines)
        # Quectel-specific commands
        elif '+QENG' in command:
            parsed.update(self._parse_qeng(lines))
        elif '+QNWINFO' in command:
            parsed.update(self._parse_qnwinfo(lines))
        elif '+QSPN' in command:
            parsed.update(self._parse_qspn(lines))

        return parsed

    def _parse_qeng(self, lines: List[str]) -> Dict:
        """Parse Quectel +QENG serving cell information"""
        result = {}
        for line in lines:
            if '+QENG:' in line:
                parts = line.replace('+QENG:', '').strip().split(',')
                if len(parts) > 0:
                    result['servingcell_type'] = parts[0].strip('"')
                    if parts[0].strip('"') == 'servingcell':
                        # LTE serving cell info
                        if len(parts) >= 15:
                            result['state'] = parts[1].strip('"')
                            result['mode'] = parts[2].strip('"')
                            result['mcc'] = parts[4].strip('"')
                            result['mnc'] = parts[5].strip('"')
                            result['cellid'] = parts[6].strip('"')
                            result['pcid'] = parts[7]
                            result['earfcn'] = parts[8]
                            result['freq_band'] = parts[9]
                            result['ul_bandwidth'] = parts[10]
                            result['dl_bandwidth'] = parts[11]
                            result['tac'] = parts[12].strip('"')
                            result['rsrp'] = f"{parts[13]} dBm"
                            result['rsrq'] = f"{parts[14]} dB"
                            result['rssi'] = f"{parts[15]} dBm" if len(parts) > 15 else ''
                            result['sinr'] = f"{parts[16]} dB" if len(parts) > 16 else ''
        return result

    def _parse_qnwinfo(self, lines: List[str]) -> Dict:
        """Parse Quectel +QNWINFO network information"""
        result = {}
        for line in lines:
            if '+QNWINFO:' in line:
                # +QNWINFO: <Act>,<oper>,<band>,<channel>
                match = re.search(r'\+QNWINFO:\s*"([^"]*)",?"([^"]*)",?"([^"]*)",?(\d+)', line)
                if match:
                    result['access_tech'] = match.group(1)
                    result['operator'] = match.group(2)
                    result['band'] = match.group(3)
                    result['channel'] = match.group(4)
        return result

    def _parse_qspn(self, lines: List[str]) -> Dict:
        """Parse Quectel +QSPN service provider name"""
        result = {}
        for line in lines:
            if '+QSPN:' in line:
                match = re.search(r'\+QSPN:\s*"([^"]*)",?"([^"]*)",?"([^"]*)"', line)
                if match:
                    result['fnn'] = match.group(1)  # Full name
                    result['snn'] = match.group(2)  # Short name
                    result['spn'] = match.group(3)  # Service provider name
        return result

    def _parse_cops(self, lines: List[str]) -> Dict:
        """Parse +COPS operator selection response"""
        result = {}
        for line in lines:
            if '+COPS:' in line:
                # +COPS: <mode>[,<format>,<oper>[,<AcT>]]
                match = re.search(r'\+COPS:\s*(\d+)(?:,(\d+),"([^"]*)"(?:,(\d+))?)?', line)
                if match:
                    mode = int(match.group(1))
                    result['mode'] = mode
                    result['mode_text'] = {
                        0: 'Automatic',
                        1: 'Manual',
                        2: 'Deregister',
                        3: 'Set format only',
                        4: 'Manual/Automatic'
                    }.get(mode, f'Unknown ({mode})')

                    if match.group(2):
                        result['format'] = int(match.group(2))
                    if match.group(3):
                        result['operator'] = match.group(3)
                    if match.group(4):
                        act = int(match.group(4))
                        result['access_tech'] = act
                        result['access_tech_text'] = {
                            0: 'GSM',
                            1: 'GSM Compact',
                            2: 'UTRAN',
                            3: 'GSM w/EGPRS',
                            4: 'UTRAN w/HSDPA',
                            5: 'UTRAN w/HSUPA',
                            6: 'UTRAN w/HSDPA and HSUPA',
                            7: 'E-UTRAN',
                            8: 'EC-GSM-IoT',
                            9: 'E-UTRAN (NB-S1 mode)',
                            10: 'E-UTRA connected to 5GCN',
                            11: 'NR connected to 5GCN'
                        }.get(act, f'Unknown ({act})')
        return result

    def _parse_registration(self, lines: List[str]) -> Dict:
        """Parse +CREG/+CGREG/+CEREG network registration response"""
        result = {}
        for line in lines:
            match = re.search(r'\+(CREG|CGREG|CEREG):\s*(\d+)(?:,(\d+))?(?:,"([0-9A-F]+)","([0-9A-F]+)")?(?:,(\d+))?',
                              line)
            if match:
                reg_type = match.group(1).lower()
                n = int(match.group(2))
                stat = int(match.group(3)) if match.group(3) else n

                result[f'{reg_type}_status'] = stat
                result[f'{reg_type}_status_text'] = {
                    0: 'Not registered, not searching',
                    1: 'Registered, home network',
                    2: 'Not registered, searching',
                    3: 'Registration denied',
                    4: 'Unknown',
                    5: 'Registered, roaming'
                }.get(stat, f'Unknown ({stat})')

                if match.group(4):
                    result['lac'] = match.group(4)
                if match.group(5):
                    result['ci'] = match.group(5)
                if match.group(6):
                    act = int(match.group(6))
                    result['act'] = act
                    result['act_text'] = {
                        0: 'GSM',
                        1: 'GSM Compact',
                        2: 'UTRAN',
                        3: 'GSM w/EGPRS',
                        4: 'UTRAN w/HSDPA',
                        5: 'UTRAN w/HSUPA',
                        6: 'UTRAN w/HSDPA and HSUPA',
                        7: 'E-UTRAN',
                        8: 'EC-GSM-IoT',
                        9: 'E-UTRAN (NB-S1 mode)'
                    }.get(act, f'Unknown ({act})')
        return result

    def _parse_csq(self, lines: List[str]) -> Dict:
        """Parse +CSQ signal quality response"""
        result = {}
        for line in lines:
            match = re.search(r'\+CSQ:\s*(\d+),(\d+)', line)
            if match:
                rssi = int(match.group(1))
                ber = int(match.group(2))

                result['rssi_raw'] = rssi
                result['ber_raw'] = ber

                # Convert RSSI to dBm
                if rssi == 0:
                    result['rssi_dbm'] = '<= -113 dBm'
                    result['signal_quality'] = 'Very Poor'
                elif rssi == 1:
                    result['rssi_dbm'] = '-111 dBm'
                    result['signal_quality'] = 'Very Poor'
                elif 2 <= rssi <= 30:
                    dbm = -109 + (rssi - 2) * 2
                    result['rssi_dbm'] = f'{dbm} dBm'
                    if rssi < 10:
                        result['signal_quality'] = 'Poor'
                    elif rssi < 15:
                        result['signal_quality'] = 'Fair'
                    elif rssi < 20:
                        result['signal_quality'] = 'Good'
                    else:
                        result['signal_quality'] = 'Excellent'
                elif rssi == 31:
                    result['rssi_dbm'] = '>= -51 dBm'
                    result['signal_quality'] = 'Excellent'
                else:
                    result['rssi_dbm'] = 'Unknown'
                    result['signal_quality'] = 'Unknown'

                # BER interpretation
                if ber == 99:
                    result['ber_text'] = 'Unknown or not detectable'
                else:
                    result[
                        'ber_text'] = f'{ber} ({["<0.2%", "0.2-0.4%", "0.4-0.8%", "0.8-1.6%", "1.6-3.2%", "3.2-6.4%", "6.4-12.8%", ">12.8%"][min(ber, 7)]})'

        return result

    def _parse_cgdcont(self, lines: List[str]) -> Dict:
        """Parse +CGDCONT PDP context response"""
        result = {'contexts': []}
        for line in lines:
            match = re.search(r'\+CGDCONT:\s*(\d+),"([^"]*)","([^"]*)"(?:,"([^"]*)")?', line)
            if match:
                context = {
                    'cid': int(match.group(1)),
                    'pdp_type': match.group(2),
                    'apn': match.group(3),
                    'pdp_addr': match.group(4) if match.group(4) else ''
                }
                result['contexts'].append(context)
        return result

    def _parse_cpin(self, lines: List[str]) -> Dict:
        """Parse +CPIN SIM status response"""
        result = {}
        for line in lines:
            if '+CPIN:' in line:
                status = line.split(':')[1].strip()
                result['sim_status'] = status
                result['sim_ready'] = status == 'READY'
                result['sim_status_text'] = {
                    'READY': 'SIM is ready',
                    'SIM PIN': 'SIM requires PIN',
                    'SIM PUK': 'SIM requires PUK',
                    'SIM PIN2': 'SIM requires PIN2',
                    'SIM PUK2': 'SIM requires PUK2'
                }.get(status, status)
        return result


class DiagnosticTests:
    """Comprehensive diagnostic test suite"""

    def __init__(self, modem: ModemConnection):
        self.modem = modem
        self.results = []
        self.modem_vendor = None
        self.modem_model = None

    def detect_modem_vendor(self):
        """Detect modem manufacturer and model for vendor-specific optimizations"""
        manu_result = self.modem.send_at_command("AT+CGMI")
        model_result = self.modem.send_at_command("AT+CGMM")

        if 'manufacturer' in manu_result.parsed_data:
            manu = manu_result.parsed_data['manufacturer'].upper()
            if 'QUECTEL' in manu:
                self.modem_vendor = 'Quectel'
            elif 'SIERRA' in manu:
                self.modem_vendor = 'Sierra Wireless'
            elif 'UBLOX' in manu or 'U-BLOX' in manu:
                self.modem_vendor = 'u-blox'
            elif 'TELIT' in manu:
                self.modem_vendor = 'Telit'
            elif 'SIMCOM' in manu:
                self.modem_vendor = 'SimCom'
            else:
                self.modem_vendor = manu_result.parsed_data['manufacturer']

        if 'model' in model_result.parsed_data:
            self.modem_model = model_result.parsed_data['model']

    def run_full_diagnostic(self) -> List[ATResponse]:
        """Run complete diagnostic test suite"""
        self.results = []

        # Detect vendor first
        self.detect_modem_vendor()

        # Standard tests
        tests = [
            ("AT", "Basic communication test"),
            ("ATI", "Modem information"),
            ("AT+CGMI", "Manufacturer identification"),
            ("AT+CGMM", "Model identification"),
            ("AT+CGMR", "Firmware version"),
            ("AT+CGSN", "IMEI"),
            ("AT+CPIN?", "SIM status"),
            ("AT+CCID", "ICCID (SIM serial)"),
            ("AT+CIMI", "IMSI"),
            ("AT+CSQ", "Signal quality"),
            ("AT+CREG?", "Network registration (CS)"),
            ("AT+CGREG?", "GPRS registration (PS)"),
            ("AT+CEREG?", "EPS registration (LTE)"),
            ("AT+COPS?", "Operator selection"),
            ("AT+CGDCONT?", "PDP context"),
        ]

        # Add vendor-specific tests
        if self.modem_vendor == 'Quectel':
            tests.extend(self._get_quectel_tests())
        elif self.modem_vendor == 'Sierra Wireless':
            tests.extend(self._get_sierra_tests())
        elif self.modem_vendor == 'u-blox':
            tests.extend(self._get_ublox_tests())

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Running diagnostic tests...", total=len(tests))

            for cmd, description in tests:
                progress.update(task, description=f"[cyan]{description}")
                result = self.modem.send_at_command(cmd)
                self.results.append(result)
                progress.advance(task)
                time.sleep(0.2)

        return self.results

    def _get_quectel_tests(self) -> List[Tuple[str, str]]:
        """Quectel-specific diagnostic commands"""
        return [
            ("AT+QENG=\"servingcell\"", "Serving cell info (Quectel)"),
            ("AT+QNWINFO", "Network information (Quectel)"),
            ("AT+QSPN", "Service provider name (Quectel)"),
            ("AT+QCCID", "ICCID via Quectel command"),
        ]

    def _get_sierra_tests(self) -> List[Tuple[str, str]]:
        """Sierra Wireless-specific diagnostic commands"""
        return [
            ("AT!GSTATUS?", "Status information (Sierra)"),
            ("AT+KCELLMEAS=1", "Cell measurements (Sierra)"),
        ]

    def _get_ublox_tests(self) -> List[Tuple[str, str]]:
        """u-blox-specific diagnostic commands"""
        return [
            ("AT+UCGED?", "Cell information (u-blox)"),
            ("AT+UREG?", "Registration status (u-blox)"),
        ]

    def display_results(self):
        """Display diagnostic results in formatted tables"""
        console.print("\n")
        console.rule("[bold cyan]Diagnostic Test Results", style="cyan")

        # Show vendor info if detected
        if self.modem_vendor:
            console.print(f"\n[bold magenta]Detected Modem:[/bold magenta] {self.modem_vendor}", end="")
            if self.modem_model:
                console.print(f" - {self.modem_model}")
            else:
                console.print()

        console.print()

        # Device Information
        self._display_device_info()
        console.print()

        # SIM Information
        self._display_sim_info()
        console.print()

        # Network Status
        self._display_network_status()
        console.print()

        # Signal Quality
        self._display_signal_quality()
        console.print()

        # PDP Context
        self._display_pdp_context()

        # Vendor-specific information
        if self.modem_vendor == 'Quectel':
            console.print()
            self._display_quectel_advanced()

    def _display_quectel_advanced(self):
        """Display Quectel-specific advanced information"""
        # Check if we have Quectel-specific data
        has_qeng = any('servingcell_type' in r.parsed_data for r in self.results)
        has_qnwinfo = any('access_tech' in r.parsed_data and 'band' in r.parsed_data for r in self.results)

        if not has_qeng and not has_qnwinfo:
            return

        table = Table(title="Advanced Cell Information (Quectel)", box=box.ROUNDED, show_header=True,
                      header_style="bold magenta")
        table.add_column("Parameter", style="cyan", width=20)
        table.add_column("Value", style="white", width=30)
        table.add_column("Details", style="white")

        for result in self.results:
            parsed = result.parsed_data

            # QENG serving cell data
            if 'servingcell_type' in parsed and parsed['servingcell_type'] == 'servingcell':
                table.add_row("Cell ID", parsed.get('cellid', ''), f"PCI: {parsed.get('pcid', '')}")
                table.add_row("Frequency", f"EARFCN: {parsed.get('earfcn', '')}",
                              f"Band: {parsed.get('freq_band', '')}")
                table.add_row("Bandwidth", f"DL: {parsed.get('dl_bandwidth', '')} MHz",
                              f"UL: {parsed.get('ul_bandwidth', '')} MHz")
                table.add_row("TAC", parsed.get('tac', ''), "")

                # LTE signal metrics
                if 'rsrp' in parsed:
                    rsrp_val = int(parsed['rsrp'].split()[0]) if parsed['rsrp'] else -999
                    rsrp_color = "green" if rsrp_val > -100 else "yellow" if rsrp_val > -110 else "red"
                    table.add_row("RSRP", f"[{rsrp_color}]{parsed.get('rsrp', '')}[/{rsrp_color}]",
                                  "Reference Signal Received Power")

                if 'rsrq' in parsed:
                    table.add_row("RSRQ", parsed.get('rsrq', ''), "Reference Signal Received Quality")

                if 'rssi' in parsed:
                    table.add_row("RSSI", parsed.get('rssi', ''), "Received Signal Strength Indicator")

                if 'sinr' in parsed:
                    sinr_val = int(parsed['sinr'].split()[0]) if parsed['sinr'] else -999
                    sinr_color = "green" if sinr_val > 13 else "yellow" if sinr_val > 0 else "red"
                    table.add_row("SINR", f"[{sinr_color}]{parsed.get('sinr', '')}[/{sinr_color}]",
                                  "Signal to Interference plus Noise Ratio")

            # QNWINFO data
            if 'access_tech' in parsed and 'band' in parsed:
                table.add_row("Technology", parsed.get('access_tech', ''), f"Band: {parsed.get('band', '')}")
                table.add_row("Channel", parsed.get('channel', ''), "")

            # QSPN data
            if 'spn' in parsed:
                table.add_row("SPN", parsed.get('spn', ''), f"FNN: {parsed.get('fnn', '')}")

        if table.row_count > 0:
            console.print(table)

    def _display_device_info(self):
        """Display device information table"""
        table = Table(title="Device Information", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan", width=20)
        table.add_column("Value", style="white")

        for result in self.results:
            if 'manufacturer' in result.parsed_data:
                table.add_row("Manufacturer", result.parsed_data['manufacturer'])
            if 'model' in result.parsed_data:
                table.add_row("Model", result.parsed_data['model'])
            if 'firmware' in result.parsed_data:
                table.add_row("Firmware", result.parsed_data['firmware'])
            if 'imei' in result.parsed_data:
                table.add_row("IMEI", result.parsed_data['imei'])

        console.print(table)

    def _display_sim_info(self):
        """Display SIM information table"""
        table = Table(title="SIM Card Information", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan", width=20)
        table.add_column("Value", style="white")
        table.add_column("Status", style="white")

        for result in self.results:
            if 'sim_status' in result.parsed_data:
                status_color = "green" if result.parsed_data.get('sim_ready', False) else "red"
                table.add_row(
                    "SIM Status",
                    result.parsed_data['sim_status'],
                    f"[{status_color}]{result.parsed_data.get('sim_status_text', '')}[/{status_color}]"
                )
            if 'iccid' in result.parsed_data:
                table.add_row("ICCID", result.parsed_data['iccid'], "")
            if 'imsi' in result.parsed_data:
                table.add_row("IMSI", result.parsed_data['imsi'], "")

        console.print(table)

    def _display_network_status(self):
        """Display network registration status"""
        table = Table(title="Network Registration Status", box=box.ROUNDED, show_header=True,
                      header_style="bold magenta")
        table.add_column("Type", style="cyan", width=15)
        table.add_column("Status Code", style="white", width=12)
        table.add_column("Status", style="white", width=30)
        table.add_column("Details", style="white")

        for result in self.results:
            parsed = result.parsed_data

            # CS Registration
            if 'creg_status' in parsed:
                status = parsed['creg_status']
                status_color = "green" if status in [1, 5] else "yellow" if status == 2 else "red"
                details = []
                if 'lac' in parsed:
                    details.append(f"LAC: {parsed['lac']}")
                if 'ci' in parsed:
                    details.append(f"CI: {parsed['ci']}")
                table.add_row(
                    "CS (Voice)",
                    str(status),
                    f"[{status_color}]{parsed.get('creg_status_text', '')}[/{status_color}]",
                    ", ".join(details)
                )

            # PS Registration
            if 'cgreg_status' in parsed:
                status = parsed['cgreg_status']
                status_color = "green" if status in [1, 5] else "yellow" if status == 2 else "red"
                details = []
                if 'lac' in parsed:
                    details.append(f"LAC: {parsed['lac']}")
                if 'ci' in parsed:
                    details.append(f"CI: {parsed['ci']}")
                if 'act_text' in parsed:
                    details.append(f"AcT: {parsed['act_text']}")
                table.add_row(
                    "PS (Data)",
                    str(status),
                    f"[{status_color}]{parsed.get('cgreg_status_text', '')}[/{status_color}]",
                    ", ".join(details)
                )

            # EPS Registration
            if 'cereg_status' in parsed:
                status = parsed['cereg_status']
                status_color = "green" if status in [1, 5] else "yellow" if status == 2 else "red"
                details = []
                if 'lac' in parsed:
                    details.append(f"TAC: {parsed['lac']}")
                if 'ci' in parsed:
                    details.append(f"CI: {parsed['ci']}")
                if 'act_text' in parsed:
                    details.append(f"AcT: {parsed['act_text']}")
                table.add_row(
                    "EPS (LTE)",
                    str(status),
                    f"[{status_color}]{parsed.get('cereg_status_text', '')}[/{status_color}]",
                    ", ".join(details)
                )

            # Operator
            if 'operator' in parsed:
                mode_text = parsed.get('mode_text', '')
                act_text = parsed.get('access_tech_text', '')
                table.add_row(
                    "Operator",
                    "",
                    parsed['operator'],
                    f"{mode_text}, {act_text}" if act_text else mode_text
                )

        console.print(table)

    def _display_signal_quality(self):
        """Display signal quality metrics"""
        table = Table(title="Signal Quality", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Raw Value", style="white", width=12)
        table.add_column("Converted", style="white", width=20)
        table.add_column("Assessment", style="white")

        for result in self.results:
            if 'rssi_raw' in result.parsed_data:
                parsed = result.parsed_data
                rssi_raw = parsed['rssi_raw']
                quality = parsed.get('signal_quality', 'Unknown')

                # Color code based on quality
                quality_color = {
                    'Excellent': 'green',
                    'Good': 'green',
                    'Fair': 'yellow',
                    'Poor': 'red',
                    'Very Poor': 'red'
                }.get(quality, 'white')

                table.add_row(
                    "RSSI",
                    str(rssi_raw),
                    parsed.get('rssi_dbm', ''),
                    f"[{quality_color}]{quality}[/{quality_color}]"
                )

                table.add_row(
                    "BER",
                    str(parsed['ber_raw']),
                    parsed.get('ber_text', ''),
                    ""
                )

        console.print(table)

    def _display_pdp_context(self):
        """Display PDP context configuration"""
        for result in self.results:
            if 'contexts' in result.parsed_data and result.parsed_data['contexts']:
                table = Table(title="PDP Context Configuration", box=box.ROUNDED, show_header=True,
                              header_style="bold magenta")
                table.add_column("CID", style="cyan", width=5)
                table.add_column("PDP Type", style="white", width=10)
                table.add_column("APN", style="white", width=30)
                table.add_column("Address", style="white")

                for ctx in result.parsed_data['contexts']:
                    table.add_row(
                        str(ctx['cid']),
                        ctx['pdp_type'],
                        ctx['apn'],
                        ctx['pdp_addr']
                    )

                console.print(table)


class NetworkTools:
    """Network troubleshooting and configuration tools"""

    def __init__(self, modem: ModemConnection):
        self.modem = modem

    def scan_networks(self):
        """Scan for available networks"""
        console.print("\n[yellow]Scanning for available networks (this may take 30-60 seconds)...[/yellow]")

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Scanning...", total=None)
            result = self.modem.send_at_command("AT+COPS=?", wait_time=60)

        if not result.success:
            console.print(f"[red]Scan failed: {result.error or 'Unknown error'}[/red]")
            return

        # Parse network list
        networks = []
        pattern = r'\((\d+),"([^"]*)","([^"]*)","(\d+)",(\d+)\)'
        matches = re.findall(pattern, result.raw_response)

        if not matches:
            console.print("[yellow]No networks found or unable to parse results[/yellow]")
            return

        table = Table(title="Available Networks", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Status", style="cyan", width=15)
        table.add_column("Operator (Long)", style="white", width=30)
        table.add_column("Operator (Short)", style="white", width=20)
        table.add_column("Network Code", style="white", width=15)
        table.add_column("Technology", style="white")

        status_map = {
            '0': 'Unknown',
            '1': '[green]Available[/green]',
            '2': '[blue]Current[/blue]',
            '3': '[red]Forbidden[/red]'
        }

        tech_map = {
            '0': 'GSM',
            '1': 'GSM Compact',
            '2': 'UTRAN',
            '3': 'GSM w/EGPRS',
            '4': 'UTRAN w/HSDPA',
            '5': 'UTRAN w/HSUPA',
            '6': 'UTRAN w/HSUPA+HSDPA',
            '7': 'E-UTRAN (LTE)',
            '8': 'EC-GSM-IoT',
            '9': 'E-UTRAN NB-S1'
        }

        for match in matches:
            stat, long_name, short_name, numeric, tech = match
            table.add_row(
                status_map.get(stat, stat),
                long_name,
                short_name,
                numeric,
                tech_map.get(tech, f"Unknown ({tech})")
            )

        console.print("\n")
        console.print(table)

    def clear_fplmn(self):
        """Clear forbidden network list (FPLMN)"""
        console.print("\n[bold yellow]Clear Forbidden Network List (FPLMN)[/bold yellow]")
        console.print("This will clear the list of networks the modem has been denied access to.\n")

        if not Confirm.ask("Do you want to proceed?"):
            console.print("[yellow]Operation cancelled[/yellow]")
            return

        # Common AT commands to clear FPLMN (varies by modem)
        commands = [
            ("AT+CRSM=214,28539,0,0,12,\"FFFFFFFFFFFFFFFFFFFFFFFF\"", "Clear FPLMN (Method 1)"),
            ("AT+CPOL=", "Clear preferred operator list"),
        ]

        console.print()
        for cmd, description in commands:
            console.print(f"[cyan]Executing: {description}[/cyan]")
            result = self.modem.send_at_command(cmd)

            if result.success:
                console.print(f"[green]✓ {description} successful[/green]")
            else:
                console.print(f"[yellow]⚠ {description} failed (may not be supported)[/yellow]")

            console.print(f"Response: {result.raw_response.strip()}\n")

        console.print("[green]FPLMN clear operation completed[/green]")
        console.print("[yellow]Note: You may need to restart the modem for changes to take effect[/yellow]")

    def view_fplmn(self):
        """View forbidden network list (FPLMN)"""
        console.print("\n[bold cyan]Forbidden Network List (FPLMN)[/bold cyan]\n")
        console.print("This shows networks that the modem has been denied access to.\n")

        # Method 1: Try to read FPLMN from SIM EF_FPLMN file
        console.print("[cyan]Attempting to read FPLMN from SIM...[/cyan]")
        result = self.modem.send_at_command('AT+CRSM=176,28539,0,0,12')

        if result.success and result.raw_response:
            console.print(Panel(result.raw_response, title="[cyan]FPLMN Data (Raw)[/cyan]", box=box.ROUNDED))

            # Try to parse hex data
            # FPLMN is stored as 3-byte BCD entries (MCC+MNC)
            # Format: AA BB CC where AA/BB = MCC, CC = MNC
            console.print("\n[dim]Note: FPLMN is stored in BCD format (3 bytes per entry)[/dim]")
            console.print("[dim]Example: '13 F0 62' = MCC 310, MNC 260 (T-Mobile US)[/dim]")
        else:
            console.print("[yellow]Could not read FPLMN from SIM (may not be supported)[/yellow]")

        console.print()

        # Method 2: Check preferred operator list (CPOL)
        console.print("[cyan]Checking Preferred Operator List (CPOL)...[/cyan]")
        cpol_result = self.modem.send_at_command('AT+CPOL?')

        if cpol_result.success and cpol_result.raw_response:
            console.print(Panel(cpol_result.raw_response, title="[cyan]Preferred Operators[/cyan]", box=box.ROUNDED))
        else:
            console.print("[yellow]Could not read CPOL (may not be supported)[/yellow]")

        console.print()

        # Method 3: Try alternative CPLS command (some modems)
        console.print("[cyan]Checking for alternative FPLMN commands...[/cyan]")
        cpls_result = self.modem.send_at_command('AT+CPLS?')

        if cpls_result.success and 'OK' in cpls_result.raw_response:
            console.print(Panel(cpls_result.raw_response, title="[cyan]PLMN Selection[/cyan]", box=box.ROUNDED))
        else:
            console.print("[yellow]Alternative commands not supported on this modem[/yellow]")

        console.print()
        console.print("[dim]Note: If FPLMN appears empty (FFFFFF...), no networks are currently forbidden.[/dim]")

    def configure_apn(self):
        """Configure APN settings with common presets"""
        console.print("\n[bold cyan]Configure APN Settings[/bold cyan]\n")

        # Get current settings
        result = self.modem.send_at_command("AT+CGDCONT?")

        if 'contexts' in result.parsed_data and result.parsed_data['contexts']:
            console.print("[cyan]Current PDP Contexts:[/cyan]")
            table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
            table.add_column("CID", style="cyan", width=5)
            table.add_column("Type", style="white", width=10)
            table.add_column("APN", style="white", width=30)

            for ctx in result.parsed_data['contexts']:
                table.add_row(str(ctx['cid']), ctx['pdp_type'], ctx['apn'])
            console.print(table)
            console.print()

        # Offer common presets
        console.print("[bold]Quick Setup Options:[/bold]")
        console.print("  [cyan]1[/cyan]. Hologram (hologram)")
        console.print("  [cyan]2[/cyan]. T-Mobile US (fast.t-mobile.com)")
        console.print("  [cyan]3[/cyan]. AT&T (broadband)")
        console.print("  [cyan]4[/cyan]. Verizon (vzwinternet)")
        console.print("  [cyan]5[/cyan]. Custom APN")
        console.print()

        choice = Prompt.ask("Select option", choices=["1", "2", "3", "4", "5"], default="5")

        # Map choices to APNs
        apn_presets = {
            "1": ("hologram", "IP"),
            "2": ("fast.t-mobile.com", "IPV4V6"),
            "3": ("broadband", "IP"),
            "4": ("vzwinternet", "IP"),
        }

        if choice in apn_presets:
            apn, pdp_type = apn_presets[choice]
            cid = Prompt.ask("Enter Context ID (CID)", default="1")
        else:
            # Custom
            cid = Prompt.ask("Enter Context ID (CID)", default="1")
            pdp_type = Prompt.ask("Enter PDP Type", choices=["IP", "IPV6", "IPV4V6"], default="IP")
            apn = Prompt.ask("Enter APN name")

        # Set APN
        cmd = f'AT+CGDCONT={cid},"{pdp_type}","{apn}"'
        console.print(f"\n[cyan]Executing: {cmd}[/cyan]")

        result = self.modem.send_at_command(cmd)

        if result.success:
            console.print("[green]✓ APN configuration successful[/green]")

            # Ask if user wants to activate the context
            if Confirm.ask("\nActivate this PDP context now?", default=True):
                activate_result = self.modem.send_at_command(f"AT+CGACT=1,{cid}")
                if activate_result.success:
                    console.print("[green]✓ PDP context activated[/green]")
                else:
                    console.print(f"[yellow]⚠ Activation failed: {activate_result.error}[/yellow]")
        else:
            console.print(f"[red]✗ APN configuration failed: {result.error}[/red]")

        # Verify
        console.print("\n[cyan]Verifying configuration...[/cyan]")
        verify_result = self.modem.send_at_command("AT+CGDCONT?")

        if 'contexts' in verify_result.parsed_data:
            for ctx in verify_result.parsed_data['contexts']:
                if ctx['cid'] == int(cid):
                    console.print(f"[green]✓ CID {cid}: {ctx['pdp_type']}, APN: {ctx['apn']}[/green]")

    def force_network_registration(self):
        """Force network registration with specific operator"""
        console.print("\n[bold cyan]Force Network Registration[/bold cyan]\n")

        console.print("First, let's scan for available networks...")
        self.scan_networks()

        console.print("\n[yellow]Enter network selection mode:[/yellow]")
        console.print("  0 = Automatic")
        console.print("  1 = Manual")
        console.print("  4 = Manual with fallback to automatic\n")

        mode = Prompt.ask("Select mode", choices=["0", "1", "4"], default="0")

        if mode != "0":
            operator = Prompt.ask("Enter operator numeric code (e.g., 310260 for T-Mobile US)")
            cmd = f'AT+COPS={mode},2,"{operator}"'
        else:
            cmd = "AT+COPS=0"

        console.print(f"\n[cyan]Executing: {cmd}[/cyan]")
        console.print("[yellow]This may take 30-60 seconds...[/yellow]\n")

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Registering...", total=None)
            result = self.modem.send_at_command(cmd, wait_time=60)

        if result.success:
            console.print("[green]✓ Registration command successful[/green]")
        else:
            console.print(f"[red]✗ Registration failed: {result.error}[/red]")

        # Check registration status
        console.print("\n[cyan]Checking registration status...[/cyan]")
        time.sleep(2)

        reg_result = self.modem.send_at_command("AT+CREG?")
        if 'creg_status_text' in reg_result.parsed_data:
            console.print(f"Status: {reg_result.parsed_data['creg_status_text']}")


class DataTransferTest:
    """Tools for testing cellular data transfer and validating provider billing"""

    def __init__(self, modem: ModemConnection):
        self.modem = modem
        self.wifi_was_disabled = False
        self.original_wifi_interface = None
        self.routes_added = []  # Track routes we add for cleanup

    def get_default_route(self) -> Optional[Dict[str, str]]:
        """Get the current default route interface"""
        try:
            if IS_LINUX:
                result = subprocess.run(['ip', 'route', 'show', 'default'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    # Parse: "default via 192.168.1.1 dev wlan0 proto dhcp metric 600"
                    match = re.search(r'dev\s+(\S+)', result.stdout)
                    if match:
                        iface = match.group(1)
                        # Get IP for this interface
                        ip_result = subprocess.run(['ip', 'addr', 'show', iface],
                                                  capture_output=True, text=True, timeout=5)
                        ip_addr = None
                        if ip_result.returncode == 0:
                            ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', ip_result.stdout)
                            if ip_match:
                                ip_addr = ip_match.group(1)

                        return {
                            'interface': iface,
                            'ip': ip_addr,
                            'type': 'WiFi' if 'wlan' in iface else 'Ethernet' if 'eth' in iface else 'Cellular' if any(x in iface for x in ['wwan', 'ppp']) else 'Unknown'
                        }
            elif IS_WINDOWS:
                result = subprocess.run(['route', 'print', '0.0.0.0'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    # Parse Windows route output
                    for line in result.stdout.split('\n'):
                        if '0.0.0.0' in line and 'On-link' not in line:
                            parts = line.split()
                            if len(parts) >= 4:
                                return {'interface': 'default', 'ip': parts[2], 'type': 'Unknown'}
        except Exception as e:
            if DEBUG_MODE:
                console.print(f"[yellow]Error getting default route: {e}[/yellow]")

        return None

    def get_wifi_interface(self) -> Optional[str]:
        """Detect WiFi interface name"""
        try:
            if IS_LINUX:
                result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    # Look for wlan interfaces
                    match = re.search(r'\d+:\s+(wlan\d+):', result.stdout)
                    if match:
                        return match.group(1)
            elif IS_WINDOWS:
                result = subprocess.run(['netsh', 'interface', 'show', 'interface'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'wi-fi' in line.lower() or 'wireless' in line.lower():
                            parts = line.split()
                            if len(parts) >= 4:
                                return ' '.join(parts[3:])
        except Exception:
            pass

        return None

    def check_wifi_status(self) -> Dict[str, any]:
        """Check if WiFi is active and is the default route"""
        status = {
            'wifi_interface': None,
            'wifi_is_up': False,
            'wifi_has_ip': False,
            'wifi_is_default': False,
            'default_route': None
        }

        # Get WiFi interface
        wifi_iface = self.get_wifi_interface()
        status['wifi_interface'] = wifi_iface

        if wifi_iface and IS_LINUX:
            # Check if WiFi is UP
            try:
                result = subprocess.run(['ip', 'link', 'show', wifi_iface],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    status['wifi_is_up'] = 'state UP' in result.stdout

                    # Check if WiFi has IP
                    ip_result = subprocess.run(['ip', 'addr', 'show', wifi_iface],
                                              capture_output=True, text=True, timeout=5)
                    if ip_result.returncode == 0:
                        status['wifi_has_ip'] = bool(re.search(r'inet\s+\d+', ip_result.stdout))
            except Exception:
                pass

        # Check default route
        default_route = self.get_default_route()
        status['default_route'] = default_route

        if default_route and wifi_iface:
            status['wifi_is_default'] = default_route['interface'] == wifi_iface

        return status

    def disable_wifi_temporarily(self) -> bool:
        """Temporarily disable WiFi (requires sudo)"""
        wifi_iface = self.get_wifi_interface()
        if not wifi_iface:
            return False

        try:
            if IS_LINUX:
                result = subprocess.run(['sudo', 'ip', 'link', 'set', wifi_iface, 'down'],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    self.wifi_was_disabled = True
                    self.original_wifi_interface = wifi_iface
                    return True
                else:
                    console.print(f"[red]Failed to disable WiFi: {result.stderr}[/red]")
                    return False
            elif IS_WINDOWS:
                result = subprocess.run(['netsh', 'interface', 'set', 'interface', wifi_iface, 'disabled'],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    self.wifi_was_disabled = True
                    self.original_wifi_interface = wifi_iface
                    return True
                else:
                    return False
        except Exception as e:
            console.print(f"[red]Error disabling WiFi: {e}[/red]")
            return False

    def enable_wifi(self) -> bool:
        """Re-enable WiFi if it was disabled by this tool"""
        if not self.wifi_was_disabled or not self.original_wifi_interface:
            return False

        try:
            if IS_LINUX:
                result = subprocess.run(['sudo', 'ip', 'link', 'set', self.original_wifi_interface, 'up'],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    self.wifi_was_disabled = False
                    console.print(f"[green]✓ WiFi ({self.original_wifi_interface}) re-enabled[/green]")
                    return True
            elif IS_WINDOWS:
                result = subprocess.run(['netsh', 'interface', 'set', 'interface', self.original_wifi_interface, 'enabled'],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    self.wifi_was_disabled = False
                    console.print(f"[green]✓ WiFi ({self.original_wifi_interface}) re-enabled[/green]")
                    return True
        except Exception as e:
            console.print(f"[red]Error re-enabling WiFi: {e}[/red]")

        return False

    def add_temporary_route(self, destination: str, interface: str) -> bool:
        """Add a temporary route for specific destination via cellular interface"""
        try:
            if IS_LINUX:
                # Check if route already exists
                check_result = subprocess.run(['ip', 'route', 'show', destination],
                                            capture_output=True, text=True, timeout=5)
                if check_result.returncode == 0 and check_result.stdout.strip():
                    console.print(f"[yellow]Route for {destination} already exists, removing old route first[/yellow]")
                    subprocess.run(['sudo', 'ip', 'route', 'del', destination],
                                 capture_output=True, text=True, timeout=5)

                # Add new route
                result = subprocess.run(['sudo', 'ip', 'route', 'add', destination, 'dev', interface],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    self.routes_added.append({'destination': destination, 'interface': interface})
                    return True
                else:
                    console.print(f"[red]Failed to add route: {result.stderr}[/red]")
                    return False
            elif IS_WINDOWS:
                # Windows: route add destination mask 255.255.255.255 interface_ip
                result = subprocess.run(['route', 'add', destination, 'mask', '255.255.255.255', interface],
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    self.routes_added.append({'destination': destination, 'interface': interface})
                    return True
                else:
                    return False
        except Exception as e:
            console.print(f"[red]Error adding route: {e}[/red]")
            return False

    def remove_temporary_routes(self) -> bool:
        """Remove all temporary routes that were added"""
        if not self.routes_added:
            return True

        success = True
        for route in self.routes_added:
            try:
                if IS_LINUX:
                    result = subprocess.run(['sudo', 'ip', 'route', 'del', route['destination']],
                                          capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        console.print(f"[green]✓ Removed route for {route['destination']}[/green]")
                    else:
                        console.print(f"[yellow]⚠ Could not remove route for {route['destination']}[/yellow]")
                        success = False
                elif IS_WINDOWS:
                    result = subprocess.run(['route', 'delete', route['destination']],
                                          capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        console.print(f"[green]✓ Removed route for {route['destination']}[/green]")
                    else:
                        success = False
            except Exception as e:
                console.print(f"[yellow]Error removing route: {e}[/yellow]")
                success = False

        self.routes_added = []
        return success

    def resolve_hostname(self, hostname: str) -> Optional[str]:
        """Resolve hostname to IP address"""
        try:
            import socket
            ip = socket.gethostbyname(hostname)
            return ip
        except Exception as e:
            console.print(f"[yellow]Could not resolve {hostname}: {e}[/yellow]")
            return None

    def verify_routing(self) -> Dict[str, any]:
        """Comprehensive routing verification before test"""
        verification = {
            'cellular_available': False,
            'cellular_interface': None,
            'cellular_interfaces_found': [],
            'cellular_all_issues': [],
            'wifi_active': False,
            'wifi_is_default': False,
            'routing_ok': False,
            'warnings': [],
            'recommendations': []
        }

        # Get ALL cellular interfaces (diagnostic mode)
        cellular_ifaces = self.get_cellular_interfaces(diagnostic_mode=True)
        verification['cellular_interfaces_found'] = cellular_ifaces

        if cellular_ifaces:
            # Check for ready interfaces
            for iface in cellular_ifaces:
                if iface.get('is_ready', False):
                    verification['cellular_available'] = True
                    verification['cellular_interface'] = iface['name']
                    break

            # Collect all issues from all interfaces
            for iface in cellular_ifaces:
                if iface.get('issues'):
                    for issue in iface['issues']:
                        verification['cellular_all_issues'].append(f"{iface['name']}: {issue}")

        if not verification['cellular_available']:
            if not cellular_ifaces:
                verification['warnings'].append("No cellular interfaces detected (wwan*, ppp*, usb*)")
                verification['recommendations'].append("Check modem connection and AT commands")
                verification['recommendations'].append("Run: ip link show")
            else:
                verification['warnings'].append("Cellular interfaces found but not ready for data transfer")
                verification['recommendations'].append("Check details below to see what's missing")

                # Specific recommendations based on issues
                has_down_interface = any("Interface is DOWN" in str(iface.get('issues', [])) for iface in cellular_ifaces)
                has_no_ip = any("No IP address assigned" in str(iface.get('issues', [])) for iface in cellular_ifaces)

                if has_no_ip:
                    verification['recommendations'].append("Activate PDP context: APN & Data Connection → Activate PDP Context")
                    verification['recommendations'].append("Verify APN configuration is correct")
                if has_down_interface:
                    verification['recommendations'].append("Bring interface UP (may happen automatically after PDP activation)")

        # Check WiFi status
        wifi_status = self.check_wifi_status()
        verification['wifi_active'] = wifi_status['wifi_is_up'] and wifi_status['wifi_has_ip']
        verification['wifi_is_default'] = wifi_status['wifi_is_default']

        if verification['wifi_is_default']:
            verification['warnings'].append(f"WiFi ({wifi_status['wifi_interface']}) is the default route")
            verification['warnings'].append("Test data will go over WiFi, NOT cellular!")
            verification['recommendations'].append("Disable WiFi temporarily (recommended)")
            verification['recommendations'].append("Or configure routing manually")
        elif verification['wifi_active']:
            verification['warnings'].append("WiFi is active but not default route")

        # Determine if routing is OK for cellular test
        verification['routing_ok'] = (
            verification['cellular_available'] and
            not verification['wifi_is_default']
        )

        return verification

    def get_cellular_interfaces(self, diagnostic_mode: bool = False) -> List[Dict[str, str]]:
        """Detect available cellular network interfaces

        Args:
            diagnostic_mode: If True, return ALL found interfaces regardless of state
        """
        interfaces = []

        try:
            if IS_LINUX:
                # Get all network interfaces
                result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    # Look for common cellular interface patterns
                    patterns = [r'wwan\d+', r'ppp\d+', r'usb\d+', r'wwp\d+s\d+']
                    for line in result.stdout.split('\n'):
                        for pattern in patterns:
                            match = re.search(r'\d+:\s+(' + pattern + r'):', line)
                            if match:
                                iface_name = match.group(1)

                                # Get detailed interface info
                                ip_result = subprocess.run(['ip', 'addr', 'show', iface_name],
                                                          capture_output=True, text=True, timeout=5)
                                ip_addr = None
                                ip_details = ""
                                if ip_result.returncode == 0:
                                    ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+(/\d+)?)', ip_result.stdout)
                                    if ip_match:
                                        ip_addr = ip_match.group(1)
                                        ip_details = ip_match.group(0)

                                # Check if interface is UP
                                is_up = 'UP' in line and 'state UP' in line
                                is_lower_up = 'LOWER_UP' in line

                                # Detailed status
                                status_details = []
                                if is_up:
                                    status_details.append("UP")
                                else:
                                    status_details.append("DOWN")

                                if is_lower_up:
                                    status_details.append("LOWER_UP")

                                # Issues found
                                issues = []
                                if not is_up:
                                    issues.append("Interface is DOWN")
                                if not ip_addr:
                                    issues.append("No IP address assigned")
                                if is_up and not is_lower_up:
                                    issues.append("Physical layer not ready")

                                interfaces.append({
                                    'name': iface_name,
                                    'ip': ip_addr or 'No IP assigned',
                                    'status': 'UP' if is_up else 'DOWN',
                                    'is_ready': is_up and ip_addr is not None,
                                    'status_details': ', '.join(status_details),
                                    'issues': issues,
                                    'raw_line': line.strip()
                                })
            elif IS_WINDOWS:
                # Windows - look for cellular adapters
                result = subprocess.run(['netsh', 'interface', 'show', 'interface'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if any(keyword in line.lower() for keyword in ['mobile', 'cellular', 'wwan', 'lte']):
                            parts = line.split()
                            if len(parts) >= 4:
                                iface_name = ' '.join(parts[3:])
                                interfaces.append({
                                    'name': iface_name,
                                    'ip': 'Use ipconfig to check',
                                    'status': parts[1]
                                })
        except Exception as e:
            if DEBUG_MODE:
                console.print(f"[yellow]Error detecting interfaces: {e}[/yellow]")

        return interfaces

    def calculate_overhead_estimate(self, payload_bytes: int, use_https: bool = True) -> Dict[str, int]:
        """Calculate estimated overhead for data transfer"""
        overhead = {
            'payload': payload_bytes,
            'tcp_ip_headers': 0,
            'tls_handshake': 0,
            'dns_lookup': 0,
            'http_headers': 0,
        }

        # Estimate number of TCP packets (MTU ~1500, MSS ~1460)
        mss = 1460
        num_packets = max(1, (payload_bytes + mss - 1) // mss)

        # TCP/IP overhead (20 bytes TCP + 20 bytes IP per packet)
        overhead['tcp_ip_headers'] = num_packets * 40

        # Add SYN, SYN-ACK, ACK handshake
        overhead['tcp_ip_headers'] += 3 * 40  # 3-way handshake

        # Add FIN handshake
        overhead['tcp_ip_headers'] += 2 * 40  # FIN + ACK

        if use_https:
            # TLS 1.2/1.3 handshake (conservative estimate)
            overhead['tls_handshake'] = 3000  # ~3KB for handshake

            # DNS lookup for domain
            overhead['dns_lookup'] = 80  # Query + response

            # HTTPS headers (conservative estimate)
            overhead['http_headers'] = 400  # Request + response headers
        else:
            # DNS lookup
            overhead['dns_lookup'] = 80

            # HTTP headers
            overhead['http_headers'] = 300

        # Total
        overhead['total_estimated'] = sum(overhead.values())
        overhead['overhead_percentage'] = int((overhead['total_estimated'] - payload_bytes) / payload_bytes * 100) if payload_bytes > 0 else 0

        return overhead

    def send_test_data(self, size_bytes: int, interface_name: Optional[str] = None) -> Dict:
        """Send test data over cellular connection"""
        result = {
            'success': False,
            'payload_size': size_bytes,
            'error': None,
            'interface_used': interface_name or 'default route',
        }

        if not HAS_REQUESTS:
            # Fallback to curl if requests not available
            try:
                # Generate test data
                test_data = b'X' * size_bytes

                cmd = ['curl', '-X', 'POST', 'https://httpbin.org/post',
                       '-H', 'Content-Type: application/octet-stream',
                       '--data-binary', '@-',
                       '-o', '/dev/null',
                       '-w', '%{size_upload},%{size_download}',
                       '-s']

                if interface_name and IS_LINUX:
                    cmd.extend(['--interface', interface_name])

                proc = subprocess.run(cmd, input=test_data, capture_output=True, text=True, timeout=30)

                if proc.returncode == 0:
                    sizes = proc.stdout.strip().split(',')
                    result['success'] = True
                    result['bytes_uploaded'] = int(sizes[0]) if len(sizes) > 0 else size_bytes
                    result['bytes_downloaded'] = int(sizes[1]) if len(sizes) > 1 else 0
                else:
                    result['error'] = f"curl failed: {proc.stderr}"
            except Exception as e:
                result['error'] = str(e)
        else:
            # Use requests library
            try:
                test_data = b'X' * size_bytes

                # Create session
                session = requests.Session()

                # Note: Interface binding requires additional setup on Windows
                # For now, we rely on system routing

                response = session.post('https://httpbin.org/post',
                                       data=test_data,
                                       headers={'Content-Type': 'application/octet-stream'},
                                       timeout=30)

                result['success'] = response.status_code == 200
                result['bytes_uploaded'] = len(test_data)
                result['bytes_downloaded'] = len(response.content)
                result['http_status'] = response.status_code

            except Exception as e:
                result['error'] = str(e)

        return result

    def display_test_instructions(self, size_bytes: int):
        """Display instructions for validating data usage"""
        overhead = self.calculate_overhead_estimate(size_bytes, use_https=True)

        console.print("\n")
        console.rule("[bold cyan]Cellular Data Transfer Test", style="cyan")
        console.print()

        # Overview
        console.print("[bold yellow]📊 What This Test Does:[/bold yellow]")
        console.print("  • Sends exactly [cyan]" + f"{size_bytes:,}[/cyan] bytes of test data via HTTPS")
        console.print("  • Posts to httpbin.org (a public testing service)")
        console.print("  • Uses your active cellular connection")
        console.print()

        # Data breakdown
        console.print("[bold yellow]📦 Expected Data Usage Breakdown:[/bold yellow]")
        table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan", width=25)
        table.add_column("Bytes", justify="right", style="white", width=15)
        table.add_column("Purpose", style="dim")

        table.add_row("Your Payload", f"{overhead['payload']:,}", "Actual data you're sending")
        table.add_row("TCP/IP Headers", f"{overhead['tcp_ip_headers']:,}", "Protocol overhead for packets")
        table.add_row("TLS Handshake", f"{overhead['tls_handshake']:,}", "HTTPS encryption setup")
        table.add_row("DNS Lookup", f"{overhead['dns_lookup']:,}", "Domain name resolution")
        table.add_row("HTTP Headers", f"{overhead['http_headers']:,}", "Request/response metadata")
        table.add_row("", "", "")
        table.add_row("[bold]TOTAL ESTIMATED[/bold]",
                     f"[bold]{overhead['total_estimated']:,}[/bold]",
                     f"[bold]+{overhead['overhead_percentage']}% overhead[/bold]")

        console.print(table)
        console.print()

        # Provider dashboard expectations
        console.print("[bold yellow]📱 What You'll See on Hologram Dashboard:[/bold yellow]")
        console.print(f"  • Hologram shows [bold]TOTAL aggregated data usage[/bold]")
        console.print(f"  • Expected: ~[bold green]{overhead['total_estimated']:,} bytes[/bold green] ({overhead['total_estimated']/1024:.1f} KB)")
        console.print(f"  • NOT broken down by type (headers, payload, etc.)")
        console.print(f"  • Dashboard updates may take [yellow]1-2 minutes[/yellow]")
        console.print()

        # Step-by-step validation
        console.print("[bold yellow]✅ How to Validate:[/bold yellow]")
        console.print("  [bold]BEFORE running test:[/bold]")
        console.print("    1. Login to [cyan]https://dashboard.hologram.io[/cyan]")
        console.print("    2. Navigate to your device")
        console.print("    3. Note current [bold]total data usage[/bold] (in bytes)")
        console.print()
        console.print("  [bold]AFTER running test:[/bold]")
        console.print("    4. Wait [yellow]1-2 minutes[/yellow] for dashboard to update")
        console.print("    5. Refresh the dashboard page")
        console.print("    6. Check new total data usage")
        console.print(f"    7. Difference should be ~[bold green]{overhead['total_estimated']:,} bytes[/bold green]")
        console.print()

        # Important notes
        console.print("[bold red]⚠️  Important Notes:[/bold red]")
        console.print("  • This test will use [bold]real cellular data[/bold] (costs apply)")
        console.print("  • Ensure WiFi is disabled or cellular routing is configured")
        console.print("  • Background processes may also use data during test")
        console.print("  • Actual usage may vary ±10% due to network conditions")
        console.print()


class DataUsageTools:
    """Tools for monitoring and troubleshooting data usage"""

    def __init__(self, modem: ModemConnection):
        self.modem = modem

    def check_pdp_status(self):
        """Check PDP context activation status"""
        console.print("\n[bold cyan]PDP Context Status[/bold cyan]\n")

        # Get context definition
        result = self.modem.send_at_command("AT+CGDCONT?")
        if 'contexts' in result.parsed_data:
            console.print("[cyan]Defined PDP Contexts:[/cyan]")
            for ctx in result.parsed_data['contexts']:
                console.print(f"  CID {ctx['cid']}: {ctx['pdp_type']}, APN: {ctx['apn']}")

        console.print()

        # Get activation status
        act_result = self.modem.send_at_command("AT+CGACT?")
        console.print("[cyan]PDP Context Activation Status:[/cyan]")

        for line in act_result.raw_response.split('\n'):
            if '+CGACT:' in line:
                match = re.search(r'\+CGACT:\s*(\d+),(\d+)', line)
                if match:
                    cid = match.group(1)
                    state = int(match.group(2))
                    state_text = "[green]Active[/green]" if state == 1 else "[red]Inactive[/red]"
                    console.print(f"  CID {cid}: {state_text}")

        console.print()

        # Get IP address if available
        addr_result = self.modem.send_at_command("AT+CGPADDR")
        console.print("[cyan]IP Addresses:[/cyan]")

        for line in addr_result.raw_response.split('\n'):
            if '+CGPADDR:' in line:
                console.print(f"  {line.strip()}")

    def check_data_connection(self):
        """Check if data connection is established"""
        console.print("\n[bold cyan]Data Connection Check[/bold cyan]\n")

        tests = [
            ("AT+CGATT?", "GPRS Attach Status"),
            ("AT+CGACT?", "PDP Context Activation"),
            ("AT+CGPADDR", "IP Address Assignment"),
        ]

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Test", style="cyan", width=30)
        table.add_column("Result", style="white", width=15)
        table.add_column("Details", style="white")

        for cmd, description in tests:
            result = self.modem.send_at_command(cmd)

            if result.success:
                status = "[green]✓ Pass[/green]"
                details = result.raw_response.strip().replace('\r\n', ' ')
            else:
                status = "[red]✗ Fail[/red]"
                details = result.error or "No response"

            table.add_row(description, status, details)

        console.print(table)
        console.print()

        # Additional advice
        console.print("[yellow]Troubleshooting Tips:[/yellow]")
        console.print("  • If GPRS attach fails, check SIM card and network registration")
        console.print("  • If PDP context is inactive, try: AT+CGACT=1,1")
        console.print("  • If no IP address, verify APN configuration")
        console.print("  • Check signal strength with signal quality test")


class ModemDiagnosticTool:
    """Main application class"""

    def __init__(self):
        self.modem: Optional[ModemConnection] = None
        self.connected = False
        self.modemmanager_was_stopped = False  # Track if we stopped ModemManager

    def show_banner(self):
        """Display application banner"""
        banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        Cellular Modem Diagnostic & Configuration Tool        ║
║                    for Raspberry Pi & Windows                ║
║                                                               ║
║               ☕ buymeacoffee.com/mike.brandon                ║
╚═══════════════════════════════════════════════════════════════╝
        """
        console.print(Panel(banner, style="bold cyan", box=box.DOUBLE))

    def _restart_modemmanager_if_needed(self):
        """Restart ModemManager if we stopped it"""
        if self.modemmanager_was_stopped and IS_LINUX:
            console.print("\n[cyan]Restarting ModemManager...[/cyan]")
            if ModemManagerHelper.restart():
                console.print("[green]✓ ModemManager restarted[/green]")
            else:
                console.print("[yellow]⚠ Could not restart ModemManager[/yellow]")
                console.print("[dim]  You may need to restart it manually: sudo systemctl start ModemManager[/dim]")
            self.modemmanager_was_stopped = False

    def detect_serial_ports(self) -> List[Dict]:
        """Detect all available serial ports"""
        ports = []

        if IS_WINDOWS:
            # Windows COM port detection
            import serial.tools.list_ports

            for port in serial.tools.list_ports.comports():
                port_info = {
                    'path': port.device,
                    'name': port.device,
                    'type': 'COM Port',
                    'description': port.description or 'No description',
                    'vendor': port.manufacturer or '',
                    'priority': 0  # Will be set based on port number
                }

                # Extract COM port number for prioritization
                try:
                    com_num = int(re.search(r'COM(\d+)', port.device).group(1))
                    port_info['priority'] = -com_num  # Lower COM numbers get higher priority
                except:
                    port_info['priority'] = 999

                ports.append(port_info)

        else:
            # Linux/Unix serial port detection
            # Common serial port patterns for cellular modems
            patterns = [
                '/dev/ttyUSB*',
                '/dev/ttyACM*',
                '/dev/ttyAMA*',
                '/dev/ttyS*'
            ]

            for pattern in patterns:
                for port_path in glob.glob(pattern):
                    port_info = {
                        'path': port_path,
                        'name': port_path.split('/')[-1],
                        'type': 'Unknown',
                        'description': '',
                        'priority': 0
                    }

                    # Try to get additional info from udevadm
                    try:
                        result = subprocess.run(
                            ['udevadm', 'info', '--name=' + port_path, '--query=property'],
                            capture_output=True,
                            text=True,
                            timeout=1  # Reduced timeout
                        )

                        if result.returncode == 0:
                            for line in result.stdout.split('\n'):
                                if 'ID_MODEL=' in line:
                                    port_info['description'] = line.split('=')[1].strip()
                                elif 'ID_USB_INTERFACE_NUM=' in line:
                                    interface_num = line.split('=')[1].strip()
                                    port_info['interface'] = interface_num
                                elif 'ID_VENDOR=' in line:
                                    port_info['vendor'] = line.split('=')[1].strip()

                        # Determine port type and priority
                        if 'ttyUSB' in port_path:
                            port_info['type'] = 'USB Serial'
                            # Extract USB number and prioritize HIGHEST first (USB3 > USB2 > USB1 > USB0)
                            # Modem AT ports are typically on the highest USB interface
                            match = re.search(r'ttyUSB(\d+)', port_path)
                            if match:
                                usb_num = int(match.group(1))
                                # Negative priority, higher USB number = lower (better) priority value
                                port_info['priority'] = -usb_num  # USB3=-3, USB2=-2, USB1=-1, USB0=0
                            else:
                                port_info['priority'] = 0
                        elif 'ttyACM' in port_path:
                            port_info['type'] = 'USB CDC-ACM'
                            port_info['priority'] = 10
                        elif 'ttyAMA' in port_path:
                            port_info['type'] = 'UART (Hardware)'
                            port_info['priority'] = 20
                        elif 'ttyS' in port_path:
                            port_info['type'] = 'Serial Port'
                            port_info['priority'] = 30

                    except Exception:
                        pass

                    ports.append(port_info)

        # Sort by priority (lower = higher priority)
        return sorted(ports, key=lambda x: (x.get('priority', 999), x['path']))

    def test_port_for_modem(self, port: str, baudrate: int = 115200, quick_test: bool = False) -> Tuple[bool, Optional[str]]:
        """Test if a port responds to AT commands with timeout protection

        Args:
            port: Serial port path
            baudrate: Baud rate to test
            quick_test: If True, use faster timeout for initial screening
        """
        if DEBUG_MODE:
            console.print(f"[dim]DEBUG: Starting test for {port} @ {baudrate}[/dim]")

        # Check blacklist first
        if port in SKIP_PORTS:
            if DEBUG_MODE:
                console.print(f"[dim]DEBUG: {port} in skip list[/dim]")
            return False, "Port in skip list (MODEMO_SKIP_PORTS)"

        # Pre-flight checks on Linux to avoid kernel-level blocking
        if IS_LINUX:
            if DEBUG_MODE:
                console.print(f"[dim]DEBUG: Running pre-flight checks for {port}[/dim]")

            # Check if port exists and is accessible
            if not os.path.exists(port):
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} does not exist[/dim]")
                return False, "Port does not exist"

            # Check if we have read/write permissions
            if not os.access(port, os.R_OK | os.W_OK):
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} permission denied[/dim]")
                return False, "Permission denied"

            # Check if port is already locked/in use by checking for lock file
            # This is a common pattern on Linux
            lock_file = f"/var/lock/LCK..{os.path.basename(port)}"
            if os.path.exists(lock_file):
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} has lock file[/dim]")
                return False, "Port locked by another process"

            # CRITICAL: Try to open port in non-blocking mode first to detect kernel-level blocks
            # This is the most aggressive check to prevent hangs
            if DEBUG_MODE:
                console.print(f"[dim]DEBUG: Attempting non-blocking open of {port}[/dim]")
            try:
                import fcntl
                # Try to open with O_NONBLOCK to avoid blocking on open()
                fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)

                # If we got here, port can be opened. Close it immediately
                os.close(fd)
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: Non-blocking open of {port} SUCCESS[/dim]")
            except OSError as e:
                # Port is blocked at kernel level or has issues
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} OSError: {e.errno} {e.strerror}[/dim]")
                return False, f"Port unavailable ({e.errno}: {e.strerror})"
            except Exception as e:
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} Exception: {str(e)}[/dim]")
                return False, f"Port test failed: {str(e)}"

        # Use a threading approach with timeout to prevent hangs
        result_container = {'success': False, 'error': 'Timeout'}

        def test_thread():
            try:
                timeout_val = 0.5 if quick_test else 2
                test_modem = ModemConnection(port=port, baudrate=baudrate, timeout=timeout_val)

                # Pass quick_test flag to connect method
                if test_modem.connect(quick_test=quick_test):
                    # Try AT command
                    result = test_modem.send_at_command("AT", wait_time=0.3 if quick_test else 1.0)
                    test_modem.disconnect()

                    if result.success:
                        result_container['success'] = True
                        result_container['error'] = None
                    else:
                        result_container['success'] = False
                        result_container['error'] = "No AT response"
                else:
                    result_container['success'] = False
                    result_container['error'] = "Cannot open port"
            except Exception as e:
                result_container['success'] = False
                result_container['error'] = str(e)

        # Create and start thread
        if DEBUG_MODE:
            console.print(f"[dim]DEBUG: Starting thread for {port}[/dim]")
        thread = threading.Thread(target=test_thread, daemon=True)
        thread.start()

        # Wait for thread with timeout - VERY aggressive for quick test
        # If a port doesn't respond in 1 second, it's likely not an AT port
        thread_timeout = 1.0 if quick_test else 5.0
        if DEBUG_MODE:
            console.print(f"[dim]DEBUG: Waiting {thread_timeout}s for thread to complete...[/dim]")

        start_time = time.time()
        thread.join(timeout=thread_timeout)
        elapsed = time.time() - start_time

        if DEBUG_MODE:
            console.print(f"[dim]DEBUG: Thread join returned after {elapsed:.2f}s[/dim]")

        # If thread is still alive, it timed out
        if thread.is_alive():
            if DEBUG_MODE:
                console.print(f"[dim]DEBUG: Thread TIMEOUT after {thread_timeout}s[/dim]")
            return False, f"Timeout ({thread_timeout}s) - port may be unresponsive"

        if DEBUG_MODE:
            console.print(f"[dim]DEBUG: Thread completed, success={result_container['success']}[/dim]")
        return result_container['success'], result_container['error']

    def auto_detect_modem(self) -> Optional[Tuple[str, int]]:
        """Automatically detect cellular modem port with optimized two-phase testing"""
        console.print("\n[bold cyan]🔍 Auto-detecting cellular modem...[/bold cyan]\n")

        # Check for ModemManager interference on Linux
        modemmanager_was_stopped = False
        if IS_LINUX and ModemManagerHelper.is_running():
            console.print("[yellow]⚠ ModemManager is running and may interfere with port detection[/yellow]")

            managed_ports = ModemManagerHelper.get_managed_ports()
            if managed_ports:
                console.print(f"[yellow]  ModemManager is managing: {', '.join(managed_ports)}[/yellow]\n")

            console.print("[dim]ModemManager can block access to modem ports and cause detection to hang.[/dim]")
            console.print("[dim]Options:[/dim]")
            console.print("[dim]  1. Temporarily stop it (will auto-restart when done)[/dim]")
            console.print("[dim]  2. Continue anyway (may be slower or hang on some ports)[/dim]")
            console.print()

            if Confirm.ask("Temporarily stop ModemManager for detection?", default=True):
                console.print("[cyan]Stopping ModemManager...[/cyan]")
                if ModemManagerHelper.stop_temporarily():
                    console.print("[green]✓ ModemManager stopped temporarily[/green]")
                    console.print("[dim]  (Will auto-restart when you exit this program)[/dim]\n")
                    modemmanager_was_stopped = True
                    time.sleep(1)  # Give ports time to release
                else:
                    console.print("[yellow]⚠ Could not stop ModemManager (may need sudo)[/yellow]")
                    console.print("[dim]  Try running: sudo python3 modemo.py[/dim]\n")

        ports = self.detect_serial_ports()

        if not ports:
            console.print("[red]✗ No serial ports found on this system[/red]")
            if modemmanager_was_stopped:
                self.modemmanager_was_stopped = modemmanager_was_stopped
                self._restart_modemmanager_if_needed()
            return None

        # Display found ports
        console.print(f"[cyan]Found {len(ports)} serial port(s):[/cyan]\n")

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("#", style="cyan", width=3)
        table.add_column("Port", style="white", width=15)
        table.add_column("Type", style="white", width=20)
        table.add_column("Description", style="white")

        for idx, port in enumerate(ports, 1):
            desc = port.get('description', '')
            if port.get('vendor'):
                desc = f"{port.get('vendor', '')} {desc}".strip()
            if not desc:
                desc = "No description available"

            table.add_row(
                str(idx),
                port['path'],
                port['type'],
                desc
            )

        console.print(table)
        console.print()

        # Two-phase baud rate testing
        # Phase 1: Try most common baud rate (115200) on all ports first
        # Phase 2: Only try other baud rates if Phase 1 finds nothing
        primary_baudrate = 115200
        fallback_baudrates = [9600, 460800, 57600, 19200]

        working_ports = []

        # Phase 1: Quick scan with most common baud rate
        console.print(f"[cyan]Phase 1: Quick scan @ {primary_baudrate} baud...[/cyan]\n")

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Scanning ports...", total=len(ports))

            for idx, port in enumerate(ports):
                port_path = port['path']
                progress.update(task, description=f"[cyan]Testing {port_path}... ({idx+1}/{len(ports)})")

                if DEBUG_MODE:
                    console.print(f"\n[bold cyan]>>> Testing port {idx+1}/{len(ports)}: {port_path}[/bold cyan]")

                is_working, error = self.test_port_for_modem(port_path, primary_baudrate, quick_test=True)

                if is_working:
                    working_ports.append({
                        'port': port_path,
                        'baudrate': primary_baudrate,
                        'info': port
                    })
                    progress.update(task, description=f"[green]✓ {port_path} @ {primary_baudrate} baud - WORKING!")
                    if DEBUG_MODE:
                        console.print(f"[bold green]<<< SUCCESS: {port_path} works![/bold green]\n")
                    time.sleep(0.3)  # Brief pause to show success message

                    # Early exit: If we found a working port, stop testing to avoid hangs on problematic ports
                    if DEBUG_MODE:
                        console.print(f"[bold green]Found working port, stopping scan to avoid testing problematic ports[/bold green]")
                    break  # Exit the loop, we found what we need
                elif error and "Timeout" in error:
                    progress.update(task, description=f"[yellow]⏱ {port_path} - Timeout (skipping)")
                    if DEBUG_MODE:
                        console.print(f"[yellow]<<< TIMEOUT: {port_path} - moving to next port[/yellow]\n")
                    time.sleep(0.2)
                elif error and "Permission" in error:
                    progress.update(task, description=f"[red]🔒 {port_path} - {error}")
                    if DEBUG_MODE:
                        console.print(f"[red]<<< PERMISSION: {port_path} - {error}[/red]\n")
                    time.sleep(0.2)
                else:
                    if DEBUG_MODE:
                        console.print(f"[dim]<<< FAILED: {port_path} - {error}[/dim]\n")

                progress.advance(task)

        console.print()

        # Phase 2: If nothing found, try other baud rates
        if not working_ports:
            console.print("[yellow]⚠ No modems found with standard baud rate[/yellow]")
            console.print(f"[cyan]Phase 2: Testing alternate baud rates...[/cyan]\n")

            with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console
            ) as progress:

                for port in ports:
                    port_path = port['path']
                    task = progress.add_task(f"[cyan]Testing {port_path}...", total=len(fallback_baudrates))

                    for baudrate in fallback_baudrates:
                        progress.update(task, description=f"[cyan]Testing {port_path} @ {baudrate} baud...")

                        is_working, error = self.test_port_for_modem(port_path, baudrate)

                        if is_working:
                            working_ports.append({
                                'port': port_path,
                                'baudrate': baudrate,
                                'info': port
                            })
                            progress.update(task, description=f"[green]✓ {port_path} @ {baudrate} baud - WORKING!")
                            time.sleep(0.3)
                            break

                        progress.advance(task)

                    if not any(p['port'] == port_path for p in working_ports):
                        progress.update(task, description=f"[dim]✗ {port_path} - No response")

            console.print()

        if not working_ports:
            console.print("[yellow]⚠ No working modem ports detected[/yellow]")
            console.print("[dim]This could mean:[/dim]")
            console.print("[dim]  • Modem is not connected or powered[/dim]")
            console.print("[dim]  • Modem uses non-standard baud rate[/dim]")
            console.print("[dim]  • Permission issues (try running with sudo)[/dim]")
            console.print("[dim]  • Modem is in a non-AT command mode[/dim]")
            # Track ModemManager status before returning
            if modemmanager_was_stopped:
                self.modemmanager_was_stopped = True
            return None

        # Display working ports
        console.print(f"[bold green]✓ Found {len(working_ports)} working modem port(s)![/bold green]\n")

        # Track ModemManager status for later cleanup
        if modemmanager_was_stopped:
            self.modemmanager_was_stopped = True

        if len(working_ports) == 1:
            # Only one port works, use it automatically
            selected = working_ports[0]
            console.print(f"[green]Automatically selecting:[/green]")
            console.print(f"  Port: {selected['port']}")
            console.print(f"  Baud Rate: {selected['baudrate']}")
            console.print()
            return (selected['port'], selected['baudrate'])

        # Multiple working ports - let user choose
        table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta", title="Working Modem Ports")
        table.add_column("#", style="cyan", width=3)
        table.add_column("Port", style="white", width=15)
        table.add_column("Baud Rate", style="white", width=12)
        table.add_column("Description", style="white")

        for idx, port_info in enumerate(working_ports, 1):
            desc = port_info['info'].get('description', 'No description')
            if port_info['info'].get('vendor'):
                desc = f"{port_info['info'].get('vendor', '')} {desc}".strip()

            table.add_row(
                str(idx),
                port_info['port'],
                str(port_info['baudrate']),
                desc
            )

        console.print(table)
        console.print()

        # Recommend port based on common patterns
        recommended = None
        for idx, port_info in enumerate(working_ports, 1):
            port_path = port_info['port']
            # USB2 is often the AT command port for multi-port modems
            if 'ttyUSB2' in port_path:
                recommended = idx
                break
            # If no USB2, prefer USB1
            elif 'ttyUSB1' in port_path and recommended is None:
                recommended = idx

        if recommended:
            console.print(f"[yellow]💡 Recommendation: Port #{recommended} (commonly used for AT commands)[/yellow]\n")

        # Let user choose
        choices = [str(i) for i in range(1, len(working_ports) + 1)]
        default_choice = str(recommended) if recommended else "1"

        choice = Prompt.ask(
            "Select port to use",
            choices=choices,
            default=default_choice
        )

        selected = working_ports[int(choice) - 1]
        console.print()
        return (selected['port'], selected['baudrate'])

    def connect_modem(self):
        """Connect to modem with auto-detection or manual configuration"""
        console.print("\n[bold cyan]Modem Connection Setup[/bold cyan]\n")

        # Offer auto-detection
        console.print("Connection options:")
        console.print("  [bold cyan]1[/bold cyan]. Auto-detect modem (recommended)")
        console.print("  [bold cyan]2[/bold cyan]. Manual configuration")
        console.print()

        choice = Prompt.ask("Select option", choices=["1", "2"], default="1")

        if choice == "1":
            # Auto-detection
            result = self.auto_detect_modem()

            if result:
                port, baudrate = result
            else:
                console.print("\n[yellow]Would you like to try manual configuration instead?[/yellow]")
                if Confirm.ask("Configure manually?", default=True):
                    default_port = "COM3" if IS_WINDOWS else "/dev/ttyUSB2"
                    port = Prompt.ask("Enter serial port", default=default_port)
                    baudrate = int(Prompt.ask("Enter baud rate", default="115200"))
                else:
                    return False
        else:
            # Manual configuration
            console.print()

            # Show available ports as reference
            ports = self.detect_serial_ports()
            if ports:
                console.print("[cyan]Available serial ports:[/cyan]")
                for p in ports:
                    console.print(f"  • {p['path']} ({p['type']})")
                console.print()

            # Platform-aware default port
            default_port = "COM3" if IS_WINDOWS else "/dev/ttyUSB2"
            port = Prompt.ask("Enter serial port", default=default_port)
            baudrate = int(Prompt.ask("Enter baud rate", default="115200"))

        # Connect with selected settings
        self.modem = ModemConnection(port=port, baudrate=baudrate)

        console.print(f"\n[cyan]Connecting to {port} at {baudrate} baud...[/cyan]")

        if self.modem.connect():
            # Test connection
            result = self.modem.send_at_command("AT")
            if result.success:
                console.print("[green]✓ Connection established successfully![/green]")

                # Get quick device info
                info = self.modem.send_at_command("ATI")
                if info.success and 'info' in info.parsed_data:
                    console.print(f"[dim]Device: {info.parsed_data['info'].split(chr(10))[0]}[/dim]")

                self.connected = True
                return True
            else:
                console.print("[red]✗ Connection established but modem not responding[/red]")
                self.connected = False
                return False
        else:
            console.print("[red]✗ Failed to establish connection[/red]")
            self.connected = False
            return False

    def main_menu(self):
        """Display and handle main menu"""
        while True:
            console.print("\n")
            console.rule("[bold cyan]Main Menu", style="cyan")
            console.print()

            menu_items = [
                ("1", "Run Full Diagnostic Test", "Complete system diagnostic"),
                ("2", "Quick Status Check", "View current status"),
                ("3", "Network Tools", "Scan, register, troubleshoot network"),
                ("4", "APN & Data Connection", "Configure APN, manage PDP contexts"),
                ("5", "Advanced Tools", "AT commands and vendor features"),
                ("6", "Change Connection/Port", "Reconnect to different port"),
                ("7", "Export Diagnostic Report", "Save results to file"),
                ("0", "Exit", "Quit application"),
            ]

            for num, title, desc in menu_items:
                console.print(f"  [bold cyan]{num}[/bold cyan]. [white]{title}[/white] - [dim]{desc}[/dim]")

            console.print()
            choice = Prompt.ask("Select option", choices=[item[0] for item in menu_items], default="1")

            if choice == "0":
                break
            elif choice == "1":
                self.run_full_diagnostic()
            elif choice == "2":
                self.quick_status()
            elif choice == "3":
                self.network_tools_menu()
            elif choice == "4":
                self.data_tools_menu()
            elif choice == "5":
                self.advanced_tools_menu()
            elif choice == "6":
                if self.modem:
                    self.modem.disconnect()
                self.connect_modem()
            elif choice == "7":
                self.export_report()

    def run_full_diagnostic(self):
        """Run complete diagnostic test suite"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            return

        diag = DiagnosticTests(self.modem)
        diag.run_full_diagnostic()
        diag.display_results()

        Prompt.ask("\nPress Enter to continue")

    def quick_status(self):
        """Show quick status overview"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            return

        console.print("\n")
        console.rule("[bold cyan]Quick Status Check", style="cyan")

        # Signal quality
        csq = self.modem.send_at_command("AT+CSQ")
        if 'signal_quality' in csq.parsed_data:
            quality = csq.parsed_data['signal_quality']
            color = "green" if quality in ['Excellent', 'Good'] else "yellow" if quality == 'Fair' else "red"
            console.print(
                f"\n[bold]Signal Quality:[/bold] [{color}]{quality}[/{color}] ({csq.parsed_data.get('rssi_dbm', 'Unknown')})")

        # Registration
        creg = self.modem.send_at_command("AT+CREG?")
        if 'creg_status_text' in creg.parsed_data:
            status = creg.parsed_data['creg_status']
            color = "green" if status in [1, 5] else "red"
            console.print(f"[bold]Network Status:[/bold] [{color}]{creg.parsed_data['creg_status_text']}[/{color}]")

        # Operator
        cops = self.modem.send_at_command("AT+COPS?")
        if 'operator' in cops.parsed_data:
            console.print(f"[bold]Operator:[/bold] {cops.parsed_data['operator']}")

        # SIM status
        cpin = self.modem.send_at_command("AT+CPIN?")
        if 'sim_status' in cpin.parsed_data:
            color = "green" if cpin.parsed_data.get('sim_ready', False) else "red"
            console.print(f"[bold]SIM Status:[/bold] [{color}]{cpin.parsed_data['sim_status']}[/{color}]")

        Prompt.ask("\nPress Enter to continue")

    def network_tools_menu(self):
        """Network tools submenu"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        tools = NetworkTools(self.modem)

        while True:
            console.print("\n")
            console.rule("[bold cyan]Network Tools", style="cyan")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. Scan Available Networks")
            console.print("  [bold cyan]2[/bold cyan]. Force Network Registration")
            console.print("  [bold cyan]3[/bold cyan]. View Forbidden Network List (FPLMN)")
            console.print("  [bold cyan]4[/bold cyan]. Clear Forbidden Network List (FPLMN)")
            console.print("  [bold cyan]0[/bold cyan]. Back to Main Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4"], default="1")

            if choice == "0":
                break
            elif choice == "1":
                tools.scan_networks()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "2":
                tools.force_network_registration()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "3":
                tools.view_fplmn()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "4":
                tools.clear_fplmn()
                Prompt.ask("\nPress Enter to continue")

    def data_tools_menu(self):
        """APN & Data connection tools submenu"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        tools = DataUsageTools(self.modem)
        network_tools = NetworkTools(self.modem)

        while True:
            console.print("\n")
            console.rule("[bold cyan]APN & Data Connection", style="cyan")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. Configure APN")
            console.print("  [bold cyan]2[/bold cyan]. Check PDP Context Status")
            console.print("  [bold cyan]3[/bold cyan]. Check Data Connection")
            console.print("  [bold cyan]4[/bold cyan]. Activate PDP Context")
            console.print("  [bold cyan]5[/bold cyan]. Deactivate PDP Context")
            console.print("  [bold cyan]6[/bold cyan]. Delete PDP Context")
            console.print("  [bold cyan]7[/bold cyan]. Test Data Transfer")
            console.print("  [bold cyan]0[/bold cyan]. Back to Main Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4", "5", "6", "7"], default="1")

            if choice == "0":
                break
            elif choice == "1":
                network_tools.configure_apn()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "2":
                tools.check_pdp_status()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "3":
                tools.check_data_connection()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "4":
                # Show current PDP contexts and their activation status first
                console.print("\n[bold cyan]📋 Available PDP Contexts:[/bold cyan]\n")

                # Get configured contexts
                context_result = self.modem.send_at_command("AT+CGDCONT?")
                # Get activation status
                act_result = self.modem.send_at_command("AT+CGACT?")

                # Parse activation status
                active_cids = set()
                if act_result.success and act_result.response:
                    for line in act_result.response.split('\n'):
                        if '+CGACT:' in line:
                            parts = line.replace('+CGACT:', '').strip().split(',')
                            if len(parts) >= 2 and parts[1].strip() == '1':
                                active_cids.add(int(parts[0].strip()))

                if 'contexts' in context_result.parsed_data and context_result.parsed_data['contexts']:
                    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
                    table.add_column("CID", style="cyan", width=8)
                    table.add_column("APN", style="white", width=30)
                    table.add_column("Status", style="white", width=15)

                    for ctx in context_result.parsed_data['contexts']:
                        cid = ctx['cid']
                        status = "[green]Active[/green]" if cid in active_cids else "[yellow]Inactive[/yellow]"
                        table.add_row(str(cid), ctx['apn'], status)

                    console.print(table)
                    console.print()

                    # Only show inactive contexts as options
                    inactive_cids = [str(ctx['cid']) for ctx in context_result.parsed_data['contexts'] if ctx['cid'] not in active_cids]

                    if not inactive_cids:
                        console.print("[yellow]All configured PDP contexts are already active![/yellow]")
                        Prompt.ask("\nPress Enter to continue")
                        continue

                    console.print(f"[dim]Available CIDs to activate: {', '.join(inactive_cids)}[/dim]")
                    cid = Prompt.ask("Enter CID to activate", choices=inactive_cids, default=inactive_cids[0] if inactive_cids else "1")
                else:
                    console.print("[yellow]No PDP contexts configured. Use option 1 to configure APN first.[/yellow]")
                    Prompt.ask("\nPress Enter to continue")
                    continue

                result = self.modem.send_at_command(f"AT+CGACT=1,{cid}")
                if result.success:
                    console.print(f"[green]✓ PDP context {cid} activated[/green]")
                    console.print("[dim]Waiting for IP assignment...[/dim]")
                    time.sleep(3)

                    # Check for IP address
                    ip_result = self.modem.send_at_command(f"AT+CGPADDR={cid}")
                    if ip_result.success:
                        console.print(f"[cyan]IP Address result:[/cyan] {ip_result.response}")
                else:
                    console.print(f"[red]✗ Activation failed: {result.error}[/red]")
                Prompt.ask("\nPress Enter to continue")
            elif choice == "5":
                # Show current PDP contexts and their activation status first
                console.print("\n[bold cyan]📋 Active PDP Contexts:[/bold cyan]\n")

                # Get configured contexts
                context_result = self.modem.send_at_command("AT+CGDCONT?")
                # Get activation status
                act_result = self.modem.send_at_command("AT+CGACT?")

                # Parse activation status
                active_cids = set()
                if act_result.success and act_result.response:
                    for line in act_result.response.split('\n'):
                        if '+CGACT:' in line:
                            parts = line.replace('+CGACT:', '').strip().split(',')
                            if len(parts) >= 2 and parts[1].strip() == '1':
                                active_cids.add(int(parts[0].strip()))

                if 'contexts' in context_result.parsed_data and context_result.parsed_data['contexts']:
                    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
                    table.add_column("CID", style="cyan", width=8)
                    table.add_column("APN", style="white", width=30)
                    table.add_column("Status", style="white", width=15)

                    for ctx in context_result.parsed_data['contexts']:
                        cid = ctx['cid']
                        status = "[green]Active[/green]" if cid in active_cids else "[yellow]Inactive[/yellow]"
                        table.add_row(str(cid), ctx['apn'], status)

                    console.print(table)
                    console.print()

                    # Only show active contexts as options
                    active_cid_strs = [str(cid) for cid in active_cids]

                    if not active_cid_strs:
                        console.print("[yellow]No active PDP contexts to deactivate![/yellow]")
                        Prompt.ask("\nPress Enter to continue")
                        continue

                    console.print(f"[dim]Active CIDs: {', '.join(active_cid_strs)}[/dim]")
                    cid = Prompt.ask("Enter CID to deactivate", choices=active_cid_strs, default=active_cid_strs[0] if active_cid_strs else "1")
                else:
                    console.print("[yellow]No PDP contexts configured.[/yellow]")
                    Prompt.ask("\nPress Enter to continue")
                    continue

                result = self.modem.send_at_command(f"AT+CGACT=0,{cid}")
                if result.success:
                    console.print(f"[green]✓ PDP context {cid} deactivated[/green]")
                else:
                    console.print(f"[red]✗ Deactivation failed: {result.error}[/red]")
                Prompt.ask("\nPress Enter to continue")
            elif choice == "6":
                # Show current contexts first
                console.print("\n[bold cyan]Current PDP Contexts:[/bold cyan]\n")
                result = self.modem.send_at_command("AT+CGDCONT?")

                if 'contexts' in result.parsed_data and result.parsed_data['contexts']:
                    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
                    table.add_column("CID", style="cyan", width=8)
                    table.add_column("PDP Type", style="white", width=12)
                    table.add_column("APN", style="white")

                    for ctx in result.parsed_data['contexts']:
                        table.add_row(str(ctx['cid']), ctx['pdp_type'], ctx['apn'])

                    console.print(table)
                    console.print()

                    cid = Prompt.ask("Enter CID to delete (or 'cancel' to abort)")

                    if cid.lower() != 'cancel':
                        # Confirm deletion
                        if Confirm.ask(f"[yellow]⚠ Are you sure you want to delete PDP context {cid}?[/yellow]", default=False):
                            # Delete by setting to empty
                            delete_result = self.modem.send_at_command(f"AT+CGDCONT={cid}")
                            if delete_result.success:
                                console.print(f"[green]✓ PDP context {cid} deleted successfully[/green]")

                                # Verify deletion
                                verify_result = self.modem.send_at_command("AT+CGDCONT?")
                                if 'contexts' in verify_result.parsed_data:
                                    remaining = [ctx for ctx in verify_result.parsed_data['contexts'] if str(ctx['cid']) != cid]
                                    if remaining:
                                        console.print("\n[cyan]Remaining PDP Contexts:[/cyan]")
                                        for ctx in remaining:
                                            console.print(f"  CID {ctx['cid']}: {ctx['pdp_type']}, APN: {ctx['apn']}")
                                    else:
                                        console.print("\n[yellow]No PDP contexts remain[/yellow]")
                            else:
                                console.print(f"[red]✗ Deletion failed: {delete_result.error}[/red]")
                        else:
                            console.print("[yellow]Deletion cancelled[/yellow]")
                else:
                    console.print("[yellow]No PDP contexts found[/yellow]")

                Prompt.ask("\nPress Enter to continue")
            elif choice == "7":
                self.data_transfer_test_menu()

    def data_transfer_test_menu(self):
        """Test cellular data transfer and validate provider billing"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        transfer_test = DataTransferTest(self.modem)

        while True:
            console.print("\n")
            console.rule("[bold cyan]Cellular Data Transfer Test", style="cyan")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. Send 1 KB test data")
            console.print("  [bold cyan]2[/bold cyan]. Send 10 KB test data")
            console.print("  [bold cyan]3[/bold cyan]. Send 100 KB test data")
            console.print("  [bold cyan]4[/bold cyan]. Send 1 MB test data")
            console.print("  [bold cyan]5[/bold cyan]. Send custom size")
            console.print("  [bold cyan]6[/bold cyan]. Detect cellular interfaces")
            console.print("  [bold cyan]0[/bold cyan]. Back to APN & Data Connection Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4", "5", "6"], default="1")

            if choice == "0":
                break
            elif choice == "6":
                # Detect interfaces
                console.print("\n[bold cyan]Detecting Cellular Interfaces...[/bold cyan]\n")
                interfaces = transfer_test.get_cellular_interfaces()

                if interfaces:
                    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
                    table.add_column("Interface", style="cyan", width=15)
                    table.add_column("IP Address", style="white", width=20)
                    table.add_column("Status", style="white", width=10)

                    for iface in interfaces:
                        status_color = "green" if iface['status'] == 'UP' else "red"
                        table.add_row(
                            iface['name'],
                            iface['ip'],
                            f"[{status_color}]{iface['status']}[/{status_color}]"
                        )

                    console.print(table)
                    console.print()
                    console.print("[dim]Note: Data will be sent via system's default route unless you configure routing manually[/dim]")
                else:
                    console.print("[yellow]No cellular interfaces detected[/yellow]")
                    console.print("[dim]Tip: Ensure your cellular modem is connected and has an active PDP context[/dim]")

                Prompt.ask("\nPress Enter to continue")
            else:
                # Determine test size
                size_map = {
                    "1": 1024,           # 1 KB
                    "2": 10240,          # 10 KB
                    "3": 102400,         # 100 KB
                    "4": 1048576,        # 1 MB
                }

                if choice == "5":
                    size_input = Prompt.ask("Enter size in bytes", default="1024")
                    try:
                        test_size = int(size_input)
                        if test_size <= 0 or test_size > 10485760:  # Max 10 MB
                            console.print("[red]Size must be between 1 and 10,485,760 bytes (10 MB)[/red]")
                            Prompt.ask("\nPress Enter to continue")
                            continue
                    except ValueError:
                        console.print("[red]Invalid size. Please enter a number.[/red]")
                        Prompt.ask("\nPress Enter to continue")
                        continue
                else:
                    test_size = size_map[choice]

                # Display instructions
                transfer_test.display_test_instructions(test_size)

                # Confirm before sending
                if not Confirm.ask(f"\n[yellow]⚠️  Send {test_size:,} bytes of test data? (This will use real cellular data)[/yellow]", default=False):
                    console.print("[yellow]Test cancelled[/yellow]")
                    Prompt.ask("\nPress Enter to continue")
                    continue

                # ROUTING VERIFICATION - Critical for cellular data test
                console.print("\n[bold cyan]🔍 Verifying Routing Configuration...[/bold cyan]\n")
                routing = transfer_test.verify_routing()

                # Display routing status
                table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta", title="Routing Status")
                table.add_column("Check", style="cyan", width=30)
                table.add_column("Status", style="white", width=40)

                # Cellular check with diagnostics
                if routing['cellular_available']:
                    table.add_row("Cellular Interface", f"[green]✓ {routing['cellular_interface']} (Ready)[/green]")
                else:
                    # Show diagnostic information
                    if routing['cellular_interfaces_found']:
                        # Show count of found interfaces
                        count = len(routing['cellular_interfaces_found'])
                        table.add_row("Cellular Interfaces Found", f"[yellow]{count} detected but not ready[/yellow]")
                    else:
                        table.add_row("Cellular Interface", "[red]✗ None detected[/red]")

                # WiFi check
                wifi_status = transfer_test.check_wifi_status()
                if wifi_status['wifi_is_default']:
                    table.add_row("WiFi Status", f"[red]✗ {wifi_status['wifi_interface']} (DEFAULT ROUTE!)[/red]")
                elif wifi_status['wifi_is_up']:
                    table.add_row("WiFi Status", f"[yellow]⚠ {wifi_status['wifi_interface']} (Active but not default)[/yellow]")
                else:
                    table.add_row("WiFi Status", "[green]✓ Disabled or down[/green]")

                # Default route
                default_route = routing.get('default_route') or wifi_status['default_route']
                if default_route:
                    route_color = "green" if default_route['type'] == 'Cellular' else "red"
                    table.add_row("Default Route", f"[{route_color}]{default_route['interface']} ({default_route['type']})[/{route_color}]")

                # Overall status
                if routing['routing_ok']:
                    table.add_row("", "")
                    table.add_row("[bold]Overall Status[/bold]", "[bold green]✓ Routing OK for cellular test[/bold green]")
                else:
                    table.add_row("", "")
                    table.add_row("[bold]Overall Status[/bold]", "[bold red]✗ Routing NOT configured for cellular[/bold red]")

                console.print(table)
                console.print()

                # Show detailed cellular interface diagnostics if interfaces were found but not ready
                if routing['cellular_interfaces_found'] and not routing['cellular_available']:
                    console.print("[bold yellow]📋 Cellular Interface Diagnostics:[/bold yellow]\n")

                    diag_table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
                    diag_table.add_column("Interface", style="cyan", width=12)
                    diag_table.add_column("Status", style="white", width=15)
                    diag_table.add_column("IP Address", style="white", width=18)
                    diag_table.add_column("Issues", style="yellow", width=35)

                    for iface in routing['cellular_interfaces_found']:
                        status_color = "green" if iface['status'] == 'UP' else "red"
                        ip_color = "green" if iface['ip'] != 'No IP assigned' else "red"

                        issues_text = ", ".join(iface.get('issues', [])) if iface.get('issues') else "None"
                        if not iface.get('issues'):
                            issues_text = "[green]Ready![/green]"

                        diag_table.add_row(
                            iface['name'],
                            f"[{status_color}]{iface['status']}[/{status_color}]",
                            f"[{ip_color}]{iface['ip']}[/{ip_color}]",
                            issues_text
                        )

                    console.print(diag_table)
                    console.print()

                    # Explain what's needed
                    console.print("[bold cyan]🔧 What's Needed for Data Transfer:[/bold cyan]")
                    console.print("  ✓ Interface must be UP")
                    console.print("  ✓ Interface must have IP address assigned")
                    console.print()

                # Show warnings if any
                if routing['warnings']:
                    console.print("[bold red]⚠️  WARNINGS:[/bold red]")
                    for warning in routing['warnings']:
                        console.print(f"  • {warning}")
                    console.print()

                # Handle routing issues
                if not routing['routing_ok']:
                    if routing['wifi_is_default']:
                        console.print("[bold yellow]🔧 Fix Routing Issue:[/bold yellow]")
                        console.print("  [bold]WiFi is your default route - test data will use WiFi![/bold]")
                        console.print()
                        console.print("  Options:")
                        console.print("    1. [green]Disable WiFi temporarily (recommended)[/green]")

                        # Only show automatic route option if we have a cellular interface
                        if routing['cellular_interface']:
                            console.print("    2. [green]Configure route automatically (keeps WiFi enabled)[/green]")
                            console.print("    3. Show manual routing commands")
                            console.print("    4. Continue anyway (test will use WiFi, NOT cellular)")
                            console.print("    0. Cancel test")
                            console.print()
                            fix_choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4"], default="1")
                        else:
                            console.print("    2. Show manual routing commands")
                            console.print("    3. Continue anyway (test will use WiFi, NOT cellular)")
                            console.print("    0. Cancel test")
                            console.print()
                            fix_choice = Prompt.ask("Select option", choices=["0", "1", "2", "3"], default="1")

                        if fix_choice == "0":
                            console.print("[yellow]Test cancelled[/yellow]")
                            Prompt.ask("\nPress Enter to continue")
                            continue
                        elif fix_choice == "1":
                            # Disable WiFi temporarily
                            console.print("\n[cyan]Disabling WiFi temporarily...[/cyan]")
                            console.print("[dim](WiFi will be re-enabled after test or when you exit)[/dim]\n")
                            if transfer_test.disable_wifi_temporarily():
                                console.print("[green]✓ WiFi disabled successfully[/green]")
                                console.print("[green]✓ Cellular should now be the default route[/green]")
                                time.sleep(2)
                            else:
                                console.print("[red]✗ Failed to disable WiFi[/red]")
                                console.print("[yellow]You may need to run with sudo or disable WiFi manually[/yellow]")
                                if not Confirm.ask("\nContinue with test anyway?", default=False):
                                    console.print("[yellow]Test cancelled[/yellow]")
                                    Prompt.ask("\nPress Enter to continue")
                                    continue
                        elif fix_choice == "2" and routing['cellular_interface']:
                            # Configure route automatically
                            console.print("\n[cyan]Configuring temporary route for httpbin.org...[/cyan]")
                            console.print("[dim](Route will be removed after test or when you exit)[/dim]\n")

                            # Resolve httpbin.org to IP
                            console.print("[cyan]Resolving httpbin.org...[/cyan]")
                            target_ip = transfer_test.resolve_hostname("httpbin.org")
                            if not target_ip:
                                console.print("[red]✗ Failed to resolve httpbin.org[/red]")
                                console.print("[yellow]DNS resolution failed. Try option 1 (Disable WiFi) instead.[/yellow]")
                                Prompt.ask("\nPress Enter to continue")
                                continue

                            console.print(f"[green]✓ Resolved to {target_ip}[/green]")

                            # Add temporary route
                            console.print(f"[cyan]Adding route for {target_ip} via {routing['cellular_interface']}...[/cyan]")
                            if transfer_test.add_temporary_route(target_ip, routing['cellular_interface']):
                                console.print(f"[green]✓ Route added successfully[/green]")
                                console.print(f"[green]✓ Traffic to httpbin.org will now use {routing['cellular_interface']}[/green]")
                                console.print("[dim]WiFi remains enabled for other traffic[/dim]")
                                time.sleep(2)
                            else:
                                console.print("[red]✗ Failed to add route[/red]")
                                console.print("[yellow]You may need to run with sudo[/yellow]")
                                if not Confirm.ask("\nContinue with test anyway?", default=False):
                                    console.print("[yellow]Test cancelled[/yellow]")
                                    Prompt.ask("\nPress Enter to continue")
                                    continue
                        elif fix_choice == "2" and not routing['cellular_interface']:
                            # Show manual commands (when no cellular interface)
                            console.print("\n[bold cyan]Manual Routing Commands:[/bold cyan]\n")
                            if IS_LINUX:
                                console.print("[cyan]Disable WiFi:[/cyan]")
                                console.print(f"  sudo ip link set {wifi_status['wifi_interface']} down")
                                console.print()
                                console.print("[cyan]Re-enable WiFi after test:[/cyan]")
                                console.print(f"  sudo ip link set {wifi_status['wifi_interface']} up")
                            elif IS_WINDOWS:
                                console.print("[cyan]Disable WiFi:[/cyan]")
                                console.print(f"  netsh interface set interface \"{wifi_status['wifi_interface']}\" disabled")
                                console.print()
                                console.print("[cyan]Re-enable WiFi:[/cyan]")
                                console.print(f"  netsh interface set interface \"{wifi_status['wifi_interface']}\" enabled")
                            console.print()
                            Prompt.ask("Press Enter to return to menu")
                            continue
                        elif fix_choice == "3" and routing['cellular_interface']:
                            # Show manual commands (when cellular interface exists)
                            console.print("\n[bold cyan]Manual Routing Commands:[/bold cyan]\n")
                            if IS_LINUX:
                                console.print("[cyan]Disable WiFi:[/cyan]")
                                console.print(f"  sudo ip link set {wifi_status['wifi_interface']} down")
                                console.print()
                                console.print("[cyan]Or configure route for specific destination:[/cyan]")
                                console.print(f"  sudo ip route add 1.1.1.1 dev {routing['cellular_interface']}")
                                console.print()
                                console.print("[cyan]Re-enable WiFi after test:[/cyan]")
                                console.print(f"  sudo ip link set {wifi_status['wifi_interface']} up")
                            elif IS_WINDOWS:
                                console.print("[cyan]Disable WiFi:[/cyan]")
                                console.print(f"  netsh interface set interface \"{wifi_status['wifi_interface']}\" disabled")
                                console.print()
                                console.print("[cyan]Re-enable WiFi:[/cyan]")
                                console.print(f"  netsh interface set interface \"{wifi_status['wifi_interface']}\" enabled")
                            console.print()
                            Prompt.ask("Press Enter to return to menu")
                            continue
                        elif (fix_choice == "3" and not routing['cellular_interface']) or (fix_choice == "4" and routing['cellular_interface']):
                            # Continue anyway
                            console.print("\n[bold red]⚠️  WARNING: Test will use WiFi, NOT cellular![/bold red]")
                            console.print("[red]Hologram dashboard will show ZERO usage increase![/red]")
                            if not Confirm.ask("\nAre you sure you want to continue?", default=False):
                                console.print("[yellow]Test cancelled[/yellow]")
                                Prompt.ask("\nPress Enter to continue")
                                continue
                    elif not routing['cellular_available']:
                        console.print("[bold red]✗ Cannot proceed with test[/bold red]")
                        console.print("[red]Cellular interface is not ready for data transfer[/red]")
                        console.print()

                        if routing['cellular_interfaces_found']:
                            console.print("[bold yellow]📝 Step-by-Step Fix:[/bold yellow]")

                            # Check what specific issues exist
                            has_no_ip = any("No IP address assigned" in str(iface.get('issues', [])) for iface in routing['cellular_interfaces_found'])
                            has_down = any("Interface is DOWN" in str(iface.get('issues', [])) for iface in routing['cellular_interfaces_found'])

                            if has_no_ip:
                                console.print()
                                console.print("  [bold]Issue:[/bold] Interface has no IP address")
                                console.print("  [bold]Likely cause:[/bold] PDP context not activated")
                                console.print()
                                console.print("  [bold cyan]Fix:[/bold cyan]")
                                console.print("    1. Go back to APN & Data Connection menu")
                                console.print("    2. Select 'Check PDP Context Status' (option 2)")
                                console.print("    3. Verify APN is configured")
                                console.print("    4. Select 'Activate PDP Context' (option 4)")
                                console.print("    5. Enter CID (usually 1)")
                                console.print("    6. Wait a few seconds for IP assignment")
                                console.print("    7. Try this test again")

                            if has_down and not has_no_ip:
                                console.print()
                                console.print("  [bold]Issue:[/bold] Interface is DOWN")
                                console.print()
                                console.print("  [bold cyan]Fix:[/bold cyan]")
                                for iface in routing['cellular_interfaces_found']:
                                    if iface['status'] == 'DOWN':
                                        console.print(f"    sudo ip link set {iface['name']} up")

                        else:
                            console.print("[yellow]No cellular interfaces found at all[/yellow]")
                            console.print()
                            console.print("  [bold cyan]Troubleshooting:[/bold cyan]")
                            console.print("    • Check modem is connected via USB")
                            console.print("    • Run: ip link show")
                            console.print("    • Look for wwan*, ppp*, or usb* interfaces")
                            console.print("    • Modem may need to be configured first")

                        console.print()
                        Prompt.ask("Press Enter to return to menu")
                        continue

                # Detect interface (optional)
                interfaces = transfer_test.get_cellular_interfaces()
                interface_name = None
                if interfaces and IS_LINUX:
                    # Use first UP interface if available
                    for iface in interfaces:
                        if iface['status'] == 'UP' and iface['ip'] != 'No IP assigned':
                            interface_name = iface['name']
                            break

                # Send test data
                console.print("\n[cyan]Sending test data...[/cyan]")
                with console.status("[bold cyan]Transferring data via cellular..."):
                    result = transfer_test.send_test_data(test_size, interface_name)

                # Display results
                console.print("\n")
                if result['success']:
                    console.print("[bold green]✓ Test completed successfully![/bold green]\n")

                    overhead = transfer_test.calculate_overhead_estimate(test_size, use_https=True)

                    # Results table
                    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta", title="Transfer Results")
                    table.add_column("Metric", style="cyan", width=30)
                    table.add_column("Value", style="white", width=20)

                    table.add_row("Payload Sent", f"{result['payload_size']:,} bytes")
                    if 'bytes_uploaded' in result:
                        table.add_row("Bytes Uploaded", f"{result.get('bytes_uploaded', 0):,} bytes")
                    if 'bytes_downloaded' in result:
                        table.add_row("Response Received", f"{result.get('bytes_downloaded', 0):,} bytes")
                    table.add_row("Interface Used", result['interface_used'])
                    table.add_row("", "")
                    table.add_row("[bold]Expected on Dashboard[/bold]", f"[bold green]~{overhead['total_estimated']:,} bytes[/bold green]")
                    table.add_row("[bold]Wait Time[/bold]", "[bold yellow]1-2 minutes[/bold yellow]")

                    console.print(table)
                    console.print()

                    console.print("[bold yellow]📱 Next Steps:[/bold yellow]")
                    console.print("  1. Wait [yellow]1-2 minutes[/yellow] for Hologram dashboard to update")
                    console.print("  2. Login: [cyan]https://dashboard.hologram.io[/cyan]")
                    console.print("  3. Check your device's total data usage")
                    console.print(f"  4. Usage should increase by ~[bold green]{overhead['total_estimated']:,} bytes[/bold green]")
                    console.print()
                else:
                    console.print(f"[bold red]✗ Test failed[/bold red]")
                    console.print(f"[red]Error: {result.get('error', 'Unknown error')}[/red]")
                    console.print()
                    console.print("[yellow]Troubleshooting:[/yellow]")
                    console.print("  • Check that PDP context is active (option 3)")
                    console.print("  • Verify cellular interface has IP address (option 6)")
                    console.print("  • Ensure routing is configured to use cellular")
                    console.print("  • Try disabling WiFi temporarily")

                # Cleanup after test
                cleanup_needed = transfer_test.wifi_was_disabled or len(transfer_test.routes_added) > 0

                if cleanup_needed:
                    console.print()
                    console.print("[bold cyan]🧹 Cleanup:[/bold cyan]")

                    # Remove temporary routes
                    if len(transfer_test.routes_added) > 0:
                        console.print("[cyan]Removing temporary routes...[/cyan]")
                        if transfer_test.remove_temporary_routes():
                            console.print("[green]✓ Routes removed successfully[/green]")
                        else:
                            console.print("[yellow]⚠ Some routes may not have been removed[/yellow]")

                    # Re-enable WiFi if it was disabled
                    if transfer_test.wifi_was_disabled:
                        if Confirm.ask("[yellow]Re-enable WiFi now?[/yellow]", default=True):
                            transfer_test.enable_wifi()

                Prompt.ask("\nPress Enter to continue")

        # Cleanup: Remove routes and re-enable WiFi when exiting menu
        cleanup_needed = transfer_test.wifi_was_disabled or len(transfer_test.routes_added) > 0

        if cleanup_needed:
            console.print("\n[bold cyan]🧹 Cleanup needed before exiting:[/bold cyan]")

            # Remove temporary routes
            if len(transfer_test.routes_added) > 0:
                console.print(f"\n[yellow]⚠️  {len(transfer_test.routes_added)} temporary route(s) still active[/yellow]")
                if Confirm.ask("Remove temporary routes before exiting?", default=True):
                    transfer_test.remove_temporary_routes()
                else:
                    console.print("[dim]Routes will persist until system reboot or manual removal[/dim]")

            # Re-enable WiFi
            if transfer_test.wifi_was_disabled:
                console.print("\n[yellow]⚠️  WiFi is still disabled from testing[/yellow]")
                if Confirm.ask("Re-enable WiFi before exiting?", default=True):
                    transfer_test.enable_wifi()
                else:
                    console.print("[dim]Remember to re-enable WiFi manually later![/dim]")

    def common_at_commands_menu(self):
        """Menu of common AT commands with descriptions"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        while True:
            console.print("\n")
            console.rule("[bold cyan]Common AT Commands", style="cyan")
            console.print()

            commands = [
                ("1", "AT+CSQ", "Check signal quality (RSSI and BER)"),
                ("2", "AT+COPS?", "Check current network operator"),
                ("3", "AT+CREG?", "Check network registration status (CS domain)"),
                ("4", "AT+CGREG?", "Check GPRS registration status (PS domain)"),
                ("5", "AT+CEREG?", "Check EPS/LTE registration status"),
                ("6", "AT+CGDCONT?", "View PDP context configuration (APN settings)"),
                ("7", "AT+CGACT?", "Check PDP context activation status"),
                ("8", "AT+CGPADDR", "Get IP address assignment"),
                ("9", "AT+CPIN?", "Check SIM card status"),
                ("10", "AT+CIMI", "Get IMSI (subscriber identity)"),
                ("11", "AT+CCID", "Get ICCID (SIM card serial number)"),
                ("12", "AT+CGSN", "Get IMEI (device identity)"),
                ("13", "AT+CGMI", "Get modem manufacturer"),
                ("14", "AT+CGMM", "Get modem model"),
                ("15", "AT+CGMR", "Get firmware version"),
                ("16", "AT+CGATT?", "Check GPRS attach status"),
                ("17", "AT+COPS=?", "Scan available networks (slow, 30-60s)"),
                ("18", "ATI", "Get detailed modem information"),
                ("0", "Back", "Return to main menu"),
            ]

            for num, cmd, desc in commands:
                if num == "0":
                    console.print(f"  [bold cyan]{num}[/bold cyan]. [white]{desc}[/white]")
                else:
                    console.print(f"  [bold cyan]{num:2s}[/bold cyan]. [yellow]{cmd:20s}[/yellow] - [dim]{desc}[/dim]")

            console.print()
            choice = Prompt.ask("Select command", choices=[item[0] for item in commands], default="0")

            if choice == "0":
                break

            # Find the selected command
            selected = next((item for item in commands if item[0] == choice), None)
            if selected:
                cmd = selected[1]
                desc = selected[2]

                console.print(f"\n[bold cyan]Executing:[/bold cyan] [yellow]{cmd}[/yellow]")
                console.print(f"[dim]{desc}[/dim]\n")

                if "Scan" in desc:
                    console.print("[yellow]This may take 30-60 seconds...[/yellow]\n")
                    result = self.modem.send_at_command(cmd, wait_time=60)
                else:
                    result = self.modem.send_at_command(cmd)

                console.print(f"[cyan]Raw Response:[/cyan]")
                console.print(Panel(result.raw_response, box=box.ROUNDED))

                if result.parsed_data and len(result.parsed_data) > 1:
                    console.print(f"\n[cyan]Parsed Data:[/cyan]")
                    console.print(json.dumps(result.parsed_data, indent=2))

                Prompt.ask("\nPress Enter to continue")

    def manual_at_command(self):
        """Send manual AT commands"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        console.print("\n[bold cyan]Manual AT Command Interface[/bold cyan]")
        console.print("[dim]Enter 'exit' to return to main menu[/dim]\n")

        while True:
            cmd = Prompt.ask("AT Command")

            if cmd.lower() == 'exit':
                break

            if not cmd.upper().startswith('AT'):
                cmd = 'AT' + cmd

            result = self.modem.send_at_command(cmd)

            console.print(f"\n[cyan]Raw Response:[/cyan]")
            console.print(Panel(result.raw_response, box=box.ROUNDED))

            if result.parsed_data and len(result.parsed_data) > 1:
                console.print(f"\n[cyan]Parsed Data:[/cyan]")
                console.print(json.dumps(result.parsed_data, indent=2))

            console.print()

    def advanced_tools_menu(self):
        """Advanced tools submenu - AT commands and vendor features"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        while True:
            console.print("\n")
            console.rule("[bold cyan]Advanced Tools", style="cyan")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. Common AT Commands - Quick access to 18 useful commands")
            console.print("  [bold cyan]2[/bold cyan]. Manual AT Command - Send custom AT commands")
            console.print("  [bold cyan]3[/bold cyan]. Vendor-Specific Tools - Quectel, Sierra, u-blox features")
            console.print("  [bold cyan]0[/bold cyan]. Back to Main Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3"], default="1")

            if choice == "0":
                break
            elif choice == "1":
                self.common_at_commands_menu()
            elif choice == "2":
                self.manual_at_command()
            elif choice == "3":
                self.vendor_tools_menu()

    def vendor_tools_menu(self):
        """Vendor-specific advanced tools"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        # Detect vendor
        diag = DiagnosticTests(self.modem)
        diag.detect_modem_vendor()

        if not diag.modem_vendor:
            console.print("[yellow]Could not detect modem vendor. Vendor-specific features unavailable.[/yellow]")
            Prompt.ask("\nPress Enter to continue")
            return

        if diag.modem_vendor == 'Quectel':
            self.quectel_tools_menu(diag.modem_model)
        elif diag.modem_vendor == 'Sierra Wireless':
            self.sierra_tools_menu()
        elif diag.modem_vendor == 'u-blox':
            self.ublox_tools_menu()
        else:
            console.print(f"[yellow]No specialized tools available for {diag.modem_vendor}[/yellow]")
            console.print("[dim]Using generic AT commands via Manual AT Command option[/dim]")
            Prompt.ask("\nPress Enter to continue")

    def quectel_tools_menu(self, model: str = None):
        """Quectel-specific tools"""
        while True:
            console.print("\n")
            console.rule("[bold cyan]Quectel Advanced Tools", style="cyan")
            if model:
                console.print(f"[dim]Model: {model}[/dim]")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. View Advanced Cell Information (AT+QENG)")
            console.print("  [bold cyan]2[/bold cyan]. View Network Info (AT+QNWINFO)")
            console.print("  [bold cyan]3[/bold cyan]. Check Temperature (AT+QTEMP)")
            console.print("  [bold cyan]4[/bold cyan]. View Neighboring Cells (AT+QENG=\"neighbourcell\")")
            console.print("  [bold cyan]5[/bold cyan]. Query SIM Slot (AT+QUIMSLOT?)")
            console.print("  [bold cyan]6[/bold cyan]. GPS Status (AT+QGPS?)")
            console.print("  [bold cyan]7[/bold cyan]. Check eSIM Support (AT+QESIM)")
            console.print("  [bold cyan]0[/bold cyan]. Back to Main Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4", "5", "6", "7"], default="1")

            if choice == "0":
                break
            elif choice == "1":
                result = self.modem.send_at_command("AT+QENG=\"servingcell\"")
                self._display_at_result("Advanced Cell Information", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "2":
                result = self.modem.send_at_command("AT+QNWINFO")
                self._display_at_result("Network Information", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "3":
                result = self.modem.send_at_command("AT+QTEMP")
                self._display_at_result("Temperature Reading", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "4":
                console.print("\n[cyan]Scanning neighbor cells (may take 5-10 seconds)...[/cyan]")
                result = self.modem.send_at_command("AT+QENG=\"neighbourcell\"", wait_time=10)
                self._display_at_result("Neighboring Cells", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "5":
                result = self.modem.send_at_command("AT+QUIMSLOT?")
                self._display_at_result("SIM Slot Configuration", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "6":
                result = self.modem.send_at_command("AT+QGPS?")
                self._display_at_result("GPS Status", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "7":
                result = self.modem.send_at_command("AT+QESIM=\"eid\"")
                self._display_at_result("eSIM Support (EID)", result)
                Prompt.ask("\nPress Enter to continue")

    def sierra_tools_menu(self):
        """Sierra Wireless-specific tools"""
        console.print("\n[yellow]Sierra Wireless tools - Basic implementation[/yellow]")
        result = self.modem.send_at_command("AT!GSTATUS?")
        self._display_at_result("Sierra Status", result)
        Prompt.ask("\nPress Enter to continue")

    def ublox_tools_menu(self):
        """u-blox-specific tools"""
        console.print("\n[yellow]u-blox tools - Basic implementation[/yellow]")
        result = self.modem.send_at_command("AT+UCGED?")
        self._display_at_result("u-blox Cell Info", result)
        Prompt.ask("\nPress Enter to continue")

    def _display_at_result(self, title: str, result: ATResponse):
        """Display AT command result in formatted panel"""
        console.print(f"\n[bold cyan]{title}[/bold cyan]")

        if not result.success:
            console.print(f"[red]Command failed: {result.error}[/red]")
            return

        # Show parsed data if available
        if result.parsed_data and len(result.parsed_data) > 1:
            table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
            table.add_column("Parameter", style="cyan")
            table.add_column("Value", style="white")

            for key, value in result.parsed_data.items():
                if key != 'raw' and value:
                    # Format key nicely
                    formatted_key = key.replace('_', ' ').title()
                    table.add_row(formatted_key, str(value))

            console.print(table)

        # Always show raw response
        console.print(f"\n[cyan]Raw Response:[/cyan]")
        console.print(Panel(result.raw_response, box=box.ROUNDED))

    def export_report(self):
        """Export diagnostic report to file"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            return

        console.print("\n[cyan]Generating diagnostic report...[/cyan]")

        diag = DiagnosticTests(self.modem)
        results = diag.run_full_diagnostic()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Cross-platform path handling
        if IS_WINDOWS:
            # Use current directory or Documents folder on Windows
            output_dir = os.path.join(os.path.expanduser("~"), "Documents", "modemo_reports")
        else:
            # Try to use /mnt/user-data/outputs on Linux, fallback to home directory
            output_dir = "/mnt/user-data/outputs" if os.path.exists("/mnt/user-data/outputs") else os.path.join(
                os.path.expanduser("~"), "modemo_reports")

        # Create directory if it doesn't exist
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            console.print(f"[yellow]⚠ Could not create output directory: {e}[/yellow]")
            output_dir = os.getcwd()  # Fallback to current directory

        filename = os.path.join(output_dir, f"modem_diagnostic_{timestamp}.txt")

        try:
            with open(filename, 'w') as f:
                f.write("=" * 70 + "\n")
                f.write("CELLULAR MODEM DIAGNOSTIC REPORT\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("Generated by: Modem Diagnostic Tool (modemo)\n")
                f.write("=" * 70 + "\n\n")

                for result in results:
                    f.write(f"\nCommand: {result.command}\n")
                    f.write(f"Timestamp: {result.timestamp}\n")
                    f.write(f"Success: {result.success}\n")
                    if result.error:
                        f.write(f"Error: {result.error}\n")
                    f.write(f"\nRaw Response:\n{result.raw_response}\n")
                    f.write(f"\nParsed Data:\n{json.dumps(result.parsed_data, indent=2)}\n")
                    f.write("-" * 70 + "\n")

                f.write("\n" + "=" * 70 + "\n")
                f.write("Find this tool helpful?\n")
                f.write("Support development: https://buymeacoffee.com/mike.brandon\n")
                f.write("=" * 70 + "\n")

            console.print(f"[green]✓ Report saved to: {filename}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Failed to save report: {e}[/red]")

        Prompt.ask("\nPress Enter to continue")

    def run(self):
        """Main application entry point"""
        self.show_banner()

        if not self.connect_modem():
            console.print(
                "\n[yellow]Unable to establish connection. Please check your settings and try again.[/yellow]")
            if not Confirm.ask("\nRetry connection?"):
                return
            if not self.connect_modem():
                return

        try:
            self.main_menu()
        finally:
            if self.modem:
                self.modem.disconnect()
            # Restart ModemManager if we stopped it
            self._restart_modemmanager_if_needed()
            console.print("\n[cyan]Thank you for using Modem Diagnostic Tool![/cyan]")
            console.print("[dim]Found this helpful? ☕ https://buymeacoffee.com/mike.brandon[/dim]\n")


if __name__ == "__main__":
    app = ModemDiagnosticTool()
    app.run()