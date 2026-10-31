#include "hv_face_landmarks.h"
#include "hv_core.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
  /* Mouth corners deliberately differ from the eye line: using indices 2/3
   * as the second eye would turn this neutral observation into a false tilt. */
  int points[10] = {80, 60, 85, 100, 100, 80, 120, 60, 115, 100};
  hv_face_eyes_t eyes; float angle;
  assert(hv_face_eye_points(points, 10, 1, 320, 240, 0.9f, &eyes));
  assert(hv_eye_tilt(eyes.x1, eyes.y1, eyes.x2, eyes.y2, &angle));
  assert(fabsf(angle) < 0.001f);
  points[7] = 70;
  assert(hv_face_eye_points(points, 10, 1, 320, 240, 0.5f, &eyes));
  assert(hv_eye_tilt(eyes.x1, eyes.y1, eyes.x2, eyes.y2, &angle));
  assert(angle > 14 && angle < 15);
  for (unsigned count = 0; count <= 2; count += 2)
    assert(!hv_face_eye_points(points, 10, count, 320, 240, 0.9f, &eyes));
  assert(!hv_face_eye_points(points, 9, 1, 320, 240, 0.9f, &eyes));
  assert(!hv_face_eye_points(points, 10, 1, 320, 240, NAN, &eyes));
  assert(!hv_face_eye_points(points, 10, 1, 320, 240, 0.49f, &eyes));
  assert(!hv_face_eye_points(NULL, 10, 1, 320, 240, 0.9f, &eyes));
  assert(!hv_face_eye_points(points, 10, 1, 0, 240, 0.9f, &eyes));
  int saved[10]; memcpy(saved, points, sizeof(points));
  const unsigned offsets[] = {0, 4, 6};
  for (unsigned i = 0; i < 3; ++i) {
    points[offsets[i]] = 320;
    assert(!hv_face_eye_points(points, 10, 1, 320, 240, 0.9f, &eyes));
    assert(eyes.x1 == 0 && eyes.y1 == 0 && eyes.x2 == 0 && eyes.y2 == 0);
    memcpy(points, saved, sizeof(points));
  }
  float x = -1, y = -1;
  int box[4] = {80, 40, 240, 200};
  assert(hv_face_box_center(box, 4, 320, 240, &x, &y));
  assert(fabsf(x - 0.5f) < 0.001f && fabsf(y - 0.5f) < 0.001f);
  box[0] = 0; box[1] = 120; box[2] = 160; box[3] = 240;
  assert(hv_face_box_center(box, 4, 320, 240, &x, &y));
  assert(fabsf(x - 0.25f) < 0.001f && fabsf(y - 0.75f) < 0.001f);
  box[0] = -10;
  assert(hv_face_box_center(box, 4, 320, 240, &x, &y));
  assert(x > 0 && x < 0.25f);
  box[0] = -400;
  assert(!hv_face_box_center(box, 4, 320, 240, &x, &y));
  assert(x == 0 && y == 0);
  box[0] = 0; box[2] = box[0];
  assert(!hv_face_box_center(box, 4, 320, 240, &x, &y));
  box[0] = -1000; box[2] = 1100;
  assert(!hv_face_box_center(box, 4, 320, 240, &x, &y));
  puts("PASS MNP eye mapping, single-face gate, score and image bounds");
}
