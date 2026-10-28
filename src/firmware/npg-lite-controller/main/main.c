// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program. If not, see <https://www.gnu.org/licenses/>.
//
// Copyright (c) 2025 Upside Down Labs
// Author: Mahesh Tupe (tupemahesh@upsidedownlabs.tech)
//
// At Upside Down Labs, we create open-source DIY neuroscience hardware and
// software. Our mission is to make neuroscience affordable and accessible for
// everyone. By supporting us with your purchase, you help spread innovation and
// open science. Thank you for being part of this journey with us!
#include "myogrip_selftest.h"
#include "myogrip_live.h"
#include "myogrip_wire.h"
#include "myogrip_keyboard.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "common.h"
#include "driver/gpio.h"
#include "esp_adc/adc_continuous.h"
#include "esp_pm.h"
#include "gap.h"
#include "gatt.h"
#include <math.h>
#include "hal/adc_types.h"
#include "hal/gpio_types.h"
#include "neopixel.h"
#include "soc/soc_caps.h"
#include <stdint.h>
#include "emg_signal.h"
#include "emg_calibration.h"
#include "emg_episode.h"
#include "emg_gesture.h"
#include "freertos/queue.h"
#include <ctype.h>


#define SAMPLING_RATE EMG_SAMPLE_RATE_HZ
#define PACKET_LEN 25
#define NUM_CHANNELS 4 // 3 BioAmp channels, 1 Battery channel

#define SAMPLE_SIZE ((NUM_CHANNELS - 1) * 2 + 1)
// should be less than 256 - 3 (for ble)
#define PACKET_SIZE (PACKET_LEN * SAMPLE_SIZE)

#define CONV_FRAME_SIZE (NUM_CHANNELS * PACKET_LEN * SOC_ADC_DIGI_RESULT_BYTES)
#define MAX_STORE_BUF_SIZE (CONV_FRAME_SIZE * 10)

// #define DEBUG // To disable light sleep & enable debug statements
#ifdef DEBUG
#define DEBUG_PIN_1 22
#define DEBUG_PIN_2 23
#endif

// #define SECONDARY_CH // To use adc channel 3-5, default is 0-2
#ifdef SECONDARY_CH
uint8_t channels[NUM_CHANNELS] = {3, 4, 5, 6};
#else
uint8_t channels[NUM_CHANNELS] = {0, 1, 2, 6};
#endif

/* To Do: add config function which checks max value given by adc and
 * replace 3329 (max output of adc).
 */
// Trying to map adc output to 12bit range
#define MAP(X) ((X) * 4095 / 3329)

const char *TAG = "NPG-IDF";

static QueueHandle_t emg_command_queue;
static uint32_t myogrip_boot;

static void emg_console_task(void *arg)
{
  (void)arg;

  setvbuf(stdin, NULL, _IONBF, 0);

  ESP_LOGI("MYOGRIP_CONSOLE", "Input ready: r f e h v x ? | m=demo menu | @=menu packet | K=keyboard packet");

  char line[192];
  unsigned used = 0;
  bool collecting = false;
  bool overflow = false;

  while (1) {
    int input = getchar();

    if (input == EOF) {
      clearerr(stdin);
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }

    if (collecting) {
      if (input == '\r' || input == '\n') {
        mg_command_t request;
        line[used] = '\0';
        bool parsed = !overflow && (line[0] == '@'
            ? mg_parse_menu_line(line, &request)
            : mg_parse_keyboard_line(line, &request));
        if (parsed) {
          if (xQueueSend(emg_command_queue, &request, 0) != pdPASS) {
            ESP_LOGW("MYOGRIP_CONSOLE", "Command queue full; packet dropped");
          }
        } else {
          ESP_LOGW("MYOGRIP_CONSOLE", "Malformed %s packet rejected",
                   line[0] == '@' ? "menu" : "keyboard");
        }
        collecting = false;
      } else if (input == 0 || used >= sizeof(line) - 1) {
        /* Discard the whole packet through its line ending. */
        overflow = true;
      } else if (!overflow) {
        line[used++] = (char)input;
      }
      continue;
    }

    if (input == '@' || input == 'K') {
      collecting = true;
      overflow = false;
      used = 1;
      line[0] = (char)input;
      continue;
    }

    if (input == '\r' || input == '\n') {
      continue;
    }

    char command = (char)tolower((unsigned char)input);

    if (command != 'r' && command != 'f' &&
        command != 'e' && command != 'h' &&
        command != 'v' && command != 'x' && command != '?' &&
        command != 'm') {
      ESP_LOGW("MYOGRIP_CONSOLE",
               "Unknown command; use r f e h v x ? m");
      continue;
    }

    // The acquisition task owns calibration and FSM state.
    mg_command_t request = {.code = command};
    if (xQueueSend(emg_command_queue, &request, 0) != pdPASS) {
      ESP_LOGW("MYOGRIP_CONSOLE", "Command queue full; command dropped");
    }
  }
}

/* Library function declarations */
void ble_store_config_init(void);

/* Private function declarations */
static void on_stack_reset(int reason);
static void on_stack_sync(void);
static void nimble_host_config_init(void);
static void nimble_host_task(void *param);

static TaskHandle_t adc_conv_task_handle;
static portMUX_TYPE adc_stats_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t adc_pool_overflows = 0;

static uint32_t get_adc_pool_overflows(void)
{
  // The interrupt updates this counter; read it under the same lock.
  portENTER_CRITICAL(&adc_stats_lock);
  uint32_t count = adc_pool_overflows;
  portEXIT_CRITICAL(&adc_stats_lock);

  return count;
}

static bool IRAM_ATTR pool_overflow_cb(
    adc_continuous_handle_t handle,
    const adc_continuous_evt_data_t *edata,
    void *user_data)
{
  (void)handle;
  (void)edata;
  (void)user_data;

  portENTER_CRITICAL_ISR(&adc_stats_lock);
  adc_pool_overflows++;
  portEXIT_CRITICAL_ISR(&adc_stats_lock);

  // Wake the acquisition task so it can drain buffered data.
  BaseType_t must_yield = pdFALSE;
  vTaskNotifyGiveFromISR(adc_conv_task_handle, &must_yield);

  return must_yield == pdTRUE;
}

static bool IRAM_ATTR conv_done_cb(adc_continuous_handle_t handle,
                                   const adc_continuous_evt_data_t *edata,
                                   void *user_data) {
  BaseType_t mustYield = pdFALSE;
  // Notify that ADC continuous driver has done enough number of conversions
  vTaskNotifyGiveFromISR(adc_conv_task_handle, &mustYield);

  return (mustYield == pdTRUE);
}

adc_continuous_handle_t adc_handle = NULL;

static void on_stack_reset(int reason) {
  /* On reset, print reset reason to console */
  ESP_LOGI(TAG, "nimble stack reset, reset reason: %d", reason);
}

static void on_stack_sync(void) {
  /* On stack sync, do advertising initialization */
  adv_init();
}

static void nimble_host_config_init(void) {
  /* Set host callbacks */
  ble_hs_cfg.reset_cb = on_stack_reset;
  ble_hs_cfg.sync_cb = on_stack_sync;
  ble_hs_cfg.gatts_register_cb = gatt_svr_register_cb;
  ble_hs_cfg.store_status_cb = ble_store_util_status_rr;

  /* Store host configuration */
  ble_store_config_init();
}

static void nimble_host_task(void *param) {
  /* Task entry log */
  ESP_LOGI(TAG, "nimble host task has been started!");
  /* This function won't return until nimble_port_stop() is executed */
  nimble_port_run();
  /* Clean up at exit */
  vTaskDelete(NULL);
}

void continuous_adc_init() {
  adc_digi_pattern_config_t pattern[NUM_CHANNELS] = {0};
  adc_continuous_handle_cfg_t handle_conf = {
      .max_store_buf_size = MAX_STORE_BUF_SIZE,
      .conv_frame_size = CONV_FRAME_SIZE,
  };

  for (int i = 0; i < NUM_CHANNELS; i++) {
    pattern[i].atten = ADC_ATTEN_DB_12;
    pattern[i].bit_width = ADC_BITWIDTH_12;
    pattern[i].channel = channels[i];
    pattern[i].unit = ADC_UNIT_1;
  }
  adc_continuous_config_t adc_conf = {
      .adc_pattern = pattern,
      .pattern_num = NUM_CHANNELS,
      .conv_mode = ADC_CONV_SINGLE_UNIT_1,

      /* should be less than SOC_ADC_SAMPLE_FREQ_THRES_HIGH
       * and more than SOC_ADC_SAMPLE_FREQ_THRES_LOW
       * refer "soc/soc_caps.h"
       */
      .sample_freq_hz = SAMPLING_RATE * NUM_CHANNELS,
      .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
  };
  ESP_ERROR_CHECK(adc_continuous_new_handle(&handle_conf, &adc_handle));
  ESP_ERROR_CHECK(adc_continuous_config(adc_handle, &adc_conf));
  adc_continuous_evt_cbs_t cbs = {
      .on_conv_done = conv_done_cb,
      .on_pool_ovf = pool_overflow_cb,
  };
  ESP_ERROR_CHECK(
      adc_continuous_register_event_callbacks(adc_handle, &cbs, NULL));
}

static uint32_t adc_restart_after_gap(void)
{
#ifdef DEBUG
  gpio_set_level(DEBUG_PIN_1, 0);
#endif

  ESP_ERROR_CHECK(adc_continuous_stop(adc_handle));
  ESP_ERROR_CHECK(adc_continuous_flush_pool(adc_handle));

  // Discard notifications belonging to the old acquisition.
  ulTaskNotifyTake(pdTRUE, 0);

  // Snapshot while stopped so later overflows remain detectable.
  uint32_t handled_overflows = get_adc_pool_overflows();

  ESP_LOGW("MYOGRIP_ADC",
           "Acquisition gap: discarded buffered data; restarting ADC");

  ESP_ERROR_CHECK(adc_continuous_start(adc_handle));
  return handled_overflows;
}

typedef struct {
  float voltage;
  uint8_t percent;
} batt_point_t;

static const batt_point_t batt_table[] = {
    {3.27, 0},  {3.61, 5},  {3.69, 10}, {3.71, 15}, {3.73, 20}, {3.75, 25},
    {3.77, 30}, {3.79, 35}, {3.80, 40}, {3.82, 45}, {3.84, 50}, {3.85, 55},
    {3.87, 60}, {3.91, 65}, {3.95, 70}, {3.98, 75}, {4.02, 80}, {4.08, 85},
    {4.11, 90}, {4.15, 95}, {4.20, 100}};

const uint8_t batt_table_len = sizeof(batt_table) / sizeof(batt_table[0]);

static bool battery_check(int battery_reading) {
  float voltage = (battery_reading / 4095.0) * 3.3 - 0.14;
#ifdef DEBUG
  ESP_LOGI("NPG-IDF", "vol bat: %f", voltage);
#endif
  uint8_t percent = 0;
  if (voltage < batt_table[0].voltage) {
    percent = batt_table[0].percent;
  } else if (voltage > batt_table[batt_table_len - 1].voltage) {
    percent = batt_table[batt_table_len - 1].percent;
  } else {
    for (int i = 0; i < batt_table_len - 1; i++) {
      float v1 = batt_table[i].voltage;
      float v2 = batt_table[i + 1].voltage;

      if (voltage >= v1 && voltage <= v2) {
        uint8_t p1 = batt_table[i].percent;
        uint8_t p2 = batt_table[i + 1].percent;

        /* Linear interpolation */
        percent = (uint8_t)(p1 + (voltage - v1) * (p2 - p1) / (v2 - v1));
        break;
      }
    }
  }
  if (percent < 5) {
    // To Do: change to heartbeat
    set_pixel(5, RED, 10);
    nimble_port_stop(); // stop ble
    adc_continuous_stop(adc_handle);
    ESP_LOGE("NPG-IDF", "Low Battery, please charge device before use");
    return false;
  }

  return true;
}

static bool flex_active;
static bool ext_active;

static void emg_activity_reset(void)
{
  flex_active = false;
  ext_active = false;
}

static const char *emg_activity_update(
    const float rms[EMG_CHANNEL_COUNT], bool ready)
{
  emg_thresholds_t thresholds;

  if (!emg_calibration_get_thresholds(&thresholds)) {
    emg_activity_reset();
    return "UNCALIBRATED";
  }

  if (!ready) {
    emg_activity_reset();
    return "WARMUP";
  }

  for (unsigned ch = 0; ch < 2; ch++) {
    if (!isfinite(rms[ch]) || rms[ch] < 0.0f) {
      emg_activity_reset();
      return "INVALID";
    }
  }

  // Once active, require crossing the lower OFF threshold to release.
  flex_active = flex_active
      ? rms[0] > thresholds.off[0]
      : rms[0] >= thresholds.on[0];

  ext_active = ext_active
      ? rms[1] > thresholds.off[1]
      : rms[1] >= thresholds.on[1];

  if (!flex_active && !ext_active) {
    return "REST";
  }

  if (flex_active && !ext_active) {
    return "FLEX_ACTIVE";
  }

  if (ext_active && !flex_active) {
    return "EXT_ACTIVE";
  }

  // Both channels are active: compare their calibrated scales.
  float flex_normalized = fmaxf(
      0.0f,
      (rms[0] - thresholds.rest[0]) /
      (thresholds.reference[0] - thresholds.rest[0]));

  float ext_normalized = fmaxf(
      0.0f,
      (rms[1] - thresholds.rest[1]) /
      (thresholds.reference[1] - thresholds.rest[1]));

  if (flex_normalized >
      EMG_CAL_DOMINANCE_RATIO * ext_normalized) {
    return "FLEX_ACTIVE";
  }

  if (ext_normalized >
      EMG_CAL_DOMINANCE_RATIO * flex_normalized) {
    return "EXT_ACTIVE";
  }

  return "INVALID";
}

/* One snapshot per ADC frame (about 10 Hz), not one log per sample. */
static void myogrip_publish(const myogrip_live_t *live, mg_keyboard_t *keys)
{
  const mg_fsm_t *f = &live->fsm;
  mg_keyboard_expire(keys, (uint64_t)(esp_timer_get_time() / 1000));
  ESP_LOGI("MYOGRIP_FSM",
           "MGSTATE {\"v\":1,\"wire\":2,\"boot\":%lu,\"revision\":%lu,"
           "\"keyboard_wire\":1,\"keyboard_session\":%lu,\"keyboard_sequence\":%lu,"
           "\"keyboard_mask\":%u,\"keyboard_connected\":%u,"
           "\"rest\":%u,\"menu_ready\":%u,\"samples\":%lu,\"calibrated\":%u,"
           "\"armed\":%u,\"activity\":\"%s\",\"gesture\":\"%s\","
           "\"gesture_seq\":%lu,\"state\":\"%s\",\"menu_id\":%lu,"
           "\"loaded\":%u,\"selected\":%u,\"active\":%d,"
           "\"progress\":%.4f,\"gate\":%u,\"returning\":%u,"
           "\"adaptive_count\":%u,\"adaptive\":[%d,%d,%d,%d],"
           "\"full_count\":%u,\"full\":[%d,%d,%d,%d]}",
           (unsigned long)myogrip_boot, (unsigned long)live->revision,
           (unsigned long)keys->session, (unsigned long)keys->sequence,
           (unsigned)keys->mask, (unsigned)keys->connected,
           live->rest_samples, (unsigned)myogrip_live_menu_ready(live),
           (unsigned long)live->samples, (unsigned)live->calibrated,
           (unsigned)live->armed, live->activity,
           emg_gesture_name(live->last_gesture),
           (unsigned long)live->gesture_seq, mg_state_name(f->state),
           (unsigned long)f->menu.menu_id, (unsigned)f->menu_loaded,
           (unsigned)f->selected, (int)f->active_grip,
           (double)f->grip_progress, (unsigned)f->wait_release,
           (unsigned)f->returning, (unsigned)f->menu.adaptive_count,
           (int)f->menu.adaptive[0], (int)f->menu.adaptive[1],
           (int)f->menu.adaptive[2], (int)f->menu.adaptive[3],
           (unsigned)f->menu.full_count,
           (int)f->menu.full[0], (int)f->menu.full[1],
           (int)f->menu.full[2], (int)f->menu.full[3]);
}

/* Called only by the acquisition task, alongside normal FSM input. */
static bool myogrip_apply_menu(myogrip_live_t *live, const mg_command_t *request)
{
  return request->code == '@' && request->boot == myogrip_boot &&
      myogrip_live_load_menu(live, &request->menu, request->revision,
                             request->preserve_selection);
}

static void
adc_conv_task(void *arg) { // changed signature to proper FreeRTOS prototype
  esp_err_t ret = ESP_OK;
  uint32_t size_ret = 0;
  uint8_t result[CONV_FRAME_SIZE] = {0};
  uint16_t adc_reading = 0;
  uint8_t chords_packet[PACKET_LEN][SAMPLE_SIZE];
  uint8_t counter = 0;

  int battery_reading = 0;
  uint32_t samples_per_channel = 0;
  uint32_t frames_since_log = 0;
  uint32_t frame_bytes = 0;
  uint32_t partial_chunks = 0;
  uint32_t handled_overflows = 0;
  uint32_t recoveries = 0;
  bool recovery_pending = false;

  float emg_rms[EMG_CHANNEL_COUNT] = {0};
  uint32_t emg_log_samples = 0;
  const char *previous_activity = NULL;

  myogrip_live_t live;
  myogrip_live_init(&live);
  mg_keyboard_t keyboard;
  mg_keyboard_init(&keyboard);

  adc_conv_task_handle = xTaskGetCurrentTaskHandle();
  emg_signal_reset();
  emg_episode_reset();
  emg_gesture_reset();
  continuous_adc_init();
  ESP_ERROR_CHECK(adc_continuous_start(adc_handle));

  while (1) {

    // Sleep until the ADC reports available data.
    if (!recovery_pending) {
      ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    }

    mg_command_t request;
    while (xQueueReceive(emg_command_queue, &request, 0) == pdPASS) {
      char command = request.code;
      if (command == 'K') {
        bool accepted = request.boot == myogrip_boot &&
            mg_keyboard_receive(&keyboard, request.session, request.sequence,
                                request.key_mask,
                                (uint64_t)(esp_timer_get_time() / 1000));
        ESP_LOGI("MYOGRIP_FSM",
                 "MGKEYACK {\"boot\":%lu,\"session\":%lu,"
                 "\"sequence\":%lu,\"accepted\":%u}",
                 (unsigned long)myogrip_boot, (unsigned long)request.session,
                 (unsigned long)request.sequence, (unsigned)accepted);
        myogrip_publish(&live, &keyboard);
      } else if (command == '@') {
        bool accepted = !recovery_pending &&
            get_adc_pool_overflows() == handled_overflows &&
            myogrip_apply_menu(&live, &request);
        ESP_LOGI("MYOGRIP_FSM",
                 "MGACK {\"boot\":%lu,\"menu_id\":%lu,"
                 "\"accepted\":%u,\"revision\":%lu}",
                 (unsigned long)myogrip_boot,
                 (unsigned long)request.menu.menu_id,
                 (unsigned)accepted, (unsigned long)live.revision);
        /* Acknowledge the exact state before processing the next ADC frame. */
        myogrip_publish(&live, &keyboard);
      } else if (command == 'm') {
        ESP_LOGI("MYOGRIP_FSM", "DEMO MENU: %s",
                 myogrip_live_demo_menu(&live) ? "loaded" :
                 "ignored; validate calibration, rest, and return HOME first");
      } else {
        emg_calibration_command(command);
        emg_thresholds_t current_thresholds;
        if (!emg_calibration_get_thresholds(&current_thresholds)) {
          myogrip_live_gap(&live);
          emg_activity_reset();
          emg_episode_reset();
          emg_gesture_reset();
        }
      }
    }


      if (recovery_pending ||
          get_adc_pool_overflows() != handled_overflows) {
        // Never join samples collected on opposite sides of a gap.
        frame_bytes = 0;
        emg_signal_reset();
        emg_calibration_reset();
        emg_activity_reset();
        emg_episode_reset();
        emg_gesture_reset();
        myogrip_live_gap(&live);
        previous_activity = NULL;
        emg_log_samples = 0;

        // Mark a discontinuity in the existing BLE sample counter.
        counter++;

        handled_overflows = adc_restart_after_gap();
        recoveries++;
        recovery_pending = false;
      }

    // Drain all buffered data before waiting again.
    while (1) {
#ifdef DEBUG
      gpio_set_level(DEBUG_PIN_1, 1);
#endif
      uint32_t read_capacity = CONV_FRAME_SIZE - frame_bytes;

      size_ret = 0;
      ret = adc_continuous_read(adc_handle,
                                result + frame_bytes,
                                read_capacity,
                                &size_ret, 0);

      if (get_adc_pool_overflows() != handled_overflows) {
        recovery_pending = true;
        break;
      }

      if (ret == ESP_ERR_TIMEOUT) {
        // No buffered data remains. Wait for the next notification.
#ifdef DEBUG
        gpio_set_level(DEBUG_PIN_1, 0);
#endif
        break;
      }

      if (ret == ESP_OK &&
          size_ret > 0 &&
          size_ret <= read_capacity &&
          size_ret % SOC_ADC_DIGI_RESULT_BYTES == 0) {
        frame_bytes += size_ret;

        if (frame_bytes < CONV_FRAME_SIZE) {
          partial_chunks++;

#ifdef DEBUG
          gpio_set_level(DEBUG_PIN_1, 0);
#endif
          // Keep this data and append the next chunk.
          continue;
        }

        bool channel_order_valid = true;

        for (int n = 0; n < PACKET_LEN * NUM_CHANNELS; n++) {
          const adc_digi_output_data_t *sample =
              (const void *)&result[n * SOC_ADC_DIGI_RESULT_BYTES];

          if (sample->type2.channel != channels[n % NUM_CHANNELS]) {
            channel_order_valid = false;
            break;
          }
        }

        if (!channel_order_valid) {
          ESP_LOGE("MYOGRIP_ADC", "Unexpected ADC channel order");
          recovery_pending = true;
          break;
        }

        // The complete frame is ready for the existing decoder.
        frame_bytes = 0;
        battery_reading = 0;

        for (int j = 0; j < PACKET_LEN; j++) {
          uint16_t raw_emg[EMG_CHANNEL_COUNT] = {0};

          chords_packet[j][0] = counter;
          counter++;

          for (int i = 0; i < NUM_CHANNELS; i++) {
            const adc_digi_output_data_t *parsed_data =
                (const void *)&result[(i + j * NUM_CHANNELS) *
                                      SOC_ADC_DIGI_RESULT_BYTES];

            if (i < EMG_CHANNEL_COUNT) {
              // Preprocessing uses raw ADC values, before BLE scaling.
              raw_emg[i] = parsed_data->type2.data;

              adc_reading = MAP(parsed_data->type2.data);
              chords_packet[j][1 + i * 2] = (adc_reading >> 8) & 0xFF;
              chords_packet[j][2 + i * 2] = adc_reading & 0xFF;
            } else {
              adc_reading = MAP(parsed_data->type2.data * 2);
              battery_reading += adc_reading;
            }
          }

          bool ready = emg_signal_process(raw_emg, emg_rms);
          emg_calibration_process(emg_rms, ready);
          const char *activity = emg_activity_update(emg_rms, ready);

          emg_episode_t episode_result;
          emg_episode_event_t episode_event =
              emg_episode_update(activity, &episode_result);

          if (episode_event == EMG_EPISODE_BEGIN) {
            ESP_LOGI("MYOGRIP_EMG",
                     "EPISODE START %c",
                     episode_result.direction);
          } else if (episode_event == EMG_EPISODE_END) {
            ESP_LOGI("MYOGRIP_EMG",
                     "EPISODE END %c | span=%lu primary=%lu "
                     "opposite=%lu ambiguous=%lu (samples)",
                     episode_result.direction,
                     (unsigned long)episode_result.span_samples,
                     (unsigned long)episode_result.primary_samples,
                     (unsigned long)episode_result.opposite_samples,
                     (unsigned long)episode_result.ambiguous_samples);
          }

          emg_thresholds_t gesture_thresholds;
          emg_gesture_t gesture = EMG_GESTURE_NONE;

          if (emg_calibration_get_thresholds(&gesture_thresholds)) {
            gesture = emg_gesture_update(
                activity,
                episode_event,
                &episode_result,
                emg_rms[1],
                gesture_thresholds.high_extension);
          } else {
            emg_gesture_reset();
          }

          myogrip_live_sample(&live, activity, gesture);

          if (gesture != EMG_GESTURE_NONE) {
            ESP_LOGI("MYOGRIP_EMG", "GESTURE %s",
                     emg_gesture_name(gesture));
          }

          if (previous_activity == NULL ||
              strcmp(previous_activity, activity) != 0) {
            uint32_t sample_number =
                samples_per_channel + (uint32_t)j + 1;

            ESP_LOGI("MYOGRIP_EMG",
                     "ACTIVITY %s -> %s | sample=%lu flex=%.1f ext=%.1f",
                     previous_activity != NULL
                         ? previous_activity : "START",
                     activity,
                     (unsigned long)sample_number,
                     (double)emg_rms[0],
                     (double)emg_rms[1]);

            previous_activity = activity;
          }

          emg_log_samples++;
          if (emg_log_samples >= EMG_LOG_INTERVAL_SAMPLES) {
            emg_log_samples = 0;

            if (ready) {
              ESP_LOGI("MYOGRIP_EMG",
                       "%s | RMS flex=%.1f, ext=%.1f, ch3=%.1f",
                       activity,
                       (double)emg_rms[0],
                       (double)emg_rms[1],
                       (double)emg_rms[2]);
            }
          }
        }
        battery_reading = battery_reading / PACKET_LEN;
        if (!battery_check(battery_reading)) {
          myogrip_live_gap(&live);
          myogrip_publish(&live, &keyboard);
          // ADC was intentionally stopped. End this task without recovery.
          vTaskDelete(NULL);
          return;
        }

        myogrip_publish(&live, &keyboard);

        samples_per_channel += PACKET_LEN;
        frames_since_log++;

        // 50 frames × 25 samples = about five seconds at 250 Hz.
        if (frames_since_log >= 50) {
          ESP_LOGI("MYOGRIP_ADC",
                   "samples/ch=%lu, streaming=%s, pool_ovf=%lu, "
                   "partial=%lu, recoveries=%lu",
                   (unsigned long)samples_per_channel,
                   streaming ? "on" : "off",
                   (unsigned long)get_adc_pool_overflows(),
                   (unsigned long)partial_chunks,
                   (unsigned long)recoveries);
          frames_since_log = 0;
        }

        // START/STOP controls transmission, not local acquisition.
        if (streaming) {
          struct os_mbuf *om =
              ble_hs_mbuf_from_flat((void *)chords_packet, PACKET_SIZE);

          if (om) {
            int rc =
                ble_gatts_notify_custom(conn_handle, data_char_handle, om);

            if (rc != 0) {
              ESP_LOGE(TAG, "Notification failed, rc=%d", rc);
            }
          }
        }

#ifdef DEBUG
        uint16_t ch3 =
            (uint16_t)(chords_packet[0][1] << 8) | chords_packet[0][2];
        ESP_LOGI("adc_conv_task", "counter: %d, CH3:%d, data_char_handle:%d",
                 chords_packet[0][0], ch3, data_char_handle);
#endif

      } else {
        frame_bytes = 0;
        ESP_LOGE("adc_conv_task",
                 "ADC read failed or invalid payload: err=%s, bytes=%lu",
                 esp_err_to_name(ret), (unsigned long)size_ret);
#ifdef DEBUG
        gpio_set_level(DEBUG_PIN_1, 0);
#endif
        recovery_pending = true;
        break;
      }
#ifdef DEBUG
      gpio_set_level(DEBUG_PIN_1, 0);
#endif
    }
    if (recovery_pending) {
      continue;  // Restart at the outer recovery block; do not re-read stale data.
    }
    vTaskDelay(pdMS_TO_TICKS(100)); // use pdMS_TO_TICKS for portable delay
  }
}

void app_main(void) {
  do {
    myogrip_boot = esp_random();
  } while (myogrip_boot == 0);
  neopixel_init();
  set_pixel(0, RED, 10);
  /*
   * NVS flash initialization
   * Dependency of BLE stack to store configurations
   */
#ifdef DEBUG
  esp_log_level_set("*", ESP_LOG_DEBUG);
#else
  esp_log_level_set("*", ESP_LOG_ERROR);
#endif
  int rc = 0;
  esp_err_t ret = nvs_flash_init();
  if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
      ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
  }

  esp_pm_config_t pm_config = {.max_freq_mhz = 160,
                               .min_freq_mhz = 40,
#ifndef DEBUG
#if CONFIG_FREERTOS_USE_TICKLESS_IDLE
      .light_sleep_enable = false
#endif
#endif
  };
  ESP_ERROR_CHECK(esp_pm_configure(&pm_config));

  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "failed to initialize nvs flash, error code: %d ", ret);
    return;
  }
#ifdef DEBUG
  gpio_config_t gpio_conf = {.pin_bit_mask =
                                 (1ULL << DEBUG_PIN_1) | (1ULL << DEBUG_PIN_2),
                             .mode = GPIO_MODE_OUTPUT,
                             .pull_down_en = GPIO_PULLDOWN_DISABLE,
                             .pull_up_en = GPIO_PULLUP_DISABLE};
  gpio_config(&gpio_conf);
#endif

  /* NimBLE stack initialization */
  ret = nimble_port_init();
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "failed to initialize nimble stack, error code: %d ", ret);
    return;
  }

#if CONFIG_BT_NIMBLE_GAP_SERVICE
  /* GAP service initialization */
  rc = gap_init();
  if (rc != 0) {
    ESP_LOGE(TAG, "failed to initialize GAP service, error code: %d", rc);
    return;
  }
#endif

  /* GATT server initialization */
  rc = gatt_svc_init();
  if (rc != 0) {
    ESP_LOGE(TAG, "failed to initialize GATT server, error code: %d", rc);
    return;
  }

  /* NimBLE host configuration initialization */
  nimble_host_config_init();

  /* Start NimBLE host task thread and return */
  xTaskCreate(nimble_host_task, "NimBLE Host", 4 * 1024, NULL, 5, NULL);

  esp_log_level_set("MYOGRIP_ADC", ESP_LOG_INFO);

  esp_log_level_set("MYOGRIP_EMG", ESP_LOG_INFO);

  esp_log_level_set("MYOGRIP_CONSOLE", ESP_LOG_INFO);

  esp_log_level_set("MYOGRIP_CAL", ESP_LOG_INFO);

  esp_log_level_set("MYOGRIP_FSM", ESP_LOG_INFO);

  emg_command_queue = xQueueCreate(8, sizeof(mg_command_t));
  ESP_ERROR_CHECK(emg_command_queue != NULL ? ESP_OK : ESP_ERR_NO_MEM);

  BaseType_t console_rc = xTaskCreate(
      emg_console_task, "emg_console", 3 * 1024, NULL, 2, NULL);

  ESP_ERROR_CHECK(console_rc == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);

  xTaskCreate(adc_conv_task, "adc_conv_task", 4 * 1024, NULL, 5, NULL);

  /* Enable test logs after the earlier global ERROR-only setting. */
  esp_log_level_set("MYOGRIP_TEST", ESP_LOG_INFO);

  /* Independent simulated FSM; does not consume ADC data. */
  myogrip_selftest_start();
}
