# -*- coding: utf-8 -*-
r"""校验从官方来源下载的 6 个公开数据文件：大小 + SHA-256 必须与交付包完全一致。

用法：
    python verify_public_data.py external_public_data\public_data
"""
import hashlib
import os
import sys

EXPECT = {
    "uspto_model.onnx": (91518243, "BD0A3CB74CD7068DE474C8FB789A00A66BC42C75636D66510CCAC585EBE928F8"),
    "uspto_filter_model.onnx": (16788859, "AD29AA32BDFCBE37065045546493806CF04899C55386C438905D83FB14BB6320"),
    "uspto_ringbreaker_model.onnx": (15036094, "1BF0690352D9E9212D7DBE8B35649CAF74F73EF0B30EDEFDFDAC37FCE38085BE"),
    "uspto_templates.csv.gz": (3313598, "A4F1945E90CFA195538320833D68AED38F14E2FCC2F8AFB5D958BC920EDCAFBE"),
    "uspto_ringbreaker_templates.csv.gz": (373753, "5616A056454B10A2F044E69E027422128986856EBD958541A3BF9F837E3A0D14"),
    "zinc_stock.hdf5": (1339073560, "FF54C334C3DFC11882D5FA3024FDE3BE8CF3E38F979D93A39B9BE8CCA1A5DC85"),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join("external_public_data", "public_data")
    bad = 0
    for name, (size, digest) in EXPECT.items():
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            print(f"[缺失] {name}")
            bad += 1
            continue
        actual_size = os.path.getsize(path)
        actual_sha = sha256(path)
        ok = actual_size == size and actual_sha == digest
        print(f"[{'OK' if ok else '不符'}] {name}  {actual_size:,} 字节")
        if not ok:
            bad += 1
            print(f"        期望 {size:,} 字节 / {digest}")
            print(f"        实际 {actual_size:,} 字节 / {actual_sha}")
    print()
    print("全部一致：数据可直接用于复现" if bad == 0 else f"存在 {bad} 项不一致，请按《复现指南》重新下载")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
