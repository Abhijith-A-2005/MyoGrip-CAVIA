#include "myogrip_fsm.h"

void mg_init(mg_fsm_t *f)
{
    f->state = MG_HOME;
    f->selected = 0;
    f->wait_release = false;
}

void mg_step(mg_fsm_t *f, mg_event_t event)
{
    /* HOME: gestures cannot confirm anything without a menu. */
    if (f->state == MG_HOME) {
        if (event == MG_MENU_READY) {
            f->state = MG_ADAPTIVE;
            f->selected = 0;
            f->wait_release = false;
        }
        return;
    }

    /* MENU NAVIGATION */
    if (f->state == MG_ADAPTIVE || f->state == MG_FULL) {
        unsigned count = f->state == MG_ADAPTIVE
                             ? MG_ADAPTIVE_COUNT
                             : MG_FULL_COUNT;

        switch (event) {
        case MG_SF:
            f->selected = (f->selected + 1) % count;
            break;

        case MG_SE:
            f->selected = (f->selected + count - 1) % count;
            break;

        case MG_LF:
            /*
             * Confirm selection, but require rest before accepting
             * continuous flexor/extensor activity.
             */
            f->state = MG_HOLDING;
            f->wait_release = true;
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