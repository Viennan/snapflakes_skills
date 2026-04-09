# resource hub skill测试环境
本文档说明了可用于resource hub skill测试的配置参数及文件
## 基本术语
- `project_root`: resource hub skill所在项目的根目录
## 内容理解API
以下是可以用于内容理解的API配置
```jsonc
{
    "open_ai_api_key_env": "ARK_API_KEY", // 用于读取API KEY的环境变量
    "open_ai_base_url_env": "ARK_BASE_URL", // 用于读取 base url 的环境变量
    "model": "doubao-seed-2-0-pro-260215" // 支持直接输入视频
}
```
`doubao-seed-2-0-pro-260215`支持直接上传视频进行内容理解。
## 向量化API
以下是可以用于向量化的API配置
```jsonc
{
    "api_key_env": "ARK_API_KEY", // 用于读取API KEY的环境变量
    "base_url_env": "ARK_BASE_URL", // 用于读取 base url 的环境变量
    "model": "doubao-embedding-vision-251215"
}
```
## 测试文件
需要用户事先准备好，可要求用户提供。
