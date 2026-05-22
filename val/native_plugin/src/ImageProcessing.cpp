#include "ImageProcessing.h"

#include <algorithm>
#include <cmath>
#include <queue>

HsvPixel BgrToHsv(BgrPixel pixel) {
    const float r = static_cast<float>(pixel.r) / 255.0f;
    const float g = static_cast<float>(pixel.g) / 255.0f;
    const float b = static_cast<float>(pixel.b) / 255.0f;

    const float maxValue = std::max({r, g, b});
    const float minValue = std::min({r, g, b});
    const float delta = maxValue - minValue;

    float hueDegrees = 0.0f;
    if (delta > 0.0f) {
        if (maxValue == r) {
            hueDegrees = 60.0f * std::fmod(((g - b) / delta), 6.0f);
        } else if (maxValue == g) {
            hueDegrees = 60.0f * (((b - r) / delta) + 2.0f);
        } else {
            hueDegrees = 60.0f * (((r - g) / delta) + 4.0f);
        }
    }

    if (hueDegrees < 0.0f) {
        hueDegrees += 360.0f;
    }

    const float saturation = maxValue <= 0.0f ? 0.0f : delta / maxValue;
    HsvPixel hsv;
    hsv.h = static_cast<uint8_t>(std::round((hueDegrees / 2.0f)));
    hsv.s = static_cast<uint8_t>(std::round(saturation * 255.0f));
    hsv.v = static_cast<uint8_t>(std::round(maxValue * 255.0f));
    return hsv;
}

ImageHsv ConvertBgrToHsv(const ImageBgr& source) {
    ImageHsv output(source.Width(), source.Height());
    for (int y = 0; y < source.Height(); ++y) {
        for (int x = 0; x < source.Width(); ++x) {
            output.At(x, y) = BgrToHsv(source.At(x, y));
        }
    }
    return output;
}

ImageMask InRangeHsv(const ImageHsv& source, const Config& config) {
    ImageMask output(source.Width(), source.Height(), 0);
    for (int y = 0; y < source.Height(); ++y) {
        for (int x = 0; x < source.Width(); ++x) {
            const HsvPixel hsv = source.At(x, y);
            const bool inRange =
                hsv.h >= config.lowerColorHsv[0] && hsv.h <= config.upperColorHsv[0] &&
                hsv.s >= config.lowerColorHsv[1] && hsv.s <= config.upperColorHsv[1] &&
                hsv.v >= config.lowerColorHsv[2] && hsv.v <= config.upperColorHsv[2];
            output.At(x, y) = inRange ? 255 : 0;
        }
    }
    return output;
}

ImageMask ThresholdMask(const ImageMask& source, uint8_t threshold) {
    ImageMask output(source.Width(), source.Height(), 0);
    for (int y = 0; y < source.Height(); ++y) {
        for (int x = 0; x < source.Width(); ++x) {
            output.At(x, y) = source.At(x, y) > threshold ? 255 : 0;
        }
    }
    return output;
}

ImageMask DilateMask(const ImageMask& source, int kernelWidth, int kernelHeight, int iterations) {
    ImageMask current = source;
    kernelWidth = std::max(kernelWidth, 1);
    kernelHeight = std::max(kernelHeight, 1);

    for (int iteration = 0; iteration < iterations; ++iteration) {
        ImageMask next(source.Width(), source.Height(), 0);
        const int radiusX = kernelWidth / 2;
        const int radiusY = kernelHeight / 2;
        for (int y = 0; y < current.Height(); ++y) {
            for (int x = 0; x < current.Width(); ++x) {
                bool any = false;
                for (int ky = -radiusY; ky <= radiusY && !any; ++ky) {
                    const int sy = y + ky;
                    if (sy < 0 || sy >= current.Height()) {
                        continue;
                    }
                    for (int kx = -radiusX; kx <= radiusX; ++kx) {
                        const int sx = x + kx;
                        if (sx < 0 || sx >= current.Width()) {
                            continue;
                        }
                        if (current.At(sx, sy) != 0) {
                            any = true;
                            break;
                        }
                    }
                }
                next.At(x, y) = any ? 255 : 0;
            }
        }
        current = std::move(next);
    }

    return current;
}

ImageMask ErodeMask(const ImageMask& source, int kernelWidth, int kernelHeight, int iterations) {
    ImageMask current = source;
    kernelWidth = std::max(kernelWidth, 1);
    kernelHeight = std::max(kernelHeight, 1);

    for (int iteration = 0; iteration < iterations; ++iteration) {
        ImageMask next(source.Width(), source.Height(), 0);
        const int radiusX = kernelWidth / 2;
        const int radiusY = kernelHeight / 2;
        for (int y = 0; y < current.Height(); ++y) {
            for (int x = 0; x < current.Width(); ++x) {
                bool all = true;
                for (int ky = -radiusY; ky <= radiusY && all; ++ky) {
                    const int sy = y + ky;
                    if (sy < 0 || sy >= current.Height()) {
                        all = false;
                        break;
                    }
                    for (int kx = -radiusX; kx <= radiusX; ++kx) {
                        const int sx = x + kx;
                        if (sx < 0 || sx >= current.Width() || current.At(sx, sy) == 0) {
                            all = false;
                            break;
                        }
                    }
                }
                next.At(x, y) = all ? 255 : 0;
            }
        }
        current = std::move(next);
    }

    return current;
}

ImageMask CloseMask(const ImageMask& source, int kernelWidth, int kernelHeight, int iterations) {
    return ErodeMask(DilateMask(source, kernelWidth, kernelHeight, iterations), kernelWidth, kernelHeight, iterations);
}

std::vector<RectI> ConnectedComponentRects(const ImageMask& source, int minArea) {
    std::vector<RectI> rects;
    if (source.Empty()) {
        return rects;
    }

    std::vector<uint8_t> visited(source.Size(), 0);
    auto indexOf = [&source](int x, int y) {
        return static_cast<size_t>(y) * static_cast<size_t>(source.Width()) + static_cast<size_t>(x);
    };

    constexpr int kDx[8] = {1, -1, 0, 0, 1, 1, -1, -1};
    constexpr int kDy[8] = {0, 0, 1, -1, 1, -1, 1, -1};

    for (int y = 0; y < source.Height(); ++y) {
        for (int x = 0; x < source.Width(); ++x) {
            const size_t startIndex = indexOf(x, y);
            if (visited[startIndex] || source.At(x, y) == 0) {
                continue;
            }

            int minX = x;
            int maxX = x;
            int minY = y;
            int maxY = y;
            int area = 0;
            std::queue<std::pair<int, int>> queue;
            queue.push({x, y});
            visited[startIndex] = 1;

            while (!queue.empty()) {
                const auto [cx, cy] = queue.front();
                queue.pop();
                ++area;
                minX = std::min(minX, cx);
                maxX = std::max(maxX, cx);
                minY = std::min(minY, cy);
                maxY = std::max(maxY, cy);

                for (int direction = 0; direction < 8; ++direction) {
                    const int nx = cx + kDx[direction];
                    const int ny = cy + kDy[direction];
                    if (nx < 0 || ny < 0 || nx >= source.Width() || ny >= source.Height()) {
                        continue;
                    }
                    const size_t nextIndex = indexOf(nx, ny);
                    if (visited[nextIndex] || source.At(nx, ny) == 0) {
                        continue;
                    }
                    visited[nextIndex] = 1;
                    queue.push({nx, ny});
                }
            }

            if (area >= minArea) {
                rects.push_back({minX, minY, maxX + 1, maxY + 1});
            }
        }
    }

    return rects;
}

bool RectsOverlapOrTouch(const RectI& a, const RectI& b, int maxGap) {
    const int horizontalGap = std::max({b.x1 - a.x2, a.x1 - b.x2, 0});
    const int verticalGap = std::max({b.y1 - a.y2, a.y1 - b.y2, 0});
    return horizontalGap <= maxGap && verticalGap <= maxGap;
}

std::vector<RectI> MergeNearbyRects(std::vector<RectI> rects, int maxGap) {
    bool changed = true;
    while (changed) {
        changed = false;
        std::vector<RectI> merged;
        for (const RectI& rect : rects) {
            bool consumed = false;
            for (RectI& group : merged) {
                if (RectsOverlapOrTouch(rect, group, maxGap)) {
                    group.x1 = std::min(group.x1, rect.x1);
                    group.y1 = std::min(group.y1, rect.y1);
                    group.x2 = std::max(group.x2, rect.x2);
                    group.y2 = std::max(group.y2, rect.y2);
                    consumed = true;
                    changed = true;
                    break;
                }
            }
            if (!consumed) {
                merged.push_back(rect);
            }
        }
        rects = std::move(merged);
    }
    return rects;
}
