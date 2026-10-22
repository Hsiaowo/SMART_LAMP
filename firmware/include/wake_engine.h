#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>

namespace lamp {

struct Plan {
    uint32_t version = 0;
    bool enabled = false;
    std::string occurrence;
    int64_t rampStart = 0;
    int64_t wakeAt = 0;
    int64_t holdUntil = 0;
    float peak = 0;
};

struct Output {
    const char* state;
    float brightness;
};

inline bool valid(const Plan& p) {
    return !p.enabled || (
        !p.occurrence.empty() && p.occurrence.size() <= 100 &&
        p.rampStart > 0 && p.rampStart < p.wakeAt && p.wakeAt < p.holdUntil &&
        p.wakeAt - p.rampStart <= 2700000 && p.holdUntil - p.wakeAt <= 3600000 &&
        std::isfinite(p.peak) && p.peak >= 1 && p.peak <= 100
    );
}

inline Output evaluate(const Plan& p, int64_t nowMs, bool clockValid,
                       const std::string& completed) {
    if (!valid(p)) return {"fault", 0};
    if (!clockValid) return {"needs_time", 0};
    if (!p.enabled) return {"idle", 0};
    if (completed == p.occurrence) return {"done", 0};
    if (nowMs < p.rampStart) return {"armed", 0};
    if (nowMs < p.wakeAt) {
        const double ratio = static_cast<double>(nowMs - p.rampStart) /
                             static_cast<double>(p.wakeAt - p.rampStart);
        return {"ramping", static_cast<float>(p.peak * ratio)};
    }
    if (nowMs < p.holdUntil) return {"holding", p.peak};
    return {"done", 0};
}

inline uint32_t crc32(const std::string& text) {
    uint32_t crc = 0xFFFFFFFFu;
    for (const unsigned char ch : text) {
        crc ^= ch;
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return crc ^ 0xFFFFFFFFu;
}

}  // namespace lamp

