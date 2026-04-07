# resource hub
resource hub 是一个用于存储多媒体资源的本地仓库规范。

## 文档范围
- 本文档仅定义仓库目录结构、元数据文件格式和配置字段语义。
- 本文档不定义资源导入、扫描、校验、转码执行、删除、发布或命令行接口；这些属于管理工作流范畴。
- 文中的 JSON 示例均使用 `jsonc` 形式展示字段含义；实际落盘文件必须为合法 JSON。
- 除非另有说明，本文中的“必须”表示强约束，“应”表示推荐约束。

## 基本术语
- `resource hub root`：资源仓库根目录。
- `resource`：一个具名的媒体资源。
- `resource type`：资源类型，当前仅有 `video` 与 `image` 两类。
- `variation`：某个资源在仓库中的一个实际文件变体。
- `original variation`：导入仓库时保留的原始文件，对应 `type = "original"`。
- `transcoded variation`：由仓库根据配置生成的转码产物，对应 `type = "transcoded"`。
- `logical target spec`：转码目标规格。视频以 `(resolution, fps)` 唯一标识，图片以 `resolution` 唯一标识。
- `time-based visual resource`：具有时间维度的视觉资源，应归类为 `video`，包括常规视频文件以及 GIF、APNG、Animated WebP 等多帧动画资源。
- `static visual resource`：不具有时间维度的静态图像资源，应归类为 `image`。

## 目录结构
一个最小可用的 resource hub 目录结构如下：

```text
resource_hub_root/
├── resource_hub_config.json
├── videos/
│   ├── index.json
│   └── <resource_name>/
│       ├── original.<format>
│       └── transcoded_<resolution>_<fps>.<format>
└── images/
    ├── index.json
    └── <resource_name>/
        ├── original.<format>
        └── transcoded_<resolution>.<format>
```

- `videos/` 与 `images/` 目录必须存在，即使其中暂时没有任何资源。
- `videos/index.json` 与 `images/index.json` 必须存在；无资源时内容为 `{"resources": []}`。
- 同名资源允许分别存在于 `videos/` 与 `images/` 中；跨类型不要求全仓唯一。
- 每个资源目录应仅包含受仓库管理的媒体文件；其他文件视为未受管理文件。
- `index.json` 是对应资源类型的唯一事实来源；仓库中不再使用 `meta.json`。

## 公共约束
### 1. 资源名称
资源名称用于标识资源，同时直接作为资源目录名使用，因此必须满足：
- 非空字符串。
- 不得包含前后空白字符。
- 不得为 `.` 或 `..`。
- 不得包含路径分隔符，如 `/` 或 `\`。
- 在同一资源类型目录下必须唯一。

### 2. 文件名与格式
- `format` 字段表示文件格式或容器格式，必须为不带 `.` 的小写 ASCII 字符串，例如 `mp4`、`mov`、`png`、`jpg`。
- `f_name` 必须为资源目录内文件的 basename，不得包含路径分隔符。
- `f_name` 的扩展名必须与 `format` 一致。
- 每个 `variation` 必须且只能对应一个实际存在的文件。

### 3. 变体命名规则
为保证仓库结构可预测，仓库内受管理的媒体文件名必须满足以下命名规则：
- 原始文件固定命名为 `original.<format>`。
- 视频转码产物固定命名为 `transcoded_<resolution>_<fps>.<format>`。
- 图片转码产物固定命名为 `transcoded_<resolution>.<format>`。

### 4. 描述字段
- 每个资源条目必须保存一个 `description` 字段。
- `description` 表示该资源的详细描述，不设固定长度上限。
- 对应资源类型未启用 `with_description` 时，`description` 允许为空字符串。
- 对应资源类型启用 `with_description` 时，`description` 必须为非空字符串。
- `description` 的语言由 `resource_hub_config.json.description_language` 统一决定。

### 5. JSON 文件编码
- 所有 JSON 文件必须使用 UTF-8 编码。
- JSON 文件中不得包含注释。

## 目录与元数据结构
### 1. `resource_hub_config.json`
该文件为仓库行为的唯一配置入口。

```jsonc
{
    "description_language": "en",
    "content_sense": {
        "open_ai_base_url": "https://example.invalid/v1",
        "open_ai_api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4.1-mini",
        "cache_time_hours": 144,
        "video_understanding_mode": "frames"
    },
    "text_vectorization": {
        "api_key_env": "ARK_API_KEY",
        "model": "doubao-embedding-vision-251215",
        "dimensions": 1024
    },
    "video": {
        "transcoders": [
            {
                "resolution": "720p",
                "fps": 30
            }
        ],
        "with_description": {
            "resolution": "720p"
        }
    },
    "image": {
        "transcoders": [
            {
                "resolution": "1080p"
            }
        ],
        "with_description": {
            "resolution": "720p"
        }
    }
}
```

- `description_language` 为仓库级配置，表示 `description` 的统一语言。
- `description_language` 的当前推荐值为：
  - `en`
  - `zh-CN`
- `description_language` 缺省时等价于 `en`。
- `video` 与 `image` 字段必须存在，值必须为对象。
- `content_sense` 为可选字段，仅当 `video.with_description` 或 `image.with_description` 至少存在一个时才为必填。
- `text_vectorization` 为可选字段，用于配置 `description` 文本向量化。
- `video.transcoders` 与 `image.transcoders` 缺省时等价于空列表。
- `video.with_description` 与 `image.with_description` 缺省时表示该资源类型关闭语义感知。
- `content_sense.cache_time_hours` 为可选字段，单位为小时，缺省值为 `144`。
- `text_vectorization.dimensions` 为可选字段，缺省值为 `1024`。

### 2. `videos/index.json`
`videos/index.json` 用于保存视频资源的完整索引与元数据。

```jsonc
{
    "resources": [
        {
            "name": "sample_video",
            "variations": [
                {
                    "f_name": "original.mov",
                    "width": 1920,
                    "height": 1080,
                    "resolution": "1080p",
                    "type": "original",
                    "duration": 10.0,
                    "fps": 24,
                    "format": "mov",
                    "has_alpha": true
                },
                {
                    "f_name": "transcoded_720p_24.mov",
                    "width": 1280,
                    "height": 720,
                    "resolution": "720p",
                    "type": "transcoded",
                    "duration": 10.0,
                    "fps": 24,
                    "format": "mov",
                    "has_alpha": true
                }
            ],
            "description": "Detailed resource description",
            "content_sense_cache": {
                "provider_base_url": "https://example.invalid/v1",
                "api_key_env": "OPENAI_API_KEY",
                "resource_type": "video",
                "video_understanding_mode": "frames",
                "input_f_name": "transcoded_720p_24.mov",
                "input_size_bytes": 1234567,
                "input_mtime_ns": 1712486400000000000,
                "uploads": [
                    {
                        "file_id": "file_1",
                        "purpose": "vision",
                        "input_type": "input_image",
                        "uploaded_at": "2026-04-07T12:00:00Z",
                        "frame_time_seconds": 1.0
                    }
                ]
            },
            "text_vector": {
                "provider": "volcengine_ark",
                "model": "doubao-embedding-vision-251215",
                "dimensions": 1024,
                "encoding": "base64-f32le",
                "text_field": "description",
                "text_sha256": "sha256(description)",
                "instruction_profile": "resource_search_corpus_text_v1",
                "instruction_sha256": "sha256(corpus_instruction)",
                "embedding": "<base64 string>"
            }
        }
    ]
}
```

- `resources` 必须为数组。
- 数组元素必须按 `name` 的字典序升序排列。
- 每个资源对象必须完整描述该资源的全部 `variations`、`description`，以及可选的 `content_sense_cache` 与 `text_vector`。

### 3. `images/index.json`
`images/index.json` 用于保存图片资源的完整索引与元数据。

```jsonc
{
    "resources": [
        {
            "name": "sample_image",
            "variations": [
                {
                    "f_name": "original.png",
                    "width": 1280,
                    "height": 720,
                    "resolution": "720p",
                    "type": "original",
                    "format": "png",
                    "has_alpha": true
                },
                {
                    "f_name": "transcoded_540p.png",
                    "width": 960,
                    "height": 540,
                    "resolution": "540p",
                    "type": "transcoded",
                    "format": "png",
                    "has_alpha": true
                }
            ],
            "description": "Detailed resource description",
            "content_sense_cache": {
                "provider_base_url": "https://example.invalid/v1",
                "api_key_env": "OPENAI_API_KEY",
                "resource_type": "image",
                "video_understanding_mode": "",
                "input_f_name": "transcoded_540p.png",
                "input_size_bytes": 234567,
                "input_mtime_ns": 1712486400000000000,
                "uploads": [
                    {
                        "file_id": "file_2",
                        "purpose": "vision",
                        "input_type": "input_image",
                        "uploaded_at": "2026-04-07T12:00:00Z"
                    }
                ]
            },
            "text_vector": {
                "provider": "volcengine_ark",
                "model": "doubao-embedding-vision-251215",
                "dimensions": 1024,
                "encoding": "base64-f32le",
                "text_field": "description",
                "text_sha256": "sha256(description)",
                "instruction_profile": "resource_search_corpus_text_v1",
                "instruction_sha256": "sha256(corpus_instruction)",
                "embedding": "<base64 string>"
            }
        }
    ]
}
```

## 资源条目约束
### 1. 通用约束
- `name` 必须与资源目录名一致。
- `variations` 必须为数组，且必须恰好包含一个 `type = "original"` 的元素。
- `variations` 中原始文件必须排在最前。
- 图片资源其余转码文件按 `resolution` 升序排列。
- 视频资源其余转码文件按 `resolution` 升序、`fps` 升序排列。
- `description` 必须为字符串。
- `content_sense_cache` 为可选字段；若存在，则用于记录最近一次语义感知所依赖的云端文件缓存信息。
- `text_vector` 为可选字段；若存在，则表示该资源 `description` 的文本向量缓存。
- `text_vector.embedding` 必须为字符串形式存储的向量，不得使用 JSON 数字数组。
- 当前 `text_vector.embedding` 的编码格式固定为 `base64-f32le`，即 `float32 little-endian` 原始字节序列的 Base64 字符串。

### 2. 视频资源附加约束
- 同一视频资源下，不得存在两个具有相同 `(resolution, fps)` 的 `variation`。
- `width` 与 `height` 表示该文件实际存储尺寸。
- `resolution` 为根据 `width` 与 `height` 推导出的逻辑分辨率。
- `duration` 单位为秒，允许使用浮点数表示。
- `fps` 为整数，来源于原始帧率四舍五入后的结果。
- `format` 为文件容器格式。
- `has_alpha` 表示该文件是否包含 alpha 通道。

### 3. 图片资源附加约束
- 同一图片资源下，不得存在两个具有相同 `resolution` 的 `variation`。
- `width` 与 `height` 表示该文件实际存储尺寸。
- `resolution` 为根据 `width` 与 `height` 推导出的逻辑分辨率。
- `format` 为文件格式。
- `has_alpha` 表示该文件是否包含 alpha 通道。

## 配置项语义
### 1. 通用定义
#### 1.1 `resolution`
`resolution` 采用离散枚举值：

```python
resolutions = ['360p', '480p', '540p', '720p', '1080p', '2k', '4k', '8k']
standard_min_wh = {
    '360p': 360,
    '480p': 480,
    '540p': 540,
    '720p': 720,
    '1080p': 1080,
    '2k': 1440,
    '4k': 2160,
    '8k': 4320,
}

def determine_resolution(x: int, y: int) -> str:
    min_xy = min(x, y)
    if min_xy >= standard_min_wh['8k']:
        return '8k'
    elif min_xy >= standard_min_wh['4k']:
        return '4k'
    elif min_xy >= standard_min_wh['2k']:
        return '2k'
    elif min_xy >= standard_min_wh['1080p']:
        return '1080p'
    elif min_xy >= standard_min_wh['720p']:
        return '720p'
    elif min_xy >= standard_min_wh['540p']:
        return '540p'
    elif min_xy >= standard_min_wh['480p']:
        return '480p'
    else:
        return '360p'
```

- 视频与图片均使用相同的 `resolution` 定义。
- 转码时，短边对齐目标 `resolution` 对应的 `standard_min_wh`，长边按原始长宽比缩放。
- 判断资源是否满足某个目标 `resolution` 时，必须先使用 `determine_resolution(width, height)` 推导逻辑分辨率后再比较。

#### 1.2 `with_description`
`with_description` 是视频与图片共用的可选配置项，分别放置于 `video.with_description` 与 `image.with_description` 下。

```jsonc
{
    "resolution": "720p"
}
```

- 该字段缺省时，表示对应资源类型关闭语义感知。
- 启用后，应在该资源类型的全部转码任务完成后再进行语义感知。
- 感知输入应优先选择与 `with_description.resolution` 完全匹配的现有 `variation`。
- 若目标分辨率不存在，则应选择现有 `variation` 中分辨率最低的一个作为感知输入。
- 对于图片资源，应直接使用选定的图片 `variation` 作为语义感知输入。
- 对于视频资源，语义感知输入方式由 `content_sense.video_understanding_mode` 决定。
- 当 `content_sense.video_understanding_mode = "direct_upload"` 时，应直接使用选定的视频 `variation` 文件作为语义感知输入。
- 当 `content_sense.video_understanding_mode = "frames"` 时，应先从选定的视频 `variation` 中生成图片输入，再使用这些图片完成语义感知。
- 语义感知前，应先通过 `ffprobe` 获取输入资源的技术事实，尤其是 `has_alpha`、尺寸、分辨率、时长、帧率；这类技术事实应以探测结果为准，而不是由大模型自行判断。
- 图片与视频应使用不同的语义感知 prompt。
- 对视频资源，`description` 应包含按时间线合理分段的内容描述，并体现视频的运境/氛围/整体情绪。
- 若 `content_sense_cache` 中缓存的云端 `file_id` 仍在 `content_sense.cache_time_hours` 对应的有效期内，则重新进行语义感知时应优先复用这些 `file_id`，无需重新上传。
- 若缓存失效、配置变化、感知输入文件变化，或缓存记录与当前感知输入不匹配，则应重新上传并刷新 `content_sense_cache`。
- 语义感知完成后，必须同时生成并写回：
  - 资源条目的 `description`
  - 资源条目的 `content_sense_cache`

### 2. 视频配置
#### 2.1 `video.transcoders`
该选项为列表，定义视频资源在不损害观感的前提下应尽量拥有的目标规格。

```jsonc
[
    {
        "resolution": "1080p",
        "fps": 60
    },
    {
        "resolution": "720p",
        "fps": 30
    }
]
```

- 列表中每个元素表示一个视频目标规格。
- 同一 `video.transcoders` 中不应出现重复的 `(resolution, fps)`。
- 视频转码目标仅在“可实现”时才必须生成。
- 对于某个原始视频，若满足以下条件，则称某个目标规格“可实现”：
  - 原始视频的逻辑分辨率大于或等于目标 `resolution`。
  - 原始视频四舍五入后的 `fps` 大于或等于目标 `fps`。
- 管理器不得通过放大分辨率或补帧的方式强行生成不可实现的目标规格。
- 当原始视频已满足某个可实现目标规格时，无需再为该目标额外转码；此时原始文件本身即视为该目标规格的满足者，并在资源条目中记录为 `type = "original"`。

#### 2.2 视频转码默认规则
- 原始视频必须始终保留为 `original variation`。
- 若需转码，转码产物在资源条目中的 `type` 必须为 `transcoded`。
- 原视频不包含 alpha 通道时，默认编码器选择 `x264`，像素格式为 `yuv420p`，默认封装格式为 `mp4`。
- 原视频包含 alpha 通道时，默认编码器选择 `prores_ks`，像素格式为 `yuva444p10le`，默认封装格式为 `mov`。
- 转码时需保证观感不变；对 `x264` 可使用 `crf=18` 作为默认参考值，对其他编码器应选择等效的高质量参数。
- 原视频中的音频流默认不转码，直接复用原始音频流；若原视频不存在音频流，则转码产物也不包含音频流。

### 3. 图片配置
#### 3.1 `image.transcoders`
该选项为列表，定义图片资源在不损害观感的前提下应尽量拥有的目标规格。

```jsonc
[
    {
        "resolution": "1080p"
    },
    {
        "resolution": "720p"
    }
]
```

- 列表中每个元素表示一个图片目标规格。
- 同一 `image.transcoders` 中不应出现重复的 `resolution`。
- 图片转码目标仅在“可实现”时才必须生成。
- 对于某个原始图片，若其逻辑分辨率大于或等于目标 `resolution`，则该目标规格可实现。
- 管理器不得通过放大分辨率的方式强行生成不可实现的目标规格。
- 当原始图片已满足某个可实现目标规格时，无需再为该目标额外转码；此时原始文件本身即视为该目标规格的满足者，并在资源条目中记录为 `type = "original"`。

#### 3.2 图片转码默认规则
- 原始图片必须始终保留为 `original variation`。
- 若需转码，转码产物在资源条目中的 `type` 必须为 `transcoded`。
- 原图片不包含 alpha 通道时，转码图片格式为 `jpg`，应使用足够高的质量参数以保证观感不变。
- 原图片包含 alpha 通道时，转码图片格式为 `png`。

### 4. `content_sense`
`content_sense` 用于配置语义感知所依赖的多模态 LLM 服务。

```jsonc
{
    "open_ai_base_url": "https://example.invalid/v1",
    "open_ai_api_key_env": "OPENAI_API_KEY",
    "model": "gpt-4.1-mini",
    "cache_time_hours": 144,
    "video_understanding_mode": "frames"
}
```

- 当 `content_sense` 存在时，`open_ai_base_url`、`open_ai_api_key_env` 与 `model` 均为必填。
- `open_ai_api_key_env` 的值是环境变量名，而不是实际 API Key。
- `cache_time_hours` 为可选字段，表示本地认为云端上传文件可复用的缓存有效期，单位为小时；缺省值为 `144`。
- 若任一资源类型启用了 `with_description`，则 `content_sense` 必须存在且配置完整。
- 当 `video.with_description` 存在时，`content_sense.video_understanding_mode` 也必须存在。
- `content_sense.video_understanding_mode` 的可选值仅有：
  - `frames`：先从视频中抽取图片，再以图片输入完成视频语义感知。
  - `direct_upload`：直接上传视频文件完成视频语义感知。
- 当 `content_sense.video_understanding_mode = "direct_upload"` 时，调用方必须确保所配置服务提供商及模型实际支持直接视频输入。
- 若使用 OpenAI 官方 GPT-5.4 系列模型，应默认采用 `frames`；`direct_upload` 主要面向支持直接视频输入的 OpenAI-compatible 非 GPT 服务。

### 5. `text_vectorization`
`text_vectorization` 用于配置基于 `description` 的文本向量化。

```jsonc
{
    "api_key_env": "ARK_API_KEY",
    "model": "doubao-embedding-vision-251215",
    "dimensions": 1024
}
```

- `text_vectorization` 使用独立配置，不复用 `content_sense`。
- 当前实现固定使用火山方舟多模态向量模型 `doubao-embedding-vision-251215`。
- 当前实现必须使用火山方舟官方 SDK 调用，不得通过 OpenAI SDK 调用该向量模型。
- `api_key_env` 的值是环境变量名，而不是实际 API Key。
- `dimensions` 为稠密向量维度，缺省值为 `1024`。
- 当前仓库场景属于“文本 Query 检索文本 Corpus”的召回/排序任务：
  - Query 侧 `instructions` 必须使用 `Target_modality: text.\nInstruction:{}\nQuery:` 模板。
  - Corpus 侧 `instructions` 必须使用 `Instruction:Compress the text into one word.\nQuery:` 模板。
- 进行资源搜索时，不得先以词法评分筛掉资源再做向量匹配。
  - 若存在硬过滤条件，则候选集应先由硬过滤得到，再对候选集分别计算词法评分与向量相似度。
  - 若不存在硬过滤条件，则应对全量资源分别计算词法评分与向量相似度。
- 当 `description`、向量模型、向量维度或向量化 `instructions` 变化时，应重新生成对应资源的 `text_vector`。
