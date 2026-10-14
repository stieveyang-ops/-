# 公开数据包 v1（运行 ProRetro-Agent 所需的第三方数据）

本 Release 提供运行 ProRetro-Agent **所必需的 6 个第三方公开文件**，与仓库 `复现指南_REPRODUCE.md`
所记录、并被本项目实际运行使用（`package_reference_sha256.csv` 中 25 项受保护资产）的版本**逐字节一致**。

## 附件

| 文件 | 大小 | SHA-256 |
| --- | --- | --- |
| `ProRetro-Agent_公开数据_v1.zip` | 584,303,731 字节（557.2 MB） | `7C64CC6DCF7F8853CF4907B1056721A720859E7A579DD8EBE115EB512B94E7A0` |

## 包内内容与放置位置

解压后得到 `public_data/` 目录，把其中 6 个文件放入仓库的：

```
第二项\external_public_data\public_data\
```

| 文件 | 字节数 | SHA-256 |
| --- | --- | --- |
| `uspto_model.onnx` | 91,518,243 | `BD0A3CB74CD7068DE474C8FB789A00A66BC42C75636D66510CCAC585EBE928F8` |
| `uspto_filter_model.onnx` | 16,788,859 | `AD29AA32BDFCBE37065045546493806CF04899C55386C438905D83FB14BB6320` |
| `uspto_ringbreaker_model.onnx` | 15,036,094 | `1BF0690352D9E9212D7DBE8B35649CAF74F73EF0B30EDEFDFDAC37FCE38085BE` |
| `uspto_templates.csv.gz` | 3,313,598 | `A4F1945E90CFA195538320833D68AED38F14E2FCC2F8AFB5D958BC920EDCAFBE` |
| `uspto_ringbreaker_templates.csv.gz` | 373,753 | `5616A056454B10A2F044E69E027422128986856EBD958541A3BF9F837E3A0D14` |
| `zinc_stock.hdf5` | 1,339,073,560 | `FF54C334C3DFC11882D5FA3024FDE3BE8CF3E38F979D93A39B9BE8CCA1A5DC85` |

## 校验

```powershell
python verify_public_data.py 第二项\external_public_data\public_data
# 期望：6 项全部 [OK]
```

## 数据来源与许可

| 文件 | 来源 |
| --- | --- |
| 3 个 ONNX 模型 | AiZynthFinder 官方发布，Zenodo 记录 7797465 |
| 2 个模板库 | AiZynthFinder 官方发布，Zenodo 记录 7341155（原文件名含 `unique_templates`，需按上表重命名） |
| `zinc_stock.hdf5` | Figshare 文章 29145899「zincstock for aizynthfinder」，DOI 10.6084/m9.figshare.29145899.v1 |

> ⚠️ AiZynthFinder 自带命令 `download_public_data` 下载的 ZINC 库存是 **2020 年旧版**（663,232,280 字节），
> 与本项目使用的版本不同；请使用本 Release 附件或指南中的直链。

以上素材均以**依赖或调用方式**使用，未修改第三方内容；ZINC 数据受其原始许可约束，本附件仅用于复现研究。

## 配套文档

- [`复现指南_REPRODUCE.md`](复现指南_REPRODUCE.md) —— 从零开始的 5 步流程（含本数据的官方直链与校验方式）
- [`复现对照表_REPRODUCTION_BASELINE.md`](复现对照表_REPRODUCTION_BASELINE.md) —— 历史 16 次成功运行的路线数、难度区间与置信度基准，供比对
- [`第二项/README_本项说明.md`](第二项/README_本项说明.md) —— 可运行作品的结构与运行方式
