"""Check the native adapter's real boundary code; no model accuracy or device claims."""
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "headvoice/firmware/hv_hand_native_classifier.cpp"


def pinned_model_layout(raw):
    """Read real EDL2 FlatBuffer metadata using the SDK espdl.fbs field order.

    This is a narrow test reader for the hash-pinned model, not a runtime parser
    for untrusted models. TypeInfo's union occupies a tag plus a value slot.
    """
    assert raw[:4] == b"EDL2" and struct.unpack_from("<I", raw, 4)[0] == 0
    size = struct.unpack_from("<I", raw, 8)[0]
    assert size + 16 == len(raw)
    data = raw[16:]

    def u32(pos):
        return struct.unpack_from("<I", data, pos)[0]

    def field(table, index):
        vtable = table - struct.unpack_from("<i", data, table)[0]
        slot = 4 + 2 * index
        length = struct.unpack_from("<H", data, vtable)[0]
        offset = struct.unpack_from("<H", data, vtable + slot)[0] if slot < length else 0
        return table + offset if offset else None

    def reference(table, index):
        pos = field(table, index)
        return pos + u32(pos) if pos else None

    def text(table, index):
        pos = reference(table, index)
        return data[pos + 4:pos + 4 + u32(pos)].decode() if pos else ""

    def tables(table, index):
        pos = reference(table, index)
        return [pos + 4 + 4 * i + u32(pos + 4 + 4 * i) for i in range(u32(pos))] if pos else []

    def tensor(value_info):
        type_info = reference(value_info, 1)
        assert data[field(type_info, 0)] == 1  # TypeInfoValue.tensor_type
        tensor_type = reference(type_info, 1)
        dtype = struct.unpack_from("<i", data, field(tensor_type, 0))[0]
        dimensions = []
        for dimension in tables(reference(tensor_type, 1), 0):
            value = reference(dimension, 0)
            assert data[field(value, 0)] == 1  # DimensionValueType.VALUE
            pos = field(value, 1)
            dimensions.append(struct.unpack_from("<q", data, pos)[0] if pos else 0)
        return {"name": text(value_info, 0), "dtype": dtype, "shape": dimensions}

    graph = reference(u32(0), 7)
    nodes = tables(graph, 0)
    return {"inputs": [tensor(t) for t in tables(graph, 4)],
            "outputs": [tensor(t) for t in tables(graph, 5)],
            "operators": [text(n, 3) for n in nodes],
            "last_node_name": text(nodes[-1], 2)}

SUPPORT = r"""
#pragma once
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <map>
#include <new>
#include <string>
#include <vector>
extern int allocation_failure, shape_failure;
extern unsigned models, preprocessors, postprocessors, model_runs, pre_runs;
extern const char model_bytes[];
extern bool mapping_active;
inline void *allocate(std::size_t size, int stage) {
    return allocation_failure == stage ? nullptr : std::malloc(size);
}
namespace fbs { enum model_location_type_t { MODEL_LOCATION_IN_FLASH_RODATA = 0, MODEL_LOCATION_IN_FLASH_PARTITION = 1 }; }
namespace dl {
enum { DATA_TYPE_INT8=1, DATA_TYPE_INT16=2 };
struct TensorBase {
    std::vector<int> shape{1,128,128,3};
    int dtype=DATA_TYPE_INT8, count=11;
    void *data=reinterpret_cast<void *>(1);
    int get_size() { return count; }
};
class Model {
    TensorBase input, output;
    std::map<std::string,TensorBase *> inputs{{"in",&input}}, outputs{{"out",&output}};
public:
    static void *operator new(std::size_t size,const std::nothrow_t &) noexcept { return allocate(size,1); }
    static void operator delete(void *p) noexcept { std::free(p); }
    Model(const char *bytes,fbs::model_location_type_t location) {
        ++models; assert(bytes==model_bytes && mapping_active);
        assert(location==fbs::MODEL_LOCATION_IN_FLASH_RODATA);
        if(shape_failure==1)input.shape={1,64,64,1};
        if(shape_failure==2)output.count=10;
        if(shape_failure==3)input.dtype=DATA_TYPE_INT16;
        if(shape_failure==4)output.dtype=DATA_TYPE_INT16;
        if(shape_failure==5)input.data=nullptr;
        if(shape_failure==6)inputs.clear();
        if(shape_failure==7)outputs.clear();
    }
    ~Model() { assert(mapping_active); --models; }
    auto &get_inputs() { return inputs; }
    auto &get_outputs() { return outputs; }
    TensorBase *get_input() { return &input; }
    TensorBase *get_output() { return &output; }
    void minimize() {}
    void run() { ++model_runs; }
};
namespace image {
enum { DL_IMAGE_PIX_TYPE_RGB888=1,DL_IMAGE_CAP_RGB565_BIG_ENDIAN=2 };
struct img_t { uint8_t *data; uint16_t width,height; int pix_type; };
extern std::vector<int> last_crop;
class ImagePreprocessor {
public:
    static void *operator new(std::size_t size,const std::nothrow_t &) noexcept { return allocate(size,2); }
    static void operator delete(void *p) noexcept { std::free(p); }
    ImagePreprocessor(Model *,std::vector<float> mean,std::vector<float> std,uint32_t caps) {
        ++preprocessors;
        assert(mean==std::vector<float>({123.675f,116.28f,103.53f}));
        assert(std==std::vector<float>({58.395f,57.12f,57.375f}));
        assert(caps==DL_IMAGE_CAP_RGB565_BIG_ENDIAN);
    }
    ~ImagePreprocessor() { --preprocessors; }
    void preprocess(const img_t &img,const std::vector<int> &crop) {
        ++pre_runs; assert(img.data && img.width==320 && img.height==240);
        assert(img.pix_type==DL_IMAGE_PIX_TYPE_RGB888); last_crop=crop;
    }
};
}
namespace cls {
struct result_t { const char *cat_name; float score; };
extern std::vector<result_t> scripted_results;
class HandGestureClsPostprocessor {
public:
    static void *operator new(std::size_t size,const std::nothrow_t &) noexcept { return allocate(size,3); }
    static void operator delete(void *p) noexcept { std::free(p); }
    HandGestureClsPostprocessor(Model *,int topk,float threshold,bool softmax) {
        ++postprocessors; assert(topk==11 && threshold==std::numeric_limits<float>::lowest() && softmax);
    }
    ~HandGestureClsPostprocessor() { --postprocessors; }
    auto &postprocess() { return scripted_results; }
};
}
}
"""

PARTITION = r"""
#pragma once
#include <cstddef>
#include <cstdint>
#include "esp_err.h"
typedef struct { std::size_t size; uint32_t address; } esp_partition_t;
typedef uint32_t esp_partition_mmap_handle_t;
typedef enum { ESP_PARTITION_MMAP_DATA=0 } esp_partition_mmap_memory_t;
enum { ESP_PARTITION_TYPE_DATA=1,ESP_PARTITION_SUBTYPE_ANY=255 };
const esp_partition_t *esp_partition_find_first(int,int,const char *);
int esp_partition_read(const esp_partition_t *,std::size_t,void *,std::size_t);
esp_err_t esp_partition_mmap(const esp_partition_t *,std::size_t,std::size_t,
    esp_partition_mmap_memory_t,const void **,esp_partition_mmap_handle_t *);
void esp_partition_munmap(esp_partition_mmap_handle_t);
"""

SHA = r"""
#pragma once
#include <cstddef>
#include <cstdint>
typedef struct { unsigned unused; } mbedtls_sha256_context;
void mbedtls_sha256_init(mbedtls_sha256_context *);
int mbedtls_sha256_starts(mbedtls_sha256_context *,int);
int mbedtls_sha256_update(mbedtls_sha256_context *,const uint8_t *,std::size_t);
int mbedtls_sha256_finish(mbedtls_sha256_context *,uint8_t *);
void mbedtls_sha256_free(mbedtls_sha256_context *);
"""

HARNESS = r"""
#include "hv_hand_native_classifier.h"
#include "support.hpp"
#include "esp_partition.h"
#include "mbedtls/sha256.h"
#include <algorithm>

int allocation_failure,shape_failure;
unsigned models,preprocessors,postprocessors,model_runs,pre_runs;
const char model_bytes[]="EDL2";
bool mapping_active=false, mapping_null_pointer=false;
std::vector<int> dl::image::last_crop;
std::vector<dl::cls::result_t> dl::cls::scripted_results;
esp_partition_t part{3200u*1024u,0x810000};
bool present=true,read_failure=false,digest_failure=false;
int sha_failure=0;
int mapping_error=ESP_OK;
unsigned map_calls=0,unmap_calls=0;
std::size_t read_bytes=0,hashed_bytes=0;
unsigned partition_queries=0;
static uint8_t rgb[320*240*3];

const esp_partition_t *esp_partition_find_first(int type,int subtype,const char *label) {
    assert(type==ESP_PARTITION_TYPE_DATA && subtype==ESP_PARTITION_SUBTYPE_ANY && label);
    ++partition_queries; return present ? &part : nullptr;
}
int esp_partition_read(const esp_partition_t *p,std::size_t offset,void *buffer,std::size_t count) {
    assert(p==&part && count<=1024 && offset==read_bytes);
    assert(offset+count<=HV_HAND_NATIVE_MODEL_BYTES);
    if(read_failure)return -1;
    read_bytes+=count; std::memset(buffer,0,count); return 0;
}
void mbedtls_sha256_init(mbedtls_sha256_context *) { read_bytes=hashed_bytes=0; }
int mbedtls_sha256_starts(mbedtls_sha256_context *,int is224) { assert(is224==0); return sha_failure==1 ? -1:0; }
int mbedtls_sha256_update(mbedtls_sha256_context *,const uint8_t *,std::size_t count) {
    hashed_bytes+=count; return sha_failure==2 ? -1:0;
}
int mbedtls_sha256_finish(mbedtls_sha256_context *,uint8_t *digest) {
    if(sha_failure==3)return -1;
    for(int i=0;i<32;++i) {
        const char pair[]={HV_HAND_NATIVE_MODEL_SHA256[i*2],HV_HAND_NATIVE_MODEL_SHA256[i*2+1],0};
        digest[i]=digest_failure ? 0 : uint8_t(std::strtoul(pair,nullptr,16));
    }
    return 0;
}
void mbedtls_sha256_free(mbedtls_sha256_context *) {}
int64_t esp_timer_get_time() { static int64_t now=0; now+=1000; return now; }
esp_err_t esp_partition_mmap(const esp_partition_t *p,std::size_t offset,std::size_t size,
    esp_partition_mmap_memory_t memory,const void **out,esp_partition_mmap_handle_t *handle) {
    ++map_calls;
    assert(p==&part && offset==0 && size==HV_HAND_NATIVE_MODEL_BYTES);
    assert(memory==ESP_PARTITION_MMAP_DATA && !mapping_active && !models);
    assert(!digest_failure && !sha_failure && hashed_bytes==HV_HAND_NATIVE_MODEL_BYTES);
    if(mapping_error!=ESP_OK)return mapping_error;
    mapping_active=true;*out=mapping_null_pointer ? nullptr:model_bytes;
    *handle=0; // Zero is a valid owned handle, not a sentinel for no mapping.
    return ESP_OK;
}
void esp_partition_munmap(esp_partition_mmap_handle_t handle) {
    assert(handle==0 && mapping_active && !models && !preprocessors && !postprocessors);
    mapping_active=false;++unmap_calls;
}

static hv_hand_detection_t detection() {
    hv_hand_detection_t d{};d.count=1;d.valid=true;d.score=.9f;
    const int box[]={32,24,288,216};std::memcpy(d.box,box,sizeof(box));return d;
}
static void scores(int winner) {
    dl::cls::scripted_results.clear();
    for(int i=10;i>=0;--i)
        dl::cls::scripted_results.push_back({hv_hand_native_class_name(i),i==winner ? .8f:.02f});
}
static void start() {
    assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_OK);
    assert(hv_hand_native_classifier_ready());
}
static void stopped() {
    hv_hand_native_classifier_deinit();
    assert(!hv_hand_native_classifier_ready() && !models && !preprocessors && !postprocessors && !mapping_active);
}
static void cleared(const hv_hand_native_result_t &r) {
    assert(!r.valid && r.top_index==HV_HAND_NATIVE_CLASS_UNKNOWN);
    assert(!r.top_score && !r.second_score && !r.margin);
    for(float s:r.scores)assert(s==0);
}
static hv_hand_native_status_t predict(const hv_hand_detection_t &d,hv_hand_native_result_t &r) {
    std::memset(&r,0x7f,sizeof(r));
    return hv_hand_native_classifier_analyze_rgb888(rgb,sizeof(rgb),320,240,&d,&r);
}
int main(int argc,char **argv) {
    assert(argc==2); const std::string test=argv[1];
    if(test=="init") {
        assert(!hv_hand_native_classifier_ready());
        for(const char *label:{static_cast<const char *>(nullptr),"","12345678901234567"})
            assert(hv_hand_native_classifier_init(label,HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_INVALID_ARG);
        assert(hv_hand_native_classifier_init("coco_pose",nullptr)==HV_HAND_NATIVE_INVALID_ARG);
        assert(hv_hand_native_classifier_init("coco_pose","bad")==HV_HAND_NATIVE_MODEL_HASH_MISMATCH);
        assert(partition_queries==0);
        present=false;
        assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_PARTITION_MISSING);
        present=true;part.size=HV_HAND_NATIVE_MODEL_BYTES-1;
        assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_PARTITION_TOO_SMALL);
        part.size=3200*1024;read_failure=true;
        assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_IO_ERROR);
        read_failure=false;digest_failure=true;
        assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_MODEL_HASH_MISMATCH);
        assert(!models && read_bytes==HV_HAND_NATIVE_MODEL_BYTES && hashed_bytes==read_bytes);
        digest_failure=false;
        for(sha_failure=1;sha_failure<=3;++sha_failure)
            assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_IO_ERROR);
        sha_failure=0;
        assert(map_calls==0 && unmap_calls==0 && !mapping_active);
        mapping_error=ESP_ERR_NO_MEM;
        assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_NO_MEMORY);
        mapping_error=ESP_FAIL;
        assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_IO_ERROR);
        assert(map_calls==2 && unmap_calls==0 && !mapping_active && !models);
        mapping_error=ESP_OK;mapping_null_pointer=true;
        assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_IO_ERROR);
        assert(map_calls==3 && unmap_calls==1 && !mapping_active && !models);
        mapping_null_pointer=false;start();
        assert(mapping_active && read_bytes==HV_HAND_NATIVE_MODEL_BYTES && hashed_bytes==read_bytes);
        const auto queries=partition_queries,calls=map_calls;start();assert(partition_queries==queries && map_calls==calls);
        assert(hv_hand_native_classifier_init("another",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_ALREADY_INITIALIZED);
        assert(hv_hand_native_classifier_ready());stopped();
        assert(map_calls==4 && unmap_calls==2);stopped();assert(unmap_calls==2);
    } else if(test=="lifecycle") {
        for(shape_failure=1;shape_failure<=7;++shape_failure) {
            assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_BAD_MODEL);
            assert(!hv_hand_native_classifier_ready() && !models && !preprocessors && !postprocessors && !mapping_active);
            assert(map_calls==unmap_calls);
        }
        shape_failure=0;
        for(allocation_failure=1;allocation_failure<=3;++allocation_failure) {
            assert(hv_hand_native_classifier_init("coco_pose",HV_HAND_NATIVE_MODEL_SHA256)==HV_HAND_NATIVE_NO_MEMORY);
            assert(!hv_hand_native_classifier_ready() && !models && !preprocessors && !postprocessors && !mapping_active);
            assert(map_calls==unmap_calls);
        }
        allocation_failure=0;start();stopped();stopped();assert(map_calls==unmap_calls);
    } else if(test=="input") {
        auto d=detection();hv_hand_native_result_t r;
        assert(predict(d,r)==HV_HAND_NATIVE_NOT_READY);cleared(r);start();scores(1);
        assert(hv_hand_native_classifier_analyze_rgb888(rgb,sizeof(rgb),320,240,&d,nullptr)==HV_HAND_NATIVE_INVALID_ARG);
        assert(hv_hand_native_classifier_analyze_rgb888(nullptr,sizeof(rgb),320,240,&d,&r)==HV_HAND_NATIVE_INVALID_ARG);cleared(r);
        for(auto bytes:{std::size_t(0),sizeof(rgb)-1,sizeof(rgb)+1}) {
            assert(hv_hand_native_classifier_analyze_rgb888(rgb,bytes,320,240,&d,&r)==HV_HAND_NATIVE_INVALID_ARG);cleared(r);
        }
        assert(hv_hand_native_classifier_analyze_rgb888(rgb,sizeof(rgb),0,240,&d,&r)==HV_HAND_NATIVE_INVALID_ARG);
        assert(hv_hand_native_classifier_analyze_rgb888(rgb,sizeof(rgb),320,4097,&d,&r)==HV_HAND_NATIVE_INVALID_ARG);
        assert(hv_hand_native_classifier_analyze_rgb888(rgb,sizeof(rgb),320,240,nullptr,&r)==HV_HAND_NATIVE_INVALID_ARG);
        d.valid=false;assert(predict(d,r)==HV_HAND_NATIVE_INVALID_DETECTION);cleared(r);d=detection();
        for(unsigned count:{0u,2u,3u}) { d.count=count;assert(predict(d,r)==HV_HAND_NATIVE_INVALID_DETECTION);cleared(r); }
        d=detection();
        for(float score:{.4999f,1.1f,NAN,INFINITY}) { d.score=score;assert(predict(d,r)==HV_HAND_NATIVE_INVALID_DETECTION);cleared(r); }
        for(auto box:std::vector<std::vector<int>>{{-1,0,10,10},{0,-1,10,10},{2,0,2,10},{0,3,10,3},{0,0,321,240},{0,0,320,241}}) {
            d=detection();std::copy(box.begin(),box.end(),d.box);assert(predict(d,r)==HV_HAND_NATIVE_INVALID_DETECTION);cleared(r);
        }
        assert(model_runs==0 && pre_runs==0);
        d=detection();d.box[0]=d.box[1]=0;d.box[2]=320;d.box[3]=240;d.score=.5f;
        assert(predict(d,r)==HV_HAND_NATIVE_OK && r.valid);
        assert(dl::image::last_crop==std::vector<int>({0,0,320,240}));stopped();
    } else if(test=="classes") {
        start();const auto d=detection();hv_hand_native_result_t r;
        for(int winner=0;winner<11;++winner) {
            scores(winner);assert(predict(d,r)==HV_HAND_NATIVE_OK && r.valid && r.top_index==winner);
            assert(std::fabs(r.scores[winner]-.8f)<1e-6f && std::fabs(r.margin-.78f)<1e-6f);
            assert(r.preprocess_ms==1 && r.model_ms==1 && r.postprocess_ms==1);
        }
        assert(std::strcmp(hv_hand_native_class_name(1),"two")==0);
        assert(std::strcmp(hv_hand_native_class_name(4),"five")==0);
        assert(std::strcmp(hv_hand_native_class_name(7),"no_gesture")==0);
        assert(std::strcmp(hv_hand_native_class_name(10),"no_hand")==0);
        assert(std::strcmp(hv_hand_native_class_name(-1),"unknown")==0);
        assert(std::strcmp(hv_hand_native_class_name(11),"unknown")==0);
        stopped();assert(predict(d,r)==HV_HAND_NATIVE_NOT_READY);cleared(r);
    } else if(test=="output") {
        start();const auto d=detection();hv_hand_native_result_t r;
        for(int problem=0;problem<8;++problem) {
            scores(4);auto &v=dl::cls::scripted_results;
            if(problem==0)v.pop_back();
            if(problem==1)v[0].cat_name="unexpected";
            if(problem==2)v[0].cat_name=v[1].cat_name;
            if(problem==3)v[0].score=NAN;
            if(problem==4)v[0].score=INFINITY;
            if(problem==5)v[0].score=-.01f;
            if(problem==6)v[0].score=1.01f;
            if(problem==7)for(auto &s:v)s.score=.1f;
            assert(predict(d,r)==HV_HAND_NATIVE_INVALID_OUTPUT);cleared(r);
        }
        scores(1);for(auto &s:dl::cls::scripted_results)s.score=1.f/11.f;
        assert(predict(d,r)==HV_HAND_NATIVE_OK && r.valid && r.margin==0.f);
        stopped();
    } else { assert(false); }
}
"""


class NativeHandClassifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("clang++")
        if not cls.compiler:
            raise unittest.SkipTest("Host C++ compiler unavailable")
        cls.temp = tempfile.TemporaryDirectory(prefix="hand-native-")
        cls.directory = Path(cls.temp.name)
        files = {
            "support.hpp": SUPPORT,
            "dl_model_base.hpp": '#include "support.hpp"\n',
            "dl_image_preprocessor.hpp": '#include "support.hpp"\n',
            "hand_gesture_cls_postprocessor.hpp": '#include "support.hpp"\n',
            "esp_partition.h": PARTITION,
            "mbedtls/sha256.h": SHA,
            "esp_err.h": "#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_FAIL -1\n#define ESP_ERR_NO_MEM 0x101\n",
            "esp_timer.h": "#pragma once\n#include <stdint.h>\nint64_t esp_timer_get_time();\n",
            "harness.cpp": HARNESS,
        }
        for name, text in files.items():
            p = cls.directory / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        cls.binary = cls.directory / "native-test"
        subprocess.run([cls.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                        "-I", str(cls.directory), "-I", str(ROOT / "headvoice/firmware"),
                        str(SOURCE), str(cls.directory / "harness.cpp"), "-o", str(cls.binary)],
                       check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, name):
        subprocess.run([str(self.binary), name], check=True, capture_output=True, text=True)

    def test_partition_and_hash_gate_before_model_loading(self):
        self.run_case("init")

    def test_bad_layout_and_explicit_allocation_failures_release_resources(self):
        self.run_case("lifecycle")

    def test_input_rejections_never_run_inference(self):
        self.run_case("input")

    def test_all_eleven_original_labels_and_scores_are_preserved(self):
        self.run_case("classes")

    def test_incomplete_corrupt_or_nonfinite_outputs_never_escape(self):
        self.run_case("output")

    def test_upstream_bytes_are_pinned(self):
        directory = ROOT / "headvoice/third_party/hand_gesture_recognition"
        manifest = json.loads((directory / "UPSTREAM.json").read_text())
        self.assertEqual(manifest["upstream_commit"], "c39b5bb08e957dc675efa29f86a642ba79cb82d7")
        self.assertEqual(manifest["model_bytes"], 788608)
        self.assertEqual(manifest["model_sha256"], "52e18ceb0845121b4c0fa63aa06d69d17068c8c8135f43a7943a11812ac595d0")
        for name, digest in manifest["files"].items():
            data = (directory / name).read_bytes()
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
                self.assertEqual(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
                                 manifest["git_blobs"][name])

    def test_public_header_is_c_compatible(self):
        subprocess.run([shutil.which("cc") or "clang", "-x", "c", "-std=c11", "-fsyntax-only",
                        "-I", str(self.directory), "-I", str(ROOT / "headvoice/firmware"), "-"],
                       input='#include "hv_hand_native_classifier.h"\n', check=True, capture_output=True, text=True)

    def test_actual_model_has_int8_rgb_input_and_eleven_logits_without_softmax(self):
        model = ROOT / "headvoice/third_party/hand_gesture_recognition/models/s3/mobilenetv2_0_5_128_128_gesture.espdl"
        layout = pinned_model_layout(model.read_bytes())
        # TensorDataType.INT8 == 3 in espdl.fbs (not the C++ dl dtype enum).
        self.assertEqual(layout["inputs"], [{"name": "input.1", "dtype": 3, "shape": [1, 128, 128, 3]}])
        self.assertEqual(layout["outputs"], [{"name": "466", "dtype": 3, "shape": [1, 11]}])
        self.assertEqual(len(layout["operators"]), 68)
        self.assertEqual(layout["operators"][-1], "Gemm")
        self.assertEqual(layout["last_node_name"], "/classifier/classifier.1/Gemm")
        self.assertNotIn("Softmax", layout["operators"])


if __name__ == "__main__":
    unittest.main()
