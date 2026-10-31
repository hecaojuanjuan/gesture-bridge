get_filename_component(headvoice_root "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(HEADVOICE_STAGE 3 CACHE STRING "1=camera, 2=pose and voice, 3=expression")
set(HEADVOICE_ROTATE_CW90 0 CACHE STRING "Rotate mounted camera clockwise")
set(HEADVOICE_INVERT_TILT 0 CACHE STRING "Swap signed A and B")
set(HEADVOICE_GIMBAL 0 CACHE STRING "Build the on-demand gimbal controller")
set(HEADVOICE_VISION coco CACHE STRING "Vision backend: coco, face or hand")
set(HEADVOICE_FACE_SELFTEST 0 CACHE STRING "Run an isolated official face fixture before camera inference")
set(HEADVOICE_HAND_WEIGHTS_FILE "" CACHE FILEPATH "Explicit trained hand classifier header; empty keeps detection-only")
set(HEADVOICE_HAND_NATIVE_PARTITION "" CACHE STRING "Existing data partition containing the pinned ESP-DL hand gesture model; empty disables native classifier")
if(NOT HEADVOICE_VISION MATCHES "^(coco|face|hand)$")
  message(FATAL_ERROR "HEADVOICE_VISION must be coco, face or hand")
endif()
if(HEADVOICE_GIMBAL AND NOT HEADVOICE_VISION STREQUAL "coco")
  message(FATAL_ERROR "The gimbal requires the COCO body pose backend")
endif()
if(HEADVOICE_VISION STREQUAL "hand" AND NOT HEADVOICE_STAGE STREQUAL "2")
  message(FATAL_ERROR "Hand recognition currently requires stage 2")
endif()
if(HEADVOICE_HAND_NATIVE_PARTITION AND (NOT HEADVOICE_VISION STREQUAL "hand" OR HEADVOICE_HAND_WEIGHTS_FILE))
  message(FATAL_ERROR "Native hand classification requires the hand backend without custom CNN weights")
endif()
if(HEADVOICE_FACE_SELFTEST AND (NOT HEADVOICE_VISION STREQUAL "face" OR NOT HEADVOICE_STAGE STREQUAL "2"))
  message(FATAL_ERROR "Face selftest is only supported by the diagnostic face stage 2 build")
endif()
if(HEADVOICE_FACE_SELFTEST)
  set(hv_face_fixture "${CMAKE_CURRENT_SOURCE_DIR}/hv_fixtures/human_face.jpg")
  file(SHA256 "${hv_face_fixture}" hv_face_fixture_sha256)
  if(NOT hv_face_fixture_sha256 STREQUAL "65d23c18bd5d75370d3eff48130ac441b99f9ffd75bbfd6eff4c9ae0d8b4d68a")
    message(FATAL_ERROR "Official face selftest fixture SHA256 mismatch")
  endif()
  target_add_binary_data(${COMPONENT_LIB} "${hv_face_fixture}" BINARY RENAME_TO hv_face_selftest_jpg)
endif()
set(hv_face_backend 0)
if(HEADVOICE_VISION STREQUAL "face")
  set(hv_face_backend 1)
  target_sources(${COMPONENT_LIB} PRIVATE
    "${headvoice_root}/core/hv_face_landmarks.c"
    "${headvoice_root}/firmware/hv_face_pose.cpp")
endif()
if(NOT HEADVOICE_STAGE MATCHES "^[123]$")
  message(FATAL_ERROR "HEADVOICE_STAGE must be 1, 2 or 3")
endif()
target_compile_definitions(${COMPONENT_LIB} PRIVATE
  HV_STAGE=${HEADVOICE_STAGE}
  HV_FACE_BACKEND=${hv_face_backend}
  HV_FACE_SELFTEST=${HEADVOICE_FACE_SELFTEST}
  HV_VISION_BACKEND_NAME="${HEADVOICE_VISION}"
  HV_ROTATE_CW90=${HEADVOICE_ROTATE_CW90}
  HV_INVERT_TILT=${HEADVOICE_INVERT_TILT})
if(NOT QM_POSE_SUPPORT OR NOT LJYD_PLAYBACK_SUPPORT)
  message(FATAL_ERROR "HeadVoice requires the upstream pose and audio components")
endif()
target_sources(${COMPONENT_LIB} PRIVATE "${headvoice_root}/firmware/hv_camera_preview.c")
if(HEADVOICE_VISION STREQUAL "hand")
  target_sources(${COMPONENT_LIB} PRIVATE
    "${headvoice_root}/firmware/hv_hand_app.c"
    "${headvoice_root}/firmware/hv_hand_detect.cpp"
    "${headvoice_root}/core/hv_hand_classifier.c"
    "${headvoice_root}/core/hv_hand_gate.c")
  if(HEADVOICE_HAND_NATIVE_PARTITION)
    if(NOT HEADVOICE_HAND_NATIVE_PARTITION MATCHES "^[a-zA-Z0-9_][a-zA-Z0-9_-]*$")
      message(FATAL_ERROR "Invalid hand model partition label")
    endif()
    partition_table_get_partition_info(hv_native_model_size
      "--partition-name ${HEADVOICE_HAND_NATIVE_PARTITION}" "size")
    partition_table_get_partition_info(hv_native_model_type
      "--partition-name ${HEADVOICE_HAND_NATIVE_PARTITION}" "type")
    if(NOT hv_native_model_type EQUAL 1 OR NOT hv_native_model_size OR hv_native_model_size LESS 788608)
      message(FATAL_ERROR "The selected existing data partition must hold the 788608-byte gesture model")
    endif()
    set(hv_native_model "${headvoice_root}/third_party/hand_gesture_recognition/models/s3/mobilenetv2_0_5_128_128_gesture.espdl")
    file(SHA256 "${hv_native_model}" hv_native_model_sha)
    if(NOT hv_native_model_sha STREQUAL "52e18ceb0845121b4c0fa63aa06d69d17068c8c8135f43a7943a11812ac595d0")
      message(FATAL_ERROR "Pinned native gesture model SHA256 mismatch")
    endif()
    # No esptool flash target here: the deployment must first back up and
    # verify this existing partition. The model is never embedded in rodata.
    target_sources(${COMPONENT_LIB} PRIVATE "${headvoice_root}/firmware/hv_hand_native_classifier.cpp")
    target_compile_definitions(${COMPONENT_LIB} PRIVATE
      HV_HAND_NATIVE_CLASSIFIER=1 HV_HAND_NATIVE_PARTITION="${HEADVOICE_HAND_NATIVE_PARTITION}")
    foreach(hv_native_dep IN ITEMS esp-dl esp_partition mbedtls esp_timer)
      idf_component_get_property(hv_native_dep_lib ${hv_native_dep} COMPONENT_LIB)
      target_link_libraries(${COMPONENT_LIB} PUBLIC ${hv_native_dep_lib})
    endforeach()
  endif()
  if(HEADVOICE_HAND_WEIGHTS_FILE)
    if(NOT EXISTS "${HEADVOICE_HAND_WEIGHTS_FILE}")
      message(FATAL_ERROR "The explicit hand weights file does not exist")
    endif()
    target_compile_definitions(${COMPONENT_LIB} PRIVATE
      HV_HAND_WEIGHTS_HEADER="${HEADVOICE_HAND_WEIGHTS_FILE}")
  endif()
elseif(HEADVOICE_GIMBAL)
  target_sources(${COMPONENT_LIB} PRIVATE
    "${headvoice_root}/core/hv_gimbal_core.c"
    "${headvoice_root}/firmware/hv_gimbal_app.c")
else()
  target_sources(${COMPONENT_LIB} PRIVATE
    "${headvoice_root}/core/hv_core.c"
    "${headvoice_root}/firmware/headvoice_app.c")
  if(HEADVOICE_VISION STREQUAL "face" AND HEADVOICE_STAGE STREQUAL "2")
    target_sources(${COMPONENT_LIB} PRIVATE
      "${headvoice_root}/core/hv_gimbal_core.c"
      "${headvoice_root}/firmware/hv_face_gimbal.c")
  endif()
endif()
# The upstream test-camera macro stays off: HeadVoice owns stream startup.
target_sources(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/peripheral/bsp_camera.c")
target_include_directories(${COMPONENT_LIB} PRIVATE
  "${headvoice_root}/core" "${headvoice_root}/firmware")
idf_component_get_property(video_lib espressif__esp_video COMPONENT_LIB)
idf_component_get_property(sensor_lib espressif__esp_cam_sensor COMPONENT_LIB)
target_link_libraries(${COMPONENT_LIB} PUBLIC ${video_lib} ${sensor_lib})
foreach(code IN ITEMS AA AB BA BB)
  target_add_binary_data(${COMPONENT_LIB}
    "${headvoice_root}/audio/${code}.pcm" BINARY RENAME_TO hv_${code}_pcm)
endforeach()
