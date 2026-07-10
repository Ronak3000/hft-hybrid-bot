cmake_minimum_required(VERSION 3.15)
project(hft_engine)

set(PYBIND11_FINDPYTHON ON)
find_package(Python REQUIRED COMPONENTS Interpreter Development)

find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(hft_engine 
    bindings/pybind_module.cpp
)

target_include_directories(hft_engine
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

if(MINGW)
    target_link_options(hft_engine PRIVATE "-static" "-static-libgcc" "-static-libstdc++")
endif()