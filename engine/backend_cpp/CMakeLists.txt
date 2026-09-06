cmake_minimum_required(VERSION 3.15)
project(apexhft_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(apexhft_engine_headers INTERFACE)
target_include_directories(apexhft_engine_headers INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)

option(APEXHFT_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)

function(apexhft_configure_target target_name)
    target_link_libraries(${target_name} PRIVATE apexhft_engine_headers)
    if(MINGW)
        if(APEXHFT_ENABLE_SANITIZERS)
            target_link_options(${target_name} PRIVATE -static-libgcc -static-libstdc++ -static-libasan -static-libubsan)
        else()
            # Avoid loading Git for Windows' incompatible MinGW runtime from PATH.
            target_link_options(${target_name} PRIVATE -static -static-libgcc -static-libstdc++)
        endif()
    endif()
endfunction()

if(MSVC)
    target_compile_options(apexhft_engine_headers INTERFACE /W4)
else()
    target_compile_options(apexhft_engine_headers INTERFACE -Wall -Wextra -Wpedantic)
    target_compile_definitions(apexhft_engine_headers INTERFACE
        $<$<CONFIG:Debug>:_GLIBCXX_ASSERTIONS>)
endif()

if(APEXHFT_ENABLE_SANITIZERS)
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(apexhft_engine_headers INTERFACE
            -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(apexhft_engine_headers INTERFACE -fsanitize=address,undefined)
    else()
        message(FATAL_ERROR "APEXHFT_ENABLE_SANITIZERS requires GCC or Clang")
    endif()
endif()

option(APEXHFT_BUILD_PYTHON "Build the Pybind11 Python extension" ON)
option(APEXHFT_BUILD_BENCHMARKS "Build synthetic microbenchmarks" ON)
include(CTest)

if(APEXHFT_BUILD_PYTHON)
    set(PYBIND11_FINDPYTHON ON)
    find_package(Python REQUIRED COMPONENTS Interpreter Development)
    find_package(pybind11 CONFIG REQUIRED)

    pybind11_add_module(hft_engine bindings/pybind_module.cpp)
    apexhft_configure_target(hft_engine)

    if(BUILD_TESTING)
        add_test(
            NAME python_binding_smoke
            COMMAND ${Python_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/python_binding_smoke.py)
        set_tests_properties(python_binding_smoke PROPERTIES
            ENVIRONMENT "PYTHONPATH=$<TARGET_FILE_DIR:hft_engine>")
    endif()
endif()

if(BUILD_TESTING)
    add_executable(engine_correctness_tests tests/engine_correctness_tests.cpp)
    apexhft_configure_target(engine_correctness_tests)
    add_test(NAME engine_correctness COMMAND engine_correctness_tests)
endif()

if(APEXHFT_BUILD_BENCHMARKS)
    add_executable(engine_benchmark tests/engine_benchmark.cpp)
    apexhft_configure_target(engine_benchmark)
endif()
