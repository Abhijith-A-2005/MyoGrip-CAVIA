# NPG-Lite-IDF-Firmware
Neuro PlayGround (NPG) Lite (ESP-IDF) firmware repository.

Build
```bash
idf.py set-target esp32c6
idf.py build
```

Flash
```bash
idf.py flash -p <port>
```

Monitor
```bash
idf.py monitor -p <port>
```

Features:
1. ADC Channels: 3
2. ADC Sampling Rate: 250Hz
3. BLE Notification Rate: 10Hz (Packet Len: 25)
4. BLE Modem Sleep Enabled
5. Light Sleep Enabled

> [!NOTE]
> Light Sleep mode may disable serial output on monitor, for debugging uncomment `#define DEBUG` in main.c

> [!NOTE]
> Default ADC channels are 0,1,2. To use 3,4,5 uncomment `#define SECONDARY_CH` in main.c
> NPG-Lite does not provide amplifiers for these channels on main board. 
> Those are provided on [NPG VibZ+ Playmate](https://docs.upsidedownlabs.tech/hardware/bioamp/neuro-play-ground-lite/index.html#id1)

## Data Acquisition

A Python-based BLE data logger is available for streaming and recording biopotential data from NPG Lite.

### Quick Start

```bash
cd test
pip install -r requirements.txt
python record-log.py --outfile data.csv
```

**View all options:**
```bash
python record-log.py --help
```

The script automatically:
- Scans and connects to NPG Lite via BLE
- Streams 3-channel biopotential data at 250 Hz
- Saves timestamped data to CSV format
- Generates summary statistics

**Command-line options:**
- `--duration` - Set recording duration in minutes (default: 10)
- `--device-address` - Connect to specific BLE address
- `--device-name-prefix` - Scan for custom device name

For detailed usage instructions, configuration options, and troubleshooting, see [test/README.md](test/README.md).

## References 
1. [Apache Mynewt BLE user guide](https://mynewt.apache.org/latest/network/index.html)
2. [ESP-IDF NimBLE GATT SERVER Example](https://github.com/espressif/esp-idf/tree/master/examples/bluetooth/ble_get_started/nimble/NimBLE_GATT_Server)
3. [ESP-IDF NimBLE Power Save Example](https://github.com/espressif/esp-idf/blob/master/examples/bluetooth/nimble/power_save/README.md)
