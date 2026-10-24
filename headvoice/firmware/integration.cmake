get_filename_component(headvoice_root "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(HEADVOICE_STAGE 3 CACHE STRING "1=camera, 2=pose and voice, 3=expression")
set(HEADVOICE_ROTATE_CW90 0 CACHE STRING "Rotate mounted camera clockwise")
set(HEADVOICE_INVERT_TILT 0 CACHE STRING "Swap signed A and B")
if(NOT HEADVOICE_STAGE MATCHES "^[123]$")
  message(FATAL_ERROR "HEADVOICE_STAGE must be 1, 2 or 3")
endif()
target_compile_definitions(${COMPONENT_LIB} PRIVATE
  HV_STAGE=${HEADVOICE_STAGE}
  HV_ROTATE_CW90=${HEADVOICE_ROTATE_CW90}
  HV_INVERT_TILT=${HEADVOICE_INVERT_TILT})
if(NOT QM_POSE_SUPPORT OR NOT LJYD_PLAYBACK_SUPPORT)
  message(FATAL_ERROR "HeadVoice requires the upstream pose and audio components")
endif()
target_sources(${COMPONENT_LIB} PRIVATE
  "${headvoice_root}/core/hv_core.c"
  "${headvoice_root}/firmware/headvoice_app.c")
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
