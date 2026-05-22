#include "AimController.h"
#include "Config.h"
#include "OutputScheduler.h"
#include "TargetTypes.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

struct TestRunner {
    int failures = 0;

    void Expect(bool condition, const std::string& name, const std::string& detail = {}) {
        if (condition) {
            std::cout << "[ok] " << name << '\n';
            return;
        }

        ++failures;
        std::cerr << "[fail] " << name;
        if (!detail.empty()) {
            std::cerr << " -- " << detail;
        }
        std::cerr << '\n';
    }
};

struct SimulationResult {
    float finalError = 0.0f;
    float maxStep = 0.0f;
    float tailMaxStep = 0.0f;
    std::vector<float> errors;
    std::vector<float> steps;
};

SimulationResult SimulateStaticTarget(Config config, Vec2f initialError, int frames) {
    AimController aim(config);
    OutputScheduler scheduler(config);
    Vec2f error = initialError;
    SimulationResult result;

    for (int frame = 0; frame < frames; ++frame) {
        TargetMeasurement target;
        target.valid = true;
        target.offset = error;

        AimMove requested = aim.Calculate(true, target);
        scheduler.SetMove(requested);

        AimMove applied{};
        for (int tick = 0; tick < config.aimOutputBlendTicks; ++tick) {
            AimMove step = scheduler.TakeNextMove();
            applied.x += step.x;
            applied.y += step.y;
        }

        error.x -= applied.x;
        error.y -= applied.y;

        const float stepLength = std::sqrt(applied.x * applied.x + applied.y * applied.y);
        const float errorLength = std::sqrt(error.x * error.x + error.y * error.y);
        result.steps.push_back(stepLength);
        result.errors.push_back(errorLength);
        result.maxStep = std::max(result.maxStep, stepLength);
    }

    result.finalError = result.errors.empty() ? 0.0f : result.errors.back();
    const int tailStart = std::max(0, static_cast<int>(result.steps.size()) - 8);
    for (int index = tailStart; index < static_cast<int>(result.steps.size()); ++index) {
        result.tailMaxStep = std::max(result.tailMaxStep, result.steps[static_cast<size_t>(index)]);
    }
    return result;
}

void TestStaticTargetSettles(TestRunner& runner) {
    Config config = MakeDefaultConfig();
    config.aimOutputBlendTicks = 3;
    config.aimMaxStep = 55.0f;

    SimulationResult result = SimulateStaticTarget(config, {24.0f, -10.0f}, 36);
    runner.Expect(
        result.finalError <= 0.70f,
        "static target settles",
        "finalError=" + std::to_string(result.finalError));
    runner.Expect(
        result.maxStep <= config.aimMaxStep + 0.001f,
        "static target respects max step",
        "maxStep=" + std::to_string(result.maxStep));
}

void TestNoMovementWhenInactive(TestRunner& runner) {
    Config config = MakeDefaultConfig();
    AimController aim(config);

    TargetMeasurement target;
    target.valid = true;
    target.offset = {16.0f, 4.0f};

    AimMove activeMove = aim.Calculate(true, target);
    AimMove inactiveMove = aim.Calculate(false, target);

    runner.Expect(
        std::abs(activeMove.x) > 0.0f || std::abs(activeMove.y) > 0.0f,
        "active target produces movement");
    runner.Expect(
        inactiveMove.x == 0.0f && inactiveMove.y == 0.0f,
        "inactive aim clears movement");
}

void TestOutputSchedulerClearsResidual(TestRunner& runner) {
    Config config = MakeDefaultConfig();
    config.aimOutputBlendTicks = 3;
    OutputScheduler scheduler(config);

    scheduler.SetMove({12.0f, 0.0f});
    AimMove first = scheduler.TakeNextMove();
    scheduler.SetMove({0.0f, 0.0f});
    AimMove afterClear = scheduler.TakeNextMove();

    runner.Expect(
        first.x > 0.0f,
        "scheduler emits first partial move",
        "first.x=" + std::to_string(first.x));
    runner.Expect(
        afterClear.x == 0.0f && afterClear.y == 0.0f,
        "scheduler zero move clears residual");
}

void TestLimitToErrorPreventsOvershoot(TestRunner& runner) {
    Config config = MakeDefaultConfig();
    config.aimSmoothingFactor = 1.0f;
    config.speed = 3.0f;
    config.xSpeedMultiplier = 1.0f;
    config.ySpeedMultiplier = 1.0f;

    AimController aim(config);
    TargetMeasurement target;
    target.valid = true;
    target.offset = {4.0f, 0.0f};

    AimMove move = aim.Calculate(true, target);
    runner.Expect(
        move.x > 0.0f && move.x <= 4.0f,
        "controller clamps movement to remaining error",
        "move.x=" + std::to_string(move.x));
}

void TestOutputResidualCap(TestRunner& runner) {
    Config config = MakeDefaultConfig();
    config.aimOutputBlendTicks = 3;
    OutputScheduler scheduler(config);

    scheduler.SetMove({10.0f, 0.0f});
    (void)scheduler.TakeNextMove();
    scheduler.SetMove({1.0f, 0.0f});
    AimMove capped = scheduler.TakeNextMove();

    runner.Expect(
        capped.x <= 1.25f,
        "scheduler caps carried residual",
        "capped.x=" + std::to_string(capped.x));
}

} // namespace

int main() {
    TestRunner runner;

    TestStaticTargetSettles(runner);
    TestNoMovementWhenInactive(runner);
    TestOutputSchedulerClearsResidual(runner);
    TestLimitToErrorPreventsOvershoot(runner);
    TestOutputResidualCap(runner);

    if (runner.failures != 0) {
        std::cerr << runner.failures << " movement test(s) failed.\n";
        return EXIT_FAILURE;
    }

    std::cout << "movement tests: ok\n";
    return EXIT_SUCCESS;
}
