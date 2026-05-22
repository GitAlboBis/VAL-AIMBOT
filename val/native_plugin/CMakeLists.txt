cmake_minimum_required(VERSION 3.21)

project(UnibotPlugin LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(POLICY CMP0091)
  cmake_policy(SET CMP0091 NEW)
endif()

add_library(UnibotPlugin SHARED
  src/AimController.cpp
  src/Config.cpp
  src/DllMain.cpp
  src/Engine.cpp
  src/ImageProcessing.cpp
  src/OutputScheduler.cpp
  src/PluginApi.cpp
)

target_include_directories(UnibotPlugin
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_definitions(UnibotPlugin
  PRIVATE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    UNIBOTPLUGIN_EXPORTS
)

if(MSVC)
  set_property(TARGET UnibotPlugin PROPERTY
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
  target_compile_options(UnibotPlugin PRIVATE /W4 /permissive-)
else()
  target_compile_options(UnibotPlugin PRIVATE -Wall -Wextra -Wpedantic)
endif()

enable_testing()

add_executable(UnibotMovementTests
  tests/MovementTests.cpp
  src/AimController.cpp
  src/Config.cpp
  src/OutputScheduler.cpp
)

target_include_directories(UnibotMovementTests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_definitions(UnibotMovementTests
  PRIVATE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
)

if(MSVC)
  set_property(TARGET UnibotMovementTests PROPERTY
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
  target_compile_options(UnibotMovementTests PRIVATE /W4 /permissive-)
else()
  target_compile_options(UnibotMovementTests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_test(NAME UnibotMovementTests COMMAND UnibotMovementTests)

add_executable(UnibotVisionTests
  tests/VisionTests.cpp
  src/Config.cpp
  src/ImageProcessing.cpp
)

target_include_directories(UnibotVisionTests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_definitions(UnibotVisionTests
  PRIVATE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
)

if(MSVC)
  set_property(TARGET UnibotVisionTests PROPERTY
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
  target_compile_options(UnibotVisionTests PRIVATE /W4 /permissive-)
else()
  target_compile_options(UnibotVisionTests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_test(NAME UnibotVisionTests COMMAND UnibotVisionTests)
