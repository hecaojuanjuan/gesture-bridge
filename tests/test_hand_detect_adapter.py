"""Validate the production hand adapter contract without a camera or model run."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STUB = r"""
#pragma once
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <list>
#include <new>
#include <vector>
namespace dl {
class Model {
public:
    std::vector<int> inputs{1}, outputs{1};
    std::vector<int> &get_inputs() { return inputs; }
    std::vector<int> &get_outputs() { return outputs; }
};
namespace image {
enum { DL_IMAGE_PIX_TYPE_RGB888 = 1 };
struct img_t { uint8_t *data; uint16_t width, height; int pix_type; };
}
namespace detect {
struct result_t { int category; float score; std::vector<int> box, keypoint; };
}
}
extern dl::Model model;
extern bool allocate_ok, model_ok;
extern unsigned constructors, destructions, runs;
extern std::list<dl::detect::result_t> hands;
class HandDetect {
public:
    enum model_type_t { ESPDET_PICO_224_224_HAND };
    static void *operator new(std::size_t size, const std::nothrow_t &) noexcept {
        return allocate_ok ? std::malloc(size) : nullptr;
    }
    static void operator delete(void *p) noexcept { std::free(p); }
    HandDetect(model_type_t type, bool lazy) {
        assert(type == ESPDET_PICO_224_224_HAND && !lazy); ++constructors;
    }
    ~HandDetect() { ++destructions; }
    dl::Model *get_raw_model() { return model_ok ? &model : nullptr; }
    std::list<dl::detect::result_t> &run(const dl::image::img_t &image) {
        assert(image.data && image.width == 320 && image.height == 240);
        assert(image.pix_type == dl::image::DL_IMAGE_PIX_TYPE_RGB888);
        ++runs; return hands;
    }
};
"""

HARNESS = r"""
#include "hv_hand_detect.h"
#include "hand_detect.hpp"
#include <cmath>
#include <climits>
#include <cstring>

dl::Model model;
bool allocate_ok = true, model_ok = true;
unsigned constructors, destructions, runs;
std::list<dl::detect::result_t> hands;
static uint8_t rgb[3]; // Fake detector does not read the image pixels.

static void rejected(std::list<dl::detect::result_t> results) {
    hands = results;
    hv_hand_detection_t out;
    std::memset(&out, 0x7f, sizeof(out));
    assert(hv_hand_detect_analyze_rgb888(rgb, 320, 240, &out) == ESP_OK);
    assert(!out.valid && out.count == results.size() && out.score == 0);
    for (unsigned i = 0; i < 4; ++i) assert(out.box[i] == 0 && out.normalized_box[i] == 0);
}
int main() {
    hv_hand_detection_t out;
    assert(hv_hand_detect_analyze_rgb888(rgb, 320, 240, &out) == ESP_ERR_INVALID_STATE);
    assert(!out.valid && out.count == 0);
    assert(hv_hand_detect_analyze_rgb888(rgb, 320, 240, nullptr) == ESP_ERR_INVALID_ARG);
    allocate_ok = false;
    assert(hv_hand_detect_init() == ESP_ERR_NO_MEM && constructors == 0);
    allocate_ok = true; model_ok = false;
    assert(hv_hand_detect_init() == ESP_FAIL && destructions == 1);
    model_ok = true; model.inputs.clear();
    assert(hv_hand_detect_init() == ESP_FAIL && destructions == 2);
    model.inputs = {1}; model.outputs.clear();
    assert(hv_hand_detect_init() == ESP_FAIL && destructions == 3);
    model.outputs = {1};
    assert(hv_hand_detect_init() == ESP_OK && constructors == 4);
    assert(hv_hand_detect_init() == ESP_OK && constructors == 4);

    hands = {{0, .9f, {32, 24, 288, 216}, {}}};
    assert(hv_hand_detect_analyze_rgb888(rgb, 320, 240, &out) == ESP_OK);
    assert(out.valid && out.count == 1 && out.score == .9f);
    assert(out.box[0] == 32 && out.box[1] == 24 && out.box[2] == 288 && out.box[3] == 216);
    assert(std::fabs(out.normalized_box[0] - .1f) < 1e-6f);
    assert(std::fabs(out.normalized_box[3] - .9f) < 1e-6f);
    // Half-open box end equals the image size: never add another pixel.
    hands = {{0, .5f, {0, 0, 320, 240}, {}}};
    assert(hv_hand_detect_analyze_rgb888(rgb, 320, 240, &out) == ESP_OK && out.valid);
    assert(out.normalized_box[2] == 1 && out.normalized_box[3] == 1);

    rejected({});
    rejected({{0, .9f, {32, 24, 288, 216}, {}}, {0, .3f, {3, 4, 30, 40}, {}}});
    for (float score : {-.1f, .4999f, 1.01f, NAN, INFINITY})
        rejected({{0, score, {32, 24, 288, 216}, {}}});
    rejected({{1, .9f, {32, 24, 288, 216}, {}}});
    for (const auto &box : std::vector<std::vector<int>>{
        {1, 2, 3}, {1, 2, 3, 4, 5}, {-1, 0, 3, 4}, {0, -1, 3, 4},
        {3, 2, 3, 4}, {1, 4, 3, 4}, {4, 2, 3, 4}, {1, 5, 3, 4},
        {0, 0, 321, 240}, {0, 0, 320, 241}, {INT_MIN, 0, INT_MAX, 240}})
        rejected({{0, .9f, box, {}}});
    unsigned previous_runs = runs;
    assert(hv_hand_detect_analyze_rgb888(nullptr, 320, 240, &out) == ESP_ERR_INVALID_ARG);
    assert(!out.valid && out.count == 0);
    assert(hv_hand_detect_analyze_rgb888(rgb, 0, 240, &out) == ESP_ERR_INVALID_ARG);
    assert(hv_hand_detect_analyze_rgb888(rgb, 320, 0, &out) == ESP_ERR_INVALID_ARG);
    assert(runs == previous_runs);
}
"""


class HandDetectAdapterTest(unittest.TestCase):
    def test_vendored_files_match_pinned_commit(self):
        directory = ROOT / "headvoice/third_party/hand_detect"
        manifest = json.loads((directory / "UPSTREAM.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["upstream_commit"], "c39b5bb08e957dc675efa29f86a642ba79cb82d7")
        self.assertEqual(manifest["targets_included"], ["esp32s3"])
        for name, expected in manifest["files"].items():
            with self.subTest(path=name):
                data = (directory / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
                git_blob = b"blob " + str(len(data)).encode() + b"\0" + data
                self.assertEqual(hashlib.sha1(git_blob).hexdigest(), manifest["git_blobs"][name])
        self.assertEqual((directory / "models/s3/espdet_pico_224_224_hand.espdl").stat().st_size, 497136)

    def test_adapter_init_and_single_hand_boundary(self):
        compiler = shutil.which("c++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("Host C++ compiler is unavailable")
        with tempfile.TemporaryDirectory(prefix="hand-adapter-") as directory:
            tmp = Path(directory)
            (tmp / "hand_detect.hpp").write_text(STUB, encoding="utf-8")
            (tmp / "esp_log.h").write_text("#define ESP_LOGI(...) ((void)0)\n", encoding="utf-8")
            (tmp / "esp_err.h").write_text(
                "#pragma once\ntypedef int esp_err_t;\n"
                "#define ESP_OK 0\n#define ESP_FAIL -1\n#define ESP_ERR_NO_MEM 257\n"
                "#define ESP_ERR_INVALID_ARG 258\n#define ESP_ERR_INVALID_STATE 259\n",
                encoding="utf-8")
            (tmp / "test.cpp").write_text(HARNESS, encoding="utf-8")
            binary = tmp / "test"
            command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                       "-DCONFIG_HAND_DETECT_MODEL_IN_FLASH_RODATA=1",
                       "-DCONFIG_FLASH_ESPDET_PICO_224_224_HAND=1",
                       "-I", str(tmp), "-I", str(ROOT / "headvoice/firmware"),
                       str(ROOT / "headvoice/firmware/hv_hand_detect.cpp"), str(tmp / "test.cpp"),
                       "-o", str(binary)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
