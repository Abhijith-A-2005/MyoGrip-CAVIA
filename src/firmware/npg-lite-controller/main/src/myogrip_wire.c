#include "myogrip_wire.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static bool read_word(const char **cursor, uint32_t *out)
{
    const char *p = *cursor;
    if (*p != ' ') return false;
    while (*p == ' ') p++;
    if (*p < '0' || *p > '9') return false;
    uint32_t value = 0;
    do {
        unsigned digit = (unsigned)(*p++ - '0');
        if (value > (UINT32_MAX - digit) / 10) return false;
        value = value * 10 + digit;
    } while (*p >= '0' && *p <= '9');
    *out = value;
    *cursor = p;
    return true;
}

/* K boot session sequence held_mask. A new session must begin with mask 0. */
bool mg_parse_keyboard_line(const char *line, mg_command_t *out)
{
    if (line == NULL || out == NULL || *line++ != 'K') return false;
    uint32_t words[4];
    for (unsigned i = 0; i < 4; i++)
        if (!read_word(&line, &words[i])) return false;
    if (*line || !words[1] || !words[2] || words[3] > 31) return false;
    mg_command_t command = {0};
    command.code = 'K';
    command.boot = words[0];
    command.session = words[1];
    command.sequence = words[2];
    command.key_mask = (uint8_t)words[3];
    *out = command;
    return true;
}

/* @ boot revision menu_id flags adaptive_count a0 a1 a2 a3 full_count f0 f1 f2 f3 */
bool mg_parse_menu_line(const char *line, mg_command_t *out)
{
    if (line == NULL || out == NULL || *line++ != '@') return false;
    uint32_t words[14];
    for (unsigned i = 0; i < 14; i++) {
        if (*line != ' ') return false;
        while (*line == ' ') line++;
        if (*line < '0' || *line > '9') return false;
        uint32_t value = 0;
        do {
            unsigned digit = (unsigned)(*line++ - '0');
            if (value > (UINT32_MAX - digit) / 10) return false;
            value = value * 10 + digit;
        } while (*line >= '0' && *line <= '9');
        words[i] = value;
    }
    if (*line != '\0' || words[2] == 0 || words[3] > 3 ||
        words[4] > 4 || words[9] == 0 || words[9] > 4) return false;
    mg_command_t command = {0};
    command.code = '@';
    command.boot = words[0];
    command.revision = words[1];
    command.menu.menu_id = words[2];
    command.menu.full_menu_only = (words[3] & 1) != 0;
    command.preserve_selection = (words[3] & 2) != 0;
    command.menu.adaptive_count = words[4];
    command.menu.full_count = words[9];
    for (unsigned i = 0; i < 4; i++) {
        if (words[5+i] > 4 || words[10+i] > 4) return false;
        command.menu.adaptive[i] = (mg_grip_t)words[5+i];
        command.menu.full[i] = (mg_grip_t)words[10+i];
    }
    *out = command;
    return true;
}
