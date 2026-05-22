#include "OutputScheduler.h"

#include <algorithm>
#include <cmath>

namespace {
constexpr float kResidualKeep = 0.35f;
constexpr float kResidualCap = 1.25f;
}

OutputScheduler::OutputScheduler(Config config)
    : config_(config) {}

void OutputScheduler::SetMove(AimMove move) {
    std::lock_guard<std::mutex> guard(mutex_);
    if (move.x == 0.0f && move.y == 0.0f) {
        pending_ = {};
        ticksRemaining_ = 0;
        return;
    }

    AimMove next = move;
    if (ticksRemaining_ > 0) {
        if (SameDirection(next.x, pending_.x)) {
            next.x += pending_.x * kResidualKeep;
        }
        if (SameDirection(next.y, pending_.y)) {
            next.y += pending_.y * kResidualKeep;
        }
    }

    next.x = CapResidual(next.x, move.x);
    next.y = CapResidual(next.y, move.y);
    pending_ = next;
    ticksRemaining_ = std::max(ticksRemaining_, std::max(config_.aimOutputBlendTicks, 1));
}

AimMove OutputScheduler::TakeNextMove() {
    std::lock_guard<std::mutex> guard(mutex_);
    if (ticksRemaining_ <= 0) {
        return {};
    }

    AimMove move;
    move.x = pending_.x / static_cast<float>(ticksRemaining_);
    move.y = pending_.y / static_cast<float>(ticksRemaining_);
    pending_.x -= move.x;
    pending_.y -= move.y;
    --ticksRemaining_;

    if (ticksRemaining_ <= 0) {
        pending_ = {};
    }

    return move;
}

void OutputScheduler::Clear() {
    std::lock_guard<std::mutex> guard(mutex_);
    pending_ = {};
    ticksRemaining_ = 0;
}

bool OutputScheduler::SameDirection(float a, float b) {
    return a == 0.0f || b == 0.0f || (a > 0.0f) == (b > 0.0f);
}

float OutputScheduler::CapResidual(float value, float requested) {
    const float limit = std::max(std::abs(requested) * kResidualCap, 1.0f);
    return std::min(std::max(value, -limit), limit);
}
