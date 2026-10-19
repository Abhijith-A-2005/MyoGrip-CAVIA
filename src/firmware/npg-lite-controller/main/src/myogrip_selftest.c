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

    /* Confirm, then verify that closing requires release. */
    {MG_LF,          MG_HOLDING,  1, true},
    {MG_FLEX_ACTIVE, MG_HOLDING,  1, true},
    {MG_REST,        MG_HOLDING,  1, false},

    /* Simulated proportional-control states. */
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
    {MG_SE,          MG_FULL,     4, false},
    {MG_SF,          MG_FULL,     0, false},
    {MG_LE,          MG_FULL,     0, false},
    {MG_REST,        MG_FULL,     0, false},

    /* Confirmation from Full Menu. */
    {MG_LF,          MG_HOLDING,  0, true},
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

        for (unsigned i = 0; i < total; i++) {
            const test_case_t *t = &tests[i];
            mg_state_t before = fsm.state;

            mg_step(&fsm, t->event);

            bool ok =
                fsm.state == t->expected_state &&
                fsm.selected == t->expected_selected &&
                fsm.wait_release == t->expected_gate;

            ESP_LOGI(
                TAG,
                "%02u %s: %s + %s -> %s, index=%u, gate=%u",
                i + 1,
                ok ? "PASS" : "FAIL",
                mg_state_name(before),
                mg_event_name(t->event),
                mg_state_name(fsm.state),
                (unsigned)fsm.selected,
                (unsigned)fsm.wait_release
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

        if (passed == total) {
            ESP_LOGI(TAG, "RESULT: %u/%u PASS", passed, total);
        } else {
            ESP_LOGE(TAG, "RESULT: %u/%u PASS", passed, total);
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