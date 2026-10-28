#ifndef MYOGRIP_WIRE_H
#define MYOGRIP_WIRE_H
#include "myogrip_fsm.h"
typedef struct {
    char code;
    uint32_t boot;
    uint32_t revision;
    uint32_t session;
    uint32_t sequence;
    uint8_t key_mask;
    bool preserve_selection;
    mg_menu_t menu;
} mg_command_t;
bool mg_parse_menu_line(const char *line, mg_command_t *command);
bool mg_parse_keyboard_line(const char *line, mg_command_t *command);
#endif
