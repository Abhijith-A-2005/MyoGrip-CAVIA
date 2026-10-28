#include "emg_signal.h"

#include <math.h>
#include <string.h>

static struct {
  float previous_input[EMG_CHANNEL_COUNT];
  float previous_output[EMG_CHANNEL_COUNT];
  float squares[EMG_CHANNEL_COUNT][EMG_RMS_WINDOW_SAMPLES];
  unsigned position;
  unsigned samples_seen;
  bool initialized;
} signal_state;

void emg_signal_reset(void)
{
  memset(&signal_state, 0, sizeof(signal_state));
}

bool emg_signal_process(const uint16_t raw[EMG_CHANNEL_COUNT],
                        float rms[EMG_CHANNEL_COUNT])
{
  const float alpha =
      (float)EMG_SAMPLE_RATE_HZ /
      ((float)EMG_SAMPLE_RATE_HZ + 6.28318530718f * EMG_HIGHPASS_HZ);

  if (!signal_state.initialized) {
    for (unsigned ch = 0; ch < EMG_CHANNEL_COUNT; ch++) {
      signal_state.previous_input[ch] = (float)raw[ch];
    }
    signal_state.initialized = true;
  }

  for (unsigned ch = 0; ch < EMG_CHANNEL_COUNT; ch++) {
    float input = (float)raw[ch];
    float filtered = alpha * (signal_state.previous_output[ch] +
                              input - signal_state.previous_input[ch]);

    signal_state.previous_input[ch] = input;
    signal_state.previous_output[ch] = filtered;
    signal_state.squares[ch][signal_state.position] = filtered * filtered;

    // Recompute the small window to avoid cumulative subtraction drift.
    float sum = 0.0f;
    for (unsigned n = 0; n < EMG_RMS_WINDOW_SAMPLES; n++) {
      sum += signal_state.squares[ch][n];
    }
    rms[ch] = sqrtf(sum / (float)EMG_RMS_WINDOW_SAMPLES);
  }

  signal_state.position =
      (signal_state.position + 1) % EMG_RMS_WINDOW_SAMPLES;

  if (signal_state.samples_seen < EMG_WARMUP_SAMPLES) {
    signal_state.samples_seen++;
  }

  return signal_state.samples_seen >= EMG_WARMUP_SAMPLES;
}