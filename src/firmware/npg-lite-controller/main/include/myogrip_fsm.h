#ifndef MYOGRIP_FSM_H
#define MYOGRIP_FSM_H

#include <stdbool.h>
#include <stdint.h>

/* Fixed test menus only. Real CAVIA menus will come later. */
#define MG_ADAPTIVE_COUNT 3
#define MG_FULL_COUNT 4

typedef enum {
    MG_HOME,
    MG_ADAPTIVE,
    MG_FULL,
    MG_HOLDING,
    MG_CLOSING,
    MG_OPENING
} mg_state_t;

typedef enum {
    MG_MENU_READY,

    /* Discrete navigation gestures. */
    MG_SF,
    MG_SE,
    MG_LF,
    MG_LE,
    MG_HE,

    /* Activity inputs used during simulated actuation. */
    MG_REST,
    MG_FLEX_ACTIVE,
    MG_EXT_ACTIVE,
    MG_INVALID
} mg_event_t;

typedef struct {
    mg_state_t state;

    /* Zero-based index into the current/test-selected menu. */
    uint8_t selected;

    /* After invalid actuation input, require rest before resuming. */
    bool wait_release;
} mg_fsm_t;

void mg_init(mg_fsm_t *fsm);
void mg_step(mg_fsm_t *fsm, mg_event_t event);

const char *mg_state_name(mg_state_t state);
const char *mg_event_name(mg_event_t event);

#endif