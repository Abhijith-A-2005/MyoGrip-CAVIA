#include "myogrip_selftest.h"

#if MYOGRIP_SELFTEST_ENABLED

#include "myogrip_fsm.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "MYOGRIP_TEST";

typedef struct {
    mg_event_t event;
    mg_state_t expected_state;
    unsigned expected_selected;
    bool expected_gate;
} test_case_t;

/* Each row checks state, selection and release guard. */
static const test_case_t tests[] = {
    {MG_LF,          MG_HOME,     0, false},
    {MG_MENU_READY,  MG_ADAPTIVE, 0, false},

    /* Adaptive menu wraparound and normal navigation. */
    {MG_SE,          MG_ADAPTIVE, 2, false},
    {MG_SF,          MG_ADAPTIVE, 0, false},
    {MG_SF,          MG_ADAPTIVE, 1, false},
    {MG_REST,        MG_ADAPTIVE, 1, false},
    {MG_INVALID,     MG_ADAPTIVE, 1, false},

    /* Confirm, then continue into closing without release. */
    {MG_LF,          MG_HOLDING,  1, false},
    {MG_FLEX_ACTIVE, MG_CLOSING,  1, false},
    {MG_REST,        MG_HOLDING,  1, false},

    /* Simulated actuation states. */
    {MG_FLEX_ACTIVE, MG_CLOSING,  1, false},
    {MG_REST,        MG_HOLDING,  1, false},
    {MG_EXT_ACTIVE,  MG_OPENING,  1, false},
    {MG_REST,        MG_HOLDING,  1, false},

    /* Invalid activity must not leave closing active. */
    {MG_FLEX_ACTIVE, MG_CLOSING,  1, false},
    {MG_INVALID,     MG_HOLDING,  1, true},
    {MG_FLEX_ACTIVE, MG_HOLDING,  1, true},
    {MG_REST,        MG_HOLDING,  1, false},

    /* Full menu wraparound and ignored inputs. */
    {MG_HE,          MG_FULL,     0, false},
    {MG_SE,          MG_FULL,     3, false},
    {MG_SF,          MG_FULL,     0, false},
    {MG_LE,          MG_FULL,     0, false},
    {MG_REST,        MG_FULL,     0, false},

    /* Confirmation from Full Menu. */
    {MG_LF,          MG_HOLDING,  0, false},
    {MG_REST,        MG_HOLDING,  0, false},
    {MG_EXT_ACTIVE,  MG_OPENING,  0, false},
    {MG_HE,          MG_FULL,     0, false},
    {MG_HE,          MG_HOME,     0, false},

    /* Remaining navigation paths. */
    {MG_MENU_READY,  MG_ADAPTIVE, 0, false},
    {MG_LE,          MG_FULL,     0, false},
    {MG_HE,          MG_HOME,     0, false},
    {MG_MENU_READY,  MG_ADAPTIVE, 0, false},
    {MG_HE,          MG_HOME,     0, false}
};

static bool menu_snapshot_selftest(void)
{
    mg_fsm_t f;
    mg_menu_t menu = {
        .menu_id = 42,
        .adaptive = {MG_GRIP_LATERAL},
        .adaptive_count = 1,
        .full = {MG_GRIP_POWER, MG_GRIP_PINCH,
                 MG_GRIP_TRIPOD, MG_GRIP_LATERAL},
        .full_count = 4,
        .full_menu_only = false
    };

    mg_init(&f);
    bool ok = mg_load_menu(&f, &menu);
    ok &= f.state == MG_ADAPTIVE && f.active_grip == MG_GRIP_NONE;
    ok &= mg_selected_grip(&f) == MG_GRIP_LATERAL;

    // Changing the caller's buffer must not change the frozen snapshot.
    menu.menu_id = 43;
    menu.adaptive[0] = MG_GRIP_PINCH;
    ok &= mg_selected_grip(&f) == MG_GRIP_LATERAL;
    ok &= !mg_load_menu(&f, &menu) && f.menu.menu_id == 42;

    mg_step(&f, MG_SF);
    ok &= f.selected == 0;  // One item still requires LF to confirm.
    mg_step(&f, MG_LF);
    ok &= f.state == MG_HOLDING && f.active_grip == MG_GRIP_LATERAL;
    ok &= !mg_load_menu(&f, &menu);

    mg_init(&f);
    menu.full_menu_only = true;
    ok &= mg_load_menu(&f, &menu) && f.state == MG_FULL;
    ok &= mg_selected_grip(&f) == MG_GRIP_POWER;

    mg_init(&f);
    menu.full_menu_only = false;
    menu.adaptive_count = 0;
    ok &= mg_load_menu(&f, &menu) && f.state == MG_FULL;

    mg_init(&f);
    menu.full[1] = menu.full[0];  // Duplicate grip: reject atomically.
    ok &= !mg_load_menu(&f, &menu);
    ok &= f.state == MG_HOME && !f.menu_loaded;

    return ok;
}

static void selftest_task(void *arg)
{
    (void)arg;

    const unsigned total = sizeof(tests) / sizeof(tests[0]);
    unsigned cycle = 0;

    /* Allow normal firmware startup to finish. */
    vTaskDelay(pdMS_TO_TICKS(3000));

    while (1) {
        mg_fsm_t fsm;
        mg_init(&fsm);

        unsigned passed = 0;
        cycle++;

        ESP_LOGI(TAG, "SIMULATION ONLY: cycle %u", cycle);
        bool menu_ok = menu_snapshot_selftest();
        ESP_LOGI(TAG, "MENU SNAPSHOTS: %s", menu_ok ? "PASS" : "FAIL");

        for (unsigned i = 0; i < total; i++) {
            const test_case_t *t = &tests[i];
            mg_state_t before = fsm.state;

            mg_step(&fsm, t->event);

            mg_grip_t grip = mg_selected_grip(&fsm);
            bool grip_ok;

            if (fsm.state == MG_HOME) {
                grip_ok = grip == MG_GRIP_NONE &&
                          fsm.active_grip == MG_GRIP_NONE;
            } else if (fsm.state == MG_ADAPTIVE || fsm.state == MG_FULL) {
                grip_ok = grip != MG_GRIP_NONE &&
                          fsm.active_grip == MG_GRIP_NONE;
            } else {
                grip_ok = grip != MG_GRIP_NONE &&
                          grip == fsm.active_grip;
            }

            bool ok =
                fsm.state == t->expected_state &&
                fsm.selected == t->expected_selected &&
                fsm.wait_release == t->expected_gate &&
                grip_ok;

            ESP_LOGI(
                TAG,
                "%02u %s: %s + %s -> %s, index=%u, gate=%u, grip=%s",
                i + 1,
                ok ? "PASS" : "FAIL",
                mg_state_name(before),
                mg_event_name(t->event),
                mg_state_name(fsm.state),
                (unsigned)fsm.selected,
                (unsigned)fsm.wait_release,
                mg_grip_name(grip)
            );

            if (ok) {
                passed++;
            } else {
                ESP_LOGE(
                    TAG,
                    "Expected state=%s index=%u gate=%u",
                    mg_state_name(t->expected_state),
                    t->expected_selected,
                    (unsigned)t->expected_gate
                );
            }

            /* Yield CPU time to acquisition and Bluetooth tasks. */
            vTaskDelay(pdMS_TO_TICKS(1000));
        }

         if (passed == total && menu_ok) {
            ESP_LOGI(TAG, "RESULT: %u/%u PASS; menu snapshots PASS",
                     passed, total);
        } else {
            ESP_LOGE(TAG,
                     "RESULT: %u/%u state checks passed; menu snapshots %s",
                     passed, total, menu_ok ? "PASS" : "FAIL");
        }

        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

void myogrip_selftest_start(void)
{
    BaseType_t result = xTaskCreate(
        selftest_task,
        "myogrip_test",
        4096,
        NULL,
        3,
        NULL
    );

    if (result != pdPASS) {
        ESP_LOGE(TAG, "Failed to create self-test task");
    }
}

#else

void myogrip_selftest_start(void)
{
    /* Test mode disabled. */
}

#endif