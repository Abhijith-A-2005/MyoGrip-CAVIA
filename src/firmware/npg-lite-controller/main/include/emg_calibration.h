#ifndef EMG_CALIBRATION_H
#define EMG_CALIBRATION_H

#include <stdbool.h>
#include "emg_config.h"

typedef struct {
  float rest[2];
  float reference[2];
  float on[2];
  float off[2];
  float high_extension;
} emg_thresholds_t;

void emg_calibration_command(char command);

void emg_calibration_process(
    const float rms[EMG_CHANNEL_COUNT], bool ready);

// Invalidate calibration after an acquisition gap.
void emg_calibration_reset(void);

// Call from the acquisition task. False until validation succeeds.
bool emg_calibration_get_thresholds(emg_thresholds_t *out);

#endif