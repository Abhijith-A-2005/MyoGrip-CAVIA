#ifndef GAP_H
#define GAP_H

/* Includes */
/* NimBLE GAP APIs */
#include "host/ble_gap.h"
#include "services/gap/ble_svc_gap.h"
#include <stdbool.h>
#include <stdint.h>

extern bool streaming;
extern uint16_t conn_handle;
extern uint16_t data_char_handle;
extern uint16_t control_char_handle;

/* Public function declarations */
void adv_init(void);
int gap_init(void);

#endif // GAP_H
