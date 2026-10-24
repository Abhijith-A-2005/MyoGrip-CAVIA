#ifndef EMG_GESTURE_H
#define EMG_GESTURE_H

#include "emg_episode.h"

typedef enum {
  EMG_GESTURE_NONE,
  EMG_GESTURE_SF,
  EMG_GESTURE_SE,
  EMG_GESTURE_LF,
  EMG_GESTURE_LE,
  EMG_GESTURE_REJECTED
} emg_gesture_t;

void emg_gesture_reset(void);

emg_gesture_t emg_gesture_update(const char *activity,
                                emg_episode_event_t boundary,
                                const emg_episode_t *episode);

const char *emg_gesture_name(emg_gesture_t gesture);

#endif