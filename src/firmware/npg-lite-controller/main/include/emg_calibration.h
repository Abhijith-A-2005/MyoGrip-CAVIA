#ifndef EMG_CALIBRATION_H
#define EMG_CALIBRATION_H

#include <stdbool.h>
#include "emg_config.h"

void emg_calibration_command(char command);

void emg_calibration_process(
    const float rms[EMG_CHANNEL_COUNT], bool ready);

// Invalidate calibration after an acquisition gap.
void emg_calibration_reset(void);

#endif