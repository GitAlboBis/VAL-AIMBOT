#include "AimController.h"

#include <algorithm>
#include <cmath>

namespace {
constexpr float kLockEpsilon = 0.55f;
constexpr float kLockReleaseEpsilon = 1.25f;
}

AimController::AimController(Config config)
    : config_(config) {}

AimMove AimController::Calculate(bool active, TargetMeasurement target) {
    if (!active || !target.valid) {
        Reset();
        return {};
    }

    const float targetX = target.offset.x;
    const float targetY = target.offset.y;
    const float distance = std::sqrt(targetX * targetX + targetY * targetY);

    if (distance <= kLockEpsilon) {
        previous_ = {};
        previousTarget_ = target.offset;
        state_ = AimState::Lock;
        return {};
    }

    state_ = distance <= kLockReleaseEpsilon ? AimState::Lock : AimState::Track;

    const float smoothing = Clamp(config_.aimSmoothingFactor, 0.0f, 1.0f);
    const float desiredX = targetX * config_.speed * config_.xSpeedMultiplier;
    const float desiredY = targetY * config_.speed * config_.ySpeedMultiplier;

    AimMove move;
    move.x = (1.0f - smoothing) * previous_.x + smoothing * desiredX;
    move.y = (1.0f - smoothing) * previous_.y + smoothing * desiredY;

    move.x = LimitToError(move.x, targetX);
    move.y = LimitToError(move.y, targetY);
    move = ClampStep(move);

    previous_ = move;
    previousTarget_ = target.offset;
    return move;
}

AimMove AimController::ApplyRecoil(
    bool recoilEnabled,
    bool leftButtonDown,
    float deltaSeconds,
    AimMove current) {
    if (!recoilEnabled || deltaSeconds == 0.0f) {
        recoilOffset_ = 0.0f;
        recoilMove_.x *= 0.45f;
        recoilMove_.y *= 0.45f;
        return current;
    }

    if (leftButtonDown) {
        float rawX = config_.recoilX * deltaSeconds;
        float rawY = config_.recoilY * deltaSeconds;

        if (state_ == AimState::Lock) {
            rawX *= 0.30f;
            rawY *= 0.30f;
        } else if (state_ == AimState::Track) {
            rawX *= 0.55f;
            rawY *= 0.55f;
        }

        const float recoilDistance = std::max(std::abs(rawX), std::abs(rawY));
        const float maxRecoilStep = config_.aimMaxStep * 0.6f;
        if (recoilDistance > maxRecoilStep && recoilDistance > 0.0f) {
            const float scale = maxRecoilStep / recoilDistance;
            rawX *= scale;
            rawY *= scale;
        }

        recoilMove_.x = recoilMove_.x * 0.58f + rawX * 0.42f;
        recoilMove_.y = recoilMove_.y * 0.58f + rawY * 0.42f;
        current.x += recoilMove_.x;
        current.y += recoilMove_.y;
    }

    return current;
}

void AimController::Reset() {
    previous_ = {};
    previousTarget_ = {};
    state_ = AimState::Acquire;
}

float AimController::Clamp(float value, float low, float high) {
    return std::min(std::max(value, low), high);
}

float AimController::LimitToError(float move, float error) {
    if (move == 0.0f || error == 0.0f) {
        return 0.0f;
    }

    if ((move > 0.0f) != (error > 0.0f)) {
        return 0.0f;
    }

    const float errorAbs = std::abs(error);
    const float maxFraction = errorAbs <= 6.0f ? 0.62f : 0.86f;
    const float maxMove = errorAbs * maxFraction;
    if (std::abs(move) > maxMove) {
        return move > 0.0f ? maxMove : -maxMove;
    }
    return move;
}

AimMove AimController::ClampStep(AimMove move) const {
    const float distance = std::max(std::sqrt(move.x * move.x + move.y * move.y), 1.0f);
    if (distance <= config_.aimMaxStep) {
        return move;
    }

    const float scale = config_.aimMaxStep / distance;
    move.x *= scale;
    move.y *= scale;
    return move;
}
