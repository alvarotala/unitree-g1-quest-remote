cmake_minimum_required(VERSION 3.10)
project(g1_quest_lowstate_diagnostic LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BUILD_UNITREE_DIAGNOSTIC "Build the PC2 DDS executable" ON)
option(BUILD_LOGIC_TESTS "Build dependency-free logic tests" ON)

add_library(g1_quest_diagnostic_logic src/diagnostic.cpp)
target_include_directories(g1_quest_diagnostic_logic PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(g1_quest_diagnostic_logic PRIVATE -Wall -Wextra -Wpedantic)

if(BUILD_LOGIC_TESTS)
  enable_testing()
  add_executable(g1_quest_diagnostic_tests tests/diagnostic_tests.cpp)
  target_link_libraries(g1_quest_diagnostic_tests PRIVATE g1_quest_diagnostic_logic)
  target_compile_definitions(g1_quest_diagnostic_tests PRIVATE
    QUEST_MAIN_SOURCE="${CMAKE_CURRENT_SOURCE_DIR}/src/main.cpp")
  target_compile_options(g1_quest_diagnostic_tests PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME g1_quest_diagnostic_tests COMMAND g1_quest_diagnostic_tests)
endif()

if(BUILD_UNITREE_DIAGNOSTIC)
  set(UNITREE_SDK_ROOT "/home/unitree/unitree_sdk2-g1"
      CACHE PATH "Existing Unitree SDK2 source directory on PC2")
  if(NOT EXISTS "${UNITREE_SDK_ROOT}/include/unitree/robot/channel/channel_subscriber.hpp")
    message(FATAL_ERROR "Invalid UNITREE_SDK_ROOT: ${UNITREE_SDK_ROOT}")
  endif()
  if(NOT EXISTS "${UNITREE_SDK_ROOT}/include/unitree/idl/hg/LowState_.hpp")
    message(FATAL_ERROR
      "UNITREE_SDK_ROOT does not contain G1/HG IDL headers: ${UNITREE_SDK_ROOT}")
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

  add_executable(g1_lowstate_diagnostic src/main.cpp)
  target_include_directories(g1_lowstate_diagnostic PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${UNITREE_SDK_ROOT}/include
    ${DDSCXX_INCLUDE_DIR}
    /usr/local/include/iceoryx/v2.0.2)
  target_link_libraries(g1_lowstate_diagnostic PRIVATE
    g1_quest_diagnostic_logic ${UNITREE_SDK_LIBRARY}
    ${DDSC_LIBRARY} ${DDSCXX_LIBRARY} rt Threads::Threads)
  target_compile_options(g1_lowstate_diagnostic PRIVATE -Wall -Wextra -Wpedantic)
endif()
