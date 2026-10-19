#pragma once

#include "esp_camera.h"

// Proposed default profile for the OV2640 CAVIA bench test.
// Call AFTER the example's sensor/board-specific defaults and BEFORE WiFi.begin.
// Values are reapplied on every boot; no NVS storage is needed for fixed defaults.
static bool applyCaviaCameraProfile() {
  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor == nullptr) {
    return false;
  }
    bool ok = true;

  // Keep VGA: 640 × 480.
  if (sensor->set_framesize(sensor, FRAMESIZE_VGA) != 0) ok = false;
  if (sensor->set_quality(sensor, 12) != 0) ok = false;

  // Enable the requested settings.
  if (sensor->set_hmirror(sensor, 1) != 0) ok = false;
  if (sensor->set_vflip(sensor, 1) != 0) ok = false;
  if (sensor->set_aec2(sensor, 1) != 0) ok = false;

  return ok;
}
