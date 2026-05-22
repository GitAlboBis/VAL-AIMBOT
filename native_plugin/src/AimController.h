#pragma once

#include "Config.h"
#include "TargetTypes.h"

class AimController {
public:
    explicit AimController(Config config);

    AimMove Calculate(bool active, TargetMeasurement target);
    AimMove ApplyRecoil(bool recoilEnabled, bool leftButtonDown, float deltaSeconds, AimMove current);
    void Reset();

private:
    enum class AimState {
        Acquire,
        Track,
        Lock
    };

    static float Clamp(float value, float low, float high);
    static float LimitToError(float move, float error);
    AimMove ClampStep(AimMove move) const;

    Config config_;
    AimState state_ = AimState::Acquire;
    AimMove previous_;
    Vec2f previousTarget_;
    float recoilOffset_ = 0.0f;
    AimMove recoilMove_;
};
