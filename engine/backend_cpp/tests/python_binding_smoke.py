import hft_engine


book = hft_engine.OrderBook(
    price_level_capacity=1_000,
    order_pool_capacity=16,
    order_id_capacity=1_000,
)

resting = book.process_order(order_id=1, price=100, quantity=10, side=1)
assert resting.status == hft_engine.OrderStatus.ACCEPTED
assert resting.resting_quantity == 10
assert resting.quantity_is_conserved()

aggressing = book.process_order(order_id=2, price=100, quantity=4, side=0)
assert aggressing.status == hft_engine.OrderStatus.ACCEPTED
assert aggressing.executed_quantity == 4
assert aggressing.quantity_is_conserved()
assert book.get_best_ask_volume() == 6

execution = book.execute_order(order_id=1, quantity=2)
assert execution.status == hft_engine.ExecutionStatus.EXECUTED
assert execution.remaining_order_quantity == 4

duplicate = book.process_order(order_id=1, price=101, quantity=1, side=1)
assert duplicate.status == hft_engine.OrderStatus.DUPLICATE_ORDER_ID
assert duplicate.rejected_quantity == 1

print("Python binding smoke test passed")
