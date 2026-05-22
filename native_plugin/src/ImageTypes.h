#pragma once

#include <cstdint>
#include <vector>

struct BgrPixel {
    uint8_t b = 0;
    uint8_t g = 0;
    uint8_t r = 0;
};

struct HsvPixel {
    uint8_t h = 0;
    uint8_t s = 0;
    uint8_t v = 0;
};

struct RectI {
    int x1 = 0;
    int y1 = 0;
    int x2 = 0;
    int y2 = 0;

    int Width() const { return x2 - x1; }
    int Height() const { return y2 - y1; }
    int Area() const { return Width() * Height(); }
};

template <typename T>
class Image {
public:
    Image() = default;
    Image(int width, int height, T value = {}) {
        Reset(width, height, value);
    }

    void Reset(int width, int height, T value = {}) {
        width_ = width;
        height_ = height;
        pixels_.assign(static_cast<size_t>(width_) * static_cast<size_t>(height_), value);
    }

    bool Empty() const {
        return width_ <= 0 || height_ <= 0 || pixels_.empty();
    }

    int Width() const { return width_; }
    int Height() const { return height_; }
    size_t Size() const { return pixels_.size(); }

    T& At(int x, int y) {
        return pixels_[static_cast<size_t>(y) * static_cast<size_t>(width_) + static_cast<size_t>(x)];
    }

    const T& At(int x, int y) const {
        return pixels_[static_cast<size_t>(y) * static_cast<size_t>(width_) + static_cast<size_t>(x)];
    }

    const std::vector<T>& Pixels() const { return pixels_; }
    std::vector<T>& Pixels() { return pixels_; }

private:
    int width_ = 0;
    int height_ = 0;
    std::vector<T> pixels_;
};

using ImageBgr = Image<BgrPixel>;
using ImageHsv = Image<HsvPixel>;
using ImageMask = Image<uint8_t>;
