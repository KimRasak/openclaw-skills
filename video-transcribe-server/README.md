# Video Transcribe Server

粘贴抖音/B站分享链接 → 自动下载 → 转录为文字。

## 效果图

![](assets/image.png)

## 启动

```bash
conda activate /gluster_osa_cv/user/jinzili/env/whisperx
CUDA_VISIBLE_DEVICES=4 python server.py --port 8542 --model large-v3
```

打开浏览器访问 `http://<host>:8542` 即可使用。
