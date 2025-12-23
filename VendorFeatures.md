# Vendor-Specific Features Guide

## 🎯 Overview

The Cellular Modem Diagnostic Tool now includes **intelligent vendor detection** and **manufacturer-specific optimizations** for major IoT modem brands.

---

## 🔍 Supported Vendors

### ✅ **Full Support** (Advanced Features)
- **Quectel** - EC25, EG25, BG96, BC660K, etc.

### 🟡 **Basic Support** (Standard Commands + Detection)
- **Sierra Wireless** - HL series, MC series
- **u-blox** - SARA, LARA, TOBY series
- **Telit** - LE910, ME910, xE910 series
- **SimCom** - SIM7000, SIM7600, SIM800 series

### ⚪ **Generic Support** (All Others)
- Any AT-command compatible modem

---

## 🚀 Key Features

### 1. **Automatic Vendor Detection**

The tool automatically identifies your modem manufacturer and model:

```
Detected Modem: Quectel - EC25-E
```

**How it works:**
- Queries `AT+CGMI` (manufacturer)
- Queries `AT+CGMM` (model)
- Enables vendor-specific features automatically
- Shows detected vendor in diagnostic output

### 2. **Vendor-Specific Diagnostic Commands**

**Standard diagnostics** run for all modems, then **additional vendor-specific tests** are automatically added:

| Vendor | Additional Commands | Purpose |
|--------|-------------------|---------|
| **Quectel** | AT+QENG="servingcell" | Advanced cell information with RSRP, RSRQ, SINR |
| | AT+QNWINFO | Network technology and band |
| | AT+QSPN | Service provider name |
| | AT+QCCID | Alternative ICCID command |
| **Sierra** | AT!GSTATUS? | Comprehensive status |
| | AT+KCELLMEAS=1 | Cell measurements |
| **u-blox** | AT+UCGED? | Cell information |
| | AT+UREG? | Registration details |

### 3. **Enhanced Data Parsing**

Vendor-specific responses are parsed into human-readable format:

**Example - Quectel QENG Response:**
```
┌────────────────────────┬────────────────┬─────────────────────────────┐
│ Parameter              │ Value          │ Details                      │
├────────────────────────┼────────────────┼─────────────────────────────┤
│ Cell ID                │ 12345678       │ PCI: 123                    │
│ Frequency              │ EARFCN: 5230   │ Band: LTE BAND 12           │
│ Bandwidth              │ DL: 10 MHz     │ UL: 10 MHz                  │
│ TAC                    │ 1234           │                             │
│ RSRP                   │ -95 dBm        │ Reference Signal Rx Power   │
│ RSRQ                   │ -10 dB         │ Reference Signal Rx Quality │
│ RSSI                   │ -65 dBm        │ Received Signal Strength    │
│ SINR                   │ 15 dB          │ Signal to Noise Ratio       │
└────────────────────────┴────────────────┴─────────────────────────────┘
```

**Without vendor-specific parsing:**
```
+QENG: "servingcell","NOCONN","LTE","FDD",310,260,12345678,123,5230,12,10,10,"1234",-95,-10,-65,15
```

---

## 🛠️ Vendor-Specific Tools Menu

### Accessing Vendor Tools

**Main Menu → Option 5: Vendor-Specific Tools**

If modem is detected, you'll see manufacturer-specific options.

### Quectel Advanced Tools

```
╭────────── Quectel Advanced Tools ──────────╮
│ Model: EC25-E                               │
│                                             │
│ 1. View Advanced Cell Information          │
│ 2. View Network Info                       │
│ 3. Check Temperature                       │
│ 4. View Neighboring Cells                  │
│ 5. Query SIM Slot                          │
│ 6. GPS Status                              │
│ 7. Check eSIM Support                      │
│ 0. Back to Main Menu                       │
╰─────────────────────────────────────────────╯
```

#### Option Descriptions

**1. Advanced Cell Information** (`AT+QENG="servingcell"`)
- Full LTE cell parameters
- RSRP, RSRQ, RSSI, SINR metrics
- Cell ID, PCI, EARFCN, bandwidth
- Real-time serving cell data

**2. Network Info** (`AT+QNWINFO`)
- Current access technology (LTE, WCDMA, GSM)
- Operating band
- Channel number
- Quick network overview

**3. Temperature** (`AT+QTEMP`)
- Internal modem temperature sensors
- Multiple temperature readings
- Thermal monitoring

**4. Neighboring Cells** (`AT+QENG="neighbourcell"`)
- Scan nearby cell towers
- Signal strength comparison
- Handover candidate identification
- Takes 5-10 seconds to complete

**5. SIM Slot** (`AT+QUIMSLOT?`)
- Active SIM slot configuration
- Multi-SIM modem support
- SIM selection status

**6. GPS Status** (`AT+QGPS?`)
- GPS engine status
- Satellite fix information
- Location capabilities

**7. eSIM Support** (`AT+QESIM="eid"`)
- Check if modem supports eSIM
- Get eUICC ID if present
- eSIM profile management capability

---

## 📊 Enhanced Diagnostic Output

### Standard Output (All Modems)
```
Device Information
├─ Manufacturer
├─ Model  
├─ Firmware
└─ IMEI

SIM Information
├─ Status
├─ ICCID
└─ IMSI

Network Status
├─ Registration Status
├─ Operator
└─ Technology

Signal Quality
├─ RSSI
└─ BER
```

### Enhanced Output (Vendor-Specific)
```
[Standard sections above, plus:]

Advanced Cell Information (Quectel)
├─ Cell ID & PCI
├─ Frequency & Band
├─ Bandwidth (UL/DL)
├─ TAC
├─ RSRP (with color coding)
├─ RSRQ
├─ RSSI
└─ SINR (with quality indication)
```

---

## 🔧 Technical Implementation

### Vendor Detection Algorithm

```python
1. Query AT+CGMI (manufacturer)
2. Parse response for keywords:
   - "QUECTEL" → Quectel
   - "SIERRA" → Sierra Wireless
   - "UBLOX" / "U-BLOX" → u-blox
   - "TELIT" → Telit
   - "SIMCOM" → SimCom
3. Query AT+CGMM (model) for specific variant
4. Enable vendor-specific command set
```

### Command Parsing Priority

```
1. Standard 3GPP commands (all modems)
2. Vendor-specific commands (if detected)
3. Fallback to generic parsing
```

### Why This Matters

**Problem:** Different manufacturers implement AT commands differently:
- Quectel: `AT+QCCID` vs standard `AT+CCID`
- Different response formats for similar data
- Vendor-specific advanced features

**Solution:** Tool automatically:
- Detects manufacturer
- Uses optimal commands
- Parses responses correctly
- Shows advanced data when available

---

## 📱 Modem-Specific Capabilities

### Quectel Modems

**Why Special Support?**
- Market leader in IoT modules
- Rich proprietary AT command set
- Superior diagnostic capabilities
- Excellent documentation

**Unique Features:**
- `AT+QENG` - Comprehensive engineering mode
- `AT+QNWINFO` - Quick network summary
- `AT+QTEMP` - Temperature monitoring
- `AT+QGPS` - Built-in GPS (some models)
- `AT+QESIM` - eSIM management (EC25-E, EG25-G)

**Supported Models:**
- EC25 series (Global, Europe, Americas)
- EG25-G (Global LTE)
- BG96 (Cat-M1/NB-IoT)
- BC660K (NB-IoT)
- And others with similar command set

### Sierra Wireless Modems

**Supported Commands:**
- `AT!GSTATUS?` - Comprehensive status
- `AT+KCELLMEAS=1` - Cell measurements

**Common Models:**
- HL series (HL7800, HL7802, etc.)
- MC series
- WP series

### u-blox Modems

**Supported Commands:**
- `AT+UCGED?` - Cell information
- `AT+UREG?` - Registration details

**Common Models:**
- SARA-R4/R5 series
- LARA-R6 series
- TOBY series

---

## 🎓 Usage Examples

### Example 1: Quectel EC25 Diagnostics

```
1. Connect modem
   → Auto-detected: Quectel EC25-E

2. Run Full Diagnostic (Option 1)
   → Standard tests PLUS:
     - AT+QENG="servingcell"
     - AT+QNWINFO
     - AT+QSPN
     - AT+QCCID

3. Results show:
   ✓ Standard information
   ✓ Advanced Cell Information table
   ✓ RSRP: -89 dBm (Good)
   ✓ SINR: 18 dB (Excellent)
   ✓ Band: LTE BAND 12
```

### Example 2: Checking Temperature

```
Main Menu → Vendor-Specific Tools (5)
→ Quectel Advanced Tools
→ Check Temperature (3)

Result:
┌─────────────┬───────────┐
│ Sensor      │ Temp      │
├─────────────┼───────────┤
│ XO Therm    │ 35°C      │
│ PMIC        │ 38°C      │
│ PA Therm    │ 42°C      │
└─────────────┴───────────┘
```

### Example 3: Neighbor Cell Analysis

```
Main Menu → Vendor-Specific Tools (5)
→ View Neighboring Cells (4)
→ Scanning... (10 seconds)

Result shows:
- 3 LTE neighbors found
- Signal strength comparison
- Optimal cell for handover
- Frequency and band info
```

---

## ⚙️ Configuration

### Adding New Vendor Support

To add support for a new vendor, enhance these methods in `modem_diagnostics.py`:

```python
# 1. Add detection in detect_modem_vendor()
elif 'YOURVENDOR' in manu:
    self.modem_vendor = 'YourVendor'

# 2. Add test commands in _get_vendor_tests()
def _get_yourvendor_tests(self):
    return [
        ("AT+VENDORCMD", "Description"),
    ]

# 3. Add parsing in _parse_response()
elif '+VENDORCMD' in command:
    parsed.update(self._parse_vendorcmd(lines))

# 4. Add tools menu
def yourvendor_tools_menu(self):
    # Menu implementation
```

---

## 🔍 Troubleshooting Vendor Features

### Issue: Vendor Not Detected

**Check:**
```
Main Menu → Manual AT Command (6)
→ AT+CGMI
→ AT+CGMM
```

**If response is unclear:**
- Modem may use non-standard identification
- Add custom detection logic
- Fall back to manual commands

### Issue: Vendor Command Fails

**Possible causes:**
1. **Model variant** - Not all models support all commands
2. **Firmware version** - Older firmware may lack features
3. **Module configuration** - Feature may be disabled

**Solution:**
- Check modem's AT command manual
- Try alternate commands
- Use Manual AT Command option

### Issue: Parsed Data Missing

**What it means:**
- Command worked but response format differs
- Parser needs update for your specific model

**Workaround:**
- Raw response is always shown
- Use Manual AT Command for full control

---

## 📚 Additional Resources

### Quectel Documentation
- **AT Commands Manual**: See uploaded document
- **Hardware Design Guide**: Quectel website
- **Application Notes**: Vendor portal

### General Resources
- **3GPP Standards**: Standard AT commands
- **Manufacturer Support**: Vendor-specific forums
- **Community**: IoT developer communities

---

## 🚀 Future Enhancements

**Planned additions:**
- **Telit** full support
- **SimCom** optimization
- **Nordic** nRF9160 support
- **Sequans** Monarch support
- **MediaTek** modules
- More vendor-specific diagnostics
- Automated troubleshooting wizards
- Firmware update assistance

---

## 💡 Best Practices

### 1. **Always Use Auto-Detection**
Let the tool detect your modem automatically - it enables optimal features.

### 2. **Start with Full Diagnostic**
Run Option 1 first to get complete baseline with vendor-specific data.

### 3. **Explore Vendor Menu**
Check Option 5 for manufacturer-specific advanced features.

### 4. **Compare Results**
Use vendor-specific metrics (RSRP, SINR) for more accurate signal assessment.

### 5. **Export Reports**
Save diagnostics with vendor-specific data for documentation.

---

## 🎯 Key Takeaways

1. **Automatic detection** - Tool identifies your modem brand
2. **Optimized commands** - Best AT commands for your hardware
3. **Enhanced parsing** - Human-readable vendor-specific data
4. **Advanced features** - Access manufacturer-specific capabilities
5. **Quectel focus** - Full support for most popular IoT modems
6. **Extensible** - Easy to add more vendors

**Bottom line:** The tool automatically adapts to your modem, providing the best possible diagnostic experience!