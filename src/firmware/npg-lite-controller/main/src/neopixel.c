#include "neopixel.h"
#include "common.h"
#include "driver/rmt_tx.h"
#include "led_strip_encoder.h"

// 10MHz resolution, 1 tick = 0.1us (led strip needs a high resolution)
#define RMT_LED_STRIP_RESOLUTION_HZ 10000000 
#define RMT_LED_STRIP_GPIO_NUM 15
#define NUM_NEOPIXEL 6

static const char *TAG = "NEOPIXEL";
static uint8_t pixels[NUM_NEOPIXEL * 3];

/**
 * @brief Simple helper function, converting HSV color space to RGB color space
 *
 * Wiki: https://en.wikipedia.org/wiki/HSL_and_HSV
 * Credits:
 * https://github.com/espressif/esp-idf/blob/release/v5.5/examples/peripherals/rmt/led_strip/main/led_strip_example_main.c
 */
void led_strip_hsv2rgb(uint32_t h, uint32_t s, uint32_t v, uint32_t *r,
                       uint32_t *g, uint32_t *b) {
  h %= 360; // h -> [0,360]
  uint32_t rgb_max = v * 2.55f;
  uint32_t rgb_min = rgb_max * (100 - s) / 100.0f;

  uint32_t i = h / 60;
  uint32_t diff = h % 60;

  // RGB adjustment amount by hue
  uint32_t rgb_adj = (rgb_max - rgb_min) * diff / 60;

  switch (i) {
  case 0:
    *r = rgb_max;
    *g = rgb_min + rgb_adj;
    *b = rgb_min;
    break;
  case 1:
    *r = rgb_max - rgb_adj;
    *g = rgb_max;
    *b = rgb_min;
    break;
  case 2:
    *r = rgb_min;
    *g = rgb_max;
    *b = rgb_min + rgb_adj;
    break;
  case 3:
    *r = rgb_min;
    *g = rgb_max - rgb_adj;
    *b = rgb_max;
    break;
  case 4:
    *r = rgb_min + rgb_adj;
    *g = rgb_min;
    *b = rgb_max;
    break;
  default:
    *r = rgb_max;
    *g = rgb_min;
    *b = rgb_max - rgb_adj;
    break;
  }
}

uint32_t color_r = 0;
uint32_t color_g = 0;
uint32_t color_b = 0;

rmt_channel_handle_t led_chan = NULL;
rmt_encoder_handle_t led_encoder = NULL;

led_strip_encoder_config_t encoder_config = {
    .resolution = RMT_LED_STRIP_RESOLUTION_HZ,
};

rmt_transmit_config_t tx_config = {
    .loop_count = 0, // no transfer loop
};

rmt_tx_channel_config_t tx_chan_config = {
    .clk_src = RMT_CLK_SRC_DEFAULT, // select source clock
    .gpio_num = RMT_LED_STRIP_GPIO_NUM,
    .mem_block_symbols =
        64, // increase the block size can make the LED less flickering
    .resolution_hz = RMT_LED_STRIP_RESOLUTION_HZ,
    .trans_queue_depth = 4, // set the number of transactions that can be
                            // pending in the background
};

void neopixel_init() {
  ESP_ERROR_CHECK(rmt_new_tx_channel(&tx_chan_config, &led_chan));
  ESP_LOGI(TAG, "Install led strip encoder");
  ESP_ERROR_CHECK(rmt_new_led_strip_encoder(&encoder_config, &led_encoder));
  ESP_LOGI(TAG, "Enable RMT TX channel");
  ESP_ERROR_CHECK(rmt_enable(led_chan));
}

void set_pixel(uint8_t pixel_num, color_t color, uint8_t brightness) {
  if (pixel_num > NUM_NEOPIXEL - 1 || pixel_num < 0) {
    ESP_LOGE(TAG, "Pixel Num should be between 0 to 5 for NPG-LITE!");
    return;
  }
  led_strip_hsv2rgb(color, 100, brightness, &color_r, &color_g, &color_b);
  pixels[pixel_num * 3 + 0] = color_g;
  pixels[pixel_num * 3 + 1] = color_b;
  pixels[pixel_num * 3 + 2] = color_r;
  ESP_ERROR_CHECK(
      rmt_transmit(led_chan, led_encoder, pixels, sizeof(pixels), &tx_config));
  ESP_ERROR_CHECK(rmt_tx_wait_all_done(led_chan, portMAX_DELAY));
}
