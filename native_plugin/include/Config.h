#pragma once

#include <array>
#include <cstdint>

enum class InputBackend {
    Disabled,
    MicrocontrollerSerial,
    MicrocontrollerSocket,
    WinApi
};

struct Config {
    InputBackend inputBackend = InputBackend::Disabled;

    int screenCenterOffset = 0;
    float aimSmoothingFactor = 0.80f;
    float speed = 0.70f;
    float xSpeedMultiplier = 1.00f;
    float ySpeedMultiplier = 0.98f;
    float targetPrediction = 1.38f;

    float aimHeightNear = 0.18f;
    float aimHeightMid = 0.18f;
    float aimHeightFar = 0.17f;
    float colorConfidence = 0.40f;

    int aimDeadzone = 4;
    float aimMaxStep = 55.0f;
    int aimOutputHz = 240;
    int aimOutputBlendTicks = 3;

    std::array<uint8_t, 3> lowerColorHsv = {132, 105, 135};
    std::array<uint8_t, 3> upperColorHsv = {162, 255, 255};
    int groupCloseTargetBlobsX = 2;
    int groupCloseTargetBlobsY = 2;
    int captureFovX = 200;
    int captureFovY = 200;
    int aimFovX = 115;
    int aimFovY = 115;
    int maxLoopsPerSecond = 240;
    bool autoDetectResolution = true;
    int resolutionX = 1920;
    int resolutionY = 1440;

    int comPort = 3;

    float recoilX = 0.0f;
    float recoilY = 35.0f;
    float recoilRecover = 0.0f;
    int maxOffset = 100;

    int triggerDelayMs = 0;
    int triggerRandomizationMs = 30;
    int triggerThreshold = 8;
    int targetCps = 10;
};

Config MakeDefaultConfig();
