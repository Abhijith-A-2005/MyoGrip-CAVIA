#ifndef MYOGRIP_KEYBOARD_H
#define MYOGRIP_KEYBOARD_H

#include <stdbool.h>
#include <stdint.h>

#define MG_KEYBOARD_LEASE_MS 400u
#define MG_KEY_W 1u
#define MG_KEY_A 2u
#define MG_KEY_S 4u
#define MG_KEY_D 8u
#define MG_KEY_E 16u

typedef enum {
    MG_KEY_EVENT_NONE,
    MG_KEY_EVENT_PREVIOUS,
    MG_KEY_EVENT_NEXT,
    MG_KEY_EVENT_CONFIRM,
    MG_KEY_EVENT_FULL,
    MG_KEY_EVENT_HOME,
    MG_KEY_EVENT_INVALID
} mg_key_event_t;

typedef struct {
    uint32_t session;
    uint32_t sequence;
    uint64_t received_ms;
    uint8_t mask;
    bool connected;
    mg_key_event_t pending;
} mg_keyboard_t;

void mg_keyboard_init(mg_keyboard_t *keys);
void mg_keyboard_invalidate(mg_keyboard_t *keys);
mg_key_event_t mg_keyboard_take_event(mg_keyboard_t *keys);
void mg_keyboard_expire(mg_keyboard_t *keys, uint64_t now_ms);
bool mg_keyboard_receive(mg_keyboard_t *keys, uint32_t session,
                         uint32_t sequence, uint8_t mask, uint64_t now_ms);

#endif
