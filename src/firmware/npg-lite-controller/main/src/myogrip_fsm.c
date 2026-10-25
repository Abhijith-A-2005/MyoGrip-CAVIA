#include "myogrip_fsm.h"
#include <stddef.h>
#include <string.h>
#include <math.h>

/* MG_MENU_READY remains a development shortcut for the old selftest. */
static const mg_menu_t demo_menu = {
    .menu_id = 1,
    .adaptive = {MG_GRIP_POWER, MG_GRIP_LATERAL, MG_GRIP_PINCH},
    .adaptive_count = MG_ADAPTIVE_COUNT,
    .full = {MG_GRIP_POWER, MG_GRIP_PINCH, MG_GRIP_TRIPOD, MG_GRIP_LATERAL},
    .full_count = MG_FULL_COUNT,
    .full_menu_only = false
};

static bool valid_grips(const mg_grip_t *items, unsigned count)
{
    for (unsigned i = 0; i < count; i++) {
        if (items[i] < MG_GRIP_POWER || items[i] > MG_GRIP_LATERAL) {
            return false;
        }

        for (unsigned j = 0; j < i; j++) {
            if (items[i] == items[j]) {
                return false;
            }
        }
    }

    return true;
}

bool mg_load_menu(mg_fsm_t *f, const mg_menu_t *menu)
{
    if (f == NULL || menu == NULL || f->state != MG_HOME) {
        return false;
    }

    if (menu->adaptive_count > MG_MENU_CAPACITY ||
        menu->full_count == 0 || menu->full_count > MG_MENU_CAPACITY) {
        return false;
    }

    if (!valid_grips(menu->adaptive, menu->adaptive_count) ||
        !valid_grips(menu->full, menu->full_count)) {
        return false;
    }

    // Every adaptive choice must belong to the calibrated full list.
    for (unsigned i = 0; i < menu->adaptive_count; i++) {
        bool found = false;

        for (unsigned j = 0; j < menu->full_count; j++) {
            if (menu->adaptive[i] == menu->full[j]) {
                found = true;
                break;
            }
        }

        if (!found) {
            return false;
        }
    }

    // Copy only after every validation check succeeds.
    f->menu = *menu;
    f->menu_loaded = true;
    f->selected = 0;
    f->active_grip = MG_GRIP_NONE;
    f->wait_release = false;

    f->state = menu->full_menu_only || menu->adaptive_count == 0
        ? MG_FULL : MG_ADAPTIVE;

    return true;
}

mg_grip_t mg_selected_grip(const mg_fsm_t *f)
{
    if (f == NULL || !f->menu_loaded) {
        return MG_GRIP_NONE;
    }

    if (f->state == MG_ADAPTIVE && f->selected < f->menu.adaptive_count) {
        return f->menu.adaptive[f->selected];
    }

    if (f->state == MG_FULL && f->selected < f->menu.full_count) {
        return f->menu.full[f->selected];
    }

    if (f->state == MG_HOLDING || f->state == MG_CLOSING ||
        f->state == MG_OPENING) {
        return f->active_grip;
    }

    return MG_GRIP_NONE;
}

const char *mg_grip_name(mg_grip_t grip)
{
    switch (grip) {
    case MG_GRIP_POWER:   return "POWER";
    case MG_GRIP_PINCH:   return "PINCH";
    case MG_GRIP_TRIPOD:  return "TRIPOD";
    case MG_GRIP_LATERAL: return "LATERAL";
    default:             return "NONE";
    }
}

void mg_init(mg_fsm_t *f)
{
    memset(f, 0, sizeof(*f));
    f->state = MG_HOME;
    f->active_grip = MG_GRIP_NONE;
}

void mg_step(mg_fsm_t *f, mg_event_t event)
{
    /* HOME: gestures cannot confirm anything without a menu. */
    if (f->state == MG_HOME) {
        if (event == MG_MENU_READY) {
            (void)mg_load_menu(f, &demo_menu);
        }
        return;
    }

    /* MENU NAVIGATION */
    if (f->state == MG_ADAPTIVE || f->state == MG_FULL) {
        unsigned count = f->state == MG_ADAPTIVE
                             ? f->menu.adaptive_count
                             : f->menu.full_count;

        if (count == 0) {
            return;
        }

        switch (event) {
        case MG_SF:
            f->selected = (f->selected + 1) % count;
            break;

        case MG_SE:
            f->selected = (f->selected + count - 1) % count;
            break;

        case MG_LF:
            /* D16: continued confirming flexion may close immediately. */
            f->active_grip = mg_selected_grip(f);
            f->state = MG_HOLDING;
            f->wait_release = false;
            break;

        case MG_LE:
            if (f->state == MG_ADAPTIVE) {
                f->state = MG_FULL;
                f->selected = 0;
            }
            break;

        case MG_HE:
            mg_init(f);
            break;

        default:
            /* Rest, invalid input and unrelated events do nothing. */
            break;
        }
        return;
    }

    /*
     * SIMULATED ACTUATION
     * These state changes do not generate any motor output.
     */
    if (event == MG_HE) {
        f->active_grip = MG_GRIP_NONE;
        f->state = MG_FULL;
        f->selected = 0;
        f->wait_release = false;
        return;
    }

    if (event == MG_REST) {
        f->state = MG_HOLDING;
        f->wait_release = false;
        return;
    }

    if (event == MG_INVALID) {
        /*
         * Proposed guard: stop simulated movement and require rest
         * before accepting activity again.
         */
        f->state = MG_HOLDING;
        f->wait_release = true;
        return;
    }

    if (f->wait_release) {
        return;
    }

    if (event == MG_FLEX_ACTIVE) {
        f->state = MG_CLOSING;
    } else if (event == MG_EXT_ACTIVE) {
        f->state = MG_OPENING;
    }
}

void mg_tick(mg_fsm_t *f, float dt_seconds)
{
    if (f == NULL || !isfinite(dt_seconds) || dt_seconds <= 0.0f) {
        return;
    }

    if (f->state == MG_CLOSING) {
        float next = f->grip_progress + MG_CLOSE_SPEED_PER_S * dt_seconds;
        f->grip_progress = next > 1.0f ? 1.0f : next;
    } else if (f->state == MG_OPENING) {
        float next = f->grip_progress - MG_OPEN_SPEED_PER_S * dt_seconds;
        f->grip_progress = next < 0.0f ? 0.0f : next;
    }
}

const char *mg_state_name(mg_state_t state)
{
    switch (state) {
    case MG_HOME:     return "HOME";
    case MG_ADAPTIVE: return "ADAPTIVE";
    case MG_FULL:     return "FULL";
    case MG_HOLDING:  return "HOLDING";
    case MG_CLOSING:  return "CLOSING";
    case MG_OPENING:  return "OPENING";
    default:         return "UNKNOWN";
    }
}

const char *mg_event_name(mg_event_t event)
{
    switch (event) {
    case MG_MENU_READY:  return "MENU_READY";
    case MG_SF:          return "SF";
    case MG_SE:          return "SE";
    case MG_LF:          return "LF";
    case MG_LE:          return "LE";
    case MG_HE:          return "HE";
    case MG_REST:        return "REST";
    case MG_FLEX_ACTIVE: return "FLEX_ACTIVE";
    case MG_EXT_ACTIVE:  return "EXT_ACTIVE";
    case MG_INVALID:     return "INVALID";
    default:             return "UNKNOWN";
    }
}