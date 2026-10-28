#include "myogrip_live.h"
#include "emg_config.h"

#include <string.h>

void myogrip_live_gap(myogrip_live_t *live)
{
    /* Reset is appropriate here only because this build has no motor output. */
    live->revision++;
    mg_init(&live->fsm);
    live->calibrated = false;
    live->armed = false;
    live->rest_samples = 0;
    live->last_gesture = EMG_GESTURE_NONE;
    live->activity = "UNCALIBRATED";
    live->gesture_source = "device";
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
        (!live->armed || live->rest_samples >= EMG_EPISODE_REST_SAMPLES) &&
        !f->returning && f->grip_progress == 0.0f &&
        f->active_grip == MG_GRIP_NONE;
}

bool myogrip_live_menu_ready_shared(const myogrip_live_t *live,
                                    const mg_keyboard_t *keys)
{
    return myogrip_live_menu_ready(live) &&
        (keys == NULL || (!keys->mask && keys->pending == MG_KEY_EVENT_NONE));
}

bool myogrip_live_load_menu(myogrip_live_t *live, const mg_menu_t *menu,
                            uint32_t expected_revision, bool preserve_selection)
{
    if (!myogrip_live_menu_ready(live) || menu == NULL ||
        expected_revision != live->revision) return false;

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
    live->revision++;
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
    if (live->fsm.menu_loaded) live->revision++;
    return live->fsm.menu_loaded;
}

static emg_gesture_t keyboard_gesture(mg_key_event_t event)
{
    switch (event) {
    case MG_KEY_EVENT_PREVIOUS: return EMG_GESTURE_SE;
    case MG_KEY_EVENT_NEXT: return EMG_GESTURE_SF;
    case MG_KEY_EVENT_CONFIRM: return EMG_GESTURE_LF;
    case MG_KEY_EVENT_FULL: return EMG_GESTURE_LE;
    case MG_KEY_EVENT_HOME: return EMG_GESTURE_HE;
    case MG_KEY_EVENT_INVALID: return EMG_GESTURE_REJECTED;
    default: return EMG_GESTURE_NONE;
    }
}

void myogrip_live_sample_shared(myogrip_live_t *live, mg_keyboard_t *keys,
                                uint64_t now_ms, const char *activity,
                                emg_gesture_t gesture)
{
    live->samples++;
    mg_keyboard_expire(keys, now_ms);

    mg_event_t input = MG_REST;
    bool calibrated = true;
    if (activity != NULL && strcmp(activity, "REST") == 0) input = MG_REST;
    else if (activity != NULL && strcmp(activity, "FLEX_ACTIVE") == 0) input = MG_FLEX_ACTIVE;
    else if (activity != NULL && strcmp(activity, "EXT_ACTIVE") == 0) input = MG_EXT_ACTIVE;
    else if (activity != NULL && strcmp(activity, "INVALID") == 0) input = MG_INVALID;
    else calibrated = false;

    if (!calibrated) {
        if (keys == NULL || keys->session == 0) {
            myogrip_live_gap(live);
            return;
        }
        /* Missing EMG calibration does not erase a keyboard-driven menu. */
        live->armed = false;
        live->rest_samples = 0;
    }
    live->calibrated = calibrated;
    if (calibrated && input == MG_REST) {
        if (live->rest_samples < EMG_EPISODE_REST_SAMPLES) live->rest_samples++;
    } else {
        live->rest_samples = 0;
    }

    live->activity = mg_event_name(input);
    if (!live->armed) {
        live->armed = calibrated && live->rest_samples >= EMG_EPISODE_REST_SAMPLES;
        /* Preserve EMG's sustained-rest arming requirement. */
        input = MG_REST;
        gesture = EMG_GESTURE_NONE;
        if (keys == NULL || keys->session == 0) return;
    }

    mg_key_event_t event = mg_keyboard_take_event(keys);
    emg_gesture_t key_gesture = keyboard_gesture(event);
    uint8_t mask = keys != NULL && keys->connected ? keys->mask : 0;
    mg_event_t key_input = (mask & MG_KEY_A) && (mask & MG_KEY_D) ? MG_INVALID :
        mask & MG_KEY_A ? MG_FLEX_ACTIVE : mask & MG_KEY_D ? MG_EXT_ACTIVE : MG_REST;
    bool conflicting = input == MG_INVALID || key_input == MG_INVALID ||
        event == MG_KEY_EVENT_INVALID ||
        (input == MG_FLEX_ACTIVE && key_input == MG_EXT_ACTIVE) ||
        (input == MG_EXT_ACTIVE && key_input == MG_FLEX_ACTIVE);
    if (conflicting) input = MG_INVALID;
    else if (input == MG_REST) input = key_input;

    bool emg_event = gesture != EMG_GESTURE_NONE;
    bool key_event = key_gesture != EMG_GESTURE_NONE;
    if (gesture == EMG_GESTURE_HE || key_gesture == EMG_GESTURE_HE) {
        gesture = EMG_GESTURE_HE;
    } else if (conflicting || (emg_event && key_event && gesture != key_gesture)) {
        if (emg_event || key_event) gesture = EMG_GESTURE_REJECTED;
        input = MG_INVALID;
    } else if (key_event) {
        gesture = key_gesture;
    }
    live->activity = mg_event_name(input);
    if (gesture != EMG_GESTURE_NONE) {
        live->last_gesture = gesture;
        live->gesture_source = emg_event && key_event ? "both" :
            key_event ? "keyboard" : "device";
        live->gesture_seq++;
    }

    mg_state_t state_before = live->fsm.state;
    uint8_t selected_before = live->fsm.selected;
    bool returning_before = live->fsm.returning;
    if (!live->fsm.returning) {
        switch (gesture) {
        case EMG_GESTURE_SF: mg_step(&live->fsm, MG_SF); break;
        case EMG_GESTURE_SE: mg_step(&live->fsm, MG_SE); break;
        case EMG_GESTURE_LF: mg_step(&live->fsm, MG_LF); break;
        case EMG_GESTURE_LE: mg_step(&live->fsm, MG_LE); break;
        case EMG_GESTURE_HE: mg_step(&live->fsm, MG_HE); break;
        default: break;
        }
        mg_step(&live->fsm, input);
    }

    /* Matching EMG and keyboard directions still produce only one tick. */
    mg_tick(&live->fsm, 1.0f / EMG_SAMPLE_RATE_HZ);
    if (state_before != live->fsm.state || selected_before != live->fsm.selected ||
        returning_before != live->fsm.returning) live->revision++;
}

void myogrip_live_sample(myogrip_live_t *live, const char *activity,
                         emg_gesture_t gesture)
{
    myogrip_live_sample_shared(live, NULL, 0, activity, gesture);
}
