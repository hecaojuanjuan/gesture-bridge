#ifndef HV_PANEL_H
#define HV_PANEL_H
#include <stdbool.h>
#include <stdint.h>
#include "qm_spec_api.h"
#ifndef HV_PANEL_SIID
#define HV_PANEL_SIID 12
#endif
int hv_panel_init(void);
/* True only for the reserved command property (SIID / PIID 1). */
bool hv_panel_on_property(qm_spec_property_t *property);
void hv_panel_status_light(uint8_t r, uint8_t g, uint8_t b);
/* Publish while the producer serializes its epoch change. Lock order is
 * producer guard -> panel guard; this short copy never calls the producer,
 * allocates, serializes JSON, or performs I/O. */
void hv_panel_pose_epoch(unsigned epoch);
/* tracking describes eye-point quality; eligible is the core's freshness and
 * epoch decision. Old-epoch results remain ineligible even if delivered late. */
void hv_panel_pose(unsigned stage, uint64_t captured, unsigned people, float tilt,
                   bool tracking, bool eligible, unsigned inferenceMs, unsigned epoch);
#endif
