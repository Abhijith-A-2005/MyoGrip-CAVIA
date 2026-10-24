#include "emg_gesture.h"
#include "emg_config.h"

#include <stdbool.h>
#include <string.h>

static struct {
  char direction;
  unsigned primary;
  unsigned onset_run;
  unsigned nonprimary_run;
  unsigned ambiguous;
  bool active;
  bool qualified;
  bool rejected;
  bool sealed;
  bool sent;
} candidate;

void emg_gesture_reset(void)
{
  memset(&candidate, 0, sizeof(candidate));
}

const char *emg_gesture_name(emg_gesture_t gesture)
{
  switch (gesture) {
    case EMG_GESTURE_SF: return "SF";
    case EMG_GESTURE_SE: return "SE";
    case EMG_GESTURE_LF: return "LF";
    case EMG_GESTURE_LE: return "LE";
    case EMG_GESTURE_REJECTED: return "REJECTED";
    default: return "NONE";
  }
}

emg_gesture_t emg_gesture_update(const char *activity,
                                emg_episode_event_t boundary,
                                const emg_episode_t *episode)
{
  if (activity == NULL ||
      strcmp(activity, "UNCALIBRATED") == 0 ||
      strcmp(activity, "WARMUP") == 0) {
    emg_gesture_reset();
    return EMG_GESTURE_NONE;
  }

  if (boundary == EMG_EPISODE_BEGIN) {
    emg_gesture_reset();

    if (episode == NULL ||
        (episode->direction != 'F' && episode->direction != 'E')) {
      return EMG_GESTURE_NONE;
    }

    candidate.direction = episode->direction;
    candidate.active = true;
  }

  if (!candidate.active) {
    return EMG_GESTURE_NONE;
  }

  if (boundary == EMG_EPISODE_END) {
    emg_gesture_t result = EMG_GESTURE_NONE;

    if (!candidate.sent) {
      if (!candidate.rejected && candidate.qualified &&
          candidate.primary >= EMG_MS_TO_SAMPLES(EMG_SHORT_MIN_MS) &&
          candidate.primary <= EMG_MS_TO_SAMPLES(EMG_SHORT_MAX_MS)) {
        result = candidate.direction == 'F'
            ? EMG_GESTURE_SF : EMG_GESTURE_SE;
      } else {
        result = EMG_GESTURE_REJECTED;
      }
    }

    emg_gesture_reset();
    return result;
  }

  if (candidate.sent || candidate.sealed || candidate.rejected) {
    return EMG_GESTURE_NONE;
  }

  bool primary = candidate.direction == 'F'
      ? strcmp(activity, "FLEX_ACTIVE") == 0
      : strcmp(activity, "EXT_ACTIVE") == 0;

  if (primary) {
    candidate.nonprimary_run = 0;
    candidate.primary++;

    if (!candidate.qualified) {
      candidate.onset_run++;
      candidate.qualified =
          candidate.onset_run >= EMG_MS_TO_SAMPLES(EMG_ONSET_MS);
    }

    if (candidate.qualified &&
        candidate.primary >= EMG_MS_TO_SAMPLES(EMG_LONG_MS)) {
      candidate.sent = true;

      return candidate.direction == 'F'
          ? EMG_GESTURE_LF : EMG_GESTURE_LE;
    }
  } else {
    candidate.onset_run = 0;

    if (!candidate.qualified) {
      candidate.primary = 0;
    }

    if (strcmp(activity, "INVALID") == 0) {
      candidate.ambiguous++;

      if (candidate.ambiguous >=
          EMG_MS_TO_SAMPLES(EMG_AMBIGUITY_LIMIT_MS)) {
        candidate.rejected = true;
      }
    }

    candidate.nonprimary_run++;

    if (candidate.nonprimary_run >= EMG_MS_TO_SAMPLES(EMG_RELEASE_MS)) {
      // Freeze duration, retaining direction until the episode ends.
      candidate.sealed = true;
    }
  }

  return EMG_GESTURE_NONE;
}