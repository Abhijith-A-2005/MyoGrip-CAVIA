/* Host-only parser checkpoint. */
#include <assert.h>
#include <stdio.h>
#include "myogrip_wire.h"

int main(void)
{
    mg_command_t command = {0};
    assert(mg_parse_menu_line("@ 123 7 42 0 2 4 2 0 0 4 1 2 3 4", &command));
    assert(command.boot == 123 && command.revision == 7 && command.menu.menu_id == 42);
    assert(command.menu.adaptive_count == 2 && command.menu.adaptive[0] == MG_GRIP_LATERAL);
    assert(command.menu.full_count == 4 && command.menu.full[0] == MG_GRIP_POWER);
    const char *bad[] = {
        "@", "@ -1", "@ 99999999999999999999999999",
        "@ 123 7 0 0 2 4 2 0 0 4 1 2 3 4",
        "@ 123 7 42 0 5 4 2 0 0 4 1 2 3 4",
        "@ 123 7 42 0 2 4 2 0 0 0 1 2 3 4",
        "@ 123 7 42 0 2 4 2 0 0 4 1 2 3 4 extra"
    };
    for (unsigned i=0; i<sizeof(bad)/sizeof(bad[0]); i++) {
        command.code = '?';
        assert(!mg_parse_menu_line(bad[i], &command));
        assert(command.code == '?');
    }
    puts("PASS: bounded menu parser and atomic rejection");
}
