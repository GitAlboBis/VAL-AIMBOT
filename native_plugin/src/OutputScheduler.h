#pragma once

#include "Config.h"
#include "TargetTypes.h"

#include <mutex>

class OutputScheduler {
public:
    explicit OutputScheduler(Config config);

    void SetMove(AimMove move);
    AimMove TakeNextMove();
    void Clear();

private:
    static bool SameDirection(float a, float b);
    static float CapResidual(float value, float requested);

    Config config_;
    std::mutex mutex_;
    AimMove pending_;
    int ticksRemaining_ = 0;
};
