#include "emg_episode.h"
#include "emg_config.h"

#include <string.h>

enum { WAIT_REST, READY, ACTIVE };

static unsigned phase;
static unsigned rest_samples;
static emg_episode_t episode;

void emg_episode_reset(void)
{
  phase = WAIT_REST;
  rest_samples = 0;
  memset(&episode, 0, sizeof(episode));
}

emg_episode_event_t emg_episode_update(const char *activity,
                                      emg_episode_t *out)
{
  if (activity == NULL || out == NULL) {
    emg_episode_reset();
    return EMG_EPISODE_NONE;
  }

  int rest = strcmp(activity, "REST") == 0;
  int ambiguous = strcmp(activity, "INVALID") == 0;

  char direction = strcmp(activity, "FLEX_ACTIVE") == 0 ? 'F' :
                   strcmp(activity, "EXT_ACTIVE") == 0 ? 'E' : 0;

  if (!rest && !ambiguous && direction == 0) {
    // Includes UNCALIBRATED and WARMUP: discard pending work.
    emg_episode_reset();
    return EMG_EPISODE_NONE;
  }

  if (phase == WAIT_REST) {
    if (!rest) {
      rest_samples = 0;
    } else if (++rest_samples >= EMG_EPISODE_REST_SAMPLES) {
      phase = READY;
      rest_samples = 0;
    }

    return EMG_EPISODE_NONE;
  }

  if (phase == READY) {
    if (ambiguous) {
      emg_episode_reset();
    } else if (direction != 0) {
      memset(&episode, 0, sizeof(episode));

      episode.direction = direction;
      episode.span_samples = 1;
      episode.primary_samples = 1;

      phase = ACTIVE;
      *out = episode;
      return EMG_EPISODE_BEGIN;
    }

    return EMG_EPISODE_NONE;
  }

  episode.span_samples++;

  if (rest) {
    if (++rest_samples >= EMG_EPISODE_REST_SAMPLES) {
      // Exclude the final confirmed rest from the reported span.
      episode.span_samples -= rest_samples;

      *out = episode;
      phase = READY;
      rest_samples = 0;

      return EMG_EPISODE_END;
    }

    return EMG_EPISODE_NONE;
  }

  rest_samples = 0;

  if (ambiguous) {
    episode.ambiguous_samples++;
  } else if (direction == episode.direction) {
    episode.primary_samples++;
  } else {
    episode.opposite_samples++;
  }

  return EMG_EPISODE_NONE;
}