#include "Config.h"
#include "ImageProcessing.h"
#include "ImageTypes.h"

#include <cstdlib>
#include <iostream>
#include <string>

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

void DrawRectOutline(ImageBgr& image, RectI rect, BgrPixel color) {
    for (int x = rect.x1; x < rect.x2; ++x) {
        image.At(x, rect.y1) = color;
        image.At(x, rect.y2 - 1) = color;
    }
    for (int y = rect.y1; y < rect.y2; ++y) {
        image.At(rect.x1, y) = color;
        image.At(rect.x2 - 1, y) = color;
    }
}

int CountMaskPixels(const ImageMask& mask) {
    int count = 0;
    for (uint8_t value : mask.Pixels()) {
        if (value != 0) {
            ++count;
        }
    }
    return count;
}

void TestBgrToHsvPurpleRange(TestRunner& runner) {
    Config config = MakeDefaultConfig();
    const HsvPixel hsv = BgrToHsv({255, 0, 255});
    const bool inPurpleRange =
        hsv.h >= config.lowerColorHsv[0] && hsv.h <= config.upperColorHsv[0] &&
        hsv.s >= config.lowerColorHsv[1] && hsv.s <= config.upperColorHsv[1] &&
        hsv.v >= config.lowerColorHsv[2] && hsv.v <= config.upperColorHsv[2];

    runner.Expect(
        inPurpleRange,
        "BGR magenta maps into configured HSV purple range",
        "h=" + std::to_string(hsv.h) + " s=" + std::to_string(hsv.s) + " v=" + std::to_string(hsv.v));
}

void TestMaskFindsPurpleOutline(TestRunner& runner) {
    Config config = MakeDefaultConfig();
    ImageBgr image(80, 60, {10, 10, 10});
    DrawRectOutline(image, {30, 15, 45, 42}, {255, 0, 255});

    ImageHsv hsv = ConvertBgrToHsv(image);
    ImageMask mask = InRangeHsv(hsv, config);
    ImageMask closed = CloseMask(mask, 3, 3, 1);
    ImageMask dilated = DilateMask(closed, config.groupCloseTargetBlobsX, config.groupCloseTargetBlobsY, 2);
    ImageMask thresholded = ThresholdMask(dilated);
    std::vector<RectI> rects = ConnectedComponentRects(thresholded, 4);

    runner.Expect(
        CountMaskPixels(mask) > 0,
        "HSV mask captures purple outline");
    runner.Expect(
        rects.size() == 1,
        "connected components groups outline",
        "rects=" + std::to_string(rects.size()));
    if (!rects.empty()) {
        const RectI rect = rects.front();
        runner.Expect(
            rect.x1 <= 30 && rect.y1 <= 15 && rect.x2 >= 45 && rect.y2 >= 42,
            "component rect covers original outline",
            "rect=(" + std::to_string(rect.x1) + "," + std::to_string(rect.y1) + "," +
                std::to_string(rect.x2) + "," + std::to_string(rect.y2) + ")");
    }
}

void TestMergeNearbyRects(TestRunner& runner) {
    std::vector<RectI> rects = {
        {10, 10, 15, 20},
        {16, 11, 20, 21},
        {50, 50, 55, 55}
    };

    std::vector<RectI> merged = MergeNearbyRects(rects, 2);
    runner.Expect(
        merged.size() == 2,
        "nearby rects merge while distant rect remains",
        "merged=" + std::to_string(merged.size()));
}

void TestNoiseCanBeFilteredByArea(TestRunner& runner) {
    ImageMask mask(40, 40, 0);
    mask.At(5, 5) = 255;
    mask.At(20, 20) = 255;
    mask.At(21, 20) = 255;
    mask.At(20, 21) = 255;
    mask.At(21, 21) = 255;

    std::vector<RectI> rects = ConnectedComponentRects(mask, 4);
    runner.Expect(
        rects.size() == 1,
        "connected components filters tiny noise by min area",
        "rects=" + std::to_string(rects.size()));
}

} // namespace

int main() {
    TestRunner runner;

    TestBgrToHsvPurpleRange(runner);
    TestMaskFindsPurpleOutline(runner);
    TestMergeNearbyRects(runner);
    TestNoiseCanBeFilteredByArea(runner);

    if (runner.failures != 0) {
        std::cerr << runner.failures << " vision test(s) failed.\n";
        return EXIT_FAILURE;
    }

    std::cout << "vision tests: ok\n";
    return EXIT_SUCCESS;
}
