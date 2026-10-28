#include "myogrip_live.h"
#include "emg_config.h"

#include <string.h>

void myogrip_live_gap(myogrip_live_t *live)
{
    /* Reset is appropriate here only because this build has no motor output. */
    mg_init(&live->fsm);
    live->calibrated = false;
    live->armed = false;
    live->rest_samples = 0;
    live->last_gesture = EMG_GESTURE_NONE;
    live->activity = "UNCALIBRATED";
}

void myogrip_live_init(myogrip_live_t *live)
{
    memset(live, 0, sizeof(*live));
    myogrip_live_gap(live);
}

bool myogrip_live_menu_ready(const myogrip_live_t *live)
{
    if (live == NULL) return false;
    const mg_fsm_t *f = &live->fsm;
    return (f->state == MG_HOME || f->state == MG_ADAPTIVE ||
            f->state == MG_FULL) &&
        !f->returning && f->grip_progress == 0.0f &&
        f->active_grip == MG_GRIP_NONE;
}

bool myogrip_live_load_menu(myogrip_live_t *live, const mg_menu_t *menu,
                            bool preserve_selection)
{
    if (!myogrip_live_menu_ready(live) || menu == NULL) return false;

    /* Validate separately so rejection cannot alter the current menu. */
    mg_fsm_t next;
    mg_init(&next);
    mg_menu_t proposal = *menu;
    if (live->fsm.state == MG_FULL) proposal.full_menu_only = true;
    if (!mg_load_menu(&next, &proposal)) return false;

    if (preserve_selection) {
        mg_grip_t selected = mg_selected_grip(&live->fsm);
        const mg_grip_t *items = next.state == MG_FULL
            ? next.menu.full : next.menu.adaptive;
        unsigned count = next.state == MG_FULL
            ? next.menu.full_count : next.menu.adaptive_count;
        for (unsigned i = 0; i < count; i++) {
            if (items[i] == selected) {
                next.selected = i;
                break;
            }
        }
    }

    live->fsm = next;
    return true;
}

bool myogrip_live_demo_menu(myogrip_live_t *live)
{
    /* Require a validated calibration and current sustained rest. */
    if (!live->calibrated || !live->armed ||
        live->rest_samples < EMG_EPISODE_REST_SAMPLES ||
        live->fsm.state != MG_HOME) {
        return false;
    }
    mg_step(&live->fsm, MG_MENU_READY);
    return live->fsm.menu_loaded;
}

void myogrip_live_sample(myogrip_live_t *live, const char *activity,
                         emg_gesture_t gesture)
{
    live->samples++;

    mg_event_t input;
    if (activity != NULL && strcmp(activity, "REST") == 0) {
        input = MG_REST;
    } else if (activity != NULL && strcmp(activity, "FLEX_ACTIVE") == 0) {
        input = MG_FLEX_ACTIVE;
    } else if (activity != NULL && strcmp(activity, "EXT_ACTIVE") == 0) {
        input = MG_EXT_ACTIVE;
    } else if (activity != NULL && strcmp(activity, "INVALID") == 0) {
        input = MG_INVALID;
    } else {
        /* WARMUP, missing calibration or unknown input cannot drive the FSM. */
        myogrip_live_gap(live);
        return;
    }

    live->activity = mg_event_name(input);  /* Store a stable string literal. */
    live->calibrated = true;
    if (input == MG_REST) {
        if (live->rest_samples < EMG_EPISODE_REST_SAMPLES) {
            live->rest_samples++;
        }
    } else {
        live->rest_samples = 0;
    }

    if (!live->armed) {
        live->armed = live->rest_samples >= EMG_EPISODE_REST_SAMPLES;
        return;
    }

    if (gesture != EMG_GESTURE_NONE) {
        live->last_gesture = gesture;
        live->gesture_seq++;
    }

    /* Ignore input throughout HE return, including its completion sample. */
    if (!live->fsm.returning) {
        switch (gesture) {
        case EMG_GESTURE_SF: mg_step(&live->fsm, MG_SF); break;
        case EMG_GESTURE_SE: mg_step(&live->fsm, MG_SE); break;
        case EMG_GESTURE_LF: mg_step(&live->fsm, MG_LF); break;
        case EMG_GESTURE_LE: mg_step(&live->fsm, MG_LE); break;
        case EMG_GESTURE_HE: mg_step(&live->fsm, MG_HE); break;
        default:
            /* REJECTED describes a gesture; activity still controls movement. */
            break;
        }

        /* LF confirms first, so the same sustained flexion can start closing. */
        mg_step(&live->fsm, input);
    }

    /* Advance by acquisition time, never by log rate or GUI frame rate. */
    mg_tick(&live->fsm, 1.0f / EMG_SAMPLE_RATE_HZ);
}
