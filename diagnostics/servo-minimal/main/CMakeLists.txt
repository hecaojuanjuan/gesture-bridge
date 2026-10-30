idf_component_register(SRCS "servo_minimal.c" INCLUDE_DIRS "."
                       REQUIRES esp_driver_gpio esp_driver_ledc esp_driver_uart esp_timer)
