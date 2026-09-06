#include <pybind11/pybind11.h>
#include <pybind11/stl.h> 
#include "matching_engine.h"

namespace py = pybind11;

PYBIND11_MODULE(hft_engine, m) {
    py::enum_<Side>(m, "Side")
        .value("BUY", Side::BUY)
        .value("SELL", Side::SELL);

    py::enum_<OrderStatus>(m, "OrderStatus")
        .value("ACCEPTED", OrderStatus::ACCEPTED)
        .value("INVALID_SIDE", OrderStatus::INVALID_SIDE)
        .value("INVALID_PRICE", OrderStatus::INVALID_PRICE)
        .value("INVALID_QUANTITY", OrderStatus::INVALID_QUANTITY)
        .value("INVALID_ORDER_ID", OrderStatus::INVALID_ORDER_ID)
        .value("DUPLICATE_ORDER_ID", OrderStatus::DUPLICATE_ORDER_ID)
        .value("POOL_EXHAUSTED", OrderStatus::POOL_EXHAUSTED);

    py::class_<ProcessResult>(m, "ProcessResult")
        .def_readonly("status", &ProcessResult::status)
        .def_readonly("requested_quantity", &ProcessResult::requested_quantity)
        .def_readonly("executed_quantity", &ProcessResult::executed_quantity)
        .def_readonly("resting_quantity", &ProcessResult::resting_quantity)
        .def_readonly("rejected_quantity", &ProcessResult::rejected_quantity)
        .def("fully_accepted", &ProcessResult::fully_accepted)
        .def("quantity_is_conserved", &ProcessResult::quantity_is_conserved);

    py::enum_<ExecutionStatus>(m, "ExecutionStatus")
        .value("EXECUTED", ExecutionStatus::EXECUTED)
        .value("INVALID_ORDER_ID", ExecutionStatus::INVALID_ORDER_ID)
        .value("INVALID_QUANTITY", ExecutionStatus::INVALID_QUANTITY)
        .value("ORDER_NOT_FOUND", ExecutionStatus::ORDER_NOT_FOUND);

    py::class_<ExecutionResult>(m, "ExecutionResult")
        .def_readonly("status", &ExecutionResult::status)
        .def_readonly("requested_quantity", &ExecutionResult::requested_quantity)
        .def_readonly("executed_quantity", &ExecutionResult::executed_quantity)
        .def_readonly("unfilled_quantity", &ExecutionResult::unfilled_quantity)
        .def_readonly("remaining_order_quantity", &ExecutionResult::remaining_order_quantity);

    py::class_<ASQuotes>(m, "ASQuotes")
        .def_readonly("bid_price", &ASQuotes::bid_price)
        .def_readonly("ask_price", &ASQuotes::ask_price)
        .def_readonly("reservation_price", &ASQuotes::reservation_price);

    py::class_<OrderBook>(m, "OrderBook")
        .def(py::init<size_t, size_t, size_t>(),
             py::arg("price_level_capacity") = 1'000'000,
             py::arg("order_pool_capacity") = 1'000'000,
             py::arg("order_id_capacity") = 5'000'000)
        .def("process_order", &OrderBook::process_order,
             py::arg("order_id"), py::arg("price"), py::arg("quantity"), py::arg("side"))
        .def("cancel_order", &OrderBook::cancel_order, py::arg("order_id"))
        .def("execute_order", &OrderBook::execute_order,
             py::arg("order_id"), py::arg("quantity"))
        .def("get_best_bid", &OrderBook::get_best_bid)
        .def("get_best_ask", &OrderBook::get_best_ask)
        .def("get_best_bid_volume", &OrderBook::get_best_bid_volume)
        .def("get_best_ask_volume", &OrderBook::get_best_ask_volume)
        .def("get_active_order_count", &OrderBook::get_active_order_count)
        .def("load_history_csv", &OrderBook::load_history_csv, "Load tick data straight into RAM")
        .def("get_as_quotes", &OrderBook::get_as_quotes, "Calculate Avellaneda-Stoikov quotes")
        .def("advance_tick", &OrderBook::advance_tick, "Step the simulation forward")
        .def("reset_cache", &OrderBook::reset_cache, "Reset the historical data pointers for a new RL episode")
        .def("get_obi", &OrderBook::get_obi, "Calculate real-time Level-1 Order Book Imbalance (-1.0 to +1.0)")
        .def("inject_live_tick", &OrderBook::inject_live_tick, "Inject real-time trade tick into the engine state");
}
