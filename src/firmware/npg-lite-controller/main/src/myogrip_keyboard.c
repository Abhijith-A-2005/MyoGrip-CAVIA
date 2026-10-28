#include "myogrip_keyboard.h"
#include <stddef.h>
#include <string.h>

void mg_keyboard_init(mg_keyboard_t *keys)
{
    memset(keys, 0, sizeof(*keys));
}

void mg_keyboard_invalidate(mg_keyboard_t *keys)
{
    if (keys == NULL) return;
    keys->mask = 0;
    keys->connected = false;
    keys->pending = MG_KEY_EVENT_NONE;
}

mg_key_event_t mg_keyboard_take_event(mg_keyboard_t *keys)
{
    if (keys == NULL) return MG_KEY_EVENT_NONE;
    mg_key_event_t event = keys->pending;
    keys->pending = MG_KEY_EVENT_NONE;
    return event;
}

void mg_keyboard_expire(mg_keyboard_t *keys, uint64_t now_ms)
{
    if (keys == NULL || !keys->connected) return;
    if (now_ms < keys->received_ms ||
        now_ms - keys->received_ms >= MG_KEYBOARD_LEASE_MS) {
        mg_keyboard_invalidate(keys);
    }
}

bool mg_keyboard_receive(mg_keyboard_t *keys, uint32_t session,
                         uint32_t sequence, uint8_t mask, uint64_t now_ms)
{
    if (keys == NULL) return false;
    mg_keyboard_expire(keys, now_ms);
    if (!session || !sequence || mask > 31 || now_ms < keys->received_ms)
        return false;

    if (session != keys->session) {
        /* New sessions increase within a boot and always begin released. */
        if (session <= keys->session || sequence != 1 || mask != 0) return false;
    } else {
        if (sequence <= keys->sequence) return false;
        /* A timeout requires a fresh release before another held key. */
        if (!keys->connected && mask != 0) return false;
    }

    if (session != keys->session) {
        keys->pending = MG_KEY_EVENT_NONE;
    }
    uint8_t added = mask & (uint8_t)~keys->mask;
    mg_key_event_t event = MG_KEY_EVENT_NONE;
    if (added & MG_KEY_E) {
        event = MG_KEY_EVENT_HOME;
    } else if (added) {
        if (keys->mask || (added & (added - 1))) event = MG_KEY_EVENT_INVALID;
        else if (added & MG_KEY_W) event = MG_KEY_EVENT_PREVIOUS;
        else if (added & MG_KEY_S) event = MG_KEY_EVENT_NEXT;
        else if (added & MG_KEY_A) event = MG_KEY_EVENT_CONFIRM;
        else if (added & MG_KEY_D) event = MG_KEY_EVENT_FULL;
    }
    /* Preserve short taps through release; HE takes priority over other taps. */
    if (event == MG_KEY_EVENT_HOME) keys->pending = event;
    else if (event != MG_KEY_EVENT_NONE && keys->pending != MG_KEY_EVENT_HOME) {
        keys->pending = keys->pending == MG_KEY_EVENT_NONE
            ? event : MG_KEY_EVENT_INVALID;
    }

    keys->session = session;
    keys->sequence = sequence;
    keys->received_ms = now_ms;
    keys->mask = mask;
    keys->connected = true;
    return true;
}
