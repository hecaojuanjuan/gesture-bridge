#ifndef HV_FACE_LANDMARKS_H
#define HV_FACE_LANDMARKS_H
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  float x1, y1, x2, y2;
} hv_face_eyes_t;

/* MNP v1's order is eye, mouth, nose, eye, mouth (five x/y pairs).
 * A face detector counts visible faces, not every person in the scene. */
bool hv_face_eye_points(const int *points, size_t length, unsigned faces,
                        unsigned width, unsigned height, float score,
                        hv_face_eyes_t *eyes);

/* Use the whole face box for camera centering. A detector may return a box
 * that extends beyond one image edge; its center must remain in the image.
 * The eye line remains the separate input for posture recognition. */
bool hv_face_box_center(const int *box, size_t length, unsigned width,
                        unsigned height, float *x, float *y);

#ifdef __cplusplus
}
#endif
#endif
