#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include "wake_engine.h"

int main() {
    lamp::Plan plan;
    plan.enabled = true;
    plan.occurrence = "test:1";
    plan.rampStart = 10000;
    plan.wakeAt = 20000;
    plan.holdUntil = 30000;
    plan.peak = 80;
    auto check = [&](int64_t now, const char* state, float brightness,
                     bool clock = true, const std::string& done = "") {
        const auto out = lamp::evaluate(plan, now, clock, done);
        assert(std::string(out.state) == state);
        assert(std::abs(out.brightness - brightness) < 0.001);
    };
    check(9999, "armed", 0);
    check(10000, "ramping", 0);
    check(15000, "ramping", 40);
    check(19999, "ramping", 79.992f);
    check(20000, "holding", 80);
    check(29999, "holding", 80);
    check(30000, "done", 0);
    check(40000, "done", 0);
    check(15000, "needs_time", 0, false);
    check(15000, "done", 0, true, "test:1");
    check(15000, "ramping", 40, true, "old:1");
    plan.enabled = false;
    check(15000, "idle", 0);
    plan.enabled = true;
    plan.wakeAt = plan.rampStart;
    check(15000, "fault", 0);
    plan.wakeAt = 20000;
    plan.peak = std::numeric_limits<float>::quiet_NaN();
    check(15000, "fault", 0);
    plan.peak = 101;
    check(15000, "fault", 0);
    assert(lamp::crc32("123456789") == 0xCBF43926u);
    assert(lamp::crc32("") == 0u);
    std::cout << "PASS: firmware engine boundaries, restart guard, cancel and CRC32\n";
}

