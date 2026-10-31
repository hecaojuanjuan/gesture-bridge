#include "hv_face_landmarks.h"
#include <math.h>
#include <stdint.h>
#include <string.h>

bool hv_face_eye_points(const int *points, size_t length, unsigned faces,
                        unsigned width, unsigned height, float score,
                        hv_face_eyes_t *eyes)
{
  if (!eyes) return false;
  memset(eyes, 0, sizeof(*eyes));
  if (!points || length < 10 || faces != 1 || !width || !height ||
      !isfinite(score) || score < 0.5f || score > 1.0f) return false;
  /* Require both eyes and nose inside the image, as with the COCO backend. */
  const unsigned offsets[] = {0, 4, 6};
  for (unsigned i = 0; i < sizeof(offsets) / sizeof(*offsets); ++i) {
    unsigned k = offsets[i];
    if (points[k] <= 0 || points[k + 1] <= 0 ||
        (unsigned)points[k] >= width || (unsigned)points[k + 1] >= height)
      return false;
  }
  eyes->x1 = (float)points[0]; eyes->y1 = (float)points[1];
  eyes->x2 = (float)points[6]; eyes->y2 = (float)points[7];
  return true;
}

bool hv_face_box_center(const int *box, size_t length, unsigned width,
                        unsigned height, float *x, float *y)
{
  if (!x || !y) return false;
  *x = *y = 0;
  if (!box || length < 4 || !width || !height ||
      box[2] <= box[0] || box[3] <= box[1]) return false;
  if ((int64_t)box[2] - box[0] > (int64_t)width * 2 ||
      (int64_t)box[3] - box[1] > (int64_t)height * 2) return false;
  float centerX = ((float)box[0] + (float)box[2]) * 0.5f;
  float centerY = ((float)box[1] + (float)box[3]) * 0.5f;
  if (centerX < 0 || centerY < 0 || centerX >= width || centerY >= height)
    return false;
  *x = centerX / width;
  *y = centerY / height;
  return true;
}
