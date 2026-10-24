#ifndef EMG_EPISODE_H
#define EMG_EPISODE_H

#include <stdint.h>

typedef enum {
  EMG_EPISODE_NONE,
  EMG_EPISODE_BEGIN,
  EMG_EPISODE_END
} emg_episode_event_t;

typedef struct {
  char direction;  // 'F' or 'E': first observed direction.
  uint32_t span_samples;
  uint32_t primary_samples;
  uint32_t opposite_samples;
  uint32_t ambiguous_samples;
} emg_episode_t;

void emg_episode_reset(void);

emg_episode_event_t emg_episode_update(const char *activity,
                                      emg_episode_t *out);

#endif