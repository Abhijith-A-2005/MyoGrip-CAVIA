#include "emg_calibration.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "esp_log.h"

static const char *TAG = "MYOGRIP_CAL";

static const char commands[] = {'r', 'f', 'e', 'h'};
static const char *names[] = {
    "REST", "FLEXION", "EXTENSION", "HIGH_EXTENSION"
};

typedef struct {
  float median[EMG_CHANNEL_COUNT];
  float p95[EMG_CHANNEL_COUNT];
  bool valid;
} calibration_summary_t;

static calibration_summary_t summaries[4];

static float observations[EMG_CHANNEL_COUNT][EMG_CAL_POINTS];
static float sorted[EMG_CAL_POINTS];

static int active_capture = -1;
static unsigned preparation_left;
static unsigned decimation_count;
static unsigned point_count;

_Static_assert(EMG_CAL_POINTS > 0, "Calibration needs observations");
_Static_assert(
    EMG_CAL_CAPTURE_SAMPLES % EMG_CAL_DECIMATION == 0,
    "Capture length must be divisible by decimation");

static int find_capture(char command)
{
  for (int i = 0; i < 4; i++) {
    if (commands[i] == command) {
      return i;
    }
  }
  return -1;
}

static int compare_float(const void *left, const void *right)
{
  float a = *(const float *)left;
  float b = *(const float *)right;

  return (a > b) - (a < b);
}

void emg_calibration_reset(void)
{
  if (active_capture >= 0) {
    ESP_LOGW(TAG, "Capture aborted by acquisition gap");
  }

  active_capture = -1;
  preparation_left = 0;
  decimation_count = 0;
  point_count = 0;
  memset(summaries, 0, sizeof(summaries));
}

void emg_calibration_command(char command)
{
  if (command == '?') {
    ESP_LOGI(TAG,
             "r=rest/new session, f=flexion, e=extension, "
             "h=high extension, x=cancel");
    return;
  }

  if (command == 'x') {
    if (active_capture >= 0) {
      ESP_LOGI(TAG, "%s capture cancelled", names[active_capture]);
    } else {
      ESP_LOGI(TAG, "No capture running");
    }

    active_capture = -1;
    return;
  }

  int capture = find_capture(command);
  if (capture < 0) {
    return;
  }

  if (active_capture >= 0) {
    ESP_LOGW(TAG, "Capture busy; finish it or cancel with x");
    return;
  }

  if (capture == 0) {
    // A new rest capture starts a fresh calibration session.
    memset(summaries, 0, sizeof(summaries));
  } else if (!summaries[0].valid) {
    ESP_LOGW(TAG, "Capture rest with r first");
    return;
  }

  summaries[capture].valid = false;
  active_capture = capture;
  preparation_left = EMG_CAL_PREP_SAMPLES;
  decimation_count = 0;
  point_count = 0;

  ESP_LOGI(TAG, "%s: prepare for 2 seconds", names[capture]);
}

static void finish_capture(void)
{
  calibration_summary_t *summary = &summaries[active_capture];

  for (unsigned ch = 0; ch < EMG_CHANNEL_COUNT; ch++) {
    memcpy(sorted, observations[ch], sizeof(sorted));
    qsort(sorted, EMG_CAL_POINTS, sizeof(sorted[0]), compare_float);

    unsigned middle = EMG_CAL_POINTS / 2;

    if (EMG_CAL_POINTS % 2 == 0) {
      summary->median[ch] =
          0.5f * (sorted[middle - 1] + sorted[middle]);
    } else {
      summary->median[ch] = sorted[middle];
    }

    // Nearest-rank 95th percentile.
    unsigned p95_index = (95 * EMG_CAL_POINTS + 99) / 100 - 1;
    summary->p95[ch] = sorted[p95_index];
  }

  summary->valid = true;

  ESP_LOGI(TAG, "%s DONE: %u observations",
           names[active_capture], point_count);

  for (unsigned ch = 0; ch < EMG_CHANNEL_COUNT; ch++) {
    ESP_LOGI(TAG, "CH%u median=%.1f p95=%.1f",
             ch + 1,
             (double)summary->median[ch],
             (double)summary->p95[ch]);
  }

  active_capture = -1;
}

void emg_calibration_process(
    const float rms[EMG_CHANNEL_COUNT], bool ready)
{
  if (active_capture < 0 || !ready) {
    return;
  }

  for (unsigned ch = 0; ch < EMG_CHANNEL_COUNT; ch++) {
    if (!isfinite(rms[ch]) || rms[ch] < 0.0f) {
      ESP_LOGE(TAG, "Invalid RMS; capture cancelled");
      active_capture = -1;
      return;
    }
  }

  if (preparation_left > 0) {
    preparation_left--;

    if (preparation_left == 0) {
      ESP_LOGI(TAG, "%s: CAPTURE NOW, hold for 4 seconds",
               names[active_capture]);
    }
    return;
  }

  decimation_count++;
  if (decimation_count < EMG_CAL_DECIMATION) {
    return;
  }
  decimation_count = 0;

  for (unsigned ch = 0; ch < EMG_CHANNEL_COUNT; ch++) {
    observations[ch][point_count] = rms[ch];
  }

  point_count++;
  if (point_count == EMG_CAL_POINTS) {
    finish_capture();
  }
}