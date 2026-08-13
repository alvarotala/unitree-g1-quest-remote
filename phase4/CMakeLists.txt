cmake_minimum_required(VERSION 3.10)
project(g1_quest_phase4_safety LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BUILD_UNITREE_DRY_RUN "Build the PC2 read-only DDS dry-run" OFF)
option(BUILD_UNITREE_LOCOMOTION "Build explicit live G1 VR locomotion" OFF)

add_library(g1_quest_safety src/supervisor.cpp)
target_include_directories(g1_quest_safety PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(g1_quest_safety PRIVATE -Wall -Wextra -Wpedantic)

enable_testing()
add_executable(g1_quest_safety_tests tests/supervisor_tests.cpp)
target_link_libraries(g1_quest_safety_tests PRIVATE g1_quest_safety)
target_compile_options(g1_quest_safety_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME g1_quest_safety_tests COMMAND g1_quest_safety_tests)

add_executable(g1_quest_dry_run_source_tests tests/dry_run_source_tests.cpp)
target_compile_definitions(g1_quest_dry_run_source_tests PRIVATE
  DRY_RUN_SOURCE="${CMAKE_CURRENT_SOURCE_DIR}/src/dry_run_main.cpp")
target_compile_options(g1_quest_dry_run_source_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME g1_quest_dry_run_source_tests COMMAND g1_quest_dry_run_source_tests)

add_executable(g1_quest_locomotion_source_tests tests/locomotion_source_tests.cpp)
target_compile_definitions(g1_quest_locomotion_source_tests PRIVATE
  LOCOMOTION_SOURCE="${CMAKE_CURRENT_SOURCE_DIR}/src/locomotion_main.cpp")
target_compile_options(g1_quest_locomotion_source_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME g1_quest_locomotion_source_tests COMMAND g1_quest_locomotion_source_tests)

if(BUILD_UNITREE_DRY_RUN OR BUILD_UNITREE_LOCOMOTION)
  set(UNITREE_SDK_ROOT "/home/unitree/unitree_sdk2-g1"
      CACHE PATH "Existing Unitree SDK2 source directory on PC2")
  if(NOT EXISTS "${UNITREE_SDK_ROOT}/include/unitree/idl/hg/LowState_.hpp")
    message(FATAL_ERROR "UNITREE_SDK_ROOT does not contain G1/HG LowState")
  endif()
  set(UNITREE_SDK_LIBRARY
      "${UNITREE_SDK_ROOT}/lib/${CMAKE_SYSTEM_PROCESSOR}/libunitree_sdk2.a")
  if(NOT EXISTS "${UNITREE_SDK_LIBRARY}")
    message(FATAL_ERROR "Unitree SDK library not found: ${UNITREE_SDK_LIBRARY}")
  endif()
  find_path(DDSCXX_INCLUDE_DIR NAMES dds/dds.hpp
    PATHS /usr/local/include/ddscxx NO_DEFAULT_PATH)
  find_library(DDSC_LIBRARY NAMES ddsc)
  find_library(DDSCXX_LIBRARY NAMES ddscxx)
  if(NOT DDSCXX_INCLUDE_DIR OR NOT DDSC_LIBRARY OR NOT DDSCXX_LIBRARY)
    message(FATAL_ERROR "Existing CycloneDDS development files were not found")
  endif()
  find_package(Threads REQUIRED)

  add_executable(g1_arm_dry_run src/dry_run_main.cpp)
  target_include_directories(g1_arm_dry_run PRIVATE
    ${UNITREE_SDK_ROOT}/include ${DDSCXX_INCLUDE_DIR}
    /usr/local/include/iceoryx/v2.0.2)
  target_link_libraries(g1_arm_dry_run PRIVATE g1_quest_safety
    ${UNITREE_SDK_LIBRARY} ${DDSC_LIBRARY} ${DDSCXX_LIBRARY} rt Threads::Threads)
  target_compile_options(g1_arm_dry_run PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(BUILD_UNITREE_LOCOMOTION)
  add_executable(g1_vr_locomotion src/locomotion_main.cpp)
  target_include_directories(g1_vr_locomotion PRIVATE
    ${UNITREE_SDK_ROOT}/include ${DDSCXX_INCLUDE_DIR}
    /usr/local/include/iceoryx/v2.0.2)
  target_link_libraries(g1_vr_locomotion PRIVATE g1_quest_safety
    ${UNITREE_SDK_LIBRARY} ${DDSC_LIBRARY} ${DDSCXX_LIBRARY} rt Threads::Threads)
  target_compile_options(g1_vr_locomotion PRIVATE -Wall -Wextra -Wpedantic)
endif()
