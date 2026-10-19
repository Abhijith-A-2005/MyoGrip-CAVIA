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
//
// Reference:
// https://github.com/espressif/esp-idf/blob/master/examples/bluetooth/ble_get_started/nimble/NimBLE_GATT_Server/main/src/gatt_svc.c
#include "gatt.h"
#include "common.h"
#include "esp_err.h"
#include "esp_log.h"
#include "gap.h"
#include "neopixel.h"
#include <ctype.h>
#include <string.h>
#include "host/ble_hs_mbuf.h"
#include "os/os_mbuf.h"

static const char *TAG = "GATT";

// Private function declaration
// BLE UUIDs – change if desired.
//  SERVICE_UUID      "4f af c2 01 1f b5 45 9e 8f cc c5 c9 c3 31 91 4b"
static const ble_uuid128_t svc_uuid = {
    .u = {.type = BLE_UUID_TYPE_128},
    .value = {0x4b, 0x91, 0x31, 0xc3, 0xc9, 0xc5, 0xcc, 0x8f, 0x9e, 0x45, 0xb5,
              0x1f, 0x01, 0xc2, 0xaf, 0x4f}};

//  DATA_CHAR_UUID "be b5 48 3e 36 e1 46 88 b7 f5 ea 07 36 1b 26 a8"
static const ble_uuid128_t data_char_uuid = {
    .u = {.type = BLE_UUID_TYPE_128},
    .value = {0xa8, 0x26, 0x1b, 0x36, 0x07, 0xea, 0xf5, 0xb7, 0x88, 0x46, 0xe1,
              0x36, 0x3e, 0x48, 0xb5, 0xbe}};

//  CONTROL_CHAR_UUID "00 00 ff 01 00 00 10 00 80 00 00 80 5f 9b 34 fb"
static const ble_uuid128_t control_char_uuid = {
    .u = {.type = BLE_UUID_TYPE_128},
    .value = {0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80, 0x00, 0x10, 0x00,
              0x00, 0x01, 0xff, 0x00, 0x00}};

static const struct ble_gatt_svc_def gatt_svr_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &svc_uuid.u,
        .characteristics =
            (struct ble_gatt_chr_def[]){
                // Data Characteristic (Notify only)
                {
                    .uuid = &data_char_uuid.u,
                    .access_cb =
                        gatt_svr_chr_access_cb, // No access callback needed for
                    // Notify-only
                    .flags = BLE_GATT_CHR_F_NOTIFY,
                    .val_handle = &data_char_handle,
                },
                // Control Characteristic (Read/Write/Notify)
                {
                    .uuid = &control_char_uuid.u,
                    .access_cb = gatt_svr_chr_access_cb, // Use access callback
                    // for command handling
                    .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE |
                             BLE_GATT_CHR_F_NOTIFY,
                    .val_handle = &control_char_handle,
                },
                {0}, // Terminator for Characteristics
            },
    },
    {0}, // Terminator for Services
};

void gatt_svr_register_cb(struct ble_gatt_register_ctxt *ctxt, void *arg) {
  char buf[BLE_UUID_STR_LEN];
  switch (ctxt->op) {
  case BLE_GATT_REGISTER_OP_SVC:
    ESP_LOGD(TAG, "registered service %s with handle %d",
             ble_uuid_to_str(ctxt->svc.svc_def->uuid, buf), ctxt->svc.handle);
    break;
  case BLE_GATT_REGISTER_OP_CHR:
    // Store characteristic handles for later use (like Notification)
    if (ble_uuid_cmp(ctxt->chr.chr_def->uuid, &data_char_uuid.u) == 0) {
      data_char_handle = ctxt->chr.val_handle;
      ESP_LOGI(TAG, "data_char_handle: %d", data_char_handle);
    }
    if (ble_uuid_cmp(ctxt->chr.chr_def->uuid, &control_char_uuid.u) == 0) {
      control_char_handle = ctxt->chr.val_handle;
      ESP_LOGI(TAG, "control_char_handle: %d", control_char_handle);
    }
    ESP_LOGD(TAG, "registered characteristic %s with handle %d",
             ble_uuid_to_str(ctxt->chr.chr_def->uuid, buf),
             ctxt->chr.def_handle);
    break;
  case BLE_GATT_REGISTER_OP_DSC:
    ESP_LOGD(TAG, "registered descriptor %s with handle %d",
             ble_uuid_to_str(ctxt->dsc.dsc_def->uuid, buf), ctxt->dsc.handle);
    break;
  default:
    break;
  }
}

int gatt_svr_chr_access_cb(uint16_t conn_handle, uint16_t attr_handle,
                           struct ble_gatt_access_ctxt *ctxt, void *arg) {
  int rc = 0;
  if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
    // --- Command Handling (WRITE operation) ---
    // The incoming command is in ctxt->om->om_data, its length is
    // ctxt->om->om_len
    char cmd_buffer[20] = {0};

    /* Check the complete incoming command, including chained buffers. */
    uint16_t incoming_len = OS_MBUF_PKTLEN(ctxt->om);

    if (incoming_len == 0 || incoming_len >= sizeof(cmd_buffer)) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }

    uint16_t copied_len = 0;

    int copy_rc = ble_hs_mbuf_to_flat(
        ctxt->om,
        cmd_buffer,
        sizeof(cmd_buffer) - 1,
        &copied_len
    );

    if (copy_rc != 0 || copied_len != incoming_len) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    /* Reject embedded nulls rather than silently accepting a prefix. */
    if (memchr(cmd_buffer, '\0', copied_len) != NULL) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    for (uint16_t i = 0; i < copied_len; i++) {
        cmd_buffer[i] = (char)toupper((unsigned char)cmd_buffer[i]);
    }

    cmd_buffer[copied_len] = '\0';
    char *response = "UNKNOWN COMMAND";
    bool notify_response = true;
    if (strcmp(cmd_buffer, "START") == 0) {
      streaming = true;
      set_pixel(0, BLUE, 10);
      // Ensure ADC is running and cleared
      response = "RUNNING";
      ESP_LOGI(TAG, "Command: START received, streaming started.");
    } else if (strcmp(cmd_buffer, "STOP") == 0) {
      streaming = false;
      set_pixel(0, GREEN, 10);
      response = "STOPPED";
      ESP_LOGI(TAG, "Command: STOP received, streaming stopped.");
    } else if (strcmp(cmd_buffer, "WHORU") == 0) {
      response = "NPG-LITE";
      ESP_LOGI(TAG, "Command: WHORU received.");
    } else if (strcmp(cmd_buffer, "STATUS") == 0) {
      response = streaming ? "RUNNING" : "STOPPED";
      ESP_LOGI(TAG, "Command: STATUS received.");
    } else {
      // Unknown command - handled by default response
      notify_response = true; // Still notify the error message
    }

    // Notify the client with the response
    if (notify_response) {
      struct os_mbuf *om =
          ble_hs_mbuf_from_flat((uint8_t *)response, strlen(response));
      if (om) {
        rc = ble_gatts_notify_custom(conn_handle, attr_handle, om);
        if (rc != 0) {
          ESP_LOGE(TAG, "Failed to notify control response, rc=%d", rc);
        }
      }
    }
    rc = 0; // Operation handled
  } else if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
    // --- READ operation (e.g., STATUS or WHORU on read) ---
    char *read_response;
    // Default read is status
    if (attr_handle == control_char_handle) {
      read_response = streaming ? "RUNNING" : "STOPPED";
      rc = os_mbuf_append(ctxt->om, read_response, strlen(read_response));
    }
  }
  return rc;
}

int gatt_svc_init(void) {
  /* Local variables */
  int rc = 0;

  /* 1. GATT service initialization */
  ble_svc_gatt_init();

  /* 2. Update GATT services counter */
  rc = ble_gatts_count_cfg(gatt_svr_svcs);
  if (rc != 0) {
    return rc;
  }

  /* 3. Add GATT services */
  rc = ble_gatts_add_svcs(gatt_svr_svcs);
  if (rc != 0) {
    return rc;
  }

  return 0;
}
