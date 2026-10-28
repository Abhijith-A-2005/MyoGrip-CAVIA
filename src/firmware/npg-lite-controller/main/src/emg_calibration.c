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
static emg_thresholds_t thresholds;
static bool thresholds_valid;

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
  thresholds_valid = false;
  if (active_capture >= 0) {
    ESP_LOGW(TAG, "Capture aborted by acquisition gap");
  }

  active_capture = -1;
  preparation_left = 0;
  decimation_count = 0;
  point_count = 0;
  memset(summaries, 0, sizeof(summaries));
}

bool emg_calibration_get_thresholds(emg_thresholds_t *out)
{
  if (!thresholds_valid || out == NULL) {
    return false;
  }

  *out = thresholds;
  return true;
}

static bool derive_thresholds(const float rest[2],
                              const float reference[2],
                              float normal_ext_p95,
                              float high_ext_median)
{
  emg_thresholds_t candidate = {0};

  for (unsigned ch = 0; ch < 2; ch++) {
    float span = reference[ch] - rest[ch];

    candidate.rest[ch] = rest[ch];
    candidate.reference[ch] = reference[ch];
    candidate.on[ch] = rest[ch] + EMG_ACTIVATION_FRACTION * span;
    candidate.off[ch] = rest[ch] + EMG_RELEASE_FRACTION * span;

    if (!isfinite(candidate.on[ch]) ||
        !isfinite(candidate.off[ch]) ||
        !(rest[ch] < candidate.off[ch] &&
          candidate.off[ch] < candidate.on[ch] &&
          candidate.on[ch] < reference[ch])) {
      return false;
    }
  }

  // Midpoint between normal-extension p95 and high-extension median.
  candidate.high_extension =
      normal_ext_p95 + 0.5f * (high_ext_median - normal_ext_p95);

  if (!isfinite(candidate.high_extension) ||
      !(normal_ext_p95 < candidate.high_extension &&
        candidate.high_extension < high_ext_median)) {
    return false;
  }

  // Publish only after every derived value passes its checks.
  thresholds = candidate;
  thresholds_valid = true;
  return true;
}

static bool validate_calibration(void)
{
  thresholds_valid = false;
  for (int capture = 0; capture < 4; capture++) {
    if (!summaries[capture].valid) {
      ESP_LOGW(TAG, "Missing capture: %s", names[capture]);
      return false;
    }

    // CH3 is observed but does not determine acceptance.
    for (unsigned ch = 0; ch < 2; ch++) {
      float median = summaries[capture].median[ch];
      float p95 = summaries[capture].p95[ch];

      if (!isfinite(median) || !isfinite(p95) ||
          median < 0.0f || p95 < median) {
        ESP_LOGE(TAG, "Invalid statistics: %s CH%u",
                 names[capture], ch + 1);
        return false;
      }
    }
  }

  float rest[2] = {
      summaries[0].p95[0],
      summaries[0].p95[1]
  };

  float reference[2] = {
      summaries[1].median[0],  // Flexor during flexion.
      summaries[2].median[1]   // Extensor during extension.
  };

  float span[2];

  for (unsigned ch = 0; ch < 2; ch++) {
    span[ch] = reference[ch] - rest[ch];

    if (span[ch] < EMG_CAL_MIN_REFERENCE_SPAN ||
        reference[ch] < rest[ch] * EMG_CAL_MIN_REFERENCE_RATIO) {
      ESP_LOGW(TAG,
               "Weak CH%u reference: rest_p95=%.1f reference=%.1f",
               ch + 1, (double)rest[ch], (double)reference[ch]);
      return false;
    }
  }

  // Each intended contraction has normalized activation 1.0.
  // Compare the opposite channel using its own calibrated scale.
  float ext_during_flex = fmaxf(
      0.0f, (summaries[1].median[1] - rest[1]) / span[1]);

  float flex_during_ext = fmaxf(
      0.0f, (summaries[2].median[0] - rest[0]) / span[0]);

  if (ext_during_flex * EMG_CAL_DOMINANCE_RATIO >= 1.0f ||
      flex_during_ext * EMG_CAL_DOMINANCE_RATIO >= 1.0f) {
    ESP_LOGW(TAG,
             "Excessive normalized channel overlap: "
             "ext_during_flex=%.2f flex_during_ext=%.2f",
             (double)ext_during_flex, (double)flex_during_ext);
    return false;
  }

  float normal_ext_p95 = summaries[2].p95[1];
  float high_ext_median = summaries[3].median[1];

  if (high_ext_median < normal_ext_p95 * EMG_CAL_MIN_HE_RATIO) {
    ESP_LOGW(TAG,
             "Weak HE separation: normal_ext_p95=%.1f HE_median=%.1f",
             (double)normal_ext_p95, (double)high_ext_median);
    return false;
  }

  if (!derive_thresholds(rest, reference,
                         normal_ext_p95, high_ext_median)) {
    ESP_LOGE(TAG, "Invalid derived thresholds; check configuration");
    return false;
  }

  ESP_LOGI(TAG, "Reference checks PASSED");

  ESP_LOGI(TAG,
           "Normalized overlap: ext_during_flex=%.2f "
           "flex_during_ext=%.2f",
           (double)ext_during_flex, (double)flex_during_ext);

  ESP_LOGI(TAG, "Flexor thresholds: ON=%.1f OFF=%.1f",
           (double)thresholds.on[0],
           (double)thresholds.off[0]);

  ESP_LOGI(TAG, "Extensor thresholds: ON=%.1f OFF=%.1f",
           (double)thresholds.on[1],
           (double)thresholds.off[1]);

  ESP_LOGI(TAG, "High-extension threshold: %.1f",
           (double)thresholds.high_extension);

  return true;
}

void emg_calibration_command(char command)
{
  if (command == '?') {
    ESP_LOGI(TAG,
             "r=rest/new session, f=flexion, e=extension, "
             "h=high extension, v=validate, x=cancel");
    return;
  }

  if (command == 'x') {
    thresholds_valid = false;
    if (active_capture >= 0) {
      ESP_LOGI(TAG, "%s capture cancelled", names[active_capture]);
    } else {
      ESP_LOGI(TAG, "No capture running");
    }

    active_capture = -1;
    return;
  }

  if (command == 'v') {
    if (active_capture >= 0) {
      ESP_LOGW(TAG, "Finish or cancel the current capture first");
    } else {
      (void)validate_calibration();
    }
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

  thresholds_valid = false;
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