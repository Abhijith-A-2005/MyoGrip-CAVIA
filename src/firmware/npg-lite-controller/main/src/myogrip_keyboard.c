#include "myogrip_keyboard.h"
#include <stddef.h>
#include <string.h>

void mg_keyboard_init(mg_keyboard_t *keys)
{
    memset(keys, 0, sizeof(*keys));
}

void mg_keyboard_expire(mg_keyboard_t *keys, uint64_t now_ms)
{
    if (keys == NULL || !keys->connected) return;
    if (now_ms < keys->received_ms ||
        now_ms - keys->received_ms >= MG_KEYBOARD_LEASE_MS) {
        keys->mask = 0;
        keys->connected = false;
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

    keys->session = session;
    keys->sequence = sequence;
    keys->received_ms = now_ms;
    keys->mask = mask;
    keys->connected = true;
    return true;
}
