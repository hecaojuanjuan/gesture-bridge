/* Diagnostic app: no camera, network, audio, or recognition startup. */
#include <stdio.h>
#include <string.h>

#include "driver/ledc.h"
#include "driver/uart.h"
#include "esp_check.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

static const int pins[2] = {17, 18};
static int active_axis = -1;
static int pulse_us;
static int64_t expires_us;

static void stop(void)
{
  for (int axis = 0; axis < 2; ++axis) {
    ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE, axis, 0));
  }
  active_axis = -1;
  pulse_us = 0;
  expires_us = 0;
}

static void status(const char * event)
{
  printf(
    "SERVO_MIN {\"event\":\"%s\",\"axis\":%d,\"pulse_us\":%d,"
    "\"uptime_ms\":%lld}\n",
    event, active_axis, pulse_us, (long long)(esp_timer_get_time() / 1000));
  fflush(stdout);
}

static void command(const char * line)
{
  char axis_name[8], extra;
  int requested;
  if (!strcmp(line, "stop")) {
    stop();
    status("stopped");
  } else if (!strcmp(line, "status")) {
    status("status");
  } else if (
    sscanf(line, "%7s %d %c", axis_name, &requested, &extra) == 2 &&
    (!strcmp(axis_name, "pan") || !strcmp(axis_name, "tilt")) && requested >= 1300 &&
    requested <= 1700) {
    int axis = !strcmp(axis_name, "pan") ? 0 : 1;
    int previous = active_axis == axis ? pulse_us : 1500;
    if (
      (active_axis != axis && requested != 1500) || requested - previous > 50 ||
      previous - requested > 50) {
      stop();
      status("rejected_step");
      return;
    }
    ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE, 1 - axis, 0));
    unsigned duty = (unsigned)requested * ((1u << 14) - 1) / 20000;
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, axis, duty));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, axis));
    active_axis = axis;
    pulse_us = requested;
    expires_us = esp_timer_get_time() + 2500000;
    status("set");
  } else {
    stop();
    status("rejected_command");
  }
}

void app_main(void)
{
  ledc_timer_config_t timer = {
    .speed_mode = LEDC_LOW_SPEED_MODE,
    .duty_resolution = LEDC_TIMER_14_BIT,
    .timer_num = LEDC_TIMER_0,
    .freq_hz = 50,
    .clk_cfg = LEDC_AUTO_CLK,
  };
  ESP_ERROR_CHECK(ledc_timer_config(&timer));
  for (int axis = 0; axis < 2; ++axis) {
    ledc_channel_config_t channel = {
      .gpio_num = pins[axis],
      .speed_mode = LEDC_LOW_SPEED_MODE,
      .channel = axis,
      .timer_sel = LEDC_TIMER_0,
      .duty = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
  }
  stop();
  ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 256, 0, 0, NULL, 0));
  status("ready");
  char line[48];
  size_t used = 0;
  bool overflow = false;
  while (true) {
    char c;
    if (uart_read_bytes(UART_NUM_0, &c, 1, pdMS_TO_TICKS(20)) == 1) {
      if (c == '\r' || c == '\n') {
        if (overflow) {
          stop();
          status("rejected_length");
        } else if (used) {
          line[used] = 0;
          command(line);
        }
        used = 0;
        overflow = false;
      } else if (used < sizeof(line) - 1) {
        line[used++] = c;
      } else {
        overflow = true;
      }
    }
    if (expires_us && esp_timer_get_time() >= expires_us) {
      stop();
      status("lease_expired");
    }
  }
}
