#ifndef HV_CORE_H
#define HV_CORE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
  HV_CALIBRATING,
  HV_REARM,
  HV_COLLECT,
  HV_REVIEW_REARM,
  HV_REVIEW,
  HV_SPEAKING
} HvState;
typedef enum {
  HV_NONE,
  HV_CALIBRATED,
  HV_ACTION,
  HV_CANDIDATE,
  HV_CANCELLED,
  HV_PLAY,
  HV_RESET,
  HV_READY
} HvEvent;
typedef struct
{
  float neutralDegrees, actionDegrees, releaseDegrees, maxDegrees;
  float calibrationSpread;
  uint32_t calibrationMs, holdMs, neutralMs, maxGapMs, maxAgeMs;
  uint32_t actionTimeoutMs, comboTimeoutMs, confirmTimeoutMs;
  unsigned minSamples, calibrationSamples;
} hv_config_t;
typedef struct
{
  uint64_t capturedMs;
  float tiltDegrees;
  bool valid;
} hv_observation_t;
typedef struct
{
  HvEvent event;
  int phrase;
  char action;
  uint32_t ticket;
} hv_effect_t;
typedef struct
{
  hv_config_t config;
  HvState state;
  float baseline, calibrationSum, calibrationMin, calibrationMax;
  uint64_t lastCapture, windowStart, neutralStart, actionStart, deadline;
  uint64_t rejectThrough;
  unsigned samples, neutralSamples;
  int phase, direction, first, phrase;
  bool haveCapture, haveWindow, haveNeutral, held;
  uint32_t ticket;
} hv_core_t;

hv_config_t hv_default_config(void);
void hv_init(hv_core_t * core, const hv_config_t * config);
void hv_recalibrate(hv_core_t * core);
hv_effect_t hv_observe(hv_core_t * core, hv_observation_t observation, uint64_t nowMs);
hv_effect_t hv_tick(hv_core_t * core, uint64_t nowMs);
hv_effect_t hv_invalidate(hv_core_t * core, uint64_t nowMs);
void hv_playback_done(hv_core_t * core, uint32_t ticket, uint64_t nowMs);
const char * hv_phrase(int phrase);
const char * hv_code(int phrase);
/* Image-space eye-line orientation, folded into [-90, 90]. Not a 3D head angle. */
bool hv_eye_tilt(float x1, float y1, float x2, float y2, float * degrees);

#ifdef __cplusplus
}
#endif
#endif
