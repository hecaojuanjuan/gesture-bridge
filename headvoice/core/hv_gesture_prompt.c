#include "hv_gesture_prompt.h"

#include <stdio.h>
#include <string.h>

size_t hv_gesture_prompt(hv_hand_gate_event_t event,
                         const hv_gesture_dictionary_t *dictionary,
                         char *output, size_t capacity)
{
  if (!output || !capacity) return 0;
  output[0] = '\0';
  if (!dictionary) return 0;
  const char *meaning = event == HV_HAND_GATE_EVENT_OPEN_PALM ? dictionary->open_palm :
                        event == HV_HAND_GATE_EVENT_V_SIGN ? dictionary->v_sign : NULL;
  if (!meaning || !meaning[0] || strlen(meaning) >= HV_GESTURE_MEANING_BYTES) return 0;
  int length = snprintf(output, capacity,
    "用户通过已完成稳定识别的手势表达了个人词典中的固定意图。"
    "以下原句是用户表达的内容，请保留其含义，用一句简短、自然的中文回应。"
    "不要重新解释手势，不要添加用户未表达的需求，不要声称已完成现实中的操作。"
    "原句：%s", meaning);
  if (length < 0 || (size_t)length >= capacity) {
    output[0] = '\0';
    return 0;
  }
  return (size_t)length;
}
