#ifndef EMG_CONFIG_H
#define EMG_CONFIG_H

#define EMG_CHANNEL_COUNT 3
#define EMG_SAMPLE_RATE_HZ 250

#define EMG_HIGHPASS_HZ 20.0f
#define EMG_RMS_WINDOW_SAMPLES 25

#define EMG_WARMUP_SAMPLES (EMG_SAMPLE_RATE_HZ / 2)
#define EMG_LOG_INTERVAL_SAMPLES (EMG_SAMPLE_RATE_HZ / 2)

#define EMG_CAL_PREP_SAMPLES (2 * EMG_SAMPLE_RATE_HZ)
#define EMG_CAL_CAPTURE_SAMPLES (4 * EMG_SAMPLE_RATE_HZ)

// Store one envelope observation every 20 ms.
#define EMG_CAL_DECIMATION 5
#define EMG_CAL_POINTS \
    (EMG_CAL_CAPTURE_SAMPLES / EMG_CAL_DECIMATION)

// Initial calibration acceptance rules; validate through repeated trials.
#define EMG_CAL_MIN_REFERENCE_RATIO 1.30f
#define EMG_CAL_MIN_REFERENCE_SPAN 5.0f
#define EMG_CAL_MIN_HE_RATIO 1.30f
#define EMG_CAL_DOMINANCE_RATIO 2.0f

// Provisional positions between resting p95 and contraction median.
#define EMG_ACTIVATION_FRACTION 0.35f
#define EMG_RELEASE_FRACTION 0.15f

#define EMG_EPISODE_REST_MS 250
#define EMG_EPISODE_REST_SAMPLES \
    ((EMG_SAMPLE_RATE_HZ * EMG_EPISODE_REST_MS + 999) / 1000)

#define EMG_MS_TO_SAMPLES(ms) \
    ((EMG_SAMPLE_RATE_HZ * (ms) + 999) / 1000)

#define EMG_ONSET_MS 80
#define EMG_SHORT_MIN_MS 120
#define EMG_SHORT_MAX_MS 900
#define EMG_LONG_MS 1200
#define EMG_RELEASE_MS 120
#define EMG_AMBIGUITY_LIMIT_MS 80

#endif