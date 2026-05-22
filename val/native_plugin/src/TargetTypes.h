#pragma once

#include <cmath>

struct Vec2f {
    float x = 0.0f;
    float y = 0.0f;
};

inline float Length(Vec2f value) {
    return std::sqrt(value.x * value.x + value.y * value.y);
}

struct TargetMeasurement {
    bool valid = false;
    Vec2f offset;
};

struct AimMove {
    float x = 0.0f;
    float y = 0.0f;
};
