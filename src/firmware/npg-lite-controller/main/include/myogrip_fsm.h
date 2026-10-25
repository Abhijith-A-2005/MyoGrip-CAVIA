#ifndef MYOGRIP_FSM_H
#define MYOGRIP_FSM_H

#include <stdbool.h>
#include <stdint.h>

/* Fixed test menus only. Real CAVIA menus will come later. */
#define MG_ADAPTIVE_COUNT 3
#define MG_FULL_COUNT 4
#define MG_MENU_CAPACITY 4
/* Simulated grip progress per second. */
#define MG_CLOSE_SPEED_PER_S 0.25f
#define MG_OPEN_SPEED_PER_S  0.35f
#define MG_HE_RETURN_SPEED_PER_S 0.5f

typedef enum {
    MG_GRIP_NONE = -1,
    MG_GRIP_POWER = 1,
    MG_GRIP_PINCH,
    MG_GRIP_TRIPOD,
    MG_GRIP_LATERAL
} mg_grip_t;

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
    uint32_t menu_id;
    mg_grip_t adaptive[MG_MENU_CAPACITY];
    uint8_t adaptive_count;
    mg_grip_t full[MG_MENU_CAPACITY];
    uint8_t full_count;
    bool full_menu_only;
} mg_menu_t;

typedef struct {
    mg_state_t state;
    mg_menu_t menu;
    bool menu_loaded;

    float grip_progress;  /* 0.0 = open, 1.0 = closed */

    bool returning;  /* HE return is opening toward the Full Menu. */

    /* Zero-based index into the current/test-selected menu. */
    uint8_t selected;

    /* Confirmed grip, independent of subsequent activity inputs. */
    mg_grip_t active_grip;

    /* After invalid actuation input, require rest before resuming. */
    bool wait_release;
} mg_fsm_t;

void mg_init(mg_fsm_t *fsm);
void mg_step(mg_fsm_t *fsm, mg_event_t event);
void mg_tick(mg_fsm_t *fsm, float dt_seconds);
bool mg_load_menu(mg_fsm_t *fsm, const mg_menu_t *menu);

mg_grip_t mg_selected_grip(const mg_fsm_t *fsm);
const char *mg_grip_name(mg_grip_t grip);

const char *mg_state_name(mg_state_t state);
const char *mg_event_name(mg_event_t event);

#endif