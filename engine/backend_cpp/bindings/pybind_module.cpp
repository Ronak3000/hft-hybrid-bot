#include <pybind11/pybind11.h>
#include <pybind11/stl.h> // Required for std::pair and std::string conversion
#include "matching_engine.h"

namespace py = pybind11;

PYBIND11_MODULE(hft_engine, m) {
    // Structure Exposure
    py::class_<ASQuotes>(m, "ASQuotes")
        .def_readonly("bid_price", &ASQuotes::bid_price)
        .def_readonly("ask_price", &ASQuotes::ask_price)
        .def_readonly("reservation_price", &ASQuotes::reservation_price);

    // Class and Method Exposure
    py::class_<OrderBook>(m, "OrderBook")
        .def(py::init<>())
        .def("load_history_csv", &OrderBook::load_history_csv, "Load tick data straight into RAM")
        .def("get_as_quotes", &OrderBook::get_as_quotes, "Calculate Avellaneda-Stoikov quotes")
        .def("advance_tick", &OrderBook::advance_tick, "Step the simulation forward 1 microsecond")
        .def("reset_cache", &OrderBook::reset_cache, "Reset the historical data pointers for a new RL episode")
        .def("get_obi", &OrderBook::get_obi, "Calculate real-time Level-1 Order Book Imbalance (-1.0 to +1.0)");
}