#ifndef MYOGRIP_LIVE_H
#define MYOGRIP_LIVE_H

#include "myogrip_fsm.h"
#include "emg_gesture.h"

/* Owned only by the acquisition task. Simulation only: no servo output. */
typedef struct {
    mg_fsm_t fsm;
    bool calibrated;
    bool armed;
    unsigned rest_samples;
    uint32_t samples;
    uint32_t gesture_seq;
    emg_gesture_t last_gesture;
    const char *activity;
} myogrip_live_t;

void myogrip_live_init(myogrip_live_t *live);
void myogrip_live_gap(myogrip_live_t *live);
bool myogrip_live_menu_ready(const myogrip_live_t *live);
bool myogrip_live_load_menu(myogrip_live_t *live, const mg_menu_t *menu,
                            bool preserve_selection);
bool myogrip_live_demo_menu(myogrip_live_t *live);
/* Exactly one call per complete, valid three-channel EMG sample set. */
void myogrip_live_sample(myogrip_live_t *live, const char *activity,
                         emg_gesture_t gesture);

#endif
