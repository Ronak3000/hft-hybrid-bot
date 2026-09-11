#include <algorithm>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <string>
#include <string_view>
#include <system_error>
#include <thread>
#include <vector>

#include "matching_engine.h"

namespace {

using Clock = std::chrono::steady_clock;

struct Options {
    std::uint64_t measured_actions = 1'000'000;
    std::uint64_t warmup_actions = 20'000;
    std::uint64_t batch_size = 256;
    std::uint64_t seed = 42;
};

struct OutcomeCounts {
    std::uint64_t attempted_crosses = 0;
    std::uint64_t successful_crosses = 0;
    std::uint64_t attempted_cancels = 0;
    std::uint64_t successful_cancels = 0;
    std::uint64_t accepted_orders = 0;
    std::uint64_t rejected_orders = 0;
};

[[noreturn]] void fail(const std::string_view message) {
    std::cerr << "engine_latency_benchmark: " << message << '\n';
    std::exit(2);
}

std::uint64_t parse_positive(const char* text, const std::string_view name) {
    std::uint64_t value = 0;
    const std::string_view input(text);
    const auto [end, error] = std::from_chars(
        input.data(), input.data() + input.size(), value
    );
    if (error != std::errc{} || end != input.data() + input.size() || value == 0) {
        fail(std::string(name) + " must be a positive integer");
    }
    return value;
}

Options parse_options(const int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; index += 2) {
        if (index + 1 >= argc) {
            fail("every option requires a value");
        }
        const std::string_view name(argv[index]);
        const std::uint64_t value = parse_positive(argv[index + 1], name);
        if (name == "--actions") {
            options.measured_actions = value;
        } else if (name == "--warmup-actions") {
            options.warmup_actions = value;
        } else if (name == "--batch-size") {
            options.batch_size = value;
        } else if (name == "--seed") {
            options.seed = value;
        } else {
            fail(std::string("unknown option: ") + std::string(name));
        }
    }
    if (options.batch_size > options.measured_actions) {
        fail("--batch-size must not exceed --actions");
    }
    return options;
}

const char* compiler_name() {
#if defined(__clang__)
    return "Clang";
#elif defined(__GNUC__)
    return "GNU";
#elif defined(_MSC_VER)
    return "MSVC";
#else
    return "unknown";
#endif
}

const char* compiler_version() {
#if defined(__clang__)
    return __clang_version__;
#elif defined(__GNUC__)
    return __VERSION__;
#elif defined(_MSC_FULL_VER)
#define APEXHFT_STRINGIFY_INNER(value) #value
#define APEXHFT_STRINGIFY(value) APEXHFT_STRINGIFY_INNER(value)
    return APEXHFT_STRINGIFY(_MSC_FULL_VER);
#else
    return "unknown";
#endif
}

const char* architecture_name() {
#if defined(__x86_64__) || defined(_M_X64)
    return "x86_64";
#elif defined(__aarch64__) || defined(_M_ARM64)
    return "aarch64";
#elif defined(__i386__) || defined(_M_IX86)
    return "x86";
#else
    return "unknown";
#endif
}

const char* build_mode() {
#ifdef NDEBUG
    return "release";
#else
    return "debug";
#endif
}

const char* instruction_set() {
#if defined(__AVX512F__)
    return "AVX-512F";
#elif defined(__AVX2__)
    return "AVX2";
#elif defined(__AVX__)
    return "AVX";
#elif defined(__SSE4_2__)
    return "SSE4.2";
#elif defined(__SSE2__) || defined(_M_X64)
    return "SSE2";
#elif defined(__ARM_NEON) || defined(__ARM_NEON__)
    return "NEON";
#else
    return "baseline/unknown";
#endif
}

double nearest_rank_percentile(
    const std::vector<double>& sorted_values, const double probability
) {
    const auto rank = static_cast<std::size_t>(
        std::ceil(probability * static_cast<double>(sorted_values.size()))
    );
    const auto index = std::min(
        std::max<std::size_t>(rank, 1) - 1, sorted_values.size() - 1
    );
    return sorted_values[index];
}

void apply_action(
    OrderBook& engine,
    const std::uint64_t operation_index,
    const std::uint64_t target_price,
    const int side,
    std::uint64_t& next_order_id,
    OutcomeCounts& counts,
    std::uint64_t& checksum
) {
    if (operation_index % 10 == 0) {
        const int opposite_best = side == 0
            ? engine.get_best_ask()
            : engine.get_best_bid();
        const std::uint64_t crossing_price = opposite_best != -1
            ? static_cast<std::uint64_t>(opposite_best)
            : (side == 0
                   ? target_price + 5
                   : (target_price > 5 ? target_price - 5 : 1));
        const ProcessResult result = engine.process_order(
            next_order_id++, crossing_price, 5, side
        );
        ++counts.attempted_crosses;
        counts.successful_crosses += result.executed_quantity > 0;
        counts.accepted_orders += result.fully_accepted();
        counts.rejected_orders += !result.fully_accepted();
        checksum ^= result.executed_quantity + result.resting_quantity;
    } else if (operation_index % 5 == 0) {
        const std::uint64_t cancel_id = next_order_id > 20'000
            ? next_order_id - 15'000
            : 1;
        ++counts.attempted_cancels;
        counts.successful_cancels += engine.cancel_order(cancel_id);
        checksum ^= cancel_id;
    } else {
        const ProcessResult result = engine.process_order(
            next_order_id++, target_price, 15, side
        );
        counts.accepted_orders += result.fully_accepted();
        counts.rejected_orders += !result.fully_accepted();
        checksum ^= result.executed_quantity + result.resting_quantity;
    }
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_options(argc, argv);
    if (options.warmup_actions >
        std::numeric_limits<std::uint64_t>::max() - options.measured_actions) {
        fail("warmup and measured action counts overflow uint64_t");
    }
    const std::uint64_t generated_actions =
        options.warmup_actions + options.measured_actions;
    std::mt19937_64 rng(options.seed);
    std::uniform_int_distribution<std::uint64_t> price_distribution(10'000, 900'000);
    std::uniform_int_distribution<int> side_distribution(0, 1);
    std::vector<std::uint64_t> prices(generated_actions);
    std::vector<std::uint8_t> sides(generated_actions);
    for (std::uint64_t index = 0; index < generated_actions; ++index) {
        prices[index] = price_distribution(rng);
        sides[index] = static_cast<std::uint8_t>(side_distribution(rng));
    }

    OrderBook engine;
    for (std::uint64_t index = 0; index < 50'000; ++index) {
        engine.process_order(
            index,
            price_distribution(rng),
            10,
            side_distribution(rng)
        );
    }

    OutcomeCounts warmup_counts;
    OutcomeCounts measured_counts;
    std::uint64_t next_order_id = 100'000;
    std::uint64_t checksum = 0;
    for (std::uint64_t index = 0; index < options.warmup_actions; ++index) {
        apply_action(
            engine,
            index,
            prices[index],
            sides[index],
            next_order_id,
            warmup_counts,
            checksum
        );
    }

    std::vector<double> amortized_batch_ns;
    amortized_batch_ns.reserve(
        static_cast<std::size_t>(
            (options.measured_actions + options.batch_size - 1) / options.batch_size
        )
    );
    std::uint64_t completed = 0;
    const auto suite_start = Clock::now();
    while (completed < options.measured_actions) {
        const std::uint64_t count = std::min(
            options.batch_size, options.measured_actions - completed
        );
        const auto batch_start = Clock::now();
        for (std::uint64_t offset = 0; offset < count; ++offset) {
            const std::uint64_t measured_index = completed + offset;
            const std::uint64_t source_index = options.warmup_actions + measured_index;
            apply_action(
                engine,
                measured_index,
                prices[source_index],
                sides[source_index],
                next_order_id,
                measured_counts,
                checksum
            );
        }
        const auto batch_end = Clock::now();
        const double elapsed_ns = static_cast<double>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                batch_end - batch_start
            ).count()
        );
        amortized_batch_ns.push_back(elapsed_ns / static_cast<double>(count));
        completed += count;
    }
    const auto suite_end = Clock::now();

    std::sort(amortized_batch_ns.begin(), amortized_batch_ns.end());
    const double total_ns = static_cast<double>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            suite_end - suite_start
        ).count()
    );
    const double mean_ns = total_ns / static_cast<double>(options.measured_actions);
    const double actions_per_second =
        static_cast<double>(options.measured_actions) * 1'000'000'000.0 / total_ns;

    std::cout << std::fixed << std::setprecision(3)
              << "{\n"
              << "  \"benchmark_schema_version\": 1,\n"
              << "  \"name\": \"mixed_in_process_engine_actions_latency\",\n"
              << "  \"measurement\": \"amortized latency of independently timed action batches\",\n"
              << "  \"clock\": \"std::chrono::steady_clock\",\n"
              << "  \"percentile_method\": \"nearest-rank over per-batch ns/action samples\",\n"
              << "  \"compiler\": {\"name\": \"" << compiler_name()
              << "\", \"version\": \"" << compiler_version() << "\"},\n"
              << "  \"build\": {\"mode\": \"" << build_mode()
              << "\", \"cpp_standard\": " << __cplusplus
              << ", \"architecture\": \"" << architecture_name()
              << "\", \"instruction_set\": \"" << instruction_set() << "\"},\n"
              << "  \"logical_hardware_threads\": "
              << std::thread::hardware_concurrency() << ",\n"
              << "  \"rng_seed\": " << options.seed << ",\n"
              << "  \"warmup_actions\": " << options.warmup_actions << ",\n"
              << "  \"measured_actions\": " << options.measured_actions << ",\n"
              << "  \"batch_size\": " << options.batch_size << ",\n"
              << "  \"batch_samples\": " << amortized_batch_ns.size() << ",\n"
              << "  \"latency_ns_per_action\": {\"mean\": " << mean_ns
              << ", \"p50\": " << nearest_rank_percentile(amortized_batch_ns, 0.50)
              << ", \"p99\": " << nearest_rank_percentile(amortized_batch_ns, 0.99)
              << ", \"p99_9\": " << nearest_rank_percentile(amortized_batch_ns, 0.999)
              << "},\n"
              << "  \"observed_actions_per_second\": " << actions_per_second << ",\n"
              << "  \"outcomes\": {\n"
              << "    \"attempted_crosses\": " << measured_counts.attempted_crosses << ",\n"
              << "    \"successful_crosses\": " << measured_counts.successful_crosses << ",\n"
              << "    \"attempted_cancels\": " << measured_counts.attempted_cancels << ",\n"
              << "    \"successful_cancels\": " << measured_counts.successful_cancels << ",\n"
              << "    \"fully_accepted_orders\": " << measured_counts.accepted_orders << ",\n"
              << "    \"partially_or_fully_rejected_orders\": " << measured_counts.rejected_orders << ",\n"
              << "    \"final_active_orders\": " << engine.get_active_order_count() << "\n"
              << "  },\n"
              << "  \"state_checksum\": " << checksum << "\n"
              << "}\n";
    return 0;
}
