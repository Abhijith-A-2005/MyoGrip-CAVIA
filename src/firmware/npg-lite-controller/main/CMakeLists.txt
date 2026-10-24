idf_component_register(
    SRCS
        "main.c"
        "src/gap.c"
        "src/gatt.c"
        "src/led_strip_encoder.c"
        "src/neopixel.c"
        "src/myogrip_fsm.c"
        "src/myogrip_selftest.c"
        "src/emg_signal.c"
        "src/emg_calibration.c"

    PRIV_REQUIRES
        bt
        nvs_flash
        esp_driver_gpio
        esp_adc
        esp_pm
        esp_driver_rmt

    INCLUDE_DIRS
        "./include"
)