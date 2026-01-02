# Cellular Modem Diagnostic & Configuration Tool

A comprehensive cross-platform terminal application for configuring, diagnosing, and troubleshooting cellular modems. Built specifically for working with the AT command ecosystem while providing human-readable translations of technical data.

## Platform Support

- **Windows**: Full support for COM ports with automatic detection
- **Linux/Raspberry Pi**: Support for USB, ACM, AMA, and UART serial ports
- **Cross-platform**: Intelligent defaults and path handling for all supported platforms

## Features

### 🔍 Diagnostic Capabilities
- **Full System Diagnostic**: Comprehensive health check of modem, SIM, and network
- **Quick Status Check**: Fast overview of current modem state
- **Signal Quality Analysis**: RSSI and BER with human-readable quality assessments
- **Network Registration Status**: CS, PS, and EPS registration with detailed explanations
- **Device Information**: Manufacturer, model, firmware, IMEI
- **SIM Card Analysis**: Status, ICCID, IMSI verification

### 🌐 Network Tools
- **Network Scanner**: Discover all available cellular networks in range
- **FPLMN Management**: View and clear forbidden network list to resolve registration issues
- **Force Registration**: Manual network selection and registration

### 📊 APN & Data Connection
- **APN Configuration**: Easy setup with carrier presets (Hologram, T-Mobile, AT&T, Verizon)
- **PDP Context Management**: View, create, activate, deactivate, and delete data contexts
- **Connection Verification**: Comprehensive data connection health checks
- **IP Address Assignment**: Monitor IP address allocation
- **Data Transfer Testing**: Send test data and validate against provider dashboard billing
  - Accurate overhead calculation (TCP/IP headers, TLS handshake, DNS, HTTP headers)
  - Clear expectations for Hologram dashboard validation
  - Multiple test sizes (1KB, 10KB, 100KB, 1MB, custom)
  - Cellular interface detection
- **Troubleshooting Guides**: Built-in tips for common issues

### 🔧 Advanced Tools
- **Common AT Commands**: Quick access to 18 pre-configured useful commands with descriptions
- **Manual AT Command Interface**: Send custom AT commands with parsed responses
- **Vendor-Specific Tools**: Specialized features for Quectel, Sierra Wireless, and u-blox modems

### 🛠️ Advanced Features
- **Optimized Auto-detection**: Two-phase port scanning for faster modem discovery
  - Phase 1: Quick scan with standard baud rate (115200)
  - Phase 2: Fallback to alternate baud rates only if needed
- **Smart Port Prioritization**: Tests likely modem ports first (USB2, USB1, USB0)
- **Platform-Aware Defaults**: Intelligent COM/serial port suggestions based on OS
- **Vendor-Specific Tools**: Advanced features for Quectel, Sierra Wireless, u-blox modems
- **Manual AT Commands**: Send any AT command with parsed responses
- **Export Reports**: Generate detailed diagnostic reports with cross-platform paths
- **Human-Readable Output**: Technical AT responses translated to plain language
- **Color-Coded Status**: Visual indicators for quick problem identification

## Installation

### Prerequisites
- **Operating System**: Windows 10/11 or Linux (including Raspberry Pi)
- **Cellular Modem**: Connected via USB or UART (COM port on Windows)
- **Python**: Version 3.7 or higher
- **Permissions**:
  - Windows: Administrator may be required for some COM ports
  - Linux: Root/sudo access or user added to `dialout` group

### Setup Steps

1. **Clone or download the application files**
```bash
cd ~
# If you have the files, navigate to their location
```

2. **Install Python dependencies**
```bash
pip3 install -r requirements.txt
```

Or install manually:
```bash
pip3 install rich pyserial requests
```

3. **Make the script executable (Linux/Mac only)**
```bash
chmod +x modemo.py
```

4. **Identify your modem's serial port**

**On Linux:**
```bash
ls /dev/tty*
```

Common modem ports:
- `/dev/ttyUSB0`, `/dev/ttyUSB1`, `/dev/ttyUSB2` (USB modems)
- `/dev/ttyAMA0`, `/dev/ttyS0` (UART modems)
- `/dev/ttyACM0` (some USB modems)

**On Windows:**
Check Device Manager → Ports (COM & LPT) or use the auto-detection feature.

Common modem ports:
- `COM3`, `COM4`, `COM5` (USB modems typically)

5. **Add user to dialout group (Linux only, if needed)**
```bash
sudo usermod -a -G dialout $USER
```
Then log out and back in for changes to take effect.

## Usage

### Starting the Application

**On Windows:**
```bash
python modemo.py
```

Or with Administrator privileges if needed:
```bash
# Run PowerShell or Command Prompt as Administrator, then:
python modemo.py
```

**On Linux/Raspberry Pi:**
```bash
python3 modemo.py
```

Or with sudo if serial port access requires it:
```bash
sudo python3 modemo.py
```

### Initial Connection

When the application starts, you'll see two connection options:

**Option 1: Auto-detect modem (recommended)**
- Intelligently scans all serial/COM ports with optimized two-phase testing
- Phase 1: Quick scan with standard baud rate (115200) - fastest detection
- Phase 2: Only tests alternate baud rates if Phase 1 finds nothing
- Prioritizes likely modem ports (USB2, USB1, USB0 on Linux; lower COM numbers on Windows)
- Shows device information for each port
- Recommends the best port based on common patterns
- Auto-selects if only one working port found
- Lets you choose if multiple working ports found

**Option 2: Manual configuration**
- Shows list of available serial/COM ports for reference
- You manually enter port path (e.g., `/dev/ttyUSB2` on Linux, `COM3` on Windows)
- You manually enter baud rate (e.g., `115200`)

The optimized auto-detection process:
1. **Port Discovery:**
   - Linux: Scans `/dev/ttyUSB*`, `/dev/ttyACM*`, `/dev/ttyAMA*`, `/dev/ttyS*`
   - Windows: Uses serial port enumeration to find all COM ports
   - Displays table of found ports with type and description
   - Prioritizes ports by likelihood (USB2 > USB1 > USB0 > ACM > others)

2. **Phase 1: Quick Scan (⚡ Fast)**
   - Tests all ports at 115200 baud (most common for cellular modems)
   - Uses reduced timeout (1 second) for faster screening
   - Identifies working modems in seconds, not minutes

3. **Phase 2: Fallback Scan (only if needed)**
   - Only runs if Phase 1 finds nothing
   - Tests alternate baud rates: 9600, 460800, 57600, 19200
   - Uses standard timeout for thorough testing

4. **Smart Selection:**
   - Recommends best port based on common patterns
   - Connects automatically if only one working port found
   - Presents choice if multiple working ports found

**Example auto-detection output:**
```
🔍 Auto-detecting cellular modem...

Found 3 serial port(s):

┌───┬─────────────────┬──────────────────────┬────────────────────────┐
│ # │ Port            │ Type                 │ Description            │
├───┼─────────────────┼──────────────────────┼────────────────────────┤
│ 1 │ /dev/ttyUSB0    │ USB Serial           │ Quectel EG25           │
│ 2 │ /dev/ttyUSB1    │ USB Serial           │ Quectel EG25           │
│ 3 │ /dev/ttyUSB2    │ USB Serial           │ Quectel EG25           │
└───┴─────────────────┴──────────────────────┴────────────────────────┘

Testing ports for AT command response...

✓ /dev/ttyUSB2 @ 115200 baud - WORKING!

✓ Found 1 working modem port(s)!

Automatically selecting:
  Port: /dev/ttyUSB2
  Baud Rate: 115200

✓ Connection established successfully!
```

### Main Menu Options

```
1. Run Full Diagnostic Test
   - Complete system diagnostic with all tests
   - Device info, SIM status, network registration, signal quality
   - Results displayed in formatted tables

2. Quick Status Check
   - Fast overview of current status
   - Signal quality, network status, operator, SIM state

3. Network Tools
   - Scan available networks
   - Force network registration
   - View FPLMN (forbidden networks list)
   - Clear FPLMN (forbidden networks list)

4. APN & Data Connection
   - Configure APN with carrier presets (Hologram, T-Mobile, AT&T, Verizon)
   - Check PDP context status
   - Check data connection
   - Activate PDP context
   - Deactivate PDP context
   - Delete PDP context
   - Test Data Transfer (NEW!)
     • Send controlled test data (1KB, 10KB, 100KB, 1MB, custom)
     • Calculate overhead (headers, TLS, DNS)
     • Validate against Hologram dashboard
     • Detect cellular interfaces

5. Advanced Tools
   Submenu with:
   - Common AT Commands: 18 pre-configured commands with descriptions
   - Manual AT Command: Send custom AT commands with parsed responses
   - Vendor-Specific Tools: Quectel, Sierra Wireless, u-blox features
     • Quectel: Advanced cell info, temperature, neighbor cells, GPS, eSIM
     • Sierra Wireless: Status information
     • u-blox: Cell information

6. Change Connection/Port
   - Reconnect to modem
   - Switch to different serial port
   - Change baud rate

7. Export Diagnostic Report
   - Generate detailed report file
   - Save all diagnostic results
   - Cross-platform save locations

0. Exit
```

## Common Use Cases

### Troubleshooting Network Registration Issues

1. Run **Full Diagnostic Test** (Option 1) to see overall status
2. Check signal quality - should be "Fair" or better
3. Look at network registration status codes:
   - `1` = Registered (home) ✓
   - `5` = Registered (roaming) ✓
   - `2` = Searching - wait or try force registration
   - `3` = Denied - clear FPLMN or check SIM
4. If registration denied:
   - Go to **Network Tools** → **Clear FPLMN**
   - Then **Force Network Registration**

### Configuring APN for Data Connection

1. Go to **APN & Data Connection** (Option 4)
2. Select **Configure APN** (Option 1)
3. Choose from carrier presets or enter custom APN:
   - Hologram: `hologram`
   - T-Mobile: `fast.t-mobile.com`
   - AT&T: `broadband`
   - Verizon: `vzwinternet`
   - Custom: Enter your own
4. Optionally activate PDP context immediately
5. Verify configuration

### Checking Data Connection

1. Go to **APN & Data Connection** (Option 4)
2. Select **Check Data Connection** (Option 3)
3. Review:
   - GPRS attach status (should be attached)
   - PDP context activation (should be active)
   - IP address assignment (should have valid IP)

### Testing Data Transfer & Validating Provider Billing

**NEW in v1.3**: Validate your cellular data usage against your provider's dashboard!

1. Go to **APN & Data Connection** (Option 4)
2. Select **Test Data Transfer** (Option 7)
3. Choose test size (1KB, 10KB, 100KB, 1MB, or custom)
4. Review the overhead breakdown:
   - Your payload (actual data)
   - TCP/IP headers (~40 bytes per packet)
   - TLS handshake (~3KB for HTTPS)
   - DNS lookup (~80 bytes)
   - HTTP headers (~400 bytes)
5. Note the **total estimated** data usage
6. Confirm to send test data
7. Wait 1-2 minutes for dashboard update
8. Login to your provider dashboard (e.g., https://dashboard.hologram.io)
9. Verify the data usage increase matches the estimate

**What You'll See:**
- Provider dashboards show **total aggregated data**
- NOT broken down by type (headers, payload, etc.)
- For 1KB payload: expect ~4.5KB total (due to overhead)
- For 10KB payload: expect ~14KB total
- For 100KB payload: expect ~105KB total

**Important Notes:**
- Uses real cellular data (costs apply)
- Ensure WiFi is disabled or routing is configured
- Dashboard updates may take 1-2 minutes
- Actual usage may vary ±10% due to network conditions

### Finding Zero-Byte Sessions

If experiencing zero-byte data sessions:

1. Check **PDP Context Status** to verify APN configuration
2. Verify **Data Connection** is fully established
3. Check signal quality - poor signal can cause failed sessions
4. Review network registration - ensure registered on correct technology

## Understanding Output

### Signal Quality Indicators

The application translates RSSI values to quality ratings:

| RSSI | dBm Range | Quality | Color |
|------|-----------|---------|-------|
| 0-1 | ≤ -111 dBm | Very Poor | Red |
| 2-9 | -109 to -95 dBm | Poor | Red |
| 10-14 | -93 to -85 dBm | Fair | Yellow |
| 15-19 | -83 to -75 dBm | Good | Green |
| 20-31 | -73 to -51 dBm | Excellent | Green |

### Network Registration Status

| Status | Meaning | Color |
|--------|---------|-------|
| 0 | Not registered, not searching | Red |
| 1 | Registered, home network | Green |
| 2 | Not registered, searching | Yellow |
| 3 | Registration denied | Red |
| 4 | Unknown | Red |
| 5 | Registered, roaming | Green |

### Access Technologies (AcT)

- **GSM**: 2G network
- **UTRAN**: 3G network
- **E-UTRAN**: 4G LTE network
- **EGPRS**: Enhanced 2G (EDGE)

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to serial port
```
Solution with auto-detection:
1. Run the application: python modemo.py (Windows) or python3 modemo.py (Linux)
2. Select "Auto-detect modem" (option 1)
3. Tool will automatically find working ports in seconds
4. If no ports found, check:
   - Modem is physically connected and powered on
   - Windows: Check Device Manager for COM port presence
   - Linux: Run with sudo or add user to dialout group

Windows manual approach:
1. Check Device Manager → Ports (COM & LPT)
2. Note the COM port number (e.g., COM3, COM4)
3. Run application and select manual configuration
4. Enter COM port when prompted

Linux manual approach:
1. List ports: ls /dev/tty{USB,ACM,AMA}*
2. Try each port manually using option 2
3. Common ports: /dev/ttyUSB2, /dev/ttyUSB1, /dev/ttyUSB0
4. Run with sudo: sudo python3 modemo.py
```

**Problem**: Auto-detection finds no working ports
```
Solution:

Windows:
1. Check Device Manager for modem/COM port presence
2. Verify modem drivers are installed
3. Try running as Administrator
4. Some modems need driver installation (check manufacturer website)
5. If port appears but doesn't respond, try different baud rates manually

Linux:
1. Verify modem is connected: lsusb | grep -i modem
2. Check dmesg for USB errors: dmesg | tail -20
3. Run with sudo: sudo python3 modemo.py
4. Some modems require mode switching first (usb_modeswitch)
5. Try manual configuration with different baud rates

Both platforms:
- Wait 10-15 seconds after connecting modem for initialization
- Try unplugging and replugging the modem
- Check if modem is in correct mode (not mass storage mode)
```

**Problem**: Multiple ports detected, unsure which to use
```
Solution:
The tool automatically recommends the best port!
- For multi-port modems, USB2 is usually AT commands
- Tool tests all ports and shows which ones work
- Green checkmark indicates working port
- Just select the recommended port (highlighted)
```

**Problem**: Modem not responding to AT commands
```
Solution:
1. Verify modem is powered on
2. Check USB cable connection
3. Try different serial port (USB2 vs USB1 vs USB0)
4. Reset modem power
5. Check dmesg for USB enumeration errors
```

### Network Issues

**Problem**: Registration status shows "Searching" (2)
```
Solution:
1. Check signal quality - must be "Fair" or better
2. Wait 30-60 seconds for network scan
3. Try manual network registration
4. Check SIM card is properly inserted
5. Verify SIM is activated and has service
```

**Problem**: Registration denied (3)
```
Solution:
1. Clear FPLMN list (Network Tools → Clear FPLMN)
2. Check if network is supported by carrier
3. Verify SIM provisioning and account status
4. Try different network manually
```

**Problem**: No data connection
```
Solution:
1. Verify APN configuration is correct
2. Check PDP context is activated
3. Ensure network registration on PS domain
4. Verify data plan is active
5. Check signal quality is sufficient
```

### SIM Issues

**Problem**: SIM PIN or SIM PUK status
```
Solution:
1. Use Manual AT Command to unlock:
   AT+CPIN="1234"  (replace with your PIN)
2. Contact carrier if PUK required
3. Verify SIM card is not locked
```

## AT Command Reference

### Essential Commands

| Command | Purpose | Response |
|---------|---------|----------|
| `AT` | Test communication | OK |
| `ATI` | Device information | Model and version info |
| `AT+CPIN?` | Check SIM status | READY or PIN required |
| `AT+CSQ` | Signal quality | RSSI and BER values |
| `AT+CREG?` | Network registration (CS) | Registration status |
| `AT+COPS?` | Current operator | Operator name and mode |
| `AT+CGDCONT?` | PDP contexts | APN configurations |
| `AT+CGACT?` | PDP activation status | Active/inactive state |

### Advanced Commands

| Command | Purpose |
|---------|---------|
| `AT+COPS=?` | Scan available networks (slow) |
| `AT+COPS=0` | Automatic network selection |
| `AT+COPS=1,2,"310260"` | Manual network selection |
| `AT+CGDCONT=1,"IP","hologram"` | Set APN |
| `AT+CGACT=1,1` | Activate PDP context 1 |
| `AT+CGPADDR` | Get IP address |

## Export Reports

Diagnostic reports are automatically saved to platform-appropriate locations:

**Windows:**
```
C:\Users\YourUsername\Documents\modemo_reports\modem_diagnostic_YYYYMMDD_HHMMSS.txt
```

**Linux/Raspberry Pi:**
```
/mnt/user-data/outputs/modem_diagnostic_YYYYMMDD_HHMMSS.txt
```
(Falls back to `~/modemo_reports/` if `/mnt/user-data/outputs` doesn't exist)

Reports include:
- Complete command history
- Raw AT responses
- Parsed data structures
- Timestamp for each test
- Success/failure status
- Error messages if any

## Advanced Configuration

### Environment Variables

**MODEMO_DEBUG** - Enable verbose debug output
```bash
export MODEMO_DEBUG=1
sudo python3 modemo.py
```
Shows detailed information about each port test, timeout events, and thread operations. Useful for troubleshooting detection issues.

**MODEMO_SKIP_PORTS** - Skip specific ports during auto-detection
```bash
export MODEMO_SKIP_PORTS="/dev/ttyUSB1,/dev/ttyUSB0"
sudo python3 modemo.py
```
Useful if certain ports consistently cause hangs or are known to not be modem AT ports (e.g., GPS/NMEA ports).

### Common AT Commands Menu

The "Common AT Commands" menu (Main Menu → Advanced Tools → Option 1) provides quick access to 18 frequently-used commands:

- **Signal & Registration**: Check signal quality, network status, operator info
- **SIM Information**: View IMSI, ICCID, SIM status
- **Device Info**: Get IMEI, manufacturer, model, firmware version
- **Data Connection**: Check PDP contexts, IP addresses, GPRS status
- **Network Scan**: Find available networks (takes 30-60 seconds)

Each command includes a description of what it does and automatically parses the response into human-readable format.

### APN Configuration Presets

Configure APN with one-click presets for popular carriers:
- Hologram (hologram)
- T-Mobile US (fast.t-mobile.com)
- AT&T (broadband)
- Verizon (vzwinternet)
- Custom APN

The tool also offers to activate the PDP context immediately after configuration.

## Tips for Best Results

1. **Signal Quality First**: Always check signal quality before troubleshooting other issues. Most problems stem from poor signal.

2. **Wait for Registration**: Network registration can take 30-60 seconds. Be patient after changing settings.

3. **Clear FPLMN Regularly**: If moving between areas or testing different networks, clear the FPLMN list periodically.

4. **Save Diagnostic Reports**: Export reports before making configuration changes for comparison.

5. **Monitor Over Time**: Run quick status checks periodically to catch degrading signal or network issues early.

6. **Check Multiple Registration Types**: LTE devices should check CEREG, not just CREG/CGREG.

7. **Use Debug Mode**: If auto-detection is slow or hanging, enable debug mode to see exactly what's happening.

## Technical Notes

### Serial Port Settings
- **Baud Rate**: Usually 115200, some modems use 9600 or 460800
- **Data Bits**: 8
- **Parity**: None
- **Stop Bits**: 1
- **Flow Control**: None (default)

### AT Command Formatting
- Commands must end with `\r\n` (handled automatically)
- Responses include echo, data, and OK/ERROR
- Wait times vary by command (network scans take 30-60s)

### Multi-Port Modems
Many USB modems present multiple serial ports:
- Port 0: Usually AT commands (diagnostic)
- Port 1: Sometimes AT commands (modem)
- Port 2: Often AT commands (main)
- Port 3: Sometimes GPS (NMEA)

Try different ports if commands fail.

## Support and References

### Hologram Documentation
- [Introduction to AT Commands](https://hologram.io/docs/reference/at-commands/introduction)
- [AT Command Reference](https://hologram.io/docs/reference/at-commands/reference)
- [Clear FPLMN List](https://hologram.io/docs/reference/at-commands/clear-fplmn)
- [Device Data Troubleshooting](https://hologram.io/docs/guides/troubleshooting/device-data)
- [Network Connection Troubleshooting](https://hologram.io/docs/guides/troubleshooting/network-connection)

### Modem Manufacturer Documentation
Consult your specific modem's AT command manual for:
- Vendor-specific commands
- Extended feature sets
- Power management commands
- GPS/GNSS commands (if applicable)

## License

This tool is provided as-is for use with cellular modems on Raspberry Pi and Linux systems.

## Support the Project

If this tool has helped you save time troubleshooting your cellular modem, consider supporting its development:

☕ **[Buy Me a Coffee](https://buymeacoffee.com/mike.brandon)**

Your support helps maintain and improve this tool for the community. Thank you! 🙏

## Contributing

To improve this tool:
1. Test with your specific modem model
2. Document any modem-specific quirks
3. Share successful configurations
4. Report bugs with detailed diagnostic output

## Performance Notes

### Auto-Detection Speed Improvements

The optimized two-phase auto-detection provides significant speed improvements:

**Previous approach:**
- Tested ALL baud rates (5) for EACH port sequentially
- For 3 ports: 3 × 5 = 15 connection attempts
- Typical time: 60-90 seconds (including timeouts on non-modem ports)

**New optimized approach:**
- Phase 1: Tests ONLY 115200 baud for ALL ports
- For 3 ports: 3 × 1 = 3 connection attempts
- Typical Phase 1 time: 5-10 seconds
- Phase 2 only runs if Phase 1 finds nothing (rare)

**Benefits:**
- ⚡ 80-90% faster in typical scenarios
- 🎯 Prioritizes likely modem ports first
- ⏱️ Reduced timeouts (1 sec vs 2 sec) for quick screening
- 🚀 Early exit when modem found (doesn't waste time on other ports)
- 🔧 Fallback testing still available if needed

### Platform-Specific Optimizations

**Windows:**
- Uses native COM port enumeration (faster than pattern matching)
- Prioritizes lower COM numbers (COM3, COM4, COM5)
- Leverages Windows device descriptions

**Linux:**
- Smart port prioritization (USB2 > USB1 > USB0)
- Reduced udevadm timeout (1 sec vs 2 sec)
- Skips unlikely ports in Phase 1

## Version History

**v1.3** - Menu Reorganization & Data Transfer Testing
- **Data Transfer Testing** - Send controlled test data and validate against provider dashboard
  - Accurate overhead calculation (TCP/IP, TLS, DNS, HTTP headers)
  - Support for multiple test sizes (1KB to 1MB)
  - Clear expectations for Hologram dashboard validation
  - Cellular interface detection
  - Step-by-step validation instructions
- **Reorganized menu structure** - Simplified from 9 to 7 main options for better clarity
- **New "APN & Data Connection" menu** - Consolidated APN config and PDP management
- **New "Advanced Tools" submenu** - Groups Common AT Commands, Manual AT, and Vendor Tools
- **Delete PDP Context** - New feature to remove unwanted APN configurations
- **Improved menu naming** - Clearer labels like "Change Connection/Port"
- **Better workflow** - Menu order follows natural troubleshooting flow

**v1.2** - UX & Reliability Update
- **Common AT Commands menu** - 18 pre-configured commands with descriptions
- **Simplified APN configuration** - One-click presets for popular carriers
- **Auto-activation** - Option to activate PDP context immediately after configuration
- **Early exit detection** - Stops testing after finding first working port
- **ModemManager integration** - Automatic detection and safe temporary stopping
- **Debug mode** - Verbose logging for troubleshooting (MODEMO_DEBUG=1)
- **Port blacklist** - Skip problematic ports via MODEMO_SKIP_PORTS
- **Improved timeout handling** - Faster detection with aggressive timeouts

**v1.1** - Performance & Cross-Platform Update
- Optimized two-phase auto-detection (80-90% faster)
- Full Windows support with COM port auto-detection
- Cross-platform path handling for report exports
- Smart port prioritization (highest USB first)
- Platform-aware defaults
- Reduced connection timeouts
- Enhanced vendor-specific tools menu

**v1.0** - Initial release
- Full diagnostic suite
- Network tools
- Data connection tools
- Manual AT interface
- Report generation
- Human-readable output translation