#ifndef EMG_SIGNAL_H
#define EMG_SIGNAL_H

#include <stdbool.h>
#include <stdint.h>
#include "emg_config.h"

void emg_signal_reset(void);

// Returns true after warmup. RMS values are in raw ADC-count units.
bool emg_signal_process(const uint16_t raw[EMG_CHANNEL_COUNT],
                        float rms[EMG_CHANNEL_COUNT]);

#endif