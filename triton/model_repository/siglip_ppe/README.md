# siglip_ppe — SigLIP2-large image encoder (PPE second-stage verifier)

The PPE plugin's second-stage verifier. Confirms/vetoes/rescues helmet, vest,
goggles and boots by comparing a body-region crop's SigLIP embedding to
precomputed text embeddings. Replaces the untrained DINOv2 vest head.

## Weights are NOT in git

Per repo policy (`.gitignore`: `triton/model_repository/**/*.onnx`) only this
README and `config.pbtxt` are committed. The model weights must be exported onto
disk before Triton starts:

```
1/model.onnx              # SigLIP2 image-encoder graph (~2.7 MB)
1/siglip2_img.onnx.data   # external weights (~1.26 GB) — the .onnx references
                          # THIS exact filename, so don't rename it
```

## Re-export

From the PPE POC (`ai_work/ppe`, needs `transformers` + `sentencepiece`):

```python
import torch
from transformers import AutoModel
m = AutoModel.from_pretrained("google/siglip2-large-patch16-256").eval()

class ImgEnc(torch.nn.Module):
    def __init__(self, m): super().__init__(); self.m = m
    def forward(self, pixel_values):
        f = self.m.get_image_features(pixel_values=pixel_values)
        t = f if torch.is_tensor(f) else f.pooler_output
        return t / t.norm(dim=-1, keepdim=True)

torch.onnx.export(ImgEnc(m).eval(), torch.randn(1,3,256,256),
    "1/model.onnx", input_names=["pixel_values"], output_names=["image_embed"],
    opset_version=17)
# -> writes 1/model.onnx + 1/siglip2_img.onnx.data (external)
```

The text heads + sigmoid scale/bias live in the plugin at
`scenarios/ppe/models/siglip_ppe_heads.npz` (committed) — keys `scale`, `bias`,
`text_helmet`, `text_vest`, `text_goggles`, `text_boots`.

## I/O

- input  `pixel_values` FP32 `[1,3,256,256]` — SigLIP-normalised RGB (mean/std .5)
- output `image_embed`  FP32 `[1,1024]` — L2-normalised embedding

Fixed batch of 1 (the exported graph carries its own batch dim); the plugin
scores one crop per infer call.
