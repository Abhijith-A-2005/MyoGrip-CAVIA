# NPG Lite Data Logger

Automated BLE data acquisition script for the **Neuro PlayGround (NPG) Lite**. The record-log.py script connects to NPG Lite via Bluetooth LE, streams 3-channel biopotential data (EMG/ECG/EOG/EEG), and saves it to CSV format with automatic timing and statistics generation.

---

## Hardware Setup

### 1. Power On NPG Lite

1. **Connect the battery**: Ensure a LiPo battery is connected to the PicoBlade connector on NPG Lite
2. **Turn on the device**: Flip the power switch on the board to the ON position

---

## Software Setup

### 1. Create Python Virtual Environment (Recommended)

**Open a terminal and navigate to the test folder:**

**On Linux/macOS:**
```bash
cd test
python3 -m venv .venv
source .venv/bin/activate
```

**On Windows:**
```bash
cd test
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install Required Libraries

```bash
pip install -r requirements.txt
```

**Required dependencies:**
- `bleak` - Bluetooth Low Energy library
- `pytz` or Python 3.9+ (for IST timezone support)

---

## Usage

### Basic Command

```bash
python record-log.py --outfile data.csv
```

### View All Available Options

```bash
python record-log.py --help
```

### Command-Line Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--outfile` | Yes | - | CSV file path to save recorded data |
| `--duration` | No | 10 | Streaming duration in minutes |
| `--device-address` | No | - | Specific BLE device address (skips scanning) |
| `--device-name-prefix` | No | NPG | Device name prefix to scan for |

### Usage Examples

**Default (10 minutes):**
```bash
python record-log.py --outfile data.csv
```

**Custom duration (30 minutes):**
```bash
python record-log.py --outfile data.csv --duration 30
```

**Long recording (2 hours):**
```bash
python record-log.py --outfile data.csv --duration 120
```

**With specific device address:**
```bash
python record-log.py --outfile data.csv --device-address AA:BB:CC:DD:EE:FF
```

**Custom device name prefix:**
```bash
python record-log.py --outfile data.csv --device-name-prefix MYNPG --duration 60
```

### What Happens When You Run It

1. **Scanning**: Script scans for BLE devices with name prefix "NPG" (unless specific address provided)
2. **Connection**: Automatically connects to your NPG Lite device
3. **Start Streaming**: Sends START command to begin data acquisition
4. **Real-time Logging**: 
   - Prints BLE notification sizes (packet sizes received)
   - Displays batch information with elapsed time (format: `hh:mm:ss`)
   - Warns if missing samples are detected (based on counter)
5. **Auto-Stop**: Stops after configured duration (default: **10 minutes**, configurable via `--duration`)
6. **Saves Files**: Creates CSV data file and summary statistics file

---

## Output Files

### 1. CSV Data File (`data.csv`)

Contains timestamped biopotential data with the following columns:

| Column | Description |
|--------|-------------|
| `timestamp_unix` | Unix timestamp (seconds since epoch) with microsecond precision |
| `counter` | Rolling sample counter (0-255) for detecting missing packets |
| `ch0` | Channel 0 ADC value (12-bit: 0-4095) |
| `ch1` | Channel 1 ADC value (12-bit: 0-4095) |
| `ch2` | Channel 2 ADC value (12-bit: 0-4095) |

**Sample rate**: 250 Hz per channel (250 samples/second)

**Example data:**
```csv
timestamp_unix,counter,ch0,ch1,ch2
1731586234.567890,0,2048,2050,2045
1731586234.571890,1,2049,2051,2046
```

### 2. Summary Statistics File (`data_summary.txt`)

Auto-generated after data collection ends. Contains:
- **Total samples received** per channel
- **Missing samples detected** (if any BLE packets were lost)
- **First and last sample timestamps** (in IST timezone)
- **Total elapsed time** (hh:mm:ss format)
- **Actual vs expected sample rate** (quality metric)

**Example:**
```
============================================================
NPG-Lite Data Collection Summary
============================================================

Total samples received: 7200000
Samples per channel: 7200000
Missing samples detected: 0

First sample received: 2025-11-14 16:30:45.123 IST
Last sample received:  2025-11-15 00:30:45.089 IST

Total time elapsed: 08:00:00
Total time elapsed (seconds): 28800.000

Expected sample rate: 250 Hz
Actual sample rate: 250.00 Hz
============================================================
```

---

## Console Output

During operation, the script prints:

- `[BLE] Notification received: 175 bytes` - Size of each BLE packet
- `[BATCH] 25 samples; last_counter=24; elapsed=00:05:23` - Processing progress
- `[CSV] Wrote 25 samples to data.csv (last_counter=24)` - Save confirmations
- `[WARNING] Detected 3 missing samples...` - Data quality alerts (if packets are dropped)

---

## Important Notes

- Duration timer starts when **first data packet is received** (not when script starts)
- No practical limit on duration - set any value you need via `--duration`
- Consider disk space: For example, 8 hours @ 250 Hz = ~7.2 million samples (~270 MB CSV)
- Script auto-exits when duration completes or BLE disconnects

---

## Stopping Data Collection

### Normal Termination
- Script automatically stops after configured duration
- Or waits for BLE disconnect

### Manual Stop
- Press **Ctrl+C** once to interrupt
- Script will save remaining data and generate summary before exiting

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No matching NPG device found" | Ensure NPG Lite is powered on and within BLE range (~10m) |
| "BLE connection lost" | Check battery level; move closer to the device |
| Missing samples detected | Reduce distance; minimize BLE interference |
| Large CSV file | Lower duration or use external storage |

---

## Technical Specifications

- **Sampling Rate**: 250 Hz per channel (750 samples/sec total)
- **ADC Resolution**: 12-bit (0-4095 range)
- **Packet Size**: 175 bytes typical (25 samples × 7 bytes)
- **Data Format**: Big-endian 16-bit integers
- **Timezone**: IST (UTC+5:30) for timestamps

---

## Requirements

- Python 3.7+
- BLE-capable computer/Raspberry Pi
- NPG Lite with charged battery
- ~35 MB disk space per hour of recording

---

## License

This script works with NPG Lite hardware from **Upside Down Labs**. Visit [docs.upsidedownlabs.tech](https://docs.upsidedownlabs.tech) for more information.

---

**Created for research, education, and HCI/BCI applications.**
