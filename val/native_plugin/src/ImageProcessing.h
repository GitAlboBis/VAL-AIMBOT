#pragma once

#include "Config.h"
#include "ImageTypes.h"

#include <vector>

HsvPixel BgrToHsv(BgrPixel pixel);
ImageHsv ConvertBgrToHsv(const ImageBgr& source);
ImageMask InRangeHsv(const ImageHsv& source, const Config& config);
ImageMask ThresholdMask(const ImageMask& source, uint8_t threshold = 60);
ImageMask DilateMask(const ImageMask& source, int kernelWidth, int kernelHeight, int iterations);
ImageMask ErodeMask(const ImageMask& source, int kernelWidth, int kernelHeight, int iterations);
ImageMask CloseMask(const ImageMask& source, int kernelWidth, int kernelHeight, int iterations);
std::vector<RectI> ConnectedComponentRects(const ImageMask& source, int minArea);
bool RectsOverlapOrTouch(const RectI& a, const RectI& b, int maxGap);
std::vector<RectI> MergeNearbyRects(std::vector<RectI> rects, int maxGap);
